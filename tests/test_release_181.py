import importlib.util
import io
import json
import tempfile
import unittest
import wave
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import patch
from installer import core
from kienzledoku_commander.config import load_settings
from kienzledoku_commander.hardware import HardwareProbe
from kienzledoku_commander_client import CommanderClient
ROOT=Path(__file__).resolve().parents[1]

class Release181Tests(unittest.TestCase):
    def test_mac_roles_remote_diarization_and_turbo_survive_configuration(self):
        hw=dict(server_supported=True,ram_gib=32,arch='arm64')
        with tempfile.TemporaryDirectory() as td,patch.object(core,'hardware',return_value=hw):
            root=Path(td);cfg=core.defaults(hw,root)
            cfg.update(mode='server',server_role='asr',remote_llm_url='http://192.0.2.2:8185',remote_diar_url='http://192.0.2.2:8185',asr_model='turbo-int8')
            core.validate(cfg,hw);file=root/'commander.toml';file.write_text(core.commander_toml(cfg,root/'version',root))
            value=load_settings(file)
            self.assertEqual('http://192.0.2.2:8185',value.remote_diar_url)
            self.assertEqual({'asr','diar','llm'},set(value.enabled_roles));self.assertIn('whisper-turbo-8bit-mlx',value.asr_model_path)
            cfg.update(server_role='llm_diar',remote_llm_url='',remote_diar_url='')
            file.write_text(core.commander_toml(cfg,root/'version',root));value=load_settings(file)
            self.assertEqual({'llm','diar'},set(value.enabled_roles))
            cfg.update(server_role='diar',selected_models=[],quality_models={})
            core.validate(cfg,hw);file.write_text(core.commander_toml(cfg,root/'version',root));value=load_settings(file)
            self.assertEqual(('diar',),value.enabled_roles)
    def test_mac_probe_is_one_bounded_read_and_does_not_call_nvidia(self):
        calls=[]
        def run(argv,timeout):
            calls.append((argv,timeout));return json.dumps([dict(kind='gpu',id='smc:Tg0C',name='Tg0C',value=42)]).encode()
        result=HardwareProbe(system='Darwin',runner=run).temperatures()
        self.assertEqual(1,len(calls));self.assertLessEqual(calls[0][1],2)
        self.assertEqual(42,result['sensors'][0]['value']);self.assertEqual('apple-smc',result['sensors'][0]['source'])
    def test_temperatures_are_deduplicated_and_missing_or_stale_are_hidden(self):
        now=datetime.now(timezone.utc)
        def data(value,when=now):return dict(sensors=[dict(kind='gpu',value=value,status='available',measured_at=when.isoformat())])
        result=data(43)
        result['remote_llm']=dict(source='http://192.0.2.2:8185/',status='available',data=data(50))
        result['remote_diar']=dict(source='http://192.0.2.2:8185',status='available',data=data(50))
        client=CommanderClient('http://192.0.2.1:8185')
        with patch.object(client,'request',return_value=result):
            self.assertEqual([43,50],[v['value'] for v in client.gpu_temperatures()])
            result['remote_llm']['data']=data(50,now-timedelta(seconds=90));result['remote_diar']['data']=data(50,now-timedelta(seconds=90))
            self.assertEqual([43],[v['value'] for v in client.gpu_temperatures()])
            result['sensors']=[]
            self.assertEqual([],client.gpu_temperatures())
    def test_native_server_roles_select_only_needed_audio_and_units(self):
        spec=importlib.util.spec_from_file_location('engine181',ROOT/'server-windows/linux/install_server.py');engine=importlib.util.module_from_spec(spec);spec.loader.exec_module(engine);engine.ROOT=ROOT/'server-windows'
        for role,wanted in [('llm',[]),('diar',['pyannote']),('llm_diar',['pyannote']),('asr',['whisper-turbo'])]:
            cfg=dict(ServerRole=role,AsrModel='turbo-int8',RemoteDiarUrl='http://192.0.2.3:8185' if role=='asr' else '')
            self.assertEqual(set(wanted),{e['path'].split('/')[0] for e in engine.audio_files(cfg)})
            self.assertEqual(('asr' in role and role=='asr'),engine.UNITS[1] in engine.selected_units(cfg))
        for mid,context in [('qwen4-q4',32768),('gemma-e2b-qat-q4',8192)]:
            cfg=dict(ServerRole='full',Models=[mid],DefaultModel=mid,QualityModels={'basis':mid},Profiles={mid:dict(Mode='serial')},
                ParallelModel='',AsrOnDemand=True,DiarizationMode='serial',AsrModel='turbo-int8',WslRamGiB=16,AudioCache='ram',GpuIndex=0,AuthEnabled=False)
            engine.validate_config(cfg,4096)
            settings=engine.runtime_settings(cfg,dict(vram_mib=4096));self.assertEqual(context,next(iter(settings['profiles'].values()))['context'])
            cfg['AsrModel']='large-v3'
            with self.assertRaises(ValueError):engine.validate_config(cfg,4096)
    def test_turbo_parser_keeps_silence_length_and_sample_values(self):
        spec=importlib.util.spec_from_file_location('turbo181',ROOT/'server-windows/linux/runtime/turbo_asr.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        frames=b'\0\0'*1600+b'\x10\x00'*1600
        f=io.BytesIO()
        with wave.open(f,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(frames)
        body=b'--a\r\nContent-Disposition: form-data; name="file"; filename="synthetic.wav"\r\nContent-Type: audio/wav\r\n\r\n'+f.getvalue()+b'\r\n--a--\r\n'
        actual,language=module.audio_input('multipart/form-data; boundary=a',body)
        self.assertEqual(frames,actual);self.assertEqual('de',language)
