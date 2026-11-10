// Optional browser regression test: requires Node.js, Playwright and Chrome/Edge.
// node tests/ui_startup_smoke.cjs /path/to/python [chrome|msedge]
// Uses temporary settings and synthetic inputs; never opens a real patient session.
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const readline = require('node:readline');
const { chromium } = require('playwright');

const root = path.resolve(__dirname, '..');
const python = process.argv[2] || 'python3';
const channel = process.argv[3] || 'chrome';
let phase = 'browser startup';
const serverCode = `
import sys
sys.path.insert(0, sys.argv[1])
from kienzledoku_settings import run_settings
import kienzledoku_config as config
setup = sys.argv[2] == 'setup'
if setup:
    initial = config.defaults()
    initial['record']['microphone'] = 'Vorhandenes Mikrofon Ä'
    config.save(initial)
saved = run_settings(no_browser=True, setup=setup)
sys.exit(1 if setup and not saved else 0)
`;

async function scenario(browser, externalEntry, setup = false) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'record-ui-test-'));
  const child = spawn(python, ['-u', '-c', serverCode, root, setup ? 'setup' : 'settings'], {
    cwd: root,
    env: { ...process.env, KIENZLEDOKU_CONFIG_DIR: directory },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  // URLs contain private bootstrap tokens: retain neither output nor exceptions.
  child.stderr.resume();
  const exited = new Promise(resolve => child.once('close', resolve));
  let context;
  try {
    phase = 'local server startup';
    const url = await new Promise((resolve, reject) => {
      const lines = readline.createInterface({ input: child.stdout });
      const timeout = setTimeout(() => reject(new Error('Server startup timeout')), 10000);
      lines.once('line', value => { clearTimeout(timeout); lines.close(); resolve(value); });
      child.once('error', () => { clearTimeout(timeout); reject(new Error('Server startup failed')); });
      child.once('exit', () => { clearTimeout(timeout); reject(new Error('Server stopped')); });
    });
    const origin = new URL(url).origin;
    phase = externalEntry ? 'external entry' : 'initial entry';
    context = await browser.newContext();
    const page = await context.newPage();
    page.setDefaultTimeout(10000);
    const failures = [];
    page.on('pageerror', () => failures.push('script'));
    const unauthorized = await context.request.get(origin + '/');
    assert.equal(unauthorized.status(), 403);

    if (externalEntry) {
      await page.route('http://entry.invalid/', route => route.fulfill({
        contentType: 'text/html', body: '<a id="launch" href="' + url + '">Record starten</a>',
      }));
      await page.goto('http://entry.invalid/');
      await page.locator('#launch').click();
    } else {
      await page.goto(url);
    }
    await page.waitForURL(value => value.origin === origin && value.pathname === '/');
    await page.locator('h1').filter({ hasText: 'kienzledoku record' }).waitFor();
    phase = 'page and cookie checks';
    assert.match(await page.title(), setup ? /Server für die Installation/ : /Einstellungen/);
    await page.waitForFunction(() => {
      const img = document.querySelector('img');
      return img && img.complete && img.naturalWidth > 0;
    });
    assert.equal(await page.locator('img').evaluate(img => img.complete && img.naturalWidth > 0), true);
    const cookies = await context.cookies(origin);
    assert.equal(cookies.length, 1);
    assert.equal(cookies[0].httpOnly, true);
    assert.equal(cookies[0].sameSite, 'Strict');
    assert.equal(await page.evaluate(() => document.cookie), '');
    assert.equal(new URL(page.url()).search, '');
    phase = 'reload';
    await page.reload();
    phase = 'mode selection';
    await page.locator('select[name="connection.mode"]').selectOption('direct');
    if (setup) {
      phase = 'installer server entry';
      await page.locator('input[name="connection.target"]').fill('https://t2med.invalid:16567/aps/fhir/api/r4');
      for (const [name, port] of [['asr',8179], ['diarization',8183], ['llm',8080]]) {
        await page.locator('input[name="services.' + name + '"]').fill('http://synthetic.invalid:' + port);
      }
      assert.equal(await page.locator('input[name="record.microphone"]').count(), 0);
    } else {
      phase = 'microphone entry';
      await page.locator('input[name="record.microphone"]').fill('Synthetisches Testmikrofon Ä');
    }
    phase = 'save submission';
    const [saveResponse] = await Promise.all([
      page.waitForNavigation(),
      page.getByRole('button', { name: setup ? 'Speichern und Installation abschließen' : 'Speichern', exact: true }).click(),
    ]);
    const requestHeaders = await saveResponse.request().allHeaders();
    console.log('Save: HTTP ' + saveResponse.status() + ', origin ' +
      (requestHeaders.origin === origin ? 'local' : requestHeaders.origin === 'null' ? 'opaque' : 'other') +
      ', cookie ' + Boolean(requestHeaders.cookie));
    assert.equal(saveResponse.status(), 200);
    assert.equal(requestHeaders.origin, origin);
    phase = 'saved page';
    assert.match(await page.locator('.notice').innerText(), /Gespeichert/);
    const saved = fs.readFileSync(path.join(directory, 'config.toml'), 'utf8');
    assert.match(saved, setup ? /Vorhandenes Mikrofon Ä/ : /Synthetisches Testmikrofon Ä/);
    if (setup) {
      assert.match(saved, /https:\/\/t2med.invalid:16567\/aps\/fhir\/api\/r4/);
      for (const port of [8179,8183,8080]) assert.ok(saved.includes('http://synthetic.invalid:' + port));
    }
    assert.equal(await page.locator('select[name="connection.mode"]').inputValue(), 'direct');
    assert.equal(failures.length, 0);
    phase = 'close';
    if (!setup) await page.getByRole('button', { name: 'Schließen', exact: true }).click();
    const exitCode = await Promise.race([
      exited,
      new Promise((_, reject) => {
        const timeout = setTimeout(() => reject(new Error('Server did not stop')), 5000);
        exited.then(() => clearTimeout(timeout));
      }),
    ]);
    assert.equal(exitCode, 0);
    console.log((setup ? 'Installer setup' : externalEntry ? 'External entry' : 'Initial window') + ': page, cookie, logo, reload, save and close OK');
  } finally {
    if (context) await context.close();
    if (child.exitCode === null) { child.kill(); await exited; }
    fs.rmSync(directory, { recursive: true, force: true });
  }
}

(async () => {
  const browser = await chromium.launch({ channel, headless: true });
  try {
    await scenario(browser, false);
    await scenario(browser, true);
    await scenario(browser, false, true);
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error('UI startup regression failed during ' + phase + ' (' + error.name + '). Private URLs and cookie values intentionally omitted.');
  process.exitCode = 1;
});
