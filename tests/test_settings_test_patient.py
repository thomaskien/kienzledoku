"""Settings → synthetic Record → dictation and document, with no FHIR transport."""
import http.cookiejar
import json
import os
from pathlib import Path
import queue
import re
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest.mock import patch

import kienzledoku as record
import kienzledoku_audio as audio
import kienzledoku_asr_v6 as asr
from kienzledoku_commander_client import CommanderClient
from kienzledoku_document import DEFAULT_DOCUMENT_FIELDS


class LocalPage:
    def __init__(self, url):
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.root = url.split('/open?', 1)[0]
        self.http.open(url, timeout=4).close()
        self.csrf = re.search(r'name="csrf" value="([^"]+)"', self.get()).group(1)

    def get(self, path='/'):
        with self.http.open(self.root + path, timeout=4) as response:
            return response.read().decode()

    def post(self, path, **fields):
        body = urllib.parse.urlencode(dict(csrf=self.csrf, **fields)).encode()
        with self.http.open(self.root + path, data=body, timeout=4) as response:
            return response.read().decode()


class TestPatientTests(unittest.TestCase):
    def test_existing_session_blocks_demo_and_never_reads_fhir(self):
        active = record.ActiveSessionError(None, None)
        with patch.object(record, 'acquire_record_session', side_effect=active), \
             patch.object(record, 'show_patient_conflict') as conflict, \
             patch.object(record, 'T2medFhirClient') as fhir:
            record.run_test_patient()
            self.assertEqual(conflict.call_args.args[1]['id'], 'testpatient')
            fhir.assert_not_called()

    def test_settings_to_record_and_document_without_t2med(self):
        # Replace hardware and model responses only. Settings, session locking,
        # local HTTP, ASR segmentation, stop/finalize and document UI are real.
        pages = queue.Queue()
        captured = threading.Event()
        class Stream:
            active = True
            def __init__(self, append):
                self.append = append
            def start(self):
                self.append(b'\x04\x11' * 32000)
                captured.set()
            def stop(self):
                self.active = False
            def close(self):
                pass
        def window(url, _directory):
            pages.put(url)
            return None, 'test-window'
        profiles = [dict(id='test', label='Test', default=True, persistent=False)]
        transcript = 'Dies ist ein synthetisches Testdiktat.'
        document = {field: 'Testdokumentation' for field in DEFAULT_DOCUMENT_FIELDS}
        with tempfile.TemporaryDirectory() as tmp, \
             patch.dict(os.environ, {'KIENZLEDOKU_CONFIG_DIR':tmp}), \
             patch.object(record, 'LOG_PATH', str(Path(tmp)/'record.log')), \
             patch.object(record, 'SERVICE_CONFIG_PATH', str(Path(tmp)/'config.toml')), \
             patch.object(sys,'argv',['record','--settings']), \
             patch.object(record,'open_ui_window',side_effect=window), \
             patch.object(record,'get_api_key',side_effect=AssertionError('FHIR key')), \
             patch.object(record,'T2medFhirClient',side_effect=AssertionError('FHIR client')), \
             patch.object(record.SpeechRecognitionManager,'start_service_check'), \
             patch.object(CommanderClient,'documentation_settings',return_value={
                 'fields':DEFAULT_DOCUMENT_FIELDS, 'prompt':'Test', 'prompt_template':'Test'}), \
             patch.object(CommanderClient,'profiles',return_value=profiles), \
             patch.dict(sys.modules, {'sounddevice': object()}), \
             patch.object(audio,'create_input',side_effect=lambda sd,dev,append,emit,ms:(Stream(append),[])), \
             patch.object(asr,'transcribe_final_block_http',return_value={'text':transcript,
                 'segments':[{'start':0,'end':2,'text':transcript}], 'words':[]}) as transcribe, \
             patch.object(CommanderClient,'extract',return_value=(document,dict(notice='', requested_quality='test', used_quality='test'))) as extract:
            cfg = record.record_config.defaults()
            cfg['record'].update(diarization=False, vad_enabled=False)
            record.record_config.save(cfg)
            results = []
            thread = threading.Thread(target=lambda:results.append(record.main()), daemon=True)
            thread.start()
            settings = LocalPage(pages.get(timeout=6))
            self.assertIn('Testpatient öffnen', settings.get())
            settings.post('/', action='test_patient')
            demo = LocalPage(pages.get(timeout=6))
            try:
                page = demo.get()
                self.assertIn('Testpatient, Toni', page)
                self.assertNotIn('In T2med übernehmen', page)
                self.assertNotIn('Patient neu laden', page)
                self.assertFalse(captured.is_set())
                for action in ('patient','encounter','write','write_resolved'):
                    with self.assertRaises(urllib.error.HTTPError) as denied:
                        demo.post('/action', do=action)
                    self.assertEqual(denied.exception.code,403)
                demo.post('/action', do='speech_start')
                self.assertTrue(captured.wait(4))
                demo.post('/action', do='speech_stop')
                deadline = time.monotonic()+10
                while not json.loads(demo.get('/status'))['document_revision']:
                    if time.monotonic() >= deadline:
                        self.fail('Testdokumentation fehlt: '+json.loads(demo.get('/status'))['message'])
                    time.sleep(.1)
                self.assertIn('Testdokumentation', demo.get())
                self.assertIn(transcript, demo.get())
                self.assertTrue(transcribe.called)
                self.assertIn(transcript,extract.call_args.args)
            finally:
                demo.post('/action', do='discard')
                thread.join(7)
            self.assertEqual(results,[0])
            self.assertFalse(list(Path(tmp).rglob('active.json')))
