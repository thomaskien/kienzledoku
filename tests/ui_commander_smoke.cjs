// Commander selection/result UI with synthetic audio and patient context only.
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const readline = require('node:readline');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');

(async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'record-commander-test-'));
  fs.writeFileSync(path.join(directory, 'allow-patient'), 'synthetic');
  const child = spawn(process.argv[2] || 'python3', ['-u', 'tests/fixtures/ui_record_session.py'], {
    cwd: root,
    env: { ...process.env, KIENZLEDOKU_CONFIG_DIR: directory, KIENZLEDOKU_TEST_COMMANDER_UI: '1' },
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
      child.once('error', reject);
    });
    browser = await chromium.launch({ channel: process.argv[3] || 'chrome', headless: true });
    const page = await browser.newPage({ viewport: { width: 1280, height: 960 } });
    page.setDefaultTimeout(10000);
    const errors = [];
    page.on('pageerror', () => errors.push('script'));
    await page.goto(url);
    await page.getByRole('heading', { name: 'Aufnahme läuft', exact: true }).waitFor();
    const quality = page.getByLabel('Verarbeitungsqualität');
    await quality.selectOption('gemma12_q8');
    await page.getByRole('heading', { name: 'Aufnahme läuft', exact: true }).click();
    // At least one status refresh must preserve the user's local selection.
    await page.waitForFunction(() => document.querySelector('#processing-quality').dataset.profiles);
    assert.equal(await quality.inputValue(), 'gemma12_q8');
    await page.getByRole('button', { name: 'Aufnahme stoppen', exact: true }).click();
    await page.getByRole('button', { name: 'Aufnahme fortsetzen', exact: true }).waitFor();
    assert.equal(await page.getByLabel('Verarbeitungsqualität').inputValue(), 'gemma12_q8');
    await page.getByText('Angefordert: Gemma 4 12B Q8_0 · Erstellt mit: Basis', { exact: true }).waitFor();
    await page.getByRole('status').filter({ hasText: 'Die Dokumentation wurde mit „Basis“ erstellt.' }).waitFor();
    assert.equal(errors.length, 0);
    if (process.argv[4]) {
      fs.mkdirSync(path.dirname(path.resolve(process.argv[4])), { recursive: true });
      await page.screenshot({ path: process.argv[4], fullPage: true });
    }
    await page.getByRole('button', { name: 'Sichern und schließen', exact: true }).click();
    const timeout = setTimeout(() => child.kill(), 10000);
    const exitCode = await exited;
    clearTimeout(timeout);
    assert.equal(exitCode, 0);
    console.log('Commander UI: server model label, selection across polling, stop, actual quality and fallback notice OK');
  } finally {
    if (browser) await browser.close();
    if (child.exitCode === null) { child.kill(); await exited; }
    fs.rmSync(directory, { recursive: true, force: true });
  }
})().catch(error => {
  console.error('Commander UI regression failed (' + error.name + '). Private URLs omitted.');
  process.exitCode = 1;
});
