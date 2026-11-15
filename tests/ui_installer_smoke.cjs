// Browser smoke test for the macOS installer UI. It starts an in-process HTTP
// fixture and never executes the installer backend or changes the machine.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const root = process.env.KIENZLEDOKU_UI_ROOT || path.resolve(__dirname, '..');
const uiPath = path.join(root, 'installer', 'ui.html');
const bootstrapPath = path.join(__dirname, 'fixtures', 'installer_bootstrap.json');
const artifactDirectory = '/private/tmp/kienzledoku-installer-ui-140';
const bootstrap = JSON.parse(fs.readFileSync(bootstrapPath, 'utf8'));
bootstrap.defaults.hf_token = 'hf_synthetic_installer_prefill';
let phase = 'HTTP fixture startup';
const connectURL = 'kienzledoku://record?kontextId=${kontextId}&fhirBasisUrl=${fhirBasisUrl}&oAuthToken=${oAuthToken}';
const directURL = connectURL.replace('kienzledoku:', 'kienzledoku-record:');

function makeFixture() {
  let installedConfig = null;
  let statusCalls = 0;
  let uninstallStatusCalls = 0;
  let uninstallStarted = false;
  let cancelled = false;
  const requests = [];
  const handle = async route => {
    const request = route.request();
    const url = new URL(request.url());
    const method = request.method();
    const fulfillJSON = (status, body) => route.fulfill({
      status,
      contentType: 'application/json; charset=utf-8',
      headers: { 'Cache-Control': 'no-store' },
      body: JSON.stringify(body),
    });
    const fulfillFile = (filename, contentType) => route.fulfill({
      status: 200,
      contentType,
      headers: { 'Cache-Control': 'no-store' },
      body: fs.readFileSync(filename),
    });
    try {
      if (method === 'GET' && (url.pathname === '/' || url.pathname === '/installer/ui.html')) {
        return fulfillFile(uiPath, 'text/html; charset=utf-8');
      }
      if (method === 'GET' && url.pathname === '/assets/kienzledoku-record.svg') {
        return fulfillFile(path.join(root, 'assets', 'kienzledoku-record.svg'), 'image/svg+xml');
      }
      if (method === 'GET' && url.pathname === '/assets/t2med-drittanbieter-suche.png') {
        return fulfillFile(path.join(root, 'docs', 'images', 't2med-drittanbieter-suche.png'), 'image/png');
      }
      if (method === 'GET' && url.pathname === '/assets/t2med-drittanbieter-url.png') {
        return fulfillFile(path.join(root, 'docs', 'images', 't2med-drittanbieter-url.png'), 'image/png');
      }
      if (method === 'GET' && ['/assets/t2med-produktcode-aktivieren.png', '/assets/t2med-produktcode-kienzledoku.png', '/assets/t2med-kienzledoku-aktiv.png'].includes(url.pathname)) {
        return fulfillFile(path.join(root, 'docs', 'images', path.basename(url.pathname)), 'image/png');
      }
      if (method === 'GET' && url.pathname === '/api/bootstrap') {
        installedConfig = null; statusCalls = 0; uninstallStatusCalls = 0; uninstallStarted = false; cancelled = false;
        return fulfillJSON(200, bootstrap);
      }
      if (method === 'GET' && url.pathname === '/api/uninstall') {
        return fulfillJSON(200, { client: true, server: true, models: true, settings: true, unsafe: [], status: { running: false, done: false, error: '', progress: 0, logs: [] } });
      }
      if (method === 'GET' && url.pathname === '/api/uninstall/status') {
        uninstallStatusCalls++;
        const done = uninstallStarted && uninstallStatusCalls >= 2;
        return fulfillJSON(200, { running: uninstallStarted && !done, done, error: '', progress: done ? 100 : 55, message: done ? 'Deinstallation abgeschlossen' : 'Programmverknüpfungen entfernen', logs: done ? ['Programmverknüpfungen entfernt', 'Deinstallation abgeschlossen'] : ['Deinstallation vorbereiten'] });
      }
      if (method === 'GET' && url.pathname === '/api/status') {
        statusCalls++;
        if (cancelled) return fulfillJSON(200, { running: false, done: false, error: 'Installation abgebrochen.', step: 'Abbruch', message: 'Abgebrochen', progress: 20, logs: ['Abbruch bestätigt'], client_installed: false, commander_url: '', server_token: '', launch_url: '' });
        const done = statusCalls >= 3;
        return fulfillJSON(200, {
          running: !done,
          done,
          error: '',
          step: done ? 'Fertig' : statusCalls === 1 ? 'Download' : 'Einrichtung',
          message: done ? 'Installation abgeschlossen' : statusCalls === 1 ? 'Modelle werden vorbereitet …' : 'Dienste werden eingerichtet …',
          progress: done ? 100 : statusCalls * 42,
          logs: done ? ['Pakete geprüft', 'Konfiguration gespeichert', 'Installation abgeschlossen'] : ['Pakete geprüft', 'Schritt ' + statusCalls + ' läuft'],
          client_installed: Boolean(installedConfig && installedConfig.mode !== 'server'),
          commander_url: installedConfig && installedConfig.mode !== 'client' ? 'http://praxis-mac.local:8185' : '',
          server_token: installedConfig && installedConfig.auth_enabled ? installedConfig.server_token : '',
          launch_url: installedConfig && installedConfig.connection_mode === 'direct'
            ? directURL : connectURL,
        });
      }
      if (method === 'POST' && url.pathname.startsWith('/api/')) {
        if (request.headers()['x-csrf-token'] !== bootstrap.csrf) return fulfillJSON(400, { error: 'CSRF-Token fehlt.' });
        const body = request.postDataJSON() || {};
        requests.push({ path: url.pathname, body });
        if (url.pathname === '/api/validate') {
          if (!body.mode) return fulfillJSON(400, { error: 'Bitte Komponenten auswählen.' });
          return fulfillJSON(200, {
            summary: [
              body.mode === 'server' ? 'Nur Server wird installiert.' : body.mode === 'client' ? 'Nur Client wird installiert.' : 'Client und Server werden installiert.',
              (body.selected_models || []).length + ' lokale Modelle ausgewählt.',
              (body.fields || []).length + ' Dokumentationsfelder aktiv.',
            ],
            download_bytes: body.mode === 'client' ? 120000000 : 20200000000,
          });
        }
        if (url.pathname === '/api/install') {
          installedConfig = body; statusCalls = 0;
          return fulfillJSON(200, { started: true });
        }
        if (url.pathname === '/api/uninstall') {
          uninstallStarted = true; uninstallStatusCalls = 0;
          return fulfillJSON(200, { started: true });
        }
        if (url.pathname === '/api/probe') {
          return fulfillJSON(200, {
            profiles: [{ id: 'standard', label: 'Standard', model_label: 'Gemma 3 12B Q8' }],
            fields: ['anamnese', 'befund', 'therapie', 'prozedere'],
            prompt: bootstrap.default_prompt,
          });
        }
        if (url.pathname === '/api/token') return fulfillJSON(200, { token: 'fixture-random-server-token' });
        if (url.pathname === '/api/cancel') { cancelled = true; return fulfillJSON(200, { cancelled: true }); }
      }
      return route.fulfill({ status: 404, body: 'Not found' });
    } catch (_) {
      return fulfillJSON(500, { error: 'Fixture-Fehler' });
    }
  };
  return { handle, requests };
}

async function clickNext(page) {
  await page.getByRole('button', { name: 'Weiter', exact: true }).click();
}

async function mainScenario(browser, origin, fixture) {
  const context = await browser.newContext({ viewport: { width: 1080, height: 820 }, deviceScaleFactor: 1 });
  await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin });
  const page = await context.newPage();
  await page.route(origin + '/**', fixture.handle);
  page.setDefaultTimeout(10000);
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  try {
    phase = 'initial installer page';
    await page.goto(origin);
    await page.getByRole('heading', { name: 'Was möchten Sie einrichten?' }).waitFor();
    assert.equal(await page.locator('#version').innerText(), 'Version ' + bootstrap.version + ' · arm64 · 32 GB RAM');
    assert.equal(await page.locator('#hf_token').getAttribute('type'), 'password');
    assert.equal(await page.locator('#hf_token').inputValue(), 'hf_synthetic_installer_prefill');
    await page.screenshot({ path: path.join(artifactDirectory, '01-komponenten.png'), fullPage: true });

    phase = 'mode switching and optional tokens';
    await page.locator('input[name="mode"][value="client"]').check();
    assert.equal(await page.locator('#server-role-panel').isVisible(), false);
    await clickNext(page);
    assert.equal(await page.locator('#client-connections').isVisible(), true);
    assert.equal(await page.locator('#server-connections').isVisible(), false);
    assert.equal(await page.locator('#commander_token').getAttribute('type'), 'password');
    assert.equal(await page.locator('#commander_token').inputValue(), '');
    await page.getByRole('button', { name: 'Zurück' }).click();
    await page.locator('input[name="mode"][value="combined"]').check();
    await clickNext(page);
    assert.equal(await page.locator('#auth_enabled').isChecked(), false);
    assert.equal(await page.locator('#server-token-area').isVisible(), false);
    assert.equal(await page.locator('#remote_llm_token').inputValue(), '');
    await page.screenshot({ path: path.join(artifactDirectory, '02-verbindungen.png'), fullPage: true });

    phase = 'model selection and active mapping';
    await clickNext(page);
    assert.equal(await page.locator('#diarization_mode').inputValue(), 'serial');
    assert.equal(await page.locator('#diarization_mode option').count(), 3);
    await page.locator('#diarization_mode').selectOption('resident');
    await page.locator('#diarization_mode').selectOption('with_asr');
    assert.match(await page.locator('#diarization-mode-field').innerText(), /6 GB Arbeitsreserve/);
    await page.locator('#diarization').uncheck();
    assert.equal(await page.locator('#diarization-mode-field').isVisible(), false);
    await page.locator('#diarization').check();
    assert.equal(await page.locator('#diarization_mode').inputValue(), 'with_asr');
    const unsupported = page.locator('.model', { hasText: 'Großes 70B-Modell' });
    assert.equal(await unsupported.locator('input').isDisabled(), true);
    assert.match(await unsupported.innerText(), /mindestens 64 GB RAM/);
    const detailed = page.locator('#model-list input[value="27b-q4"]');
    await detailed.uncheck();
    assert.equal(await page.locator('#quality-sehr_gruendlich option').count(), 0);
    await detailed.check();
    assert.equal(await page.locator('#quality-sehr_gruendlich').inputValue(), '27b-q4');
    await page.screenshot({ path: path.join(artifactDirectory, '03-modelle.png'), fullPage: true });
    await page.locator('#diarization-mode-field').scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(artifactDirectory, '03-diarisierung.png'), fullPage: true });

    phase = 'field choice, order and prompt reset';
    await clickNext(page);
    const ekg = page.locator('#field-list input[value="ekg"]');
    await ekg.check();
    const before = await page.locator('#field-list input[type="checkbox"]:checked').evaluateAll(elements => elements.map(element => element.value));
    await page.locator('#prompt').fill('Ein absichtlich veränderter Testprompt.');
    await page.getByRole('button', { name: 'Standardprompt wiederherstellen' }).click();
    assert.equal(await page.locator('#prompt').inputValue(), bootstrap.default_prompt);
    const after = await page.locator('#field-list input[type="checkbox"]:checked').evaluateAll(elements => elements.map(element => element.value));
    assert.deepEqual(after, before);
    await page.screenshot({ path: path.join(artifactDirectory, '04-dokumentation.png'), fullPage: true });

    phase = 'validation and explicit install';
    await clickNext(page);
    await page.getByRole('heading', { name: 'Bereit zur Installation' }).waitFor();
    assert.match(await page.locator('#summary-list').innerText(), /Client und Server/);
    assert.match(await page.locator('#download-size').innerText(), /Download/);
    const validates = fixture.requests.filter(request => request.path === '/api/validate');
    assert.equal(validates.length, 1);
    assert.equal(validates[0].body.fields.includes('ekg'), true);
    assert.equal(validates[0].body.commander_token, '');
    assert.equal(validates[0].body.diarization_mode, 'with_asr');
    await page.screenshot({ path: path.join(artifactDirectory, '05-zusammenfassung.png'), fullPage: true });

    await page.getByRole('button', { name: 'Installieren', exact: true }).click();
    await page.getByRole('heading', { name: 'Installation läuft' }).waitFor();
    assert.equal(fixture.requests.filter(request => request.path === '/api/install').length, 1);
    await page.screenshot({ path: path.join(artifactDirectory, '06-fortschritt.png'), fullPage: true });

    phase = 'completed install and T2med guide';
    await page.getByRole('heading', { name: 'Installation abgeschlossen' }).waitFor();
    assert.equal(await page.locator('#client-guide').isVisible(), true);
    assert.equal(await page.locator('#server-finish').isVisible(), true);
    assert.equal(await page.locator('#launch-url').innerText(), connectURL);
    assert.match(await page.locator('#client-guide').innerText(), /Drittanbieter-Zugriffe verwalten/);
    assert.match(await page.locator('#client-guide').innerText(), /kienzledoku record/);
    assert.match(await page.locator('#docs-link').getAttribute('href'), /README\.md#t2med-einrichten-und-verwenden$/);
    await page.locator('[data-copy-target="launch-url"]').click();
    await page.getByRole('button', { name: 'Kopiert', exact: true }).waitFor();
    assert.equal(await page.evaluate(() => navigator.clipboard.readText()), connectURL);
    await page.screenshot({ path: path.join(artifactDirectory, '07-erfolg.png'), fullPage: true });
    await page.locator('img[src="/assets/t2med-produktcode-aktivieren.png"]').scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(artifactDirectory, '07-produktcode-aktivierung.png'), fullPage: true });
    const urlBox = await page.locator('#launch-url').evaluate(e => ({ width: e.clientWidth, scrollWidth: e.scrollWidth, height: e.clientHeight, scrollHeight: e.scrollHeight }));
    assert.ok(urlBox.scrollWidth <= urlBox.width + 1 && urlBox.scrollHeight <= urlBox.height + 1, 'Full URL must wrap without scrollbars');
    await page.getByRole('button', { name: 'Fenster schließen', exact: true }).waitFor();
    await page.evaluate(() => { window.installerMessages = []; window.webkit = { messageHandlers: { installer: { postMessage: message => window.installerMessages.push(message) } } }; });
    await page.getByRole('button', { name: 'Fenster schließen', exact: true }).click();
    assert.deepEqual(await page.evaluate(() => window.installerMessages), [{ action: 'close' }]);
    assert.deepEqual(pageErrors, []);
  } finally {
    await context.close();
  }
}

async function serverOnlyScenario(browser, origin, fixture) {
  const context = await browser.newContext({ viewport: { width: 1080, height: 820 } });
  const page = await context.newPage();
  await page.route(origin + '/**', fixture.handle);
  page.setDefaultTimeout(10000);
  try {
    phase = 'server-only finish';
    await page.goto(origin);
    await page.getByRole('heading', { name: 'Was möchten Sie einrichten?' }).waitFor();
    await page.locator('input[name="mode"][value="server"]').check();
    await clickNext(page);
    assert.equal(await page.locator('#client-connections').isVisible(), false);
    await clickNext(page);
    await clickNext(page);
    await clickNext(page);
    await page.getByRole('button', { name: 'Installieren', exact: true }).click();
    await page.getByRole('heading', { name: 'Installation abgeschlossen' }).waitFor();
    assert.equal(await page.locator('#client-guide').isVisible(), false);
    assert.equal(await page.locator('#server-finish').isVisible(), true);
    assert.equal(await page.getByText('T2med jetzt verbinden').count(), 1);
    await page.screenshot({ path: path.join(artifactDirectory, '08-server-only.png'), fullPage: true });
  } finally {
    await context.close();
  }
}

async function uninstallScenario(browser, origin, fixture) {
  const context = await browser.newContext({ viewport: { width: 1080, height: 820 } });
  const page = await context.newPage();
  await page.route(origin + '/**', fixture.handle);
  page.setDefaultTimeout(10000);
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  try {
    phase = 'uninstaller selection and confirmation';
    await page.goto(origin);
    await page.getByRole('heading', { name: 'Was möchten Sie einrichten?' }).waitFor();
    await page.getByRole('button', { name: 'Deinstallieren …' }).click();
    await page.getByRole('heading', { name: 'Kienzledoku deinstallieren' }).waitFor();
    await page.waitForFunction(() => document.querySelector('#uninstall-detection').textContent.includes('Client und Server erkannt'));
    assert.ok((await page.locator('#uninstall-page').boundingBox()).width > 700, 'Uninstaller must use the available width after hiding the sidebar');
    assert.match(await page.locator('#uninstall-detection').innerText(), /Client und Server erkannt/);
    assert.equal(await page.locator('input[name="uninstall_mode"][value="both"]').isChecked(), true);
    assert.equal(await page.locator('#keep-models').isChecked(), true);
    assert.equal(await page.locator('#keep-settings').isChecked(), true);
    assert.match(await page.locator('#uninstall-summary').innerText(), /Modelle.*bleiben erhalten/s);
    assert.equal(await page.getByRole('button', { name: 'Deinstallieren', exact: true }).isDisabled(), true);
    await page.locator('#keep-models').uncheck();
    await page.locator('#confirm-uninstall').check();
    await page.locator('main').evaluate(element => { element.scrollTop = 0; });
    await page.screenshot({ path: path.join(artifactDirectory, '09-deinstallation-auswahl.png'), fullPage: true });
    await page.evaluate(() => { window.installerMessages = []; window.webkit = { messageHandlers: { installer: { postMessage: message => window.installerMessages.push(message) } } }; });
    await page.getByRole('button', { name: 'Deinstallieren', exact: true }).click();
    await page.getByRole('heading', { name: 'Deinstallation läuft' }).waitFor();
    const requests = fixture.requests.filter(request => request.path === '/api/uninstall');
    assert.deepEqual(requests.at(-1).body, { remove_client: true, remove_server: true, remove_models: true, remove_settings: false });
    await page.getByRole('heading', { name: 'Deinstallation abgeschlossen' }).waitFor();
    assert.deepEqual(await page.evaluate(() => window.installerMessages.slice(0, 2)), [{ action: 'busy', value: true }, { action: 'busy', value: false }]);
    await page.getByRole('button', { name: 'Fenster schließen', exact: true }).click();
    assert.deepEqual((await page.evaluate(() => window.installerMessages)).at(-1), { action: 'close' });
    assert.deepEqual(pageErrors, []);
  } finally {
    await context.close();
  }
}

(async () => {
  fs.mkdirSync(artifactDirectory, { recursive: true });
  const fixture = makeFixture();
  // Loopback is a secure browser context (needed for the Clipboard API). Every
  // request is fulfilled by page.route above, so no process listens on this port.
  const origin = 'http://127.0.0.1:41731';
  let browser;
  try {
    phase = 'browser startup';
    browser = await chromium.launch({ channel: process.argv[2] || 'chrome', headless: true });
    await mainScenario(browser, origin, fixture);
    await serverOnlyScenario(browser, origin, fixture);
    await uninstallScenario(browser, origin, fixture);
    console.log('Installer UI: installation flows and explicit safe uninstaller flow OK');
    console.log('Screenshots: ' + artifactDirectory);
  } finally {
    if (browser) await browser.close();
  }
})().catch(error => {
  console.error('Installer UI smoke failed during ' + phase + ': ' + error.message);
  process.exitCode = 1;
});
