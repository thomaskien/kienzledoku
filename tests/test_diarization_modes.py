import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

from kienzledoku_commander.config import Settings, load_settings
from kienzledoku_commander.scheduler import Commander
from test_commander import RuntimeDouble, eventually
from installer import core


class ModelRuntime(RuntimeDouble):
    def __init__(self, settings):
        super().__init__(settings)
        self.calls=[]
        self.remote_allowed=('basis',);self.remote_default='basis'

    def infer(self, job):
        with self.lock:
            self.active.append(job.role);self.started.add(job.id)
            self.calls.append((job.role,dict(self.loaded)))
        try:
            if job.id in self.holds:self.holds[job.id].wait(3)
            return {'documentation':{},'completion':{}} if job.role=='llm' else {'text':'synthetic'}
        finally:
            with self.lock:self.active.remove(job.role)


class DiarizationModeTests(unittest.TestCase):
    def create(self, mode, **options):
        settings=Settings(tier=8,memory_mode='serial',diarization_mode=mode,
                          **options).validate()
        runtime=ModelRuntime(settings);commander=Commander(settings,runtime)
        self.addCleanup(commander.close)
        eventually(lambda:commander.wait_ready(0) and not commander.status()['transition_running'])
        return commander,runtime

    def job(self, commander, role):
        return commander.submit(role,{},quality='basis' if role=='llm' else None).future.result(3)

    def test_three_policies_and_cold_return_after_llm(self):
        for mode in ('resident','with_asr','serial'):
            with self.subTest(mode=mode):
                commander,runtime=self.create(mode,asr_on_demand=True)
                self.assertEqual(mode=='resident',runtime.loaded['diar'])
                self.assertFalse(runtime.loaded['asr'])
                for role in ('asr','diar','llm'):self.job(commander,role)
                eventually(lambda:not commander.status()['transition_running'] and runtime.loaded['llm'] is None)
                calls=dict(runtime.calls)
                self.assertEqual(mode in ('resident','with_asr'),calls['asr']['diar'])
                self.assertEqual(mode!='serial',calls['diar']['asr'])
                self.assertIsNone(calls['diar']['llm'])
                self.assertEqual(mode=='resident',calls['llm']['diar'])
                self.assertFalse(calls['llm']['asr'])
                self.assertFalse(runtime.loaded['asr'])
                self.assertEqual(mode=='resident',runtime.loaded['diar'])
                self.assertEqual(1,runtime.events.count('load_asr'))
                commander.close()

    def test_normal_serial_does_not_reload_whisper_between_diar_and_llm(self):
        commander,runtime=self.create('serial',asr_on_demand=False)
        self.job(commander,'asr');self.job(commander,'diar')
        time.sleep(.12)  # Deliberate gap before the client's following request.
        self.assertFalse(runtime.loaded['asr'])
        self.assertEqual(1,runtime.events.count('load_asr'))
        self.job(commander,'llm')
        eventually(lambda:runtime.loaded['asr'] and not commander.status()['transition_running'])
        self.assertEqual(2,runtime.events.count('load_asr'))

    def test_disabled_diar_is_never_loaded(self):
        commander,runtime=self.create('resident',asr_on_demand=True,enabled_roles=('asr','llm'))
        self.job(commander,'asr');self.job(commander,'llm')
        self.assertNotIn('load_diar',runtime.events)

    def test_serial_diar_waits_for_running_asr(self):
        commander,runtime=self.create('serial',asr_on_demand=True)
        runtime.events.clear()
        release=threading.Event();runtime.holds['held_asr']=release
        job=commander.submit('asr',{},request_id='held_asr')
        eventually(lambda:'held_asr' in runtime.started)
        diar=commander.submit('diar',{})
        time.sleep(.1)
        self.assertNotIn('park_asr',runtime.events)
        self.assertNotIn('load_diar',runtime.events)
        release.set();job.future.result(3);diar.future.result(3)
        self.assertFalse(dict(runtime.calls)['diar']['asr'])

    def test_remote_llm_does_not_load_a_local_model(self):
        commander,runtime=self.create('serial',asr_on_demand=True,remote_llm_url='http://192.0.2.1:8185')
        for role in ('asr','diar','llm'):self.job(commander,role)
        self.assertNotIn('load_basis',runtime.events)

    def test_parallel_llm_still_obeys_serial_diarization(self):
        settings=Settings(tier=8,memory_mode='parallel',diarization_mode='serial',asr_on_demand=False).validate()
        runtime=ModelRuntime(settings);commander=Commander(settings,runtime);self.addCleanup(commander.close)
        eventually(lambda:runtime.loaded['llm']=='basis' and not commander.status()['transition_running'])
        self.job(commander,'diar')
        self.assertEqual({'asr':False,'diar':True,'llm':None},dict(runtime.calls)['diar'])
        self.job(commander,'llm')
        self.assertFalse(dict(runtime.calls)['llm']['diar'])

    def test_config_validation_and_installer_round_trip(self):
        hw=dict(platform='darwin',arch='arm64',ram_gib=64,free_gib=100,server_supported=True)
        with tempfile.TemporaryDirectory() as directory:
            support=Path(directory);cfg=core.defaults(hw,support)
            for mode in ('resident','with_asr','serial'):
                cfg['diarization_mode']=mode;core.validate(cfg,hw)
                with mock.patch.object(core,'hardware',return_value=hw):
                    (support/'commander.toml').write_text(core.commander_toml(cfg,support/'version',support))
                self.assertEqual(mode,load_settings(support/'commander.toml').diarization_mode)
            cfg['diarization_mode']='wrong'
            with self.assertRaises(ValueError):core.validate(cfg,hw)
            with self.assertRaises(ValueError):Settings(diarization_mode='wrong').validate()
            (support/'installer.json').write_text(json.dumps({'memory_mode':'parallel'}))
            self.assertEqual('resident',core.defaults(hw,support)['diarization_mode'])
            (support/'installer.json').write_text(json.dumps({'memory_mode':'parallel','diarization_mode':'with_asr'}))
            self.assertEqual('with_asr',core.defaults(hw,support)['diarization_mode'])


if __name__=='__main__':unittest.main()
