from kienzledoku_vad import AudioControls
import asyncio
import io
import struct
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest import mock
import kienzledoku_asr_v6 as asr
from kienzledoku_commander.api import MAX_AUDIO, validate_audio_duration
from kienzledoku_commander.errors import PayloadTooLarge
from test_record_140 import _Stream


def wav_header(seconds):
    size=seconds*32000
    return struct.pack('<4sI4s4sIHHIIHH4sI',b'RIFF',size+36,b'WAVE',b'fmt ',16,1,1,16000,32000,2,16,b'data',size)

class AudioLimitTests(unittest.TestCase):
    def test_two_hour_boundary_without_allocating_two_hours(self):
        self.assertEqual(7200,asr.MAX_SECTION_SECONDS)
        self.assertLess(7200*32000+44,MAX_AUDIO)
        validate_audio_duration(wav_header(7200))
        with self.assertRaises(PayloadTooLarge):validate_audio_duration(wav_header(7201))
        audio=asr.AudioState(max_seconds=.01)
        audio.append(b'\x01\x00'*1000)
        self.assertEqual(320,audio.length_bytes())
        self.assertTrue(audio.limit_reached)
        audio.append(b'\x02\x00'*1000)
        self.assertEqual(b'\x01\x00'*160,audio.all_pcm())

    def test_auto_stop_finalizes_and_preserves_text_in_ram(self):
        with tempfile.TemporaryDirectory() as directory:
            stop=threading.Event();events=[]
            args=types.SimpleNamespace(asr='http://127.0.0.1:8179',language='de',asr_api_key=None,
                asr_timeout=30,pause_seconds=.8,short_block_pause_seconds=1.5,min_block_seconds=.2,
                max_block_seconds=.4,context_seconds=0,segment_frame_ms=30,silence_rms=None,
                auto_rms_min=160,auto_rms_max=1200,auto_rms_factor=2,audio_chunk_ms=100,
                status_seconds=5,input_wav=None,replay_speed=1,device=None,wav='',json='',
                commander=None,recording_finalized=False,commander_metadata=None,ram_only=True,
                quiet=True,audio_controls=AudioControls(False),stop_event=stop,event_callback=events.append)
            fake=types.ModuleType('kienzledoku_audio')
            fake.create_input=lambda _sd,_dev,append,_emit,_ms:(_Stream(append),[])
            original=asr.AudioState
            with mock.patch.dict('sys.modules',{'sounddevice':types.ModuleType('sounddevice'),'kienzledoku_audio':fake}),mock.patch.object(asr,'AudioState',side_effect=lambda **kw:original(max_seconds=.4,**kw)),mock.patch.object(asr,'transcribe_final_block_http',return_value={'text':'synthetisch','words':[],'segments':[{'start':0,'end':.4,'text':'synthetisch'}]}):
                result=asyncio.run(asyncio.wait_for(asr.run_recording(args),3))
            self.assertTrue(stop.is_set())
            self.assertTrue(result['recording_finalized'])
            self.assertEqual('synthetisch',result['transcript'])
            self.assertEqual(.4,result['audio_duration'])
            self.assertTrue(any(e['type']=='recording_limit' for e in events))
            self.assertEqual([],list(Path(directory).iterdir()))

if __name__=='__main__':unittest.main()
