import json
import math
import os
from pathlib import Path
import struct
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
import wave

from kienzledoku_speech import SpeechRecognitionManager, STATUS_READY, STATUS_RECORDING


DOC = {'anamnese': 'Synthetisch', 'befund': '', 'therapie': '', 'prozedere': ''}
PROFILES = [
    {'id': 'gemma12_q8', 'label': 'Gemma 4 12B Q8_0', 'persistent': True,
     'fallback': None, 'default': True},
]


def eventually(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError('Testzustand nicht erreicht')
        time.sleep(.01)


class CommanderRecordTests(unittest.TestCase):
    def test_audio_stops_and_asr_queue_finishes_before_finalization(self):
        import asyncio
        import kienzledoku_asr_v6 as asr
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source.wav'
            with wave.open(str(source), 'wb') as handle:
                handle.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
                handle.writeframes(b''.join(struct.pack(
                    '<h', int(8000 * math.sin(index * 2 * math.pi * 220 / 16000)))
                    for index in range(9600)))
            argv = ['asr', '--input-wav', str(source), '--replay-speed', '0',
                    '--wav', str(root / 'copy.wav'), '--json', str(root / 'result.json'),
                    '--commander', 'http://127.0.0.1:8185', '--min-block-seconds', '.2',
                    '--max-block-seconds', '.4', '--context-seconds', '0']
            release = threading.Event()
            entered = threading.Event()
            events = []
            result = {}
            def transcribe(*_args, **_kwargs):
                entered.set()
                release.wait(5)
                return {'text': 'synthetic', 'words': [],
                        'segments': [{'start': 0, 'end': .2, 'text': 'synthetic'}]}
            def run():
                with mock.patch.object(sys, 'argv', argv):
                    args = asr.parse_args()
                result['args'] = args
                result['payload'] = asyncio.run(asr.run_recording(args))
            with mock.patch.object(asr, 'transcribe_final_block_http', side_effect=transcribe), \
                 mock.patch.object(asr, 'emit_event', side_effect=lambda kind, **data: events.append((kind, data))):
                thread = threading.Thread(target=run)
                thread.start()
                self.assertTrue(entered.wait(3))
                eventually(lambda: any(kind == 'phase' and data.get('phase') == 'audio_stopped'
                                       for kind, data in events))
                self.assertFalse(any(kind == 'phase' and data.get('phase') == 'recording_finalized'
                                     for kind, data in events))
                release.set()
                thread.join(5)
            self.assertFalse(thread.is_alive())
            phases = [data['phase'] for kind, data in events if kind == 'phase']
            self.assertLess(phases.index('audio_stopped'), phases.index('recording_finalized'))
            self.assertTrue(result['payload']['recording_finalized'])
            args = result['args']
            self.assertEqual({args.commander}, {args.asr, args.diarization, args.llm})

    def test_commander_is_exclusive_waits_for_runner_and_reprocesses(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sessions = root / 'sessions'
            sessions.mkdir()
            (root / 'prompt_documentation.txt').write_text('synthetic', encoding='utf-8')
            (root / 'config.json').write_text(json.dumps({
                'services': {'asr': 'http://legacy.invalid:8179',
                             'diarization': 'http://legacy.invalid:8183',
                             'llm': 'http://legacy.invalid:8080'},
                'commander': {'enabled': True, 'url': 'http://commander.invalid:8185',
                              'token_env': 'TEST_COMMANDER_TOKEN',
                              'default_quality': 'gemma12_q8'},
            }), encoding='utf-8')
            runner = root / 'runner.py'
            runner.write_text('''
import json, pathlib, sys, time
assert '--commander' in sys.argv and 'http://commander.invalid:8185' in sys.argv
assert '--no-llm' in sys.argv
root = pathlib.Path(__file__).parent
print('KIENZLEDOKU_EVENT '+json.dumps({'type':'final_block','block_id':1,'text':'synthetic'}), flush=True)
sys.stdin.readline()
(root/'stop-received').touch()
while not (root/'allow-finalization').exists(): time.sleep(.01)
target = pathlib.Path(sys.argv[sys.argv.index('--json')+1])
target.write_text(json.dumps({'transcript':'synthetic','speaker_transcript':'[SPEAKER_00] synthetic','llm':None,'recording_finalized':True}))
''', encoding='utf-8')
            extracts = []
            def extract(_client, text, quality, profiles, recording_finalized=False):
                extracts.append((text, quality, recording_finalized))
                return DOC, {'requested_quality': 'gemma12_q8', 'used_quality': 'gemma12_q8',
                             'fallback_used': False, 'notice': ''}
            received = []
            with mock.patch.dict(os.environ, {'TEST_COMMANDER_TOKEN': 'synthetic-token'}), \
                 mock.patch('kienzledoku_speech.session_dir', return_value=sessions), \
                 mock.patch('kienzledoku_commander_client.CommanderClient.profiles', return_value=PROFILES), \
                 mock.patch('kienzledoku_commander_client.CommanderClient.extract', new=extract):
                manager = SpeechRecognitionManager(str(root), on_document=received.append)
                manager.native_python = True
                manager.runner_path = str(runner)
                manager.set_quality('gemma12_q8') if manager.quality_profiles else None
                manager.start()
                eventually(lambda: manager.snapshot()['live_transcript'])
                self.assertEqual(STATUS_RECORDING, manager.status)
                self.assertEqual({'http://commander.invalid:8185'}, set(manager.service_urls.values()))
                manager.stop()
                eventually(lambda: (root / 'stop-received').exists())
                self.assertFalse(extracts)
                (root / 'allow-finalization').touch()
                eventually(lambda: manager.status == STATUS_READY and received)
                self.assertEqual('[SPEAKER_00] synthetic', extracts[0][0])
                self.assertTrue(extracts[0][2])
                manager.regenerate('[SPEAKER_00] changed')
                eventually(lambda: manager.status == STATUS_READY and len(extracts) == 2)
                self.assertEqual('[SPEAKER_00] changed', extracts[1][0])
                manager.cancel()

    def test_ui_uses_server_labels_and_displays_requested_and_used_quality(self):
        import kienzledoku as record
        state = mock.Mock()
        state.recovery_pending = False
        state.patient = None
        state.encounter = None
        state.error = ''
        state.message = ''
        state.write_uncertain = False
        state.csrf = 'synthetic'
        state.documentation = dict(DOC)
        state.output_mode = 'structured'
        state.single_code = 'KI'
        state.link_data = {'context_id': 'ctx', 'fhir_base_url': 'https://127.0.0.1:16567/aps/fhir/api/r4'}
        state.key_source = 'test'
        state.t2med_host = 'localhost'
        state.t2med_status = 'ok'
        state.t2med_message = 'ok'
        state.patient_error = ''
        state.document_revision = 0
        snapshot = {
            'status': STATUS_READY, 'message': '', 'elapsed_seconds': 0,
            'live_transcript': '', 'diarized_text': 'synthetic', 'can_regenerate': True,
            'audio_devices': [], 'selected_device': '', 'selected_device_name': 'Standard',
            'commander_enabled': True, 'quality_profiles': PROFILES,
            'selected_quality': 'gemma12_q8', 'commander_notice': 'Fallback-Hinweis',
            'requested_quality_label': 'Gemma 4 12B Q8_0', 'used_quality_label': 'Basis',
            'services': {name: {'host': 'commander', 'url': 'http://commander:8185',
                                'status': 'ok', 'message': 'ok'}
                         for name in ('asr', 'diarization', 'llm')},
            'config_source': 'test',
        }
        state.speech.snapshot.return_value = snapshot
        page = record.page_html(state)
        self.assertIn('Gemma 4 12B Q8_0', page)
        self.assertIn('Angefordert: Gemma 4 12B Q8_0 · Erstellt mit: Basis', page)
        self.assertIn('Fallback-Hinweis', page)


if __name__ == '__main__':
    unittest.main()
