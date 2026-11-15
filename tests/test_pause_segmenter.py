"""One amplitude gate, bounded cores and a RAM-only recording pipeline."""
import asyncio
from array import array
from types import SimpleNamespace, ModuleType
import threading
import unittest
from unittest import mock

import kienzledoku_asr_v6 as asr
from kienzledoku_vad import AudioControls


def options():
    return SimpleNamespace(pause_seconds=.8, short_block_pause_seconds=1.5,
        min_block_seconds=4., max_block_seconds=20., context_seconds=.7,
        segment_frame_ms=30, silence_rms=999999, auto_rms_min=999999,
        auto_rms_max=999999, auto_rms_factor=2., audio_controls=AudioControls(False,-50),
        asr='http://synthetic.invalid:8185', commander=None, language='de',
        asr_api_key=None, asr_timeout=2., audio_chunk_ms=100, status_seconds=5.,
        input_wav=None, replay_speed=1., device=None, wav='', json='', ram_only=True,
        quiet=True, stop_event=threading.Event(), event_callback=lambda event:None)


def pcm(amplitude, seconds):
    return array('h', [amplitude, -amplitude] * round(8000*seconds)).tobytes()


class PauseSegmenterTests(unittest.TestCase):
    def segment(self, original, args=None):
        args=args or options()
        audio=asr.AudioState(controls=args.audio_controls)
        audio.append(original);audio.finish_gate()
        self.assertEqual(original,audio.all_pcm())
        working=audio.working_bytes(0)
        self.assertEqual(len(original),len(working))
        segmenter=asr.PauseSegmenter(args);events=[]
        frame_bytes=960
        for start in range(0,len(working)-frame_bytes+1,frame_bytes):
            events.extend(segmenter.feed(working[start:start+frame_bytes],start/32000,(start+frame_bytes)/32000))
        prior=0.
        for event in events:
            self.assertAlmostEqual(prior,event['core_start'])
            self.assertLessEqual(event['core_end']-event['core_start'],20.030001)
            prior=event['core_end']
        return events,working

    def test_quiet_signal_above_slider_reaches_bounded_blocks(self):
        events,working=self.segment(pcm(140,90))  # -47.4 dBFS, above -50 slider
        self.assertTrue(any(working))
        self.assertEqual(4,len(events))
        self.assertEqual({'failsafe_max'},{e['reason'] for e in events})

    def test_silence_is_bounded_even_without_any_detected_speech(self):
        events,working=self.segment(pcm(0,90))
        self.assertEqual(4,len(events));self.assertFalse(any(working))

    def test_slider_is_the_only_amplitude_threshold_and_preserves_timeline(self):
        args=options();args.audio_controls.update(True,-40)
        events,working=self.segment(pcm(140,90),args)
        self.assertFalse(any(working));self.assertEqual(4,len(events))

    def test_natural_pause_still_cuts_with_word_margins(self):
        events,working=self.segment(pcm(140,5)+pcm(0,3))
        self.assertEqual(1,len(events));self.assertEqual('pause',events[0]['reason'])
        # Gate post-roll + pause offset move the cut into genuine silence.
        cut=events[0]['core_end']
        self.assertGreater(cut,5);self.assertLess(cut,5.6)
        self.assertTrue(any(working[:160000]))

    def test_full_recording_silence_has_no_whisper_call_and_rest_finalizes(self):
        self.recording(pcm(0,45),expected_calls=0)

    def test_full_recording_quiet_signal_runs_asr_and_rest_finalizes(self):
        self.recording(pcm(140,45),expected_calls=3)

    def recording(self, original, expected_calls):
        args=options()
        class Stream:
            active=False
            def start(self):
                self.active=True;audio_append(original);args.stop_event.set()
            def stop(self): self.active=False
            def close(self): pass
        audio_append=None
        def create(_sd,_device,append,_emit,_chunk):
            nonlocal audio_append
            audio_append=append
            return Stream(),[]
        fake=ModuleType('kienzledoku_audio');fake.create_input=create
        with mock.patch.dict('sys.modules',{'sounddevice':ModuleType('sounddevice'),'kienzledoku_audio':fake}), \
             mock.patch.object(asr,'transcribe_final_block_http',return_value={'text':'synthetic','words':[],'segments':[]}) as request:
            result=asyncio.run(asyncio.wait_for(asr.run_recording(args),10))
        self.assertEqual(expected_calls,request.call_count)
        self.assertTrue(result['recording_finalized'])
        self.assertEqual(45,result['audio_duration'])
        self.assertEqual(3,len(result['blocks']))
        self.assertEqual('final',result['blocks'][-1]['reason'])
        self.assertEqual(45,result['blocks'][-1]['core_end'])
        self.assertTrue(all(b['core_end']-b['core_start']<=20.030001 for b in result['blocks']))
        self.assertEqual([],args._recording_tasks)


if __name__=='__main__':unittest.main()
