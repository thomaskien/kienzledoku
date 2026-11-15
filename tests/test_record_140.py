from kienzledoku_vad import AudioControls
import asyncio
import json
import subprocess
import sys
import os
from pathlib import Path
import tempfile
import threading
import types
import unittest
from unittest import mock

import kienzledoku as record
import kienzledoku_asr_v6 as asr
import kienzledoku_commander_client as commander
from kienzledoku_document import DOCUMENT_FIELDS
from kienzledoku_session import cleanup_legacy_patient_data
from kienzledoku_speech import SpeechRecognitionManager, continuation_marker, strip_continuation_markers


ALL_DOC = {name: name.upper() for name in DOCUMENT_FIELDS}


class _Stream:
    active = True
    def __init__(self, append): self.append = append
    def start(self):
        self.append(b'\x00\x10' * 8000)
    def stop(self): self.active = False
    def close(self): pass


class Record140Tests(unittest.TestCase):
    def test_real_recording_core_keeps_pcm_and_result_in_ram(self):
        with tempfile.TemporaryDirectory() as directory:
            before = set(Path(directory).iterdir())
            stop = threading.Event(); stop.set()
            args = types.SimpleNamespace(
                asr='http://127.0.0.1:8179', language='de', asr_api_key=None,
                asr_timeout=30, pause_seconds=.8, short_block_pause_seconds=1.5,
                min_block_seconds=.2, max_block_seconds=.4, context_seconds=0,
                segment_frame_ms=30, silence_rms=None, auto_rms_min=160,
                auto_rms_max=1200, auto_rms_factor=2, audio_chunk_ms=100,
                status_seconds=5, input_wav=None, replay_speed=1, device=None,
                wav=str(Path(directory) / 'forbidden.wav'),
                json=str(Path(directory) / 'forbidden.json'), commander=None,
                recording_finalized=False, commander_metadata=None, ram_only=True,
                quiet=True, audio_controls=AudioControls(False), stop_event=stop, event_callback=lambda _event: None)
            fake_audio = types.ModuleType('kienzledoku_audio')
            fake_audio.create_input = lambda _sd, _dev, append, _emit, _ms: (_Stream(append), [])
            result = {'text': 'synthetisch', 'words': [],
                      'segments': [{'start': 0, 'end': .5, 'text': 'synthetisch'}]}
            with mock.patch.dict('sys.modules', {'sounddevice': types.ModuleType('sounddevice'),
                                                  'kienzledoku_audio': fake_audio}), \
                 mock.patch.object(asr, 'transcribe_final_block_http', return_value=result):
                payload = asyncio.run(asr.run_recording(args))
            self.assertTrue(payload['recording_finalized'])
            self.assertTrue(payload['_audio_wav'].startswith(b'RIFF'))
            self.assertEqual(before, set(Path(directory).iterdir()))

    def test_close_cancels_a_blocked_asr_call_and_closes_audio(self):
        stop = threading.Event(); stop.set()
        cancel = threading.Event(); started = threading.Event(); release = threading.Event()
        args = types.SimpleNamespace(
            asr='http://127.0.0.1:8179', language='de', asr_api_key=None,
            asr_timeout=30, pause_seconds=.8, short_block_pause_seconds=1.5,
            min_block_seconds=.2, max_block_seconds=.4, context_seconds=0,
            segment_frame_ms=30, silence_rms=None, auto_rms_min=160,
            auto_rms_max=1200, auto_rms_factor=2, audio_chunk_ms=100,
            status_seconds=5, input_wav=None, replay_speed=1, device=None,
            commander=None, recording_finalized=False, commander_metadata=None,
            ram_only=True, audio_controls=AudioControls(False), quiet=True, stop_event=stop, cancel_event=cancel,
            event_callback=lambda _event: None)
        streams = []
        fake_audio = types.ModuleType('kienzledoku_audio')
        def make_stream(_sd, _dev, append, _emit, _ms):
            stream = _Stream(append); streams.append(stream); return stream, []
        fake_audio.create_input = make_stream
        def blocked(*_):
            started.set(); release.wait(5)
            return {'text': 'late synthetic result', 'segments': [], 'words': []}
        def close_window():
            if started.wait(3): cancel.set()
        closer = threading.Thread(target=close_window); closer.start()
        try:
            with mock.patch.dict('sys.modules', {'sounddevice': types.ModuleType('sounddevice'),
                                                  'kienzledoku_audio': fake_audio}), \
                 mock.patch.object(asr, 'transcribe_final_block_http', side_effect=blocked):
                with self.assertRaises(asr.RecordingCancelled):
                    asyncio.run(asyncio.wait_for(asr.run_recording(args), 2))
            self.assertTrue(started.is_set()); self.assertFalse(streams[0].active)
            self.assertEqual([], args._recording_tasks)
            self.assertFalse(args.recording_finalized)
        finally:
            release.set(); closer.join(4)

    def test_continuation_marker_is_sectioned_and_sent_to_llm(self):
        self.assertIn('Abschnitt 2', continuation_marker(2))
        manager = SpeechRecognitionManager(str(Path(record.__file__).parent))
        manager.section_number = 1
        manager.live_transcript = 'vorher'
        manager.diarized_text = '[SPEAKER_00] vorher'
        captured = []
        def fake_pipeline(base_transcript, base_diarized, _continued):
            captured.extend([base_transcript, base_diarized])
            manager.status = 'ready'
        with mock.patch.object(manager, '_run_ram_pipeline', side_effect=fake_pipeline):
            manager.start(); manager.thread.join(2)
        self.assertTrue(all('Abschnitt 2' in value for value in captured))
        cleaned = strip_continuation_markers({'anamnese': 'vorher\n' + continuation_marker(2) + '\nnachher'})
        self.assertEqual('vorher\nnachher', cleaned['anamnese'])

    def test_all_fields_use_one_transaction_and_new_freetext_codes(self):
        client = record.T2medFhirClient(
            'https://127.0.0.1:16567/aps/fhir/api/r4', 'ctx', '', 'key')
        resources = client.build_documentation_resources(
            ALL_DOC, 'structured', 'KI', DOCUMENT_FIELDS)
        self.assertEqual(list(DOCUMENT_FIELDS), [name.lower() for name, _ in resources])
        codes = {label: resource.get('extension', [{}])[0].get('valueString')
                 for label, resource in resources if label in ('EKG', 'Sonografie', 'Notiz')}
        self.assertEqual({'EKG': 'EKG', 'Sonografie': 'SON', 'Notiz': 'NOT'}, codes)
        bundle = client.build_transaction_bundle([item for _label, item in resources])
        self.assertEqual(7, len(bundle['entry']))

    def test_second_process_is_blocked_and_patient_identity_stays_in_ram(self):
        with tempfile.TemporaryDirectory() as directory:
            env=dict(os.environ,KIENZLEDOKU_CONFIG_DIR=directory)
            holder_code="""
import sys
import kienzledoku_session as session
session.acquire()
try:
    session.start_active_broker(lambda: {'patient': {'name':'Synthetic Alpha','birth_date':'1915-01-01'}, 'open':True})
    print('ready',flush=True)
    sys.stdin.readline()
finally:
    session.unregister_window()
"""
            holder=subprocess.Popen([sys.executable,'-u','-c',holder_code],env=env,
                                    stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                self.assertEqual('ready',holder.stdout.readline().strip())
                probe_code="""
import json
import kienzledoku_session as session
try:
    session.acquire()
except session.ActiveSessionError as active:
    print(json.dumps(active.request()))
else:
    raise AssertionError('Second patient window was not blocked')
"""
                output=subprocess.check_output([sys.executable,'-c',probe_code],env=env,text=True,timeout=5)
                self.assertEqual('Synthetic Alpha',json.loads(output)['patient']['name'])
                metadata=list(Path(directory).rglob('active.json'))
                self.assertEqual(1,len(metadata))
                self.assertEqual({'port','token'},set(json.loads(metadata[0].read_text())))
                for path in Path(directory).rglob('*'):
                    if path.is_file():self.assertNotIn(b'Synthetic Alpha',path.read_bytes())
            finally:
                holder.communicate('\n',timeout=5)
            self.assertEqual(0,holder.returncode)
            self.assertFalse(list(Path(directory).rglob('active.json')))

    def test_conflict_warning_is_explicit_and_truthful(self):
        page = record.patient_conflict_html(
            {'name': 'Alt, Anna', 'birth_date': '1980-01-02'}, None,
            new_error='FHIR nicht erreichbar', csrf='x')
        self.assertIn('ACHTUNG Gefahr der Patientenverwechslung!', page)
        self.assertIn('Offene Aufnahme:', page)
        self.assertIn('Neue Aufnahme:', page)
        self.assertIn('Offenes Fenster anzeigen', page)
        self.assertIn('Hinweis schließen', page)
        self.assertIn('Nicht ermittelbar', page)

    def test_legacy_cleanup_is_symlink_safe_and_preserves_foreign_files(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory); target = Path(outside) / 'keep'; target.write_text('keep')
            (root / 'recovery.json').write_text('patient')
            spool = root / 'audio-old'; spool.mkdir(); (spool / 'aufnahme.wav').write_bytes(b'x')
            link = root / 'audio-link'; link.symlink_to(target)
            foreign = root / 'user.txt'; foreign.write_text('keep')
            cleanup_legacy_patient_data(root)
            self.assertFalse((root / 'recovery.json').exists())
            self.assertFalse(spool.exists()); self.assertFalse(link.exists())
            self.assertEqual('keep', target.read_text()); self.assertTrue(foreign.exists())

    def test_remote_token_is_optional_and_settings_fallback_only_on_404(self):
        client = commander.CommanderClient('http://commander.invalid:8185',
                                           token_env='UNSET_RECORD_140_TOKEN')
        with mock.patch.dict(os.environ, {}, clear=False):
            self.assertEqual('', client.token)
        with mock.patch.object(client, 'request', side_effect=commander.CommanderRequestError('old', 404)):
            self.assertEqual(('anamnese', 'befund', 'therapie', 'prozedere'),
                             client.documentation_settings()['fields'])
        with mock.patch.object(client, 'request', side_effect=commander.CommanderRequestError('offline')):
            with self.assertRaises(commander.CommanderRequestError):
                client.documentation_settings()


if __name__ == '__main__':
    unittest.main()
