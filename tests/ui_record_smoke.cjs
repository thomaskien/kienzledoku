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
    cwd: root, env: { ...process.env, KIENZLEDOKU_CONFIG_DIR: directory, KIENZLEDOKU_TEST_COMMANDER_UI: "single" },
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
    await page.getByText('Verarbeitung: Basis', { exact: true }).waitFor();
    assert.equal(await page.locator('#processing-quality').count(), 0);
    phase = 'live VAD and threshold, client persistence';
    assert.equal(await page.locator('#audio-settings').evaluate(el => el.open), false);
    assert.equal(await page.locator('#vad-enabled').isVisible(), false);
    assert.equal(await page.locator('#audio-settings').evaluate(el => el.nextElementSibling.classList.contains('technical')), true);
    assert.equal(await page.locator('.primary-screen #audio-settings').count(), 0);
    await page.getByText('Aufnahme-Einstellungen', { exact: true }).click();
    phase = 'threshold handle inside transparent live meter';
    let inputLevel = -36;
    await page.route('**/status', async route => {
      const response = await route.fetch(), data = await response.json();
      data.audio_dbfs = inputLevel;
      await route.fulfill({response,json:data});
    });
    await page.waitForFunction(() => document.querySelector('#input-meter').getAttribute('aria-valuenow') === '-36');
    for (const width of [1280,520]) {
      phase = 'integrated meter geometry at '+width;
      await page.setViewportSize({width,height:960});
      await page.locator('.level-meter').scrollIntoViewIfNeeded();
      const meter = await page.locator('#input-meter').boundingBox();
      const slider = await page.locator('#silence-threshold').boundingBox();
      assert.ok(slider.y <= meter.y && slider.y+slider.height >= meter.y+meter.height,'Slider must overlay meter');
      for (const threshold of [-80,-50,-20]) {
        phase = 'integrated meter click at '+width+' / '+threshold;
        // The native handle's centre and the live fill must use the same dBFS
        // coordinates, even though the slider has narrower permitted bounds.
        const x=meter.x+meter.width*(threshold+96)/96;
        await page.mouse.click(x,slider.y+slider.height/2);
        assert.equal(await page.locator('#silence-threshold').inputValue(),String(threshold));
      }
      const transparent=await page.locator('#silence-threshold').evaluate(el => [null,'::-webkit-slider-runnable-track','::-webkit-slider-thumb'].every(pseudo=>getComputedStyle(el,pseudo).backgroundColor==='rgba(0, 0, 0, 0)'));
      assert.ok(transparent,'Slider track, progress and thumb must not cover live level');
    }
    await page.setViewportSize({width:1280,height:960});
    await page.locator('#silence-threshold').fill('-50');
    inputLevel=-72;
    await page.waitForFunction(() => document.querySelector('#input-meter').getAttribute('aria-valuenow') === '-72');
    await page.waitForFunction(() => {const el=document.querySelector('.input-meter-fill');return Math.round(el.getBoundingClientRect().width/el.parentElement.getBoundingClientRect().width*100)===25;});
    inputLevel=-24;
    await page.waitForFunction(() => document.querySelector('#input-meter').getAttribute('aria-valuenow') === '-24');
    await page.waitForFunction(() => {const el=document.querySelector('.input-meter-fill');return Math.round(el.getBoundingClientRect().width/el.parentElement.getBoundingClientRect().width*100)===75;});
    assert.equal(await page.locator('#silence-threshold').inputValue(),'-50','Live level must not move the threshold');
    if(process.argv[4]) await page.locator('#audio-settings').screenshot({path:process.argv[4]});
    await page.unroute('**/status');
    phase = 'live VAD and threshold, client persistence';
    await page.locator('#vad-enabled').uncheck();
    await page.locator('#silence-threshold').fill('-62');
    await page.waitForFunction(() => document.querySelector('#audio-controls-message').textContent.includes('Für diesen Client gespeichert'));
    let state = await (await page.request.get(new URL('/status', page.url()).href)).json();
    assert.equal(state.vad_enabled, false); assert.equal(state.silence_threshold_dbfs, -62);
    assert.match(fs.readFileSync(path.join(directory, 'config.toml'), 'utf8'), /silence_threshold_dbfs = -62/);
    await page.locator('#silence-threshold').focus();
    await page.keyboard.press('ArrowRight');
    await page.waitForFunction(() => document.querySelector('#audio-controls-message').textContent.includes('Für diesen Client gespeichert'));
    assert.equal(await page.locator('#silence-threshold').inputValue(), '-61');
    await page.reload();
    assert.equal(await page.locator('#audio-settings').evaluate(el => el.open), false);
    await page.getByText('Aufnahme-Einstellungen', { exact: true }).click();
    assert.equal(await page.locator('#vad-enabled').isChecked(), false);
    assert.equal(await page.locator('#silence-threshold').inputValue(), '-61');
    await page.locator('#vad-enabled').check();
    await page.waitForFunction(() => document.querySelector('#audio-controls-message').textContent.includes('Für diesen Client gespeichert'));
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
    assert.equal(await page.locator('#audio-settings').count(), 0);
    assert.equal(await page.locator('#silence-threshold').count(), 0);
    // Status polling must still work without the recording-only controls.
    await page.route('**/status', async route => {
      const response = await route.fetch(); const data = await response.json();
      data.services.asr.status = 'ready';
      await route.fulfill({ response, json: data });
    });
    await page.waitForFunction(() => document.querySelector('#asr-server').classList.contains('ready'));
    await page.unroute('**/status');
    await page.getByRole('button', { name: 'Aufnahme starten', exact: true }).click();
    await page.getByRole('heading', { name: 'Aufnahme läuft', exact: true }).waitFor();
    assert.equal(await page.locator('#audio-settings').evaluate(el => el.open), false);
    assert.equal(await page.locator('#silence-threshold').inputValue(), '-61');
    await page.getByRole('button', { name: 'Aufnahme stoppen', exact: true }).click();
    await page.getByRole('button', { name: 'Aufnahme starten', exact: true }).waitFor();
    assert.equal(await page.locator('#audio-settings').count(), 0);
    await page.getByText('Technische Informationen', { exact: true }).click();
    await page.getByRole('button', { name: 'Patient neu laden', exact: true }).click();
    await page.getByRole('button', { name: 'Aufnahme starten', exact: true }).waitFor();
    assert.equal(errors.length, 0);
    phase = 'close';
    page.once('dialog', dialog => dialog.dismiss());
    await page.getByRole('button', { name: 'Fenster schließen und verwerfen', exact: true }).click();
    assert.equal(child.exitCode, null);
    assert.equal((await page.request.get(new URL('/status', page.url()).href)).status(), 200);
    page.once('dialog', dialog => dialog.accept());
    await page.getByRole('button', { name: 'Fenster schließen und verwerfen', exact: true }).click();
    const timeout = setTimeout(() => child.kill(), 10000);
    const exitCode = await exited;
    clearTimeout(timeout);
    assert.equal(exitCode, 0);
    console.log('Record UI: transparent threshold handle inside live meter, matching scale at two widths, keyboard/client persistence, recording-only controls, stop/restart and close OK');
  } finally {
    if (browser) await browser.close();
    if (child.exitCode === null) { child.kill(); await exited; }
    fs.rmSync(directory, { recursive: true, force: true });
  }
})().catch(error => {
  console.error('Record UI regression failed during ' + phase + ' (' + error.name + '). Private URLs omitted.');
  if (error.name === 'AssertionError') console.error(error.message);
  process.exitCode = 1;
});
