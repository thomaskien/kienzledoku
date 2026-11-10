from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'linux'),str(ROOT/'linux/runtime'),str(ROOT/'tests')]
from test_windows_server import settings, CATALOG
from test_commander import RuntimeDouble,eventually
from serial_server import SerialCommander,SerialSettings
from kienzledoku_commander.api import API
import install_server
import verify


class ResidentSelection(unittest.TestCase):
    def config(self,resident='gruendlich',default='basis'):
        modes={resident:'parallel'} if resident else {}
        return replace(settings(default,modes),resident_quality=resident).validate()

    def commander(self,cfg):
        runtime=RuntimeDouble(cfg);commander=SerialCommander(cfg,runtime)
        self.addCleanup(commander.close)
        eventually(lambda:commander.status()['loaded']==commander._baseline() and not commander.status()['transition_running'])
        return commander,runtime

    def test_default_request_and_parallel_resident_are_independent(self):
        cfg=self.config();c,r=self.commander(cfg)
        self.assertEqual('basis',cfg.quality())
        self.assertEqual({'asr':True,'diar':True,'llm':'gruendlich'},r.loaded)
        r.holds['serial-default']=threading.Event();self.addCleanup(r.holds['serial-default'].set)
        job=c.submit('llm',{'llm':{}},request_id='serial-default')
        eventually(lambda:'serial-default' in r.started)
        self.assertEqual({'asr':False,'diar':False,'llm':'basis'},r.loaded)
        self.assertEqual('serial',c.status()['loaded_llm_mode'])
        r.holds['serial-default'].set();job.future.result(3)
        eventually(lambda:r.loaded=={'asr':True,'diar':True,'llm':'gruendlich'})
        state=c.status()
        self.assertEqual('gruendlich',state['resident_quality'])
        self.assertEqual('parallel',state['loaded_llm_mode'])
        self.assertEqual(CATALOG['9b-q6']['label'],state['loaded_llm_label'])

    def test_diarization_keeps_the_chosen_parallel_model_and_whisper_loaded(self):
        c,r=self.commander(self.config())
        r.holds['diar']=threading.Event();self.addCleanup(r.holds['diar'].set)
        job=c.submit('diar',{'body':b'synthetic'},request_id='diar')
        eventually(lambda:'diar' in r.started)
        self.assertEqual({'asr':True,'diar':True,'llm':'gruendlich'},r.loaded)
        r.holds['diar'].set();job.future.result(3)

    def test_no_parallel_selection_keeps_all_llms_serial(self):
        cfg=self.config('');c,r=self.commander(cfg)
        self.assertEqual({'asr':True,'diar':False,'llm':None},r.loaded)
        self.assertIsNone(cfg.baseline_llm)
        for quality in cfg.allowed:
            self.assertFalse(cfg.persistent(quality))
            c.submit('llm',{'llm':{}},quality).future.result(3)
            eventually(lambda:r.loaded=={'asr':True,'diar':False,'llm':None})

    def test_legacy_configs_preserve_the_old_default_based_baseline(self):
        self.assertEqual('basis',settings('basis',{'basis':'parallel'}).baseline_llm)
        self.assertIsNone(settings('sehr_gruendlich',{'basis':'parallel'}).baseline_llm)

    def test_multiple_resident_flags_or_a_missing_selection_are_rejected(self):
        with self.assertRaises(ValueError):
            replace(settings('basis',{'basis':'parallel','gruendlich':'parallel'}),resident_quality='gruendlich').validate()
        with self.assertRaises(ValueError):
            replace(settings(),resident_quality='missing').validate()

    def test_additional_model_uses_catalog_hardware_profile_and_declared_fallback(self):
        cfg=self.config('')
        profiles=dict(cfg.profiles)
        profiles['future_14b']=dict(profiles['basis'],path='/models/future.gguf',label='Synthetic future model',
            mode='parallel',parallel_vram_mib=24576,fallbacks=['basis'])
        cfg=replace(cfg,profiles=profiles,resident_quality='future_14b').validate()
        self.assertEqual('future_14b',cfg.baseline_llm)
        self.assertEqual('basis',cfg.fallback('future_14b'))
        with self.assertRaises(ValueError):replace(cfg,tier=16).validate()
        profiles=dict(profiles);profiles['future_14b']=dict(profiles['future_14b'],parallel_vram_mib=None)
        with self.assertRaises(ValueError):replace(cfg,profiles=profiles).validate()

    def test_generated_runtime_and_final_verification_use_selected_resident(self):
        cfg=dict(Models=list(CATALOG),DefaultModel='27b-q4',ParallelModel='9b-q6',WslRamGiB=32,
                 AudioCache='ram',GpuIndex=0,Profiles={key:{'Mode':'parallel' if key=='9b-q6' else 'serial'} for key in CATALOG})
        with patch.object(install_server,'ROOT',ROOT):
            install_server.validate_config(cfg,24576)
            runtime=install_server.runtime_settings(cfg,dict(vram_mib=24576))
        self.assertEqual('sehr_gruendlich',runtime['default_quality'])
        self.assertEqual('gruendlich',runtime['resident_quality'])
        self.assertEqual({'asr':True,'diar':True,'llm':'gruendlich'},verify.expected_baseline(runtime))
        cfg['ParallelModel']=''
        with patch.object(install_server,'ROOT',ROOT):
            with self.assertRaises(ValueError):install_server.validate_config(cfg,24576)

    def test_discovery_reports_chosen_resident_loaded_model_and_serial_availability(self):
        c,r=self.commander(self.config())
        with patch.dict(os.environ,{c.settings.token_env:'synthetic-token'}):
            server=API(('127.0.0.1',0),c)
        thread=threading.Thread(target=server.serve_forever);thread.start()
        def cleanup():
            server.shutdown();server.server_close();thread.join()
        self.addCleanup(cleanup)
        def get(path):
            request=Request('http://127.0.0.1:'+str(server.server_port)+path,headers={'Authorization':'Bearer synthetic-token'})
            with urlopen(request,timeout=3) as response:return json.load(response)
        data=get('/v1/models')['data']
        selected={entry['id']:entry for entry in data}
        self.assertTrue(selected['basis']['default'])
        self.assertTrue(selected['gruendlich']['resident'])
        self.assertTrue(selected['gruendlich']['loaded'])
        self.assertFalse(selected['basis']['persistent'])
        self.assertTrue(all(entry['serial_available'] for entry in data))
        self.assertEqual('gruendlich',get('/v1/runtime/status')['resident_quality'])


if __name__=='__main__':unittest.main()
