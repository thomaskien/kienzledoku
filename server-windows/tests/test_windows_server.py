import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'linux'),str(ROOT/'linux/runtime')]
from serial_server import SerialSettings,SerialCommander
from kienzledoku_commander.asr_stage import install
from test_commander import RuntimeDouble,eventually
import install_server

CATALOG=json.loads((ROOT/'models.json').read_text())

def settings(default='basis',modes=None,tier=24):
    profiles={}
    for key,item in CATALOG.items():
        profiles[item['quality']]=dict(item['profile'],path='/models/'+item['files'][0]['filename'],
            label=item['label'],mode=(modes or {}).get(item['quality'],'serial'))
    return SerialSettings(tier=tier,default_quality=default,profiles=profiles).validate()

class ServerModes(unittest.TestCase):
    def commander(self,cfg):
        runtime=RuntimeDouble(cfg);commander=SerialCommander(cfg,runtime)
        self.addCleanup(commander.close)
        eventually(lambda:commander.status()['loaded']==commander._baseline() and not commander.status()['transition_running'])
        return commander,runtime

    def test_parallel_q6_keeps_audio_loaded_during_llm_request(self):
        cfg=settings('gruendlich',{'basis':'parallel','gruendlich':'parallel'})
        c,r=self.commander(cfg)
        eventually(lambda:r.loaded=={'asr':True,'diar':True,'llm':'gruendlich'})
        r.holds['held']=threading.Event();self.addCleanup(r.holds['held'].set)
        request=c.submit('llm',{'llm':{}},'gruendlich',request_id='held')
        eventually(lambda:'held' in r.started)
        audio=c.submit('asr',{'body':b'synthetic'},request_id='audio')
        audio.future.result(3)
        self.assertTrue(r.loaded['asr']);self.assertTrue(r.loaded['diar'])
        r.holds['held'].set();request.future.result(3)

    def test_27b_serial_restores_parallel_default_after_success(self):
        cfg=settings('basis',{'basis':'parallel'})
        c,r=self.commander(cfg)
        r.holds['large']=threading.Event();self.addCleanup(r.holds['large'].set)
        request=c.submit('llm',{'llm':{}},'sehr_gruendlich',request_id='large')
        eventually(lambda:'large' in r.started)
        self.assertEqual({'asr':False,'diar':False,'llm':'sehr_gruendlich'},r.loaded)
        r.holds['large'].set();request.future.result(3)
        eventually(lambda:r.loaded=={'asr':True,'diar':True,'llm':'basis'})

    def test_q6_parallel_refuses_16gib_full_gpu_and_27b_has_no_parallel_profile(self):
        with self.assertRaises(ValueError):settings('gruendlich',{'gruendlich':'parallel'},tier=16)
        with self.assertRaises(ValueError):settings('sehr_gruendlich',{'sehr_gruendlich':'parallel'},tier=32)
        self.assertTrue(settings('basis',{'basis':'parallel'},tier=16).persistent('basis'))

    def test_failed_27b_falls_back_only_to_installed_9b_and_recovers(self):
        c,r=self.commander(settings('basis',{'basis':'parallel'}))
        r.fail_load.add('sehr_gruendlich')
        result=c.submit('llm',{'llm':{}},'sehr_gruendlich').future.result(3)
        self.assertIn(result['commander']['used_quality'],('basis','gruendlich'))
        eventually(lambda:c.status()['asr_ready'] and not c.status()['transition_running'])

class ModelImport(unittest.TestCase):
    def test_stale_wsl_memory_limit_is_rejected_before_models_start(self):
        cfg={'WslRamGiB':24}
        with self.assertRaises(ValueError):install_server.check_memory(cfg,{'ram_bytes':16*1024**3})
        install_server.check_memory(cfg,{'ram_bytes':int(23.8*1024**3)})

    def test_git_blob_sha1_and_sha256_detect_same_size_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'small';path.write_bytes(b'hello\n')
            entry={'bytes':6,'git_blob_sha1':'ce013625030ba8dba906f756967f9e9ca394464a'}
            self.assertTrue(install_server.file_valid(path,entry))
            entry={'bytes':6,'sha256':hashlib.sha256(b'hello\n').hexdigest()}
            self.assertTrue(install_server.file_valid(path,entry))
            path.write_bytes(b'other\n');self.assertFalse(install_server.file_valid(path,entry))

    def test_config_rejects_changed_gpu_and_unproven_27b_low_ram_cache(self):
        cfg=dict(WslRamGiB=16,Models=['27b-q4'],DefaultModel='27b-q4',AudioCache='ram',Profiles={'27b-q4':{'Mode':'serial'}})
        with patch.object(install_server,'ROOT',ROOT):
            with self.assertRaises(ValueError):install_server.validate_config(cfg,24576)
            cfg['AudioCache']='disk';install_server.validate_config(cfg,24576)
            with self.assertRaises(ValueError):install_server.validate_config(cfg,8192)

    def test_archive_has_only_required_audio_assets_and_pinned_model_revisions(self):
        audio=json.loads((ROOT/'audio-files.json').read_text())
        self.assertEqual({'9b-q4','9b-q6','27b-q4','gemma12-qat-q4','gemma12-q8','gemma26-qat-q4'},set(CATALOG))
        for entry in audio:
            self.assertTrue(entry.get('sha256') or entry.get('git_blob_sha1'))
            self.assertGreater(entry['bytes'],0)
            self.assertNotIn('..',Path(entry['path']).parts)
        self.assertIn('whisper/large-v3.pt',{f['path'] for f in audio})
        self.assertIn('pyannote/embedding/pytorch_model.bin',{f['path'] for f in audio})

class MappedWhisper(unittest.TestCase):
    def test_checkpoint_maps_to_cpu_and_loader_is_restored_after_transfer(self):
        calls=[];torch=types.ModuleType('torch')
        def torch_load(file,*a,**kw):calls.append(('checkpoint',Path(file).name,kw));return {}
        torch.load=torch_load
        class Model:
            def to(self,device):calls.append(('move',device));return self
        model=Model();backend=types.ModuleType('whisperlivekit.simul_whisper.backend')
        def original(name,device=None):
            calls.append(('loader',device));torch.load('/models/large-v3.pt',map_location=device);return model
        backend.load_model=original
        parent=types.ModuleType('whisperlivekit');simul=types.ModuleType('whisperlivekit.simul_whisper')
        parent.simul_whisper=simul;simul.backend=backend
        with patch.dict(sys.modules,{'torch':torch,'whisperlivekit':parent,'whisperlivekit.simul_whisper':simul,'whisperlivekit.simul_whisper.backend':backend}):
            install();self.assertIs(backend.load_model('fixture','cuda:0'),model)
            self.assertIs(torch.load,torch_load)
        self.assertEqual(('loader','cpu'),calls[0]);self.assertTrue(calls[1][2]['mmap'])
        self.assertEqual(('move','cuda:0'),calls[2])

if __name__=='__main__':unittest.main()
