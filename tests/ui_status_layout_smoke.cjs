// Real Record HTML/status polling with synthetic data; no Windows install required.
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const readline = require('node:readline');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');
const texts = { ready:'BEREIT', loading:'WIRD GELADEN', standby:'STANDBY',
  error:'FEHLER', checking:'PRÜFUNG', busy:'AKTIV', disabled:'DEAKTIVIERT' };
let phase = 'startup';

(async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'record-status-layout-'));
  fs.writeFileSync(path.join(directory, 'allow-patient'), 'synthetic');
  const child = spawn(process.argv[2] || 'python3', ['-u', 'tests/fixtures/ui_record_session.py'], {
    cwd:root, env:{...process.env, KIENZLEDOKU_CONFIG_DIR:directory, KIENZLEDOKU_TEST_COMMANDER_UI:'single', KIENZLEDOKU_TEST_WINDOWS_LAYOUT:'1'},
    stdio:['ignore','pipe','pipe'],
  });
  child.stderr.resume();
  const exited = new Promise(resolve => child.once('close', resolve));
  let browser;
  try {
    const url = await new Promise((resolve,reject) => {
      const lines = readline.createInterface({input:child.stdout});
      const timer = setTimeout(() => reject(new Error('Startup timeout')),10000);
      lines.once('line',value => {clearTimeout(timer);lines.close();resolve(value);});
      child.once('exit',() => {clearTimeout(timer);reject(new Error('Fixture stopped'));});
      child.once('error',reject);
    });
    browser = await chromium.launch({channel:'chrome',headless:true});
    for (const scale of [1,1.25,1.5]) {
      const context = await browser.newContext({deviceScaleFactor:scale});
      const page = await context.newPage();
      let status = 'ready', host = '10.0.83.140', temperatureCount=0;
      const errors = [];
      page.on('pageerror',() => errors.push('script'));
      await page.route('**/status',async route => {
        const response = await route.fetch(), data = await response.json();
        for (const service of Object.values(data.services)) {service.status=status;service.host=host;}
        data.t2med_status=status;data.t2med_host=host;
        data.gpu_temperatures=Array.from({length:temperatureCount},(_,i)=>({address:`http://192.0.2.${i+1}:8185`,value:44+i,tooltip:`http://192.0.2.${i+1}:8185 · GPU`}));
        await route.fulfill({response,json:data});
      });
      await page.goto(url);
      await page.waitForFunction(() => document.querySelector('#patient-name').textContent === 'Testperson, ÄÖÜ');
      for (const width of [1280,1440,1100,980,820]) {
        await page.setViewportSize({width,height:960});
        let reference;
        for (const current of Object.keys(texts)) {
          phase = `${width}px at ${scale}x, ${current}`;
          status=current;
          await page.waitForFunction(s => [...document.querySelectorAll('.server-badge')].every(el => el.classList.contains(s)),status);
          const metrics = await page.evaluate(() => {
            const box = el => {const r=el.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,right:r.right};};
            return {patient:box(document.querySelector('.patient-row')),heading:box(document.querySelector('.record-heading')),
              title:box(document.querySelector('.topbar h1')),row:box(document.querySelector('.server-row')),
              compact:document.querySelector('.topbar').classList.contains('compact-brand'),
              byline:getComputedStyle(document.querySelector('.brand-byline')).display,
              rowDisplay:getComputedStyle(document.querySelector('.server-row')).display,
              badges:[...document.querySelectorAll('.server-badge')].map(el => ({...box(el),
                dot:box(el.querySelector('.server-dot')),state:box(el.querySelector('.server-state')),
                label:box(el.querySelector('.server-label')),name:box(el.querySelector('.server-name')),
                display:getComputedStyle(el).display,
                radius:getComputedStyle(el).borderRadius,
                text:el.querySelector('.server-state').textContent,
                tooltip:el.querySelector('.server-state').title,
                ellipsis:getComputedStyle(el.querySelector('.server-state')).textOverflow}))};
          });
          assert.equal(metrics.badges.length,4);
          assert.equal(metrics.rowDisplay,'flex','Natural pill row replaced by a grid');
          assert.equal(metrics.byline==='none',metrics.compact,'Version/author must disappear together');
          assert.ok(metrics.badges.every(b => Math.abs(b.y-metrics.badges[0].y)<0.5),'Status badges wrapped');
          for (const badge of metrics.badges) {
            assert.equal(badge.display,'flex','Mac/Linux pill shape must be retained');
            assert.equal(badge.radius,'999px');
            assert.ok(Math.abs(badge.y-metrics.badges[0].y)<0.5,'Status badges wrapped');
            assert.ok(badge.right<=metrics.row.right+0.5,'Badge escaped row');
            assert.ok(badge.state.right<=badge.right+0.5,'State escaped badge');
            assert.equal(badge.dot.w,8,'Status dot shrank');
            assert.ok(badge.label.right<=badge.name.right+0.5,'Service label was clipped');
            assert.equal(badge.text,texts[current]);
            assert.equal(badge.tooltip,texts[current]);
            assert.equal(badge.ellipsis,'ellipsis');
          }
          assert.ok(metrics.title.right<=metrics.row.x+0.5,'Title overlaps status row');
          assert.ok(metrics.row.right<=metrics.heading.right+0.5,'Status row overflows header');
          // Natural pills change width with their content, but never move the
          // patient/workspace down or produce a second status line.
          const positions=[metrics.patient.y,metrics.heading.h,...metrics.badges.flatMap(b => [b.y,b.h])];
          if(reference) positions.forEach((value,i) => assert.ok(Math.abs(value-reference[i])<0.5,'Status changed layout'));
          else reference=positions;
        }
      }
      host='commander-mit-einem-sehr-langen-hostnamen.praxis.example';
      await page.waitForFunction(h => document.querySelector('#asr-server .server-name').title.endsWith(h),host);
      assert.equal(await page.locator('#asr-server .server-host').evaluate(el => getComputedStyle(el).textOverflow),'ellipsis');
      assert.equal(await page.locator('.brand-byline').isVisible(),false,'Hide metadata before shortening statuses');
      for (const width of [820,980,1280,1440]) {
        await page.setViewportSize({width,height:960});
        const fits=await page.locator('.server-row').evaluate(row => {
          const r=row.getBoundingClientRect(),badges=[...row.querySelectorAll(".server-badge")].map(el=>el.getBoundingClientRect());
          return badges.every(b=>Math.abs(b.y-badges[0].y)<0.5 && b.right<=r.right+0.5);
        });
        assert.ok(fits,'Long hosts must not wrap or overflow');
      }
      status='ready';host='10.0.83.140';
      await page.waitForFunction(() => document.querySelector('#asr-server .server-name').title.endsWith('10.0.83.140') && document.querySelector('#asr-server').classList.contains('ready'));
      await page.setViewportSize({width:1800,height:960});
      await page.waitForFunction(() => !document.querySelector('.topbar').classList.contains('compact-brand'));
      assert.equal(await page.locator('.brand-byline').isVisible(),true,'Metadata returns when there is room');
      const widths=await page.locator('.server-badge').evaluateAll(nodes=>nodes.map(el=>el.getBoundingClientRect().width));
      assert.ok(Math.max(...widths)-Math.min(...widths)>3,'Pills must keep natural, unequal widths');
      assert.equal(errors.length,0);
      if(process.argv[3] && scale===1) {
        await page.setViewportSize({width:1280,height:960});
        fs.mkdirSync(path.dirname(path.resolve(process.argv[3])),{recursive:true});
        await page.locator('.record-heading').screenshot({path:process.argv[3]});
        await page.setViewportSize({width:1800,height:960});
        await page.locator('.record-heading').screenshot({path:process.argv[3]+'.wide.png'});
        await page.setViewportSize({width:820,height:960});
        await page.locator('.record-heading').screenshot({path:process.argv[3]+'.narrow.png'});
      }
      for(const count of [1,3,0]) {
        temperatureCount=count;
        await page.waitForFunction(n=>document.querySelectorAll('.gpu-temperature').length===n,count);
        for(const width of [820,980,1280,1440]) {
          await page.setViewportSize({width,height:960});await page.waitForTimeout(40);
          const boxes=await page.locator('.server-badge').evaluateAll(nodes=>nodes.map(el=>({top:el.getBoundingClientRect().top,right:el.getBoundingClientRect().right,bottom:el.getBoundingClientRect().bottom})));
          assert(boxes.every(b=>Math.abs(b.top-boxes[0].top)<.5),'Temperature badges wrap');
          assert(boxes.every(b=>b.right<=width),'Temperature badge overflows');
          assert.equal(await page.locator('.gpu-temperature').count(),count);
          if(process.argv[3] && scale===1 && count===3 && width===1280)await page.locator('.record-heading').screenshot({path:process.argv[3]+'.temperatures.png'});
        }
      }
      await context.close();
    }
    console.log('PASS: natural Mac/Linux-style pills at 5 widths / 3 scales / 7 states; stable vertical layout, metadata priority, long hosts, ellipsis and full tooltips. Native Windows resize not exercised.');
  } finally {
    if(browser) await browser.close();
    if(child.exitCode===null) {child.kill();await exited;}
    fs.rmSync(directory,{recursive:true,force:true});
  }
})().catch(error => {
  console.error('Status layout regression failed at '+phase+': '+error.message);
  process.exitCode=1;
});
