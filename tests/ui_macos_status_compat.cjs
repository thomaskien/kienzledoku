// Compare real old/new Record pages in one browser, with synthetic data only.
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const readline = require('node:readline');
const zlib = require('node:zlib');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');
const oldRoot = process.argv[2];
assert.ok(oldRoot, 'Pass the extracted 1.7.1 Mac payload');

function pixels(png) {
  let width, height, channels;
  const compressed = [];
  for (let p = 8; p < png.length;) {
    const length = png.readUInt32BE(p), type = png.toString('ascii', p+4, p+8), data = png.subarray(p+8, p+8+length);
    if (type === 'IHDR') {
      width = data.readUInt32BE(0); height = data.readUInt32BE(4);
      assert.equal(data[8], 8); assert.ok([2,6].includes(data[9])); assert.equal(data[12], 0);
      channels = data[9] === 2 ? 3 : 4;
    }
    if (type === 'IDAT') compressed.push(data);
    p += length+12;
  }
  const raw = zlib.inflateSync(Buffer.concat(compressed)), stride = width*channels, output = Buffer.alloc(stride*height);
  for (let y=0; y<height; y++) {
    const filter = raw[y*(stride+1)];
    assert.ok(filter <= 4);
    for (let x=0; x<stride; x++) {
      const i=y*stride+x, a=x>=channels?output[i-channels]:0, b=y?output[i-stride]:0, c=y&&x>=channels?output[i-stride-channels]:0;
      const p=a+b-c, pa=Math.abs(p-a), pb=Math.abs(p-b), pc=Math.abs(p-c);
      const prediction=[0,a,b,Math.floor((a+b)/2),pa<=pb&&pa<=pc?a:pb<=pc?b:c][filter];
      output[i]=(raw[y*(stride+1)+1+x]+prediction)&255;
    }
  }
  return {width,height,channels,output};
}

function sameRendering(a, b) {
  const one=pixels(a), two=pixels(b);
  if (one.width!==two.width || one.height!==two.height || one.channels!==two.channels) return false;
  let differences=0;
  for(let i=0;i<one.output.length;i++) {
    const delta=Math.abs(one.output[i]-two.output[i]);
    // Chromium varied two edge pixels by one blue-channel level in otherwise
    // identical old/new badge borders. Keep tolerance below any layout change.
    if (delta>1 || (delta && ++differences>16)) return false;
  }
  return true;
}

(async () => {
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'mac-status-compat-'));
  const children = [];
  let browser;
  try {
    browser = await chromium.launch({channel:'chrome', headless:true});
    const pages = [];
    let status = 'ready';
    for (const [index, source] of [oldRoot, root].entries()) {
      const directory = path.join(temporary, String(index));
      fs.mkdirSync(directory);
      fs.writeFileSync(path.join(directory, 'allow-patient'), 'synthetic');
      fs.writeFileSync(path.join(directory, 'config.toml'), '[commander]\nenabled = true\nurl = "http://10.0.83.140:8185"\n');
      const child = spawn(process.argv[3] || 'python3', ['-u', 'tests/fixtures/ui_record_session.py'], {
        cwd:root, env:{...process.env, PYTHONDONTWRITEBYTECODE:'1', KIENZLEDOKU_CONFIG_DIR:directory,
          KIENZLEDOKU_TEST_SOURCE_ROOT:source, KIENZLEDOKU_TEST_COMMANDER_UI:'single', KIENZLEDOKU_TEST_WINDOWS_LAYOUT:'0'},
        stdio:['ignore','pipe','pipe'],
      });
      children.push(child);
      child.stderr.resume();
      const url = await new Promise((resolve, reject) => {
        const lines = readline.createInterface({input:child.stdout});
        const timer = setTimeout(() => reject(new Error('Fixture startup timed out')), 10000);
        lines.once('line', value => {clearTimeout(timer);lines.close();resolve(value);});
        child.once('error', reject);
        child.once('exit', () => {clearTimeout(timer);reject(new Error('Fixture exited'));});
      });
      const page = await browser.newPage({viewport:{width:1440,height:960}});
      await page.route('**/status', async route => {
        const response = await route.fetch(), data = await response.json();
        for (const service of Object.values(data.services)) service.status = status;
        data.t2med_status = 'ok';
        await route.fulfill({response, json:data});
      });
      await page.goto(url);
      await page.waitForFunction(() => document.querySelector('#patient-name').textContent === 'Testperson, ÄÖÜ');
      await page.locator('.brand-byline').evaluate(el => {el.textContent = 'vTEST · von Dr. Thomas Kienzle';});
      pages.push(page);
    }
    let checks = 0;
    for (const width of [1280,1440,1800]) {
      for (const current of ['ready','loading','standby']) {
        status = current;
        const screenshots = [];
        const geometry = [];
        for (const page of pages) {
          await page.setViewportSize({width,height:960});
          await page.waitForFunction(s => ['asr-server','diarization-server','llm-server'].every(id => document.getElementById(id).classList.contains(s)), status);
          assert.equal(await page.locator('.server-row').evaluate(el => getComputedStyle(el).display), 'flex');
          geometry.push(await page.locator('.record-heading').evaluate(el => [...el.querySelectorAll('h1,.brand-byline,.server-badge,.server-dot,.server-state,.patient-row')].map(node => {
            const r=node.getBoundingClientRect(); return [r.x,r.y,r.width,r.height];
          })));
          screenshots.push(await page.locator('.record-heading').screenshot());
        }
        assert.deepEqual(geometry[0], geometry[1], 'Mac header geometry changed');
        if (!sameRendering(screenshots[0], screenshots[1])) {
          const prefix = process.argv[4] || path.join(os.tmpdir(), 'mac-status-comparison.png');
          fs.writeFileSync(prefix + '.old.png', screenshots[0]);
          fs.writeFileSync(prefix + '.new.png', screenshots[1]);
          for (const [i, page] of pages.entries()) {
            fs.writeFileSync(prefix + '.' + i + '.html', await page.locator('.record-heading').evaluate(el => el.outerHTML));
          }
          throw new Error(`Mac header differs from 1.7.1: ${width}px, ${status}`);
        }
        if (width === 1440 && current === 'ready' && process.argv[4]) fs.writeFileSync(process.argv[4], screenshots[1]);
        checks++;
      }
    }
    console.log(`PASS: Mac header matches 1.7.1 at ${checks} width/state combinations; identical geometry, at most 16 edge channels differing by 1/255 (version label normalised, Chromium on Mac).`);
  } finally {
    if (browser) await browser.close();
    for (const child of children) {
      if (child.exitCode === null) await new Promise(resolve => {child.once('close', resolve);child.kill();});
    }
    fs.rmSync(temporary, {recursive:true, force:true});
  }
})().catch(error => {console.error(error);process.exitCode = 1;});
