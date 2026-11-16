import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from installer import windows_core as win
import kienzledoku_config as client

ROOT=Path(__file__).resolve().parents[1]

class WindowsWizardTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        self.env=patch.dict(os.environ,LOCALAPPDATA=str(self.base),KIENZLEDOKU_COMMANDER_TOKEN='',HF_TOKEN='',HUGGING_FACE_HUB_TOKEN='',HF_HOME=str(self.base/'hf'));self.env.start();self.addCleanup(self.env.stop)
        for target,value in [('load',client.defaults()),('read_commander_token','')]:
            p=patch.object(client,target,return_value=value);p.start();self.addCleanup(p.stop)
        self.info=dict(client=False,previous={},hardware=dict(Build=26100,Architecture='AMD64',RamBytes=64*2**30,Gpus=[dict(Index=0,Name='RTX 3090',VramMiB=24576)],Addresses=[dict(IPAddress='10.0.83.50')]))
        self.hw=win.hardware(self.info);self.cfg=win.defaults(self.hw,self.base)
        self.cfg.update(cache_directory=r'C:\Models',install_directory=r'C:\Programs\kienzledoku Server')
    def test_fresh_client_has_only_commander_and_no_gpu_requirement(self):
        h=win.hardware(dict(hardware=dict(Build=19045,Architecture='AMD64',RamBytes=8*2**30),previous={}))
        cfg=win.defaults(h,self.base)
        self.assertEqual(cfg['mode'],'client');self.assertEqual(cfg['commander_url'],'http://10.0.83.140:8185')
        win.validate(cfg,h)
        cfg['mode']='server'
        with self.assertRaisesRegex(ValueError,'Windows 11'):win.validate(cfg,h)
    def test_suitable_gpu_can_follow_an_unsupported_adapter(self):
        info=copy.deepcopy(self.info);info['previous']=None
        info['hardware']['Gpus'].insert(0,dict(Index=1,Name='small adapter',VramMiB=2048))
        h=win.hardware(info)
        self.assertTrue(h['server_supported']);self.assertEqual(h['gpu_index'],0)

    def test_upgrade_preserves_server_model_prompt_and_tokens(self):
        old=dict(Models=['gemma12-q8','27b-q4'],QualityModels={'gruendlich':'gemma12-q8','sehr_gruendlich':'27b-q4'},DefaultModel='gemma12-q8',ParallelModel='gemma12-q8',PromptText='CUSTOM PROMPT',DiarizationMode='with_asr',WslRamGiB=28,CacheDirectory=r'D:\Models',Sources=[r'E:\Offline'],AuthEnabled=True)
        self.info['previous']=old;self.info['client']=True
        state=self.base/'kienzledoku-server';state.mkdir()
        for name,value in [('hf.token','hf_synthetic'),('client.token','synthetic-commander'),('remote-llm.token','synthetic-remote')]: (state/name).write_text(value)
        cfg=win.defaults(win.hardware(self.info),self.base)
        self.assertEqual(cfg['mode'],'combined');self.assertEqual(cfg['quality_models'],old['QualityModels'])
        self.assertEqual(cfg['prompt'],'CUSTOM PROMPT');self.assertEqual(cfg['parallel_model'],'gemma12-q8')
        self.assertEqual(cfg['hf_token'],'hf_synthetic');self.assertEqual(cfg['server_token'],'synthetic-commander')
        self.assertEqual(cfg['sources'],r'E:\Offline');self.assertEqual(cfg['diarization_mode'],'with_asr')
    def test_parallel_profile_is_one_supported_model(self):
        cfg=self.cfg;cfg.update(mode='combined',selected_models=['qwen4-q4','gemma12-q8','27b-q4'],quality_models={'basis':'qwen4-q4','gruendlich':'gemma12-q8','sehr_gruendlich':'27b-q4'},memory_mode='parallel',parallel_model='gemma12-q8')
        win.validate(cfg,self.hw)
        cfg['parallel_model']='qwen4-q4'
        with self.assertRaisesRegex(ValueError,'Parallelmodell'):win.validate(cfg,self.hw)
    def test_mapping_and_windows_ram_reserve_checked(self):
        cfg=self.cfg;cfg['mode']='server';win.validate(cfg,self.hw)
        cfg['quality_models']={'gruendlich':'qwen4-q4'}
        with self.assertRaisesRegex(ValueError,'Modellzuordnung'):win.validate(cfg,self.hw)
        cfg['quality_models']={'basis':'qwen4-q4'};small=dict(self.hw,ram_gib=32);cfg['wsl_ram_gib']=32
        with self.assertRaisesRegex(ValueError,'freihalten'):win.validate(cfg,small)
    def test_plan_contains_no_secret(self):
        self.cfg.update(mode='combined',network='lan',listen_host='10.0.83.50',hf_token='secret-hf',commander_token='secret-command',remote_llm_url='http://other:8185',remote_llm_token='secret-remote')
        result=win.plan(self.cfg,self.hw)
        self.assertIn('http://127.0.0.1:8185',str(result));self.assertNotIn('secret-',json.dumps(result))
    def test_client_apply_keeps_vad_and_record_options(self):
        spec=importlib.util.spec_from_file_location('installer_client',ROOT/'windows/installer_client.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        saved=client.defaults();saved['record'].update(vad_enabled=False,silence_threshold_dbfs=-42)
        cfgfile=self.base/'request.json';cfgfile.write_text(json.dumps(self.cfg))
        with patch.object(client,'load',return_value=saved),patch.object(client,'save') as save,patch.object(client,'store_commander_token') as token,patch.object(client,'config_dir',return_value=self.base),patch.object(sys,'argv',['installer_client','--wizard-config',str(cfgfile)]):mod.main()
        output=save.call_args.args[0]
        self.assertFalse(output['record']['vad_enabled']);self.assertEqual(output['record']['silence_threshold_dbfs'],-42)
        self.assertTrue(output['commander']['enabled']);token.assert_not_called()
    def test_failed_config_save_restores_previous_private_files(self):
        spec=importlib.util.spec_from_file_location('installer_client',ROOT/'windows/installer_client.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        request=self.base/'request.json';selected=dict(self.cfg,commander_token='synthetic-new-token');request.write_text(json.dumps(selected))
        config_path=self.base/'config.toml';token_path=self.base/'commander-token.dpapi'
        config_path.write_bytes(b'old config');token_path.write_bytes(b'old encrypted token')
        def replace_token(value): token_path.write_bytes(b'new encrypted token')
        with patch.object(client,'config_dir',return_value=self.base),patch.object(client,'config_path',return_value=config_path),patch.object(client,'store_commander_token',side_effect=replace_token),patch.object(client,'save',side_effect=OSError('synthetic save failure')),patch.object(sys,'argv',['installer_client','--wizard-config',str(request)]):
            with self.assertRaisesRegex(OSError,'synthetic save failure'):mod.main()
        self.assertEqual(config_path.read_bytes(),b'old config');self.assertEqual(token_path.read_bytes(),b'old encrypted token')

    def test_standard_prompt_uses_utf8_even_with_windows_1252_default(self):
        prompt_path=win.ROOT/'prompt_documentation.txt'
        standard=prompt_path.read_bytes().decode('utf-8')
        original=Path.read_text
        def simulated_windows_read(path,*args,**kwargs):
            if path==prompt_path and not kwargs.get('encoding'):
                return path.read_bytes().decode('cp1252')
            return original(path,*args,**kwargs)
        with patch.object(Path,'read_text',simulated_windows_read):
            b=win.bootstrap(self.hw,self.base)
        self.assertEqual(b['defaults']['prompt'],standard)
        self.assertEqual(b['default_prompt'],standard)
        self.assertIn('ausschließlich',b['default_prompt']);self.assertNotIn('Ã',b['default_prompt'])

    def test_only_known_broken_standard_is_repaired(self):
        standard=win.standard_prompt()
        for encoding in ('cp1252','latin1'):
            broken=standard.encode('utf-8').decode(encoding)
            self.info['previous']={'PromptText':broken.replace('\n','\r\n')}
            b=win.bootstrap(win.hardware(self.info),self.base)
            self.assertEqual(b['defaults']['prompt'],standard)
            self.assertTrue(b['prompt_encoding_repaired'])
        for customized in ('Äußere Befunde, Übelkeit, Größe — eigene Regel.','Angepasster Prompt mit tatsÃ¤chlich als Testbeispiel.'):
            self.info['previous']={'PromptText':customized}
            b=win.bootstrap(win.hardware(self.info),self.base)
            self.assertEqual(b['defaults']['prompt'],customized)
            self.assertFalse(b['prompt_encoding_repaired'])
        self.info['previous']={'PromptText':standard}
        self.assertFalse(win.bootstrap(win.hardware(self.info),self.base)['prompt_encoding_repaired'])

    def test_bootstrap_is_windows_and_preserves_no_gpu_client(self):
        b=win.bootstrap(self.hw,self.base)
        self.assertEqual(b['platform'],'windows');self.assertEqual(b['version'],'1.8')
        self.assertTrue(next(m for m in b['models'] if m['id']=='gemma12-q8')['parallel_supported'])
        (self.base/'fixture.json').write_text(json.dumps(b))
    def test_install_rejects_injected_or_incomplete_options(self):
        cfg=dict(self.cfg,services={'asr':'http://invalid'})
        with self.assertRaises(ValueError):win.validate(cfg,self.hw)
        self.cfg['hf_token']='secret\nextra'
        with self.assertRaises(ValueError):win.validate(self.cfg,self.hw)

if __name__=='__main__':unittest.main()
