import io
import json
import os
import threading
import unittest
import wave
from dataclasses import replace
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from kienzledoku_commander.config import Settings
from kienzledoku_commander.api import API
from kienzledoku_commander.scheduler import Commander, Job
from kienzledoku_commander.runtime import Runtime
from kienzledoku_commander.errors import BackendFailure
from test_commander import RuntimeDouble, eventually

class Target(RuntimeDouble):
    def infer(self,job):
        self.seen=dict(job.payload)
        return dict(segments=[dict(start=.1,end=.2,speaker='SPEAKER_00')],request_id=job.id)
class Forward(RuntimeDouble):
    def infer(self,job):return Runtime(self.settings).infer(job)
    def remote_get(self,*a,**kw):return Runtime(self.settings).remote_get(*a,**kw)

class RemoteDiarTests(unittest.TestCase):
    def server(self,cfg,runtime):
        cmd=Commander(cfg,runtime);self.addCleanup(cmd.close)
        api=API(('127.0.0.1',0),cmd);thread=threading.Thread(target=api.serve_forever);thread.start()
        self.addCleanup(lambda:(api.shutdown(),thread.join(),api.server_close()))
        eventually(lambda:not cmd._uncertain and not cmd._transition)
        return cmd,'http://127.0.0.1:'+str(api.server_port)
    def test_original_audio_query_identity_and_no_local_model_changes(self):
        target_cfg=Settings(enabled_roles=('diar',),memory_mode='serial',diarization_mode='serial',remote_llm_url='http://192.0.2.1:8185').validate()
        target=Target(target_cfg);_,url=self.server(target_cfg,target)
        cfg=Settings(enabled_roles=('asr','diar'),memory_mode='serial',diarization_mode='resident',remote_diar_url=url).validate()
        runtime=Forward(cfg);cmd,source=self.server(cfg,runtime);before=list(runtime.events)
        data=io.BytesIO()
        with wave.open(data,'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes(b'\0\0'*320)
        body=data.getvalue();headers={'Content-Type':'audio/wav','X-Kienzledoku-Recording-Finalized':'true','Idempotency-Key':'synthetic-diar'}
        with urlopen(Request(source+'/v1/diarize?min_speakers=1&max_speakers=3',body,headers),timeout=4) as f:answer=json.load(f)
        self.assertEqual(body,target.seen['body']);self.assertEqual('?min_speakers=1&max_speakers=3',target.seen['query'])
        self.assertEqual('synthetic-diar',answer['request_id']);self.assertEqual(.1,answer['segments'][0]['start'])
        self.assertEqual(before,runtime.events);self.assertFalse(cmd.status()['loaded']['diar'])
        # A forwarding request must never be forwarded a second time.
        headers['X-Kienzledoku-Commander-Hop']='1'
        with self.assertRaises(HTTPError) as error:urlopen(Request(source+'/v1/diarize',body,headers))
        self.assertEqual(502,error.exception.code)
    def test_transport_uses_only_configured_target_token_and_finalization(self):
        cfg=Settings(remote_diar_url='http://192.0.2.10:8185');r=Runtime(cfg)
        with patch.dict(os.environ,{cfg.remote_diar_token_env:'synthetic-target-token'}),patch.object(r,'_http',return_value={'segments':[]}) as call:
            r.infer(Job('my-id','diar',{'body':b'audio','content_type':'audio/wav','query':'?num_speakers=2'}))
            self.assertEqual('synthetic-target-token',call.call_args.kwargs['token'])
            self.assertEqual('my-id',call.call_args.kwargs['extra_headers']['Idempotency-Key'])
            self.assertEqual('true',call.call_args.kwargs['extra_headers']['X-Kienzledoku-Recording-Finalized'])
            call.side_effect=BackendFailure()
            with self.assertRaises(BackendFailure):r.infer(Job('x','diar',{'body':b'audio','content_type':'audio/wav'}))
    def test_invalid_target_and_macos_remote_needs_no_local_diar_worker(self):
        for url in ('http://127.0.0.1:8185','http://example.com','http://user:secret@example.com:8185','file:///tmp'):
            with self.assertRaises(ValueError):Settings(remote_diar_url=url).validate()
        Settings(platform='macos',memory_mode='serial',enabled_roles=('diar',),remote_diar_url='http://192.0.2.2:8185').validate()
