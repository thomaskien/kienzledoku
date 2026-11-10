#!/usr/bin/env python3
"""Check publisher metadata and transform the real pinned Whisper wheel offline.

Only the small wheel and public metadata are downloaded, never model weights.
Run explicitly with network access; results contain no credentials.
"""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1]
def get(url):
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'kienzledoku-build/1.0'}),timeout=60) as response:return response.read()

def main():
    evidence={'model_metadata':[]}
    for model in json.loads((ROOT/'models.json').read_text()).values():
        url=f"https://huggingface.co/api/models/{model['repository']}/revision/{model['revision']}?blobs=true"
        data=json.loads(get(url));siblings={f['rfilename']:f for f in data['siblings']}
        for file in model['files']:
            actual=siblings[file['filename']]
            assert actual['lfs']['sha256']==file['sha256']
            assert (actual.get('size') or actual['lfs']['size'])==file['bytes']
        evidence['model_metadata'].append({'repository':model['repository'],'revision':model['revision'],'matches':True})
    release=json.loads(get('https://pypi.org/pypi/whisperlivekit/0.2.24/json'))
    wheel=next(f for f in release['urls'] if f['filename'].endswith('.whl'))
    raw=get(wheel['url']);sha=hashlib.sha256(raw).hexdigest()
    assert sha=='f11ff4c74f3efe11d09b50a08cfd6c33ed74fed4a397429d70254ada3feeeda6'
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        original=archive.read('whisperlivekit/basic_server.py')
    assert hashlib.sha256(original).hexdigest()=='ae89062f8f7146a130e48b973187cd81f6451a672d93bc04e9ec1fcbb28fe78f'
    final_block=(ROOT/'linux/vendor/final-block.sh').read_text()
    start='TARGET="$TARGET" "$PY" - <<\'PY\'\n'
    source=final_block.split(start,1)[1].split('\nPY\n',1)[0]
    with tempfile.TemporaryDirectory() as tmp:
        target=Path(tmp)/'basic_server.py';target.write_bytes(original)
        subprocess.run([sys.executable,'-c',source],env=dict(os.environ,TARGET=str(target)),check=True,stdout=subprocess.DEVNULL)
        patched=target.read_bytes()
    expected='bd80dddcffb1e24782508adeac17f1b91b3ef4b819a59035769985ae968f4412'
    assert hashlib.sha256(patched).hexdigest()==expected
    spec=importlib.util.spec_from_file_location('patch_workers',ROOT/'linux/runtime/kienzledoku_commander/patch_workers.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    final=module.transform('whisper',patched)
    compile(final,'actual-pinned-whisper','exec')
    diar=(ROOT/'linux/vendor/diarization_server.py').read_bytes()
    assert hashlib.sha256(diar).hexdigest()==module.HASHES['diar']
    compile(module.transform('diar',diar),'actual-pinned-pyannote','exec')
    evidence['whisper_wheel']={'sha256':sha,'original_source_verified':True,'final_endpoint_hash_verified':True,'worker_hook_compiles':True}
    evidence['pyannote_worker']={'original_source_verified':True,'worker_hook_compiles':True}
    ubuntu=json.loads((ROOT/'ubuntu.json').read_text())
    with urllib.request.urlopen(urllib.request.Request(ubuntu['url'],method='HEAD'),timeout=60) as response:
        evidence['ubuntu']={'url':ubuntu['url'],'http_status':response.status,'bytes':response.headers.get('Content-Length')}
    (ROOT/'evidence/publisher-verification.json').write_text(json.dumps(evidence,indent=2)+'\n')
    print(json.dumps(evidence,indent=2))

if __name__=='__main__':main()
