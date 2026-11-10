"""Graphical setup without Connect or a patient session."""
import copy
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
import shutil
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

import kienzledoku_config as config
from kienzledoku_commander_client import configured_client
from kienzledoku_http import SecureLocalHandler, configure_server

FIELDS = [
 ('connection', 'mode', 'FHIR-Verbindung', 'mode'),
 ('connection', 'target', 'T2med-FHIR-Basis (genaues HTTPS-Ziel)', 'text'),
 ('connection', 'ca_file', 'CA-Zertifikat (PEM-Dateipfad, optional)', 'text'),
 ('connection', 'allow_insecure_tls', 'Lokales T2med-Zertifikat ohne Prüfung akzeptieren', 'checkbox'),
 ('commander', 'enabled', 'Commander für alle KI-Dienste verwenden', 'checkbox'),
 ('commander', 'url', 'Commander-Adresse', 'text'),
 ('services', 'asr', 'ASR-Adresse', 'text'),
 ('services', 'diarization', 'Sprechertrennung-Adresse', 'text'),
 ('services', 'llm', 'LLM-Adresse', 'text'),
 ('record', 'diarization', 'Sprechertrennung verwenden', 'checkbox'),
 ('record', 'microphone', 'Mikrofon (leer = Standard; Auswahl auch in der Aufnahme)', 'text'),
 ('record', 'output_mode', 'Dokumentationsformat', 'output'),
 ('record', 'single_code', 'Kürzel für Freitext', 'text'),
]


def run_settings(no_browser=False, window_opener=None, setup=False):
    try:
        initial, message = config.load(), ''
    except (ValueError, OSError) as exc:
        initial, message = config.defaults(), 'Einstellungen konnten nicht gelesen werden: %s. Angezeigt werden Standardwerte; die vorhandene Datei wird erst beim Speichern ersetzt.' % exc
    state = {'config': initial, 'message': message, 'last': time.monotonic(), 'devices': []}
    fields_to_show = [field for field in FIELDS if not setup or field[0] in ('connection', 'commander', 'services')]
    saved = False
    csrf = secrets.token_urlsafe(32)
    stopped = threading.Event()
    class Handler(SecureLocalHandler, BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def page(self):
            fields = []
            for section, key, label, kind in fields_to_show:
                value = state['config'][section][key]
                name = section + '.' + key
                if kind == 'checkbox':
                    marker = '<input type="hidden" name="%s-present" value="1">' % name if section == 'commander' else ''
                    control = marker + '<input type="checkbox" name="%s" %s>' % (name, 'checked' if value else '')
                elif key == 'microphone' and state['devices']:
                    values = [('', 'System-Standardgerät')] + [(d['index'], d['name']) for d in state['devices']]
                    if value and value not in [k for k, _ in values]:
                        values.append((value, 'Gespeichertes Gerät (derzeit nicht verfügbar)'))
                    control = '<select name="%s">%s</select>' % (name, ''.join('<option value="%s" %s>%s</option>' % (html.escape(k,quote=True), 'selected' if value == k else '', html.escape(v)) for k, v in values))
                elif kind in ('mode', 'output'):
                    values = [('direct', 'Direktbetrieb'), ('connect', 'Über Connect')] if kind == 'mode' else [('structured', 'Vier Einträge'), ('single', 'Ein Freitext')]
                    control = '<select name="%s">%s</select>' % (name, ''.join('<option value="%s" %s>%s</option>' % (k, 'selected' if value == k else '', v) for k, v in values))
                else:
                    control = '<input name="%s" value="%s">' % (name, html.escape(value, quote=True))
                fields.append('<label>%s%s</label>' % (label, control))
            heading = 'Server für die Installation einrichten' if setup else 'Einstellungen'
            explanation = ('Bitte T2med und Commander eintragen. Die bisherigen einzelnen KI-Dienstadressen bleiben für deaktivierten Commander erhalten. '
                           'Mit „Speichern und Installation abschließen“ werden diese Werte übernommen. '
                           'Spätere Änderungen sind über kienzledoku record im Startmenü möglich.') if setup else ''
            buttons = ('<button name="action" value="save">Speichern und Installation abschließen</button>'
                       '<button name="action" value="check">KI-Dienste prüfen</button>'
                       '<button name="action" value="close">Abbrechen</button>') if setup else (
                       '<button name="action" value="save">Speichern</button>'
                       '<button name="action" value="check">KI-Dienste prüfen</button>'
                       '<button name="action" value="devices">Mikrofone anzeigen</button>'
                       '<button name="action" value="audio_test">Mikrofon 3 Sekunden testen</button>'
                       '<button name="action" value="close">Schließen</button>')
            key_field = '<label>Commander-Zugang (leer = unverändert)<input type="password" name="commander_token" autocomplete="new-password"></label>'
            if not setup:
                key_field += '<label>Eigener API-Key für Direktbetrieb (leer = unverändert)<input type="password" name="direct_key" autocomplete="new-password"></label>'
            data = ('''<!doctype html><html lang="de"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>kienzledoku record 1.3.3 – %s</title><style>
body{font:16px system-ui;margin:32px auto;padding:0 24px;max-width:760px;background:#f2f3f5;color:#172536}
header{display:flex;gap:20px;align-items:center}img{width:96px}h1{font-size:26px}form{background:white;padding:24px;border-radius:16px}
label{display:block;margin:15px 0}input:not([type=checkbox]),select{display:block;width:100%%;box-sizing:border-box;padding:10px;margin-top:6px}
button{padding:12px 16px;margin:8px 4px 0 0}p{line-height:1.5}.notice{white-space:pre-wrap}</style>
<header><img src="/logo.svg" alt=""><div><h1>kienzledoku record 1.3.3</h1><p>%s</p></div></header>
<p>%s</p><p class="notice">%s</p><form method="post"><input type="hidden" name="csrf" value="%s">%s%s
<p>Ohne eigenen Key wird der öffentliche Demo-Key verwendet. Connect ersetzt jeden mitgesendeten Key durch seinen eingebetteten Key.
Die Zertifikatsausnahme betrifft ausschließlich das eingetragene T2med-Ziel. Änderungen gelten für den nächsten Patientenvorgang.</p>
%s</form>
<script>window.addEventListener('kienzledoku-close-request',()=>{window.close();});</script></html>'''
                    % (heading, heading, explanation, html.escape(state['message']), csrf, ''.join(fields), key_field, buttons)).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            # Keep the local Origin on form POSTs. no-referrer makes Chromium
            # send Origin: null, which our strict local authorization rejects.
            self.send_header('Referrer-Policy', 'same-origin')
            self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; frame-ancestors 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(data)
        def do_GET(self):
            if not self.authorize():
                return
            state['last'] = time.monotonic()
            if self.path == '/logo.svg':
                data = Path(__file__).with_name('assets').joinpath('kienzledoku-record.svg').read_bytes()
                self.send_response(200); self.send_header('Content-Type', 'image/svg+xml')
                self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
            else:
                self.page()
        def do_POST(self):
            nonlocal saved
            if not self.authorize():
                return
            state['last'] = time.monotonic()
            try:
                form = self.read_form()
                if not secrets.compare_digest(form.get('csrf', [''])[0], csrf):
                    self.send_error(403); return
                action = form.get('action', [''])[0]
                if action == 'close':
                    state['message'] = 'Einstellungen geschlossen. Dieses Fenster kann geschlossen werden.'
                    self.page(); stopped.set(); return
                candidate = copy.deepcopy(state['config'])
                for section, key, _label, kind in fields_to_show:
                    if section == 'commander' and key == 'enabled' and section + '.' + key + '-present' not in form:
                        continue
                    if section + '.' + key not in form and kind != 'checkbox':
                        continue
                    raw = form.get(section + '.' + key, [''])[0]
                    candidate[section][key] = bool(raw) if kind == 'checkbox' else raw.strip()
                config.validate(candidate)
                if action == 'save':
                    if not setup and form.get('direct_key', [''])[0]:
                        config.store_direct_key(form['direct_key'][0])
                    if form.get('commander_token', [''])[0]:
                        config.store_commander_token(form['commander_token'][0])
                        candidate['commander']['token_file'] = ''
                    config.save(candidate); state['config'] = candidate
                    state['message'] = 'Gespeichert. T2med-Aufruf: ' + ('kienzledoku://record' if candidate['connection']['mode'] == 'connect' else 'kienzledoku-record://record')
                    saved = True
                    if setup:
                        self.page()
                        stopped.set()
                        return
                elif action == 'check':
                    state['config'] = candidate
                    lines = []
                    commander = configured_client(candidate['commander'],
                        token_override=form.get('commander_token', [''])[0] or None)
                    if commander:
                        try:
                            profiles = commander.profiles()
                            commander.request('/health', timeout=3)
                            lines.append('Commander: OK (%d Qualitätsprofile)' % len(profiles))
                        except Exception as exc:
                            lines.append('Commander: ' + str(exc))
                        if form.get('commander_token', [''])[0]:
                            lines.append('Der eingegebene Zugang wurde nur geprüft. Zum Speichern erneut eingeben.')
                    else:
                        for name, base in candidate['services'].items():
                            suffix = '/v1/models' if name == 'llm' and not base.rstrip('/').endswith('/v1') else ('/models' if name == 'llm' else '/health')
                            try:
                                with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(base.rstrip('/') + suffix, timeout=3) as response:
                                    lines.append(name + ': ' + ('OK' if response.status == 200 else 'nicht bereit'))
                            except Exception:
                                lines.append(name + ': nicht erreichbar')
                    state['message'] = '\n'.join(lines)
                elif not setup and action in ('devices', 'audio_test'):
                    import sounddevice as sd
                    from kienzledoku_audio import devices, create_input
                    state['devices'] = devices(sd)
                    state['config'] = candidate
                    state['message'] = '%d Audioeingänge verfügbar. Auswahl anschließend speichern.' % len(state['devices'])
                    if action == 'audio_test':
                        # Discard all samples: this test sends no audio to any service.
                        levels = []
                        def level(event, **data):
                            if event == 'audio_level': levels.append(data['rms'])
                        stream, failure = create_input(sd, candidate['record']['microphone'], lambda pcm: None, level)
                        with stream:
                            time.sleep(3)
                        if failure: raise ValueError(failure[0])
                        peak = max(levels or [0])
                        state['message'] = 'Mikrofontest: %s (Pegel %d / 32768). Audio wurde verworfen.' % ('Signal erkannt' if peak > 50 else 'kein deutliches Signal', peak)
                else:
                    raise ValueError('Unbekannte Aktion')
            except Exception as exc:
                state['message'] = 'Nicht gespeichert: ' + str(exc)
            self.page()
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    url = configure_server(server)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    ui = None
    try:
        if no_browser:
            print(url, flush=True)
        elif window_opener:
            ui, _ = window_opener(url, str(Path(__file__).parent))
        else:
            webbrowser.open(url)
        while not stopped.wait(1) and time.monotonic() - state['last'] < 1800:
            if ui and ui.poll() is not None: break
    finally:
        server.shutdown(); server.server_close()
        if ui and ui.poll() is None:
            ui.terminate()
            try: ui.wait(timeout=3)
            except Exception: ui.kill(); ui.wait()
        if ui and getattr(ui, 'record_profile', None):
            shutil.rmtree(ui.record_profile, ignore_errors=True)
    return saved
