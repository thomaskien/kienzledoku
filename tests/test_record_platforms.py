import copy
import http.client
import json
import os
import re
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock
import urllib.parse

import kienzledoku as record
import kienzledoku_config as config
import kienzledoku_settings as settings
from kienzledoku_http import configure_server
from kienzledoku_speech import SpeechRecognitionManager

class ConfigurationTests(unittest.TestCase):
    def test_windows_credential_lookup_still_reads_its_encrypted_key(self):
        with tempfile.TemporaryDirectory() as d:
            directory=Path(d)
            (directory/'direct-key.dpapi').write_bytes(b'synthetic-encrypted-data')
            with mock.patch('kienzledoku_config.sys.platform','win32'), mock.patch.object(config,'config_dir',return_value=directory), mock.patch.object(config,'_windows_crypt',return_value=b'synthetic-api-key') as decrypt:
                self.assertEqual(config.read_windows_key(),'synthetic-api-key')
                decrypt.assert_called_once_with(b'synthetic-encrypted-data',False)

    def test_windows_protocol_uri_cannot_inject_record_cli_options(self):
        import kienzledoku_launch as launcher
        with mock.patch.object(launcher.record, 'run_session') as launch, mock.patch.object(launcher.record, 'safe_log'), mock.patch('kienzledoku_launch.sys.platform', 'linux'):
            for args in (['kienzledoku-record://record', '--settings'], ['--import-config', 'untrusted.toml']):
                self.assertEqual(launcher.main(args),1)
            launch.assert_not_called()
            self.assertEqual(launcher.main(['kienzledoku-record://record?synthetic=context']),0)
            launch.assert_called_once_with('kienzledoku-record://record?synthetic=context')
    def test_fresh_install_preserves_local_ai_preseed_but_never_overwrites_an_update(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {'KIENZLEDOKU_CONFIG_DIR':d, 'KIENZLEDOKU_INSTALL_ASR_HOST':'ai.local'}):
            config.initialize_installation()
            self.assertEqual(config.load()['services']['asr'], 'http://ai.local:8179')
            with mock.patch.dict(os.environ, {'KIENZLEDOKU_INSTALL_ASR_HOST':'changed.local'}):
                config.initialize_installation()
            self.assertEqual(config.load()['services']['asr'], 'http://ai.local:8179')
    def test_toml_roundtrip_and_both_modes(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'config.toml'
            for mode in ('direct','connect'):
                cfg=config.defaults();cfg['connection']['mode']=mode
                cfg['record']['microphone']='Mikrofon "Ä" :: WASAPI'
                config.save(cfg,path)
                self.assertEqual(cfg,config.load(path))
                self.assertNotIn('API-Key',path.read_text())
    def test_legacy_import_retains_services_and_is_read_only(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ,{'KIENZLEDOKU_CONFIG_DIR':d}):
            old={'t2med':{'fhir_host':'t2med.local'},'services':config.defaults()['services']}
            path=Path(d)/'config.json';path.write_text(json.dumps(old))
            cfg=config.load()
            self.assertEqual(cfg['connection']['mode'],'direct')
            self.assertTrue(cfg['connection']['allow_insecure_tls'])
            self.assertFalse((Path(d)/'config.toml').exists())
            self.assertEqual(json.loads(path.read_text()),old)
    def test_exact_target_rejects_other_host_port_path_and_credentials(self):
        cfg=config.defaults()
        for target in ('https://127.0.0.1:9999/aps/fhir/api/r4', 'https://other/aps/fhir/api/r4',
                       'https://127.0.0.1:16567/aps/fhir/api/r4/../private',
                       'https://u:p@127.0.0.1:16567/aps/fhir/api/r4'):
            with self.assertRaises(ValueError):config.validate_target(target,cfg)
    def test_direct_client_has_no_connect_process(self):
        cfg=config.defaults()
        with mock.patch('kienzledoku.ConnectProxy') as proxy:
            client=record.T2medFhirClient(cfg['connection']['target'],'context','oauth','own-key',cfg['connection'])
            self.assertEqual(client._headers()['X-API-Key'],'own-key')
            proxy.assert_not_called();client.close()
    def test_connect_does_not_replace_oauth_and_no_failure_fallback(self):
        cfg=config.defaults();cfg['connection']['mode']='connect'
        with mock.patch('kienzledoku.ConnectProxy',side_effect=RuntimeError('not available')):
            with self.assertRaisesRegex(RuntimeError,'not available'):
                record.T2medFhirClient(cfg['connection']['target'],'context','oauth','old-key',cfg['connection'])
        with mock.patch('kienzledoku.ConnectProxy') as proxy:
            proxy.return_value.token='local-capability'
            client=record.T2medFhirClient(cfg['connection']['target'],'context','oauth','old-key',cfg['connection'])
            headers=client._headers()
            self.assertEqual(headers['Authorization'],'Bearer oauth')
            self.assertEqual(headers['X-Kienzledoku-Connect-Token'],'local-capability')
            client.close();proxy.return_value.close.assert_called_once()

class SessionStartupTests(unittest.TestCase):
    def make_state(self):
        state = record.SessionState({'context_id': 'synthetic', 'fhir_base_url': config.defaults()['connection']['target']}, mock.Mock(), 'test')
        state.speech = mock.Mock()
        return state

    def test_capture_starts_before_patient_read_and_ui_lock_remains_available(self):
        state = self.make_state()
        entered = threading.Event()
        finish = threading.Event()
        def get_patient():
            state.speech.start.assert_called_once_with()
            entered.set()
            self.assertTrue(finish.wait(3))
            return {'resourceType': 'Patient', 'id': 'synthetic'}
        state.client.get_patient_by_context.side_effect = get_patient
        worker = record.start_initial_work(state)
        try:
            self.assertTrue(entered.wait(1))
            self.assertTrue(state.lock.acquire(timeout=0.2))
            state.lock.release()
            self.assertIsNone(state.patient)
            record.start_initial_work(state)
            record.start_patient_load(state)
            state.speech.start.assert_called_once_with()
            state.client.get_patient_by_context.assert_called_once_with()
        finally:
            finish.set()
            worker.join(3)
        self.assertEqual(state.patient['id'], 'synthetic')
        self.assertEqual(state.t2med_status, 'ok')
        # Reloading patient data after a manual stop must never resume recording.
        state.speech.start.reset_mock()
        state.client.get_patient_by_context.side_effect = None
        state.client.get_patient_by_context.return_value = state.patient
        record.start_patient_load(state).join(3)
        state.speech.start.assert_not_called()

    def test_recovery_does_not_start_recording_and_failed_patient_read_keeps_capture(self):
        for recovery in (False, True):
            with self.subTest(recovery=recovery):
                state = self.make_state()
                state.recovery_pending = recovery
                state.client.get_patient_by_context.side_effect = record.FhirError('Synthetic read failure')
                record.start_initial_work(state).join(3)
                self.assertEqual(state.speech.start.call_count, 0 if recovery else 1)
                state.speech.stop.assert_not_called()
                self.assertEqual(state.t2med_status, 'error')
                self.assertEqual(state.patient_error, 'Synthetic read failure')
                self.assertIsNone(state.patient)

    def test_closed_session_does_not_accept_late_patient_result(self):
        state = self.make_state()
        def closing_read():
            state.closing = True
            return {'resourceType': 'Patient', 'id': 'synthetic'}
        state.client.get_patient_by_context.side_effect = closing_read
        record.start_initial_work(state).join(3)
        self.assertIsNone(state.patient)
        self.assertFalse(state.patient_loading)

class LocalHTTPTests(unittest.TestCase):
    def setUp(self):
        self.client=mock.Mock()
        self.state=record.SessionState({'context_id':'test','fhir_base_url':config.defaults()['connection']['target']},self.client,'test')
        self.state.patient={'resourceType':'Patient','id':'demo','name':[{'family':'Test'}]}
        self.state.speech=SpeechRecognitionManager(str(Path(record.__file__).parent))
        self.server=record.ThreadingHTTPServer(('127.0.0.1',0),record.make_handler(self.state))
        self.url=configure_server(self.server)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.port=self.server.server_address[1]
        self.cookie='record_%d=%s'%(self.port,self.server.ui_token)
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
    def request(self,method,path,body=None,headers=None):
        c=http.client.HTTPConnection('127.0.0.1',self.port,timeout=3)
        c.request(method,path,body,headers or {})
        response=c.getresponse();result=(response.status,response.read(),dict(response.getheaders()));c.close();return result
    def post(self,values):
        values['csrf']=self.state.csrf
        return self.request('POST','/action',urllib.parse.urlencode(values),{'Cookie':self.cookie,'Content-Type':'application/x-www-form-urlencoded'})
    def test_gets_require_capability(self):
        self.assertEqual(self.request('GET','/')[0],403)
        self.assertEqual(self.request('GET','/status')[0],403)
        path=urllib.parse.urlsplit(self.url).path+'?'+urllib.parse.urlsplit(self.url).query
        reply=self.request('GET',path)
        self.assertEqual(reply[0],200)
        self.assertNotIn('Location',reply[2])
        self.assertIn('HttpOnly',reply[2]['Set-Cookie'])
        self.assertIn('SameSite=Strict',reply[2]['Set-Cookie'])
        self.assertIn(b'window.location.replace("/")',reply[1])
        self.assertNotIn(self.server.ui_token.encode(),reply[1])
        self.assertIn("frame-ancestors 'none'",reply[2]['Content-Security-Policy'])
        nonce=re.search(rb'<script nonce="([^"]+)"',reply[1]).group(1).decode()
        self.assertIn("script-src 'nonce-%s'" % nonce,reply[2]['Content-Security-Policy'])
        self.assertEqual(self.request('GET','/open?token=wrong')[0],403)
        self.assertEqual(self.request('GET','/open')[0],403)
        self.assertEqual(self.request('GET','/',headers={'Cookie':self.cookie})[0],200)
        self.assertEqual(self.request('GET','/',headers={'Cookie':self.cookie,'Host':'evil.local'})[0],403)
    def test_uncertain_write_cannot_be_repeated_without_explicit_resolution(self):
        self.client.write_documentation.side_effect=record.FhirError('response lost')
        self.post({'do':'write','anamnese':'Synthetic documentation'})
        self.assertTrue(self.state.write_uncertain)
        self.post({'do':'write','anamnese':'Synthetic documentation'})
        self.assertEqual(self.client.write_documentation.call_count,1)
        self.post({'do':'write_resolved'})
        self.post({'do':'write','anamnese':'Synthetic documentation'})
        self.assertEqual(self.client.write_documentation.call_count,2)
    def test_confirmed_rollback_keeps_draft_without_uncertainty_or_retry(self):
        from kienzledoku_session import Recovery
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
                os.environ, {'KIENZLEDOKU_CONFIG_DIR': directory}):
            self.state.recovery = Recovery(self.state.link_data)
            saved_flags = []
            def rejected_write(document, mode, code):
                # The write is durably uncertain until a complete response arrives.
                saved_flags.append(json.loads(self.state.recovery.path.read_text())['write_uncertain'])
                record.validate_transaction_response({
                    'resourceType': 'Bundle', 'type': 'transaction-response', 'entry': [
                        {'response': {'status': '200 OK', 'outcome': {
                            'resourceType': 'OperationOutcome', 'issue': [{'severity': 'error',
                            'diagnostics': 'Behandlungsort ist nicht gesetzt.'}]}}}
                    ]}, ['Anamnese'])
            self.client.write_documentation.side_effect = rejected_write
            self.post({'do': 'write', 'anamnese': 'Synthetic draft'})
            self.assertEqual(saved_flags, [True])
            self.assertEqual(self.client.write_documentation.call_count, 1)
            self.assertFalse(self.state.write_uncertain)
            self.assertFalse(self.state.completed_event.is_set())
            self.assertEqual(self.state.documentation['anamnese'], 'Synthetic draft')
            saved = json.loads(self.state.recovery.path.read_text())
            self.assertFalse(saved['write_uncertain'])
            self.assertEqual(saved['documentation']['anamnese'], 'Synthetic draft')
            page = self.request('GET', '/', headers={'Cookie': self.cookie})[1].decode()
            self.assertIn('Nicht gespeichert: T2med', page)
            self.assertNotIn('Schreibausgang unklar.', page)
            # A fresh user click is permitted, but no automatic retry took place.
            self.post({'do': 'write', 'anamnese': 'Synthetic draft'})
            self.assertEqual(self.client.write_documentation.call_count, 2)
    def test_cross_origin_and_bad_csrf_cannot_write(self):
        self.request('POST','/action','do=write',{'Cookie':self.cookie,'Origin':'https://untrusted.example'})
        self.assertEqual(self.request('POST','/action','do=write',{'Cookie':self.cookie,'Origin':'null'})[0],403)
        self.request('POST','/action','do=write&csrf=wrong',{'Cookie':self.cookie})
        self.client.write_documentation.assert_not_called()

    def test_status_carries_live_umlauts_and_patient_without_reloading_page(self):
        text = 'Ärztliche Äußerung: Öl, Füße, Übelkeit – α.'
        self.state.speech.live_transcript = text
        self.state.speech.status = record.STATUS_RECORDING
        status, body, headers = self.request('GET', '/status', headers={'Cookie': self.cookie})
        self.assertEqual(status, 200)
        self.assertIn('charset=utf-8', headers['Content-Type'])
        payload = json.loads(body.decode('utf-8'))
        self.assertEqual(payload['live_transcript'], text)
        self.assertEqual(payload['patient']['name'], 'Test')
        # Recording alone never enables writes before a valid patient is loaded.
        self.state.patient = None
        self.state.speech.status = record.STATUS_READY
        self.post({'do': 'write', 'anamnese': 'Synthetic draft'})
        self.client.write_documentation.assert_not_called()

class SettingsHTTPTests(unittest.TestCase):
    def test_installer_setup_prefills_preserves_unshown_options_and_requires_save(self):
        for save in (True, False):
            with self.subTest(save=save), tempfile.TemporaryDirectory() as directory, mock.patch.dict(
                    os.environ, {'KIENZLEDOKU_CONFIG_DIR': directory}):
                initial = config.defaults()
                initial['services']['asr'] = 'http://existing.local:8179'
                initial['record']['microphone'] = 'Äußeres Mikrofon'
                initial['record']['output_mode'] = 'single'
                initial['record']['single_code'] = 'Ä'
                initial['connection']['mode'] = 'connect'
                config.save(initial)
                def open_window(url, _script_dir):
                    parsed = urllib.parse.urlsplit(url)
                    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=3)
                    def request(method, path, form=None, headers=None):
                        connection.request(method, path, urllib.parse.urlencode(form) if form else None, headers or {})
                        response = connection.getresponse()
                        return response.status, response.read().decode('utf-8'), dict(response.getheaders())
                    try:
                        _, _, headers = request('GET', parsed.path + '?' + parsed.query)
                        cookie = headers['Set-Cookie'].split(';', 1)[0]
                        headers = {'Cookie': cookie, 'Origin': 'http://' + parsed.netloc,
                                   'Content-Type': 'application/x-www-form-urlencoded'}
                        status, page, _ = request('GET', '/', headers=headers)
                        self.assertEqual(status, 200)
                        self.assertIn('Server für die Installation einrichten', page)
                        self.assertIn('http://existing.local:8179', page)
                        self.assertNotIn('name="record.microphone"', page)
                        self.assertNotIn('name="direct_key"', page)
                        csrf = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
                        form = {'csrf': csrf, 'action': 'save' if save else 'close'}
                        for section, key, _label, kind in settings.FIELDS:
                            if section not in ('connection', 'services'):
                                continue
                            value = initial[section][key]
                            if kind != 'checkbox' or value:
                                form[section + '.' + key] = 'on' if kind == 'checkbox' else value
                        form['services.asr'] = 'http://new.local:8180'
                        # The setup endpoint cannot silently replace hidden options or keys.
                        form['record.microphone'] = 'overwrite attempt'
                        form['direct_key'] = 'synthetic-injected-key'
                        if save:
                            invalid = dict(form, **{'connection.target': 'http://invalid.local'})
                            _, page, _ = request('POST', '/', invalid, headers)
                            self.assertIn('Nicht gespeichert:', page)
                            self.assertEqual(config.load(), initial)
                        self.assertEqual(request('POST', '/', form, headers)[0], 200)
                    finally:
                        connection.close()
                    return None, 'test'
                with mock.patch.object(config, 'store_direct_key') as key_store:
                    self.assertEqual(settings.run_settings(window_opener=open_window, setup=True), save)
                    key_store.assert_not_called()
                expected = copy.deepcopy(initial)
                if save:
                    expected['services']['asr'] = 'http://new.local:8180'
                self.assertEqual(config.load(), expected)

    def test_initial_page_save_and_close_use_real_session_cookie(self):
        # Exercise the actual settings handler; the old tests never rendered it.
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
                os.environ, {'KIENZLEDOKU_CONFIG_DIR': directory}):
            initial = config.defaults()
            initial['record']['microphone'] = 'Test <Mikrofon> "Ä"'
            config.save(initial)

            def open_window(url, _script_dir):
                parsed = urllib.parse.urlsplit(url)

                def request(method, path, body=None, headers=None):
                    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=3)
                    try:
                        connection.request(method, path, body, headers or {})
                        response = connection.getresponse()
                        return response.status, response.read().decode('utf-8'), dict(response.getheaders())
                    finally:
                        connection.close()

                self.assertEqual(request('GET', '/')[0], 403)
                status, _body, headers = request('GET', parsed.path + '?' + parsed.query)
                self.assertEqual(status, 200)
                cookie = headers['Set-Cookie'].split(';', 1)[0]
                status, page, page_headers = request('GET', '/', headers={'Cookie': cookie})
                self.assertEqual(status, 200)
                self.assertEqual(page_headers['Referrer-Policy'], 'same-origin')
                self.assertIn('width:100%;', page)
                self.assertIn('Test &lt;Mikrofon&gt; &quot;Ä&quot;', page)
                csrf = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
                form = {'csrf': csrf, 'action': 'save'}
                for section, key, _label, kind in settings.FIELDS:
                    value = initial[section][key]
                    if kind != 'checkbox' or value:
                        form[section + '.' + key] = 'on' if kind == 'checkbox' else value
                form['connection.mode'] = 'direct'
                post_headers = {'Cookie': cookie, 'Content-Type': 'application/x-www-form-urlencoded',
                                'Origin': 'http://' + parsed.netloc}
                # Bad CSRF must not write settings even with a valid session.
                bad_form = dict(form, csrf='wrong')
                self.assertEqual(request('POST', '/', urllib.parse.urlencode(bad_form), post_headers)[0], 403)
                self.assertEqual(request('POST', '/', urllib.parse.urlencode(form), dict(post_headers, Origin='null'))[0], 403)
                self.assertEqual(config.load(), initial)
                status, page, _headers = request('POST', '/', urllib.parse.urlencode(form), post_headers)
                self.assertEqual(status, 200)
                self.assertIn('Gespeichert.', page)
                self.assertEqual(config.load()['connection']['mode'], 'direct')
                status, page, _headers = request('POST', '/', urllib.parse.urlencode(
                    {'csrf': csrf, 'action': 'close'}), post_headers)
                self.assertEqual(status, 200)
                self.assertIn('Einstellungen geschlossen.', page)
                return None, 'test'

            settings.run_settings(window_opener=open_window)

class AudioConversionTests(unittest.TestCase):
    def test_streaming_48khz_stereo_preserves_time_across_chunk_boundaries(self):
        from kienzledoku_audio import PcmConverter
        from array import array
        import math
        samples=array('h')
        for i in range(48000):
            samples.extend([int(8000*math.sin(2*math.pi*440*i/48000))]*2)
        data=samples.tobytes()
        converter=PcmConverter(48000,2)
        result=b''.join(converter.feed(data[n:n+4444]) for n in range(0,len(data),4444))
        self.assertLessEqual(abs(len(result)-32000),2)
        import audioop
        self.assertGreater(audioop.rms(result,2),5000)
        self.assertEqual(result,PcmConverter(48000,2).feed(data))

class RecoveryTests(unittest.TestCase):
    def test_replayed_segment_replaces_partial_text_instead_of_appending_it_twice(self):
        from kienzledoku_session import session_dir
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {'KIENZLEDOKU_CONFIG_DIR':d}):
            root=Path(d)
            runner=root/'kienzledoku_asr_v6.py'
            runner.write_text("import json,sys\npath=sys.argv[sys.argv.index('--json')+1]\nwith open(path,'w') as f:json.dump({'transcript':'complete segment','speaker_transcript':'complete segment'},f)\n")
            (root/'prompt_documentation.txt').write_text('test')
            manager=SpeechRecognitionManager(root)
            manager.native_python=True;manager.runner_path=str(runner)
            spool=session_dir()/'audio-interrupted';spool.mkdir()
            partial=spool/'aufnahme.wav.partial.wav';partial.write_bytes(b'synthetic fixture')
            manager.interrupted_audio=str(partial)
            manager.live_transcript='earlier recording\npartial segment'
            manager.diarized_text=manager.live_transcript
            manager.run_base_transcript='earlier recording'
            manager.run_base_diarized='earlier recording'
            with mock.patch('kienzledoku_speech.call_llm',return_value='{"anamnese":"test","befund":"","therapie":"","prozedere":""}'):
                manager.start()
                manager.thread.join(timeout=5)
            self.assertFalse(manager.thread.is_alive())
            self.assertEqual(manager.status,'ready',manager.message)
            self.assertIn('earlier recording',manager.diarized_text)
            self.assertIn('complete segment',manager.diarized_text)
            self.assertNotIn('partial segment',manager.diarized_text)
            self.assertFalse(partial.exists())

    def test_recovery_keeps_draft_and_audio_but_no_credentials_and_cleans_only_owned_spool(self):
        from kienzledoku_session import Recovery, session_dir
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {'KIENZLEDOKU_CONFIG_DIR':d}):
            link={'context_id':'synthetic-context', 'fhir_base_url':config.defaults()['connection']['target'], 'oauth_token':'synthetic-secret'}
            recovery=Recovery(link)
            state=record.SessionState(link,mock.Mock(),'synthetic-key')
            state.speech=SpeechRecognitionManager(str(Path(record.__file__).parent))
            state.documentation['anamnese']='Synthetic draft'
            state.speech.run_base_diarized='Earlier completed recording'
            spool=session_dir()/'audio-test';spool.mkdir()
            audio=spool/'aufnahme.wav.partial.wav';audio.write_bytes(b'synthetic audio')
            preserved=session_dir()/'user-file.txt';preserved.write_text('keep')
            state.speech.interrupted_audio=str(audio)
            state.write_uncertain=True
            recovery.save(state)
            raw=recovery.path.read_text()
            self.assertNotIn('synthetic-secret',raw)
            self.assertNotIn('synthetic-key',raw)
            self.assertNotIn('synthetic-context',raw)
            recovered=Recovery(link)
            self.assertEqual(recovered.previous['documentation']['anamnese'],'Synthetic draft')
            self.assertTrue(recovered.previous['write_uncertain'])
            self.assertEqual(recovered.previous['audio_base_diarized'],'Earlier completed recording')
            recovered.clear()
            self.assertFalse(audio.exists());self.assertFalse(recovery.path.exists())
            self.assertTrue(preserved.exists())
