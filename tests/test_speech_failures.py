"""Synthetic regression cases for failed speaker assignment; no real audio or services."""
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from urllib.error import HTTPError

import kienzledoku_asr_v6 as asr
import kienzledoku_speech as speech


class SpeechFailureTests(unittest.TestCase):
    def test_failed_diarization_preserves_text_and_edits_for_continuation(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'prompt_documentation.txt').write_text('synthetic prompt')
            manager = speech.SpeechRecognitionManager(directory)
            manager.record_options['diarization'] = True
            manager.live_transcript = 'original first section'
            manager.diarized_text = 'physician-edited first section'
            manager.section_number = 1
            payloads = [dict(transcript=text, recording_finalized=True,
                             _audio_wav=b'synthetic WAV', words=[], segments=[])
                        for text in ('second section', 'third section')]
            async def recording(args):
                payload = payloads.pop(0)
                args.event_callback({'type': 'final_block', 'block_id': 1,
                                     'text': payload['transcript']})
                return payload
            with mock.patch.object(speech, 'run_recording',
                                   new=recording), \
                 mock.patch.object(speech, 'diarize_audio', side_effect=[
                     RuntimeError('Sprecherzuordnung fehlgeschlagen (HTTP 502).'),
                     {'segments': []}]), \
                 mock.patch.object(manager, '_document_text', return_value={}) as document:
                manager.start()
                manager.thread.join(3)
                self.assertFalse(manager.thread.is_alive())
                state = manager.snapshot()
                self.assertEqual('error', state['status'])
                self.assertIn('second section', state['live_transcript'])
                self.assertIn('second section', state['diarized_text'])
                self.assertIn('physician-edited first section', state['diarized_text'])
                self.assertNotIn('original first section', state['diarized_text'])
                self.assertTrue(state['can_regenerate'])
                self.assertIn('ohne neue Sprecherzuordnung', state['message'])
                document.assert_not_called()
                manager.start()
                manager.thread.join(3)
                self.assertFalse(manager.thread.is_alive())
                self.assertEqual('ready', manager.status)
                sent = document.call_args.args[0]
                for text in ('physician-edited first section', 'second section', 'third section',
                             speech.continuation_marker(2), speech.continuation_marker(3)):
                    self.assertEqual(1, sent.count(text))
                self.assertEqual(['prompt_documentation.txt'],
                                 sorted(p.name for p in Path(directory).iterdir()))

    def test_diarization_http_error_names_stage_without_server_response(self):
        failure = HTTPError('http://synthetic.invalid/v1/diarize', 502,
                            'untrusted server message', {}, io.BytesIO(b'private response'))
        with mock.patch.object(asr, 'direct_open', side_effect=failure):
            with self.assertRaisesRegex(RuntimeError,
                                        r'^Sprecherzuordnung fehlgeschlagen \(HTTP 502\)\.$'):
                asr.diarize_audio('http://synthetic.invalid:8185', b'synthetic WAV',
                                 1, 4, None, 1, recording_finalized=True, commander=True)


if __name__ == '__main__':
    unittest.main()
