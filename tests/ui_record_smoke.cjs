// Optional browser regression for the real session/UI with synthetic audio and FHIR.
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const readline = require('node:readline');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');
let phase = 'startup';

(async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'record-live-test-'));
  const child = spawn(process.argv[2] || 'python3', ['-u', 'tests/fixtures/ui_record_session.py'], {
    cwd: root, env: { ...process.env, KIENZLEDOKU_CONFIG_DIR: directory },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  child.stderr.resume();
  const exited = new Promise(resolve => child.once('close', resolve));
  let browser;
  try {
    const url = await new Promise((resolve, reject) => {
      const lines = readline.createInterface({ input: child.stdout });
      const timer = setTimeout(() => reject(new Error('Startup timeout')), 10000);
      lines.once('line', value => { clearTimeout(timer); lines.close(); resolve(value); });
      child.once('exit', () => { clearTimeout(timer); reject(new Error('Server stopped')); });
      child.once('error', () => { clearTimeout(timer); reject(new Error('Server failed')); });
    });
    browser = await chromium.launch({ channel: process.argv[3] || 'chrome', headless: true });
    const page = await browser.newPage();
    page.setDefaultTimeout(10000);
    const errors = [];
    page.on('pageerror', () => errors.push('script'));
    phase = 'automatic recording before patient response';
    await page.goto(url);
    await page.getByRole('heading', { name: 'Aufnahme läuft', exact: true }).waitFor();
    await page.waitForFunction(() => document.querySelector('#live-transcript').value.includes('Übelkeit'));
    assert.equal(await page.locator('#patient-name').innerText(), 'Patient wird geladen …');
    assert.equal(await page.locator('#live-transcript').inputValue(), 'Ärztliche Äußerung: Öl, Füße, Übelkeit – α.');
    phase = 'patient arrives while recording continues';
    await page.evaluate(() => { window.syntheticUnchangedPage = true; });
    fs.writeFileSync(path.join(directory, 'allow-patient'), 'synthetic');
    await page.waitForFunction(() => document.querySelector('#patient-name').textContent === 'Testperson, ÄÖÜ');
    assert.equal(await page.locator('#patient-birth').innerText(), '02.01.2000');
    assert.equal(await page.locator('#patient-error').isVisible(), false);
    assert.equal(await page.evaluate(() => window.syntheticUnchangedPage), true);
    phase = 'stop without automatic restart';
    await page.getByRole('button', { name: 'Aufnahme stoppen', exact: true }).click();
    await page.getByRole('button', { name: 'Aufnahme starten', exact: true }).waitFor();
    await page.getByText('Technische Informationen', { exact: true }).click();
    await page.getByRole('button', { name: 'Patient neu laden', exact: true }).click();
    await page.getByRole('button', { name: 'Aufnahme starten', exact: true }).waitFor();
    assert.equal(errors.length, 0);
    phase = 'close';
    await page.getByRole('button', { name: 'Sichern und schließen', exact: true }).click();
    const timeout = setTimeout(() => child.kill(), 10000);
    const exitCode = await exited;
    clearTimeout(timeout);
    assert.equal(exitCode, 0);
    console.log('Record UI: immediate capture, live umlauts, delayed patient, stop, reload and close OK');
  } finally {
    if (browser) await browser.close();
    if (child.exitCode === null) { child.kill(); await exited; }
    fs.rmSync(directory, { recursive: true, force: true });
  }
})().catch(error => {
  console.error('Record UI regression failed during ' + phase + ' (' + error.name + '). Private URLs omitted.');
  process.exitCode = 1;
});
