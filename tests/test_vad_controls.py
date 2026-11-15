import asyncio
from array import array
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

import kienzledoku_asr_v6 as asr
import kienzledoku_config as config
import kienzledoku_speech as speech
from kienzledoku_vad import AudioControls, SilenceGate, speech_spans, dbfs


def pcm(value, seconds):
    return array('h', [value] * round(16000 * seconds)).tobytes()


class VADTests(unittest.TestCase):
    def test_gate_exact_timeline_raw_buffer_and_word_margins(self):
        controls = AudioControls(True, -40)
        raw = pcm(10, 1) + pcm(8000, .4) + pcm(10, 1) + pcm(8000, .2) + pcm(10, .523)
        audio = asr.AudioState(controls=controls)
        for start in range(0, len(raw), 154): audio.append(raw[start:start+154])
        audio.finish_gate()
        gated = audio.working_bytes(0)
        self.assertEqual(raw, audio.all_pcm()); self.assertEqual(len(raw), len(gated))
        self.assertEqual(bytes(16000), gated[:16000])
        self.assertEqual(raw[32000:44800], gated[32000:44800])
        self.assertEqual(raw[30000:32000], gated[30000:32000]) # protected quiet onset
        self.assertEqual(raw[44800:51000], gated[44800:51000]) # protected ending
        self.assertEqual(bytes(6400), gated[56000:62400])
        audio.clear(); self.assertEqual(b'', audio.working_bytes(0))

    def test_threshold_changes_only_future_audio_and_independent_controls(self):
        controls = AudioControls(True, -30); other = AudioControls()
        gate = SilenceGate(controls)
        first = gate.feed(pcm(300, 1))
        controls.update(False, -70)
        second = gate.feed(pcm(300, 1)) + gate.finish()
        self.assertFalse(any(first)); self.assertTrue(any(second))
        self.assertEqual(-50, other.snapshot()['silence_threshold_dbfs'])
        self.assertTrue(other.snapshot()['vad_enabled'])
        self.assertEqual(64000, len(first + second))

    def test_client_preferences_survive_new_manager_but_not_modify_open_manager(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, 'config.toml'); config.save(config.defaults(), path)
            one = speech.SpeechRecognitionManager(directory, config_path=str(path))
            other_open = speech.SpeechRecognitionManager(directory, config_path=str(path))
            one.set_audio_controls(False, -67)
            fresh = speech.SpeechRecognitionManager(directory, config_path=str(path))
            self.assertEqual(False, fresh.snapshot()['vad_enabled'])
            self.assertEqual(-67, fresh.snapshot()['silence_threshold_dbfs'])
            self.assertTrue(other_open.snapshot()['vad_enabled'])
            before = path.read_bytes()
            for enabled, threshold in [(1,-50),(True,False),(True,-100),(False,1),(True,float('nan'))]:
                with self.assertRaises(ValueError): one.set_audio_controls(enabled,threshold)
            self.assertEqual(before,path.read_bytes())
            self.assertEqual(['config.toml'], [p.name for p in Path(directory).iterdir()])

    def test_zero_and_explicit_bypass_do_not_load_model(self):
        with mock.patch.dict('sys.modules', {'kienzledoku_vad_model': None}):
            self.assertEqual([], speech_spans(bytes(32000)))
            self.assertEqual([{'start':0,'end':16000}], speech_spans(pcm(1000,1), False))
            with self.assertRaisesRegex(RuntimeError, 'VAD konnte nicht'): speech_spans(pcm(1000,1))
        self.assertEqual(-96, dbfs(0))

    def test_spans_remain_separate_and_restore_original_offsets(self):
        controls = AudioControls()
        args=SimpleNamespace(audio_controls=controls,language='de',asr_api_key=None,asr_timeout=1,commander=None)
        job={'core_start':10,'core_end':20,'is_final':True}
        calls=[]
        def transcribe(*args):
            calls.append(args[1])
            return {'words':[{'word':' ja','start':.5,'end':.7}], 'segments':[]}
        with mock.patch('kienzledoku_vad.speech_spans', return_value=[{'start':0,'end':32000},{'start':96000,'end':128000}]), mock.patch.object(asr,'transcribe_final_block_http',side_effect=transcribe):
            result=asyncio.run(asr.transcribe_vad_block(args,'synthetic',pcm(5000,10),job,10))
        self.assertEqual(2,len(calls))
        text,words,_,_=asr._select_result_for_core(result,10,10,20,True)
        self.assertEqual([10.5,16.5],[word['start'] for word in words])
        self.assertEqual('ja ja',text)

    def test_non_speech_never_calls_whisper_and_toggle_is_snapshot(self):
        controls=AudioControls()
        args=SimpleNamespace(audio_controls=controls,language='de',asr_api_key=None,asr_timeout=1,commander=None)
        received=[]
        def detect(pcm, enabled):
            received.append(enabled); controls.update(False,-50); return []
        with mock.patch('kienzledoku_vad.speech_spans',side_effect=detect), mock.patch.object(asr,'transcribe_final_block_http') as request:
            for _ in range(2): asyncio.run(asr.transcribe_vad_block(args,'synthetic',pcm(500,1),{'core_start':0,'core_end':1},0))
            request.assert_not_called()
        self.assertEqual([True,False],received)

    def test_silent_section_preserves_document_and_skips_llm_diarization(self):
        with tempfile.TemporaryDirectory() as directory:
            callback=mock.Mock(); manager=speech.SpeechRecognitionManager(directory,on_document=callback)
            manager.live_transcript='existing'; manager.diarized_text='edited existing'
            async def recording(_): return {'transcript':'','recording_finalized':True,'metrics':{'failed':0}}
            with mock.patch.object(speech,'run_recording',new=recording),mock.patch.object(speech,'diarize_audio') as diar,mock.patch.object(manager,'_document_text') as llm:
                manager._run_ram_pipeline('existing','edited existing',True)
                diar.assert_not_called();llm.assert_not_called();callback.assert_not_called()
            self.assertEqual('ready',manager.status);self.assertIn('Keine Sprache',manager.message)
            self.assertEqual('edited existing',manager.diarized_text)
            self.assertEqual([],list(Path(directory).iterdir()))

if __name__=='__main__':unittest.main()
