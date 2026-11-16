"""Exercise real text prompts and generated Commander policy without installing."""
from contextlib import ExitStack
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from installer import linux_cli

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'server-windows/linux'),str(ROOT/'server-windows/linux/runtime')]
import install_server
from serial_server import SerialSettings


class LinuxModeTests(unittest.TestCase):
    def ask_server(self,previous=None,responses=None,vram=24576,tokens=''):
        responses=responses or {};prompts=[];output=io.StringIO()
        def answer(prompt):
            prompts.append(prompt)
            return next((value for key,value in responses.items() if prompt.startswith(key)),'')
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            state=Path(directory)/'settings.json';token_file=Path(directory)/'token.env'
            if previous is not None:state.write_text(json.dumps(previous))
            token_file.write_text(tokens)
            stack.enter_context(mock.patch.object(linux_cli,'SERVER_STATE',state))
            stack.enter_context(mock.patch.object(linux_cli,'SERVER_TOKENS',token_file))
            stack.enter_context(mock.patch.object(linux_cli.subprocess,'check_output',return_value=f'0, Synthetic NVIDIA GPU, {vram}\n'))
            stack.enter_context(mock.patch.object(linux_cli.os,'sysconf',side_effect=(4096,16*1024*1024)))
            stack.enter_context(mock.patch.dict(os.environ,{'HF_TOKEN':'hf_synthetic'}))
            stack.enter_context(mock.patch('builtins.input',side_effect=answer))
            stack.enter_context(mock.patch.object(linux_cli.getpass,'getpass',return_value=''))
            stack.enter_context(mock.patch('sys.stdout',output))
            result=linux_cli.server_answers()
        cfg=result[0]
        with mock.patch.object(install_server,'ROOT',ROOT/'server-windows'):
            install_server.validate_config(cfg,vram)
            runtime=SerialSettings(**install_server.runtime_settings(cfg,dict(vram_mib=vram)))
            with mock.patch.dict(os.environ,{'KIENZLEDOKU_COMMANDER_TOKEN':'synthetic'}):runtime.validate()
        return cfg,runtime,prompts,output.getvalue(),result[1:]

    def test_remote_diar_and_turbo_survive_native_wizard(self):
        cfg,runtime,_,_,_=self.ask_server(responses={
            'Anderer Commander für Sprechertrennung':'http://192.0.2.3:8185',
            'Whisper-Modell':'turbo-int8'})
        self.assertEqual('http://192.0.2.3:8185',runtime.remote_diar_url)
        self.assertEqual('turbo-int8',cfg['AsrModel'])

    def test_new_install_can_choose_normal_serial_instead_of_hardcoded_cold_start(self):
        cfg,runtime,prompts,output,_=self.ask_server(responses={
            'Modellbetrieb:':'seriell','Whisper erst bei Bedarf':'n'})
        self.assertEqual('',cfg['ParallelModel'])
        self.assertFalse(cfg['AsrOnDemand']);self.assertFalse(runtime.asr_on_demand)
        self.assertTrue(all(p['Mode']=='serial' for p in cfg['Profiles'].values()))
        self.assertTrue(any(p.startswith('Modellbetrieb:') for p in prompts))
        self.assertIn('beim Dienststart laden',output)

    def test_parallel_choice_reaches_actual_commander_profile_mapping(self):
        cfg,runtime,_,_,_=self.ask_server(responses={
            'Modellbetrieb:':'parallel','Whisper erst bei Bedarf':'n',
            'Sprechertrennung: resident':'with_asr'})
        self.assertEqual('gemma12-q8',cfg['ParallelModel'])
        self.assertEqual('parallel',cfg['Profiles']['gemma12-q8']['Mode'])
        self.assertEqual('serial',cfg['Profiles']['27b-q4']['Mode'])
        self.assertEqual('@gemma12_q8',runtime.baseline_llm)
        self.assertEqual('with_asr',runtime.diarization_mode)

    def test_each_available_grade_is_explicitly_confirmed_even_with_one_model(self):
        cfg,_,prompts,output,_=self.ask_server()
        for grade,label in linux_cli.GRADE_LABELS.items():
            self.assertTrue(any(p.startswith(label+' — aktives Modell') for p in prompts),label)
            self.assertEqual(linux_cli.DEFAULTS[grade],cfg['QualityModels'][grade])
        self.assertIn('Modelle den Verarbeitungsstufen zuordnen',output)

    def test_multiple_thorough_models_can_be_installed_and_active_one_selected(self):
        cfg,_,prompts,_,_=self.ask_server(responses={
            'Zu installierende Modelle':'gemma12-q8,9b-q6,27b-q4',
            'Gründlich — aktives Modell':'9b-q6'})
        self.assertEqual(['gemma12-q8','9b-q6','27b-q4'],cfg['Models'])
        self.assertEqual('9b-q6',cfg['QualityModels']['gruendlich'])

    def test_eight_gib_keeps_unsupported_parallel_unavailable_but_offers_cold_switch(self):
        cfg,runtime,prompts,output,_=self.ask_server(vram=8192)
        self.assertEqual('',cfg['ParallelModel']);self.assertTrue(runtime.asr_on_demand)
        self.assertIn('kein Parallelprofil freigegeben',output)
        self.assertTrue(any(p.startswith('Whisper erst bei Bedarf') for p in prompts))

    def test_enter_retains_existing_models_modes_prompt_fields_and_connections(self):
        old=dict(Models=['gemma12-q8','27b-q4'],DefaultModel='27b-q4',
                 QualityModels={'gruendlich':'gemma12-q8','sehr_gruendlich':'27b-q4'},
                 ParallelModel='gemma12-q8',AsrOnDemand=False,DiarizationMode='resident',
                 EnabledFields=['befund','ekg','sonografie','notiz'],PromptText='synthetic saved prompt',
                 NativeBind='0.0.0.0',AuthEnabled=True,GpuIndex=0,AudioCache='disk',WslRamGiB=24,
                 RemoteLlmUrl='http://192.0.2.1:8185')
        cfg,_,_,output,secrets=self.ask_server(old,tokens='KIENZLEDOKU_COMMANDER_TOKEN=local_synthetic\nKIENZLEDOKU_REMOTE_LLM_TOKEN=remote_synthetic\n')
        for key in old:self.assertEqual(old[key],cfg[key],key)
        self.assertEqual(('hf_synthetic','local_synthetic','remote_synthetic',''),secrets)
        self.assertNotIn('local_synthetic',output);self.assertNotIn('remote_synthetic',output)
        self.assertIn('Vorhandener Commander-Token erkannt',output)

    def test_changed_remote_target_never_inherits_previous_target_token(self):
        cfg,_,_,_,secrets=self.ask_server({'RemoteLlmUrl':'http://192.0.2.1:8185'},
            responses={'Anderer Commander':'http://192.0.2.2:8185'},
            tokens='KIENZLEDOKU_REMOTE_LLM_TOKEN=old_target_secret\n')
        self.assertEqual('http://192.0.2.2:8185',cfg['RemoteLlmUrl'])
        self.assertEqual('',secrets[-1])

    def test_saved_parallel_selection_is_downgraded_visibly_when_hardware_cannot_run_it(self):
        cfg,runtime,_,output,_=self.ask_server(dict(Models=['9b-q4','gemma12-q8'],ParallelModel='gemma12-q8'),vram=16384)
        self.assertEqual('',cfg['ParallelModel']);self.assertIsNone(runtime.baseline_llm)
        self.assertIn('bisherige Parallelmodell',output)

    def test_corrupt_existing_config_is_not_silently_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'state.json';path.write_text('invalid')
            with mock.patch.object(linux_cli,'SERVER_STATE',path),self.assertRaisesRegex(ValueError,'nicht durch Standardwerte'):
                linux_cli.previous_server_settings()


if __name__=='__main__':unittest.main()


class ComponentDefaultsTests(unittest.TestCase):
    def test_saved_selection_and_detected_components(self):
        import tempfile
        from pathlib import Path
        from installer import linux_cli
        from unittest import mock
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            with mock.patch.object(linux_cli.client_config,'config_dir',return_value=folder), mock.patch.object(linux_cli,'SERVER_STATE',folder/'server.json'), mock.patch.object(linux_cli.os,'geteuid',return_value=1000):
                self.assertEqual('client',linux_cli.previous_components())
                (folder/'server.json').write_text('{}')
                (folder/'config.toml').write_text('# synthetic')
                self.assertEqual('both',linux_cli.previous_components())
                (folder/'installer.json').write_text('{"components":"server"}')
                self.assertEqual('server',linux_cli.previous_components())
                (folder/'installer.json').write_text('invalid')
                with self.assertRaises(ValueError):linux_cli.previous_components()
