"""A02/A05 regressions, executed independently in both Commander trees."""
import ast
import builtins
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import wave
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlsplit

from kienzledoku_commander import patch_workers
from kienzledoku_commander.api import API
from kienzledoku_commander.config import Settings

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'kienzledoku.py').is_file())
VENDOR = ROOT/'server-windows/linux/vendor/diarization_server.py'


def wav_bytes():
    buffer=io.BytesIO()
    with wave.open(buffer,'wb') as audio:
        audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(16000)
        audio.writeframes(b'\x00\x00\xff\x7f\x00\x80'*20)
    return buffer.getvalue()


def handler_for(body, pipeline, source=None):
    tree=ast.parse(VENDOR.read_text() if source is None else source)
    handler=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Handler')
    tensor=Mock();tensor.to.return_value=tensor;tensor.div_.return_value=tensor;tensor.unsqueeze.return_value=tensor
    torch=SimpleNamespace(inference_mode=contextlib.nullcontext,int16='int16',float32='float32',frombuffer=Mock(return_value=tensor))
    namespace=dict(io=io,wave=wave,json=json,BaseHTTPRequestHandler=BaseHTTPRequestHandler,
                   parse_qs=parse_qs,urlsplit=urlsplit,pipeline=pipeline,pipeline_lock=threading.Lock(),
                   torch=torch,MAX_BYTES=100000,MODEL='synthetic',DEVICE='synthetic',
                   annotation_segments=lambda _:[])
    exec(compile(ast.Module(body=[handler],type_ignores=[]),str(VENDOR),'exec'),namespace)
    instance=object.__new__(namespace['Handler']);instance.path='/v1/diarize'
    instance.headers={'Content-Length':str(len(body))};instance.rfile=io.BytesIO(body)
    instance.send_json=Mock()
    return instance,torch


class ServerGuardTests(unittest.TestCase):
    def test_diarization_decodes_validated_pcm_without_a_file(self):
        pipeline=Mock(return_value=SimpleNamespace(exclusive_speaker_diarization=[]))
        handler,torch=handler_for(wav_bytes(),pipeline)
        with patch.object(builtins,'open',side_effect=AssertionError('Audio file access')),patch('tempfile.NamedTemporaryFile',side_effect=AssertionError('Audio temp file')):
            handler.do_POST()
        self.assertEqual(handler.send_json.call_args.args[0],200)
        self.assertEqual(torch.frombuffer.call_args.args[0],bytearray(b'\x00\x00\xff\x7f\x00\x80'*20))
        self.assertEqual(pipeline.call_args.args[0]['sample_rate'],16000)

    def test_truncated_or_invalid_wav_never_reaches_pipeline(self):
        for data in (b'synthetic invalid wav',wav_bytes()[:-2]):
            handler,_=handler_for(data,Mock())
            handler.do_POST()
            self.assertEqual(handler.send_json.call_args.args[0],500)

    def test_hard_exit_leaves_no_audio_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            script='''import os, sys, tempfile
sys.path.insert(0, sys.argv[1])
from test_audit_server_guards import handler_for, wav_bytes
tempfile.tempdir=sys.argv[2]
def exit_pipeline(*args, **kwargs): os._exit(70)
handler,_=handler_for(wav_bytes(),exit_pipeline)
handler.do_POST()
'''
            result=subprocess.run([sys.executable,'-B','-c',script,str(Path(__file__).parent),tmp],env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'))
            self.assertEqual(result.returncode,70)
            self.assertEqual(list(Path(tmp).iterdir()),[])

    def test_telemetry_is_disabled_before_pyannote_import(self):
        source=VENDOR.read_text()
        real_import=builtins.__import__
        class StopImport(Exception):pass
        def importing(name,*args,**kwargs):
            if name=='torch':return SimpleNamespace()
            if name=='pyannote.audio':
                self.assertEqual(os.environ.get('PYANNOTE_METRICS_ENABLED'),'0')
                raise StopImport()
            return real_import(name,*args,**kwargs)
        with patch.dict(os.environ,PYANNOTE_METRICS_ENABLED='1'),patch.object(builtins,'__import__',side_effect=importing),self.assertRaises(StopImport):
            exec(compile(source,str(VENDOR),'exec'),{'__name__':'synthetic'})
        mac=ROOT/'local-ai-macos/diarization_server_mps.py'
        with patch.dict(os.environ,PYANNOTE_METRICS_ENABLED='1'):
            exec(compile(mac.read_text(),str(mac),'exec'),{'__name__':'synthetic'})
            self.assertEqual(os.environ['PYANNOTE_METRICS_ENABLED'],'0')


    def test_existing_worker_manifest_is_upgraded_without_losing_original(self):
        # Both variant runners put their test directory on sys.path.
        from test_commander_patch import WHISPER,DIAR
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);paths={role:root/(role+'.py') for role in ('whisper','diar')}
            for role,data in [('whisper',WHISPER),('diar',DIAR)]:paths[role].write_bytes(data)
            hashes={role:hashlib.sha256(p.read_bytes()).hexdigest() for role,p in paths.items()}
            backup=root/'backup';patch_workers.apply(paths,backup,hashes)
            manifest=json.loads((backup/'manifest.json').read_text())
            for item in manifest.values():item.pop('patch_revision')
            # A previous transformation with different output must not be treated as current.
            old=paths['diar'].read_bytes()+b'\n# previous patch\n';paths['diar'].write_bytes(old)
            manifest['diar']['after']=hashlib.sha256(old).hexdigest()
            (backup/'manifest.json').write_text(json.dumps(manifest))
            patch_workers.apply(paths,backup,hashes)
            self.assertNotIn(b'previous patch',paths['diar'].read_bytes())
            self.assertEqual((backup/'diar.original').read_bytes(),DIAR)
            self.assertIn(b'PYANNOTE_METRICS_ENABLED',paths['diar'].read_bytes())
            patch_workers.rollback(backup)
            self.assertEqual(paths['diar'].read_bytes(),DIAR)

    def test_original_released_worker_is_migrated_to_memory_only(self):
        original=(ROOT/'tests/fixtures/diarization-before-audit.py').read_bytes()
        self.assertIn(hashlib.sha256(original).hexdigest(),patch_workers.LEGACY_DIAR_HASHES)
        upgraded=patch_workers.transform('diar',original)
        self.assertNotIn(b'NamedTemporaryFile',upgraded)
        self.assertNotIn(b'os.unlink',upgraded)
        self.assertLess(upgraded.index(b'PYANNOTE_METRICS_ENABLED'),upgraded.index(b'from pyannote.audio'))
        pipeline=Mock(return_value=SimpleNamespace(exclusive_speaker_diarization=[]))
        handler,_=handler_for(wav_bytes(),pipeline,upgraded)
        with patch('tempfile.NamedTemporaryFile',side_effect=AssertionError('Audio file')):handler.do_POST()
        self.assertEqual(handler.send_json.call_args.args[0],200)


if __name__=='__main__':unittest.main()
