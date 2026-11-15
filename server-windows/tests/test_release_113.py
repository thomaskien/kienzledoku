"""Public model grades and cold serial lifecycle with synthetic workers."""
import json
import os
from dataclasses import asdict, replace
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'linux'),str(ROOT/'linux/runtime')]
import install_server
from serial_server import SerialSettings,SerialCommander,model_command
from test_commander import RuntimeDouble,eventually

class Release113(unittest.TestCase):
    def config(self):
        models=['qwen4-q4','9b-q4','gemma12-q8','27b-q4']
        cfg=dict(Models=models,DefaultModel='qwen4-q4',QualityModels=dict(basis='qwen4-q4',gruendlich='gemma12-q8',sehr_gruendlich='27b-q4'),
            ParallelModel='',WslRamGiB=32,AudioCache='ram',GpuIndex=0,AuthEnabled=False,AsrOnDemand=True,
            EnabledFields=['anamnese','befund','ekg','sonografie','therapie','prozedere','notiz'],
            Profiles={key:dict(Mode='serial') for key in models})
        with patch.object(install_server,'ROOT',ROOT):
            install_server.validate_config(cfg,24576)
            return SerialSettings(**install_server.runtime_settings(cfg,dict(vram_mib=24576))).validate()
    def test_grade_mapping_does_not_mix_dataclass_backend_with_model_label(self):
        cfg=self.config()
        self.assertEqual(('basis','gruendlich','sehr_gruendlich'),cfg.allowed)
        self.assertEqual('qwen4_q4',cfg.model('basis').model_id)
        self.assertEqual('gemma12_q8',cfg.model('gruendlich').model_id)
        self.assertEqual('llama.cpp',cfg.model('basis').backend)
        self.assertEqual(999,cfg.model('basis').gpu_layers)
        self.assertIn('--n-gpu-layers',model_command(cfg,cfg.model('basis'),'basis'))
        self.assertFalse(cfg.auth_enabled)
        self.assertIn('ekg',cfg.enabled_fields)
        self.assertEqual('basis',cfg.default)
    def test_first_audio_loads_and_last_llm_does_not_reload_whisper(self):
        cfg=self.config();runtime=RuntimeDouble(cfg);commander=SerialCommander(cfg,runtime);self.addCleanup(commander.close)
        eventually(lambda:not commander.status()['transition_running'] and commander._ready_once.is_set())
        self.assertFalse(commander.status()['loaded']['asr'])
        audio=commander.submit('asr',{'body':b'synthetic'},request_id='release-audio');audio.future.result(timeout=3)
        eventually(lambda:commander.status()['loaded']['asr'])
        job=commander.submit('llm',{'llm':{}},quality='basis',request_id='release-llm');job.future.result(timeout=3)
        eventually(lambda:commander.status()['loaded']=={'asr':False,'diar':False,'llm':None} and not commander.status()['transition_running'])
        self.assertTrue(commander.status()['asr_on_demand'])
    def test_unknown_grade_assignment_is_rejected(self):
        with self.assertRaises(ValueError): replace(self.config(),quality_models={'basis':'missing'}).validate()

    def test_real_check_config_resolves_grades_to_profiles(self):
        all_grades=self.config()
        two_grades=replace(all_grades, default_quality='gruendlich',
                           quality_models={'gruendlich':'gemma12_q8','sehr_gruendlich':'sehr_gruendlich'},
                           profiles={q:p for q,p in all_grades.profiles.items() if q in ('gemma12_q8','sehr_gruendlich')})
        legacy=replace(all_grades, quality_models={}, default_quality='gemma12_q8')
        remote=replace(all_grades, remote_llm_url='http://192.0.2.1:8185', default_quality='auto')
        for cfg in (all_grades,two_grades,legacy,remote):
            with self.subTest(grades=cfg.allowed,remote=bool(cfg.remote_llm_url)), tempfile.TemporaryDirectory() as temp:
                path=Path(temp)/'config.json';path.write_text(json.dumps(asdict(cfg)))
                result=subprocess.run([sys.executable,str(ROOT/'linux/runtime/serial_server.py'),
                                       '--config',str(path),'--check-config'],
                                      capture_output=True,text=True,timeout=10)
                self.assertEqual(0,result.returncode,result.stderr)
                output=json.loads(result.stdout)
                self.assertEqual(list(cfg.allowed),output['allowed'])
                self.assertEqual({q:'serial' for q in cfg.allowed},output['modes'])
if __name__=='__main__':unittest.main()
