import io
import os
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from kienzledoku_commander.config import Settings
from kienzledoku_commander.scheduler import Commander
from kienzledoku_commander.runtime import Runtime
from kienzledoku_commander.api import API
from kienzledoku_commander.benchmark import inventory
from kienzledoku_commander.errors import Busy, BackendFailure, Conflict, InvalidRequest
from test_commander import RuntimeDouble, eventually


class BenchRuntime(RuntimeDouble):
    def infer(self,job):
        with self.lock:
            self.active.append(job.role);self.started.add(job.id)
        try:
            if job.id in self.holds:self.holds[job.id].wait(3)
            if job.quality in self.fail_infer:raise BackendFailure()
            if job.role=='llm':
                return {'choices':[{'message':{'content':'raw answer'},'finish_reason':'stop'}],
                        'timings':{'predicted_ms':12,'prompt_n':42},'usage':{'completion_tokens':2}}
            return {'text':'synthetic'}
        finally:
            with self.lock:self.active.remove(job.role)


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        token=patch.dict(os.environ,{"KIENZLEDOKU_COMMANDER_TOKEN":"synthetic-token"});token.start();self.addCleanup(token.stop)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'test-Q8.gguf';self.path.touch()
        other=Path(self.tmp.name)/'other-Q4.gguf';other.touch()
        options=dict(path=str(other),context=32768,slots=1,kv='q8_0',parallel_available=True)
        self.cfg=Settings(tier=16,memory_mode='serial',diarization_mode='serial',explicit_models=True,
            model_paths={'basis':str(self.path)},model_options={'basis':{'model_id':'default'}},
            benchmark_models={'chosen':options},auth_enabled=True).validate()
        self.runtime=BenchRuntime(self.cfg);self.cmd=Commander(self.cfg,self.runtime)
        def close():
            for hold in self.runtime.holds.values():hold.set()
            self.cmd.close()
        self.addCleanup(close)
        eventually(lambda:not self.cmd._uncertain and not self.cmd._transition)

    def begin(self,mode='serial'):
        return self.cmd.benchmark_begin('chosen',mode)['id']

    def finish(self,sid):
        self.cmd.benchmark_end(sid)
        eventually(lambda:self.cmd.benchmark_status(sid)['state']=='completed')
        self.assertEqual({'asr':True,'diar':False,'llm':None},self.cmd.status()['loaded'])

    def job(self,sid,rid='job',role='llm'):
        return self.cmd.submit(role,{'llm':{'messages':[{'role':'user','content':'original'}]}} if role=='llm' else {'body':b'synthetic'},
            '@chosen' if role=='llm' else None,rid,benchmark_session=sid)

    def test_explicit_nondefault_model_serial_switch_and_fresh_requests(self):
        sid=self.begin();self.assertEqual('basis',self.cfg.default)
        with self.assertRaises(Busy):self.cmd.submit('asr',{'body':b'normal'})
        first=self.job(sid).future.result(2)
        self.assertEqual('chosen',first['benchmark']['model_id'])
        self.assertFalse(first['benchmark']['fallback_allowed'])
        self.assertIsNone(first['benchmark']['ttft_seconds'])
        self.assertEqual(42,first['benchmark']['backend']['timings']['prompt_n'])
        with self.assertRaises(Conflict):self.job(sid)
        self.job(sid,'second').future.result(2)
        self.assertEqual({'job','second'},self.runtime.started)
        self.assertIn('load_@chosen',self.runtime.events)
        self.assertNotIn('load_basis',self.runtime.events)
        self.finish(sid)
        self.assertEqual('serial',self.cfg.memory_mode)

    def test_parallel_real_overlap_and_restore(self):
        sid=self.begin('parallel');hold=threading.Event();self.runtime.holds['asr']=hold
        audio=self.job(sid,'asr','asr');eventually(lambda:'asr' in self.runtime.active)
        llm=self.job(sid,'llm');llm.future.result(2)
        self.assertIn('asr',self.runtime.active)
        self.assertTrue(self.cmd.status()['loaded']['asr'])
        self.assertEqual('@chosen',self.cmd.status()['loaded']['llm'])
        self.cmd.benchmark_end(sid)
        self.assertEqual('restoring',self.cmd.benchmark_status(sid)['state'])
        hold.set();audio.future.result(2);self.finish(sid)

    def test_expiry_drains_only_owned_active_work_and_restores(self):
        sid=self.begin();hold=threading.Event();self.runtime.holds['held']=hold
        job=self.job(sid,'held');eventually(lambda:'held' in self.runtime.started)
        with self.cmd._condition:self.cmd._benchmark['expires']=time.monotonic()-1
        eventually(lambda:self.cmd.benchmark_status(sid)['state']=='restoring')
        with self.assertRaises(Busy):self.job(sid,'late')
        hold.set();job.future.result(2)
        eventually(lambda:self.cmd.benchmark_status(sid)['state']=='completed')
        self.assertEqual('lease_expired',self.cmd.benchmark_status(sid)['end_reason'])

    def test_failed_model_has_no_fallback_and_can_end(self):
        sid=self.begin();self.runtime.fail_infer.add('@chosen')
        with self.assertRaises(BackendFailure):self.job(sid).future.result(2)
        self.assertNotIn('load_basis',self.runtime.events)
        self.finish(sid)

    def test_conflicts_inventory_and_normal_hidden_model_rejected(self):
        self.assertEqual(['default','chosen'],[m['id'] for m in inventory(self.cfg)])
        with self.assertRaises(InvalidRequest):self.cmd.submit('llm',{},'@chosen')
        with self.assertRaises(InvalidRequest):self.cmd.benchmark_begin('/arbitrary/path','serial')
        with self.assertRaises(InvalidRequest):self.cmd.benchmark_begin('default','parallel')
        hold=threading.Event();self.runtime.holds['normal']=hold
        job=self.cmd.submit('asr',{},request_id='normal');eventually(lambda:'normal' in self.runtime.started)
        with self.assertRaises(Busy):self.begin()
        hold.set();job.future.result(2)

    def test_restoration_failure_is_separate_and_recovery_preserves_config(self):
        from dataclasses import replace
        cfg=replace(self.cfg,memory_mode='parallel')
        runtime=BenchRuntime(cfg);cmd=Commander(cfg,runtime);self.addCleanup(cmd.close)
        eventually(lambda:not cmd._uncertain and not cmd._transition)
        sid=cmd.benchmark_begin('chosen','serial')['id']
        cmd.submit('llm',{'llm':{}},'@chosen','return-error',benchmark_session=sid).future.result(2)
        runtime.fail_load.add('basis');cmd.benchmark_end(sid)
        eventually(lambda:cmd.benchmark_status(sid)['restoration_error']=='restoration_failed')
        self.assertEqual('restoring',cmd.benchmark_status(sid)['state'])
        self.assertEqual('parallel',cfg.memory_mode)
        runtime.fail_load.clear()
        with cmd._condition:cmd._baseline_retry_at=0;cmd._retry_at=0;cmd._condition.notify_all()
        eventually(lambda:cmd.benchmark_status(sid)['state']=='completed')
        self.assertEqual('basis',cmd.status()['loaded']['llm'])

    def test_raw_prompt_reaches_backend_without_rewriting(self):
        sid=self.begin();job=self.job(sid);job.future.result(2)
        from kienzledoku_commander.scheduler import Job
        original={'messages':[{'role':'system','content':'historical prompt\n'},{'role':'user','content':'raw input'}], 'temperature':0.4,'seed':42}
        j=Job('raw','llm',{'llm':original},quality='@chosen',benchmark_session=sid)
        runtime=Runtime(self.cfg)
        captured=[]
        def http(url,body,*args,**kwargs):
            captured.append(json.loads(body));return {'choices':[{'message':{'content':'not JSON'},'finish_reason':'stop'}]}
        with patch.object(runtime,'_http',side_effect=http):
            answer=runtime.infer(j)
        self.assertEqual(original['messages'],captured[0]['messages'])
        self.assertFalse(captured[0]['cache_prompt'])
        self.assertEqual('not JSON',answer['choices'][0]['message']['content'])
        self.finish(sid)

    def test_remote_hardware_preserves_origin_and_failure(self):
        from dataclasses import replace
        prompt=Path(self.tmp.name)/'prompt';prompt.write_text('normal prompt')
        self.cmd.settings=replace(self.cfg,prompt_path=str(prompt),remote_llm_url='http://192.0.2.8:8185')
        api=API(('127.0.0.1',0),self.cmd)
        thread=threading.Thread(target=api.serve_forever);thread.start()
        self.addCleanup(lambda:(api.shutdown(),thread.join(),api.server_close()))
        def get():
            with urlopen(Request('http://127.0.0.1:'+str(api.server_address[1])+'/v1/runtime/temperatures',headers={'Authorization':'Bearer synthetic-token'})) as reply:return json.load(reply)
        with patch.object(api.hardware,'temperatures',return_value={'sensors':[]}), patch.object(self.runtime,'_http',create=True,return_value={'sensors':[{'kind':'gpu','value':42}]}) as remote:
            value=get();self.assertEqual('http://192.0.2.8:8185',value['remote_llm']['source'])
            self.assertEqual(42,value['remote_llm']['data']['sensors'][0]['value'])
            self.assertNotIn('llm',value['context']['roles'])
            self.assertEqual('1',remote.call_args.kwargs['extra_headers']['X-Kienzledoku-Commander-Hop'])
            remote.side_effect=BackendFailure()
            value=get();self.assertIsNone(value['remote_llm']['data'])
            self.assertEqual('unavailable',value['remote_llm']['status'])

    def test_http_auth_metadata_and_session_lifecycle(self):
        import dataclasses,os
        prompt=Path(self.tmp.name)/'prompt';prompt.write_text('normal prompt')
        self.cmd.settings=dataclasses.replace(self.cfg,prompt_path=str(prompt))
        with patch.dict(os.environ,{self.cfg.token_env:'synthetic-token'}):
            api=API(('127.0.0.1',0),self.cmd)
        thread=threading.Thread(target=api.serve_forever);thread.start()
        self.addCleanup(lambda:(api.shutdown(),thread.join(),api.server_close()))
        base='http://127.0.0.1:'+str(api.server_address[1])
        def call(path,data=None,token=True,sid=None):
            headers={'Content-Type':'application/json'}
            if token:headers['Authorization']='Bearer synthetic-token'
            if sid:headers['X-Kienzledoku-Benchmark-Session']=sid
            with urlopen(Request(base+path,data=json.dumps(data).encode() if data is not None else None,headers=headers),timeout=3) as response:return json.load(response)
        with self.assertRaises(HTTPError) as error:call('/v1/runtime/capabilities',token=False)
        self.assertEqual(401,error.exception.code)
        self.assertTrue(call('/v1/runtime/capabilities')['benchmark_control'])
        with patch.object(api.hardware,'temperatures',return_value={'sensors':[]}) as temperatures:
            call('/v1/runtime/status');temperatures.assert_not_called()
            self.assertEqual([],call('/v1/runtime/temperatures')['sensors']);temperatures.assert_called_once()
        sid=call('/v1/benchmark/session',{'model_id':'chosen','mode':'serial'})['id']
        reply=call('/v1/benchmark/chat/completions',{'model_id':'chosen','request_id':'http','messages':[{'role':'user','content':'synthetic'}]},sid=sid)
        self.assertEqual('chosen',reply['benchmark']['model_id'])
        call('/v1/benchmark/session/end',{},sid=sid)
        self.finish(sid)
        self.cmd.settings=dataclasses.replace(self.cmd.settings,auth_enabled=False)
        self.assertFalse(call('/v1/runtime/capabilities',token=False)['benchmark_control'])
        with self.assertRaises(HTTPError) as error:call('/v1/benchmark/session',{'model_id':'chosen','mode':'serial'},token=False)
        self.assertEqual(403,error.exception.code)


if __name__=='__main__':unittest.main()
