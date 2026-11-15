import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from installer import core
from kienzledoku_commander.config import Settings
from kienzledoku_commander.errors import BackendFailure
from kienzledoku_commander.runtime import Runtime
from test_commander_140 import FakeProcess


HW=dict(platform='darwin',arch='arm64',ram_gib=64,free_gib=100,server_supported=True)


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.support=self.root/'support'
        self.installer=core.Installer(self.support,HW)
        self.cfg=core.defaults(HW,self.support)
        self.cfg.update(mode='server',memory_mode='parallel',diarization_mode='resident',asr_on_demand=False)
        with mock.patch.object(core,'hardware',return_value=HW):
            core.atomic_write(self.support/'commander/config.toml',core.commander_toml(self.cfg,self.root/'version',self.support))
        core.atomic_write(self.support/'commander/credentials.json','{}')
        self.now=0

    def sleep(self,seconds):self.now+=seconds

    def response(self,value):
        response=io.BytesIO(json.dumps(value).encode());response.status=200
        return response

    def test_loading_longer_than_30_seconds_is_allowed_while_api_is_reachable(self):
        states=iter([dict(asr=True,diar=False,llm=None),dict(asr=True,diar=True,llm=None),
                     dict(asr=True,diar=True,llm='basis')])
        def respond(request,timeout):
            if request.full_url.endswith('/health'):return self.response({})
            self.now+=20
            state=next(states)
            return self.response(dict(loaded=state,last_error=None,transition_running=state['llm'] is None))
        with mock.patch.object(core,'urlopen',side_effect=respond), \
             mock.patch.object(core.time,'monotonic',side_effect=lambda:self.now), \
             mock.patch.object(core.time,'sleep',side_effect=self.sleep):
            self.installer._wait_commander()
        self.assertGreater(self.now,60)
        self.assertIn('Modelle werden geladen',self.installer.snapshot()['logs'][0])

    def test_unreachable_api_still_times_out_after_30_seconds(self):
        with mock.patch.object(core,'urlopen',side_effect=OSError), \
             mock.patch.object(core.time,'monotonic',side_effect=lambda:self.now), \
             mock.patch.object(core.time,'sleep',side_effect=self.sleep):
            with self.assertRaisesRegex(RuntimeError,'nicht erreichbar'):
                self.installer._wait_commander()
        self.assertGreaterEqual(self.now,30);self.assertLess(self.now,32)

    def test_backend_load_failure_is_reported_without_waiting_for_timeout(self):
        with mock.patch.object(core,'urlopen',return_value=self.response({'last_error':'model_change_failed'})):
            with self.assertRaisesRegex(RuntimeError,'ein Modell nicht laden'):
                self.installer._wait_commander()

    def test_failed_new_start_restores_and_verifies_old_service(self):
        home=self.root/'home';home.mkdir();version=self.root/'version';version.mkdir()
        agent=home/'Library/LaunchAgents/de.kienzledoku.commander.plist'
        core.atomic_write(agent,b'synthetic previous plist')
        original=(self.support/'commander/config.toml').read_bytes()
        self.cfg.update(memory_mode='serial',asr_on_demand=True,hf_token='synthetic')
        with mock.patch.object(Path,'home',return_value=home), \
             mock.patch.object(core,'hardware',return_value=HW), \
             mock.patch.object(self.installer,'run'), \
             mock.patch.object(self.installer,'_stop_commander') as stop, \
             mock.patch.object(self.installer,'_wait_commander',side_effect=[RuntimeError('synthetic start error'),None]) as wait, \
             mock.patch.object(core.subprocess,'run',return_value=mock.Mock(returncode=0)):
            with self.assertRaisesRegex(RuntimeError,'synthetic start error'):
                self.installer._activate(self.cfg,version,Path(sys.executable),True,False)
        self.assertEqual(2,stop.call_count);self.assertEqual(2,wait.call_count)
        self.assertEqual(original,(self.support/'commander/config.toml').read_bytes())
        self.assertEqual(b'synthetic previous plist',agent.read_bytes())

    def test_shutdown_interrupts_model_load_and_reaps_owned_worker(self):
        settings=Settings(tier=8,platform='macos',memory_mode='serial',enabled_roles=('asr',),
                          asr_command=(sys.executable,'/tmp/synthetic.py'),asr_model_path='/tmp/model',load_timeout=600).validate()
        runtime=Runtime(settings);process=FakeProcess()
        def loading(*args,**kwargs):
            runtime.cancel_loading();raise BackendFailure()
        with mock.patch('kienzledoku_commander.runtime.socket.create_connection',side_effect=OSError), \
             mock.patch('kienzledoku_commander.runtime.subprocess.Popen',return_value=process), \
             mock.patch.object(runtime,'_http',side_effect=loading), \
             mock.patch('kienzledoku_commander.runtime.os.killpg') as kill:
            with self.assertRaises(BackendFailure):runtime.load_asr()
        kill.assert_called_once_with(process.pid,15)
        self.assertIsNone(runtime.worker_processes['asr'])


if __name__=='__main__':unittest.main()
