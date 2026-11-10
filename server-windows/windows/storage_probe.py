"""Read-only capacity probe run by Windows with Python in its own WSL distro.

Reuse only unchanged verification fingerprints. Never read model payloads or
write cache entries during this estimate; import still checks every file.
"""
import base64
import hashlib
import tempfile
import json
import os
from pathlib import Path
import shutil
import sys


def probe(files, base=Path('/opt/kienzledoku-server'), state=Path('/var/lib/kienzledoku-server'), force=False, cuda=Path('/usr/local/cuda/bin/nvcc'), verify_models=True, validate=False):
    models = (base/'models').resolve()
    try:
        saved = json.loads((state/'model-verifications.json').read_text())
        cache = saved['files'] if saved.get('schema') == 1 else {}
        if not isinstance(cache, dict):
            cache = {}
    except (OSError, ValueError, KeyError, TypeError):
        cache = {}
    def fingerprint(path):
        stat=path.stat()
        return dict(path=str(path), bytes=stat.st_size, device=stat.st_dev,
                    inode=stat.st_ino, mtime_ns=stat.st_mtime_ns, ctime_ns=stat.st_ctime_ns)
    def save_cache():
        temporary=None
        try:
            state.mkdir(parents=True,exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w',dir=state,delete=False) as out:
                temporary=Path(out.name)
                json.dump(dict(schema=1,files=cache),out)
            temporary.replace(state/'model-verifications.json')
        except OSError: pass
        finally:
            if temporary is not None: temporary.unlink(missing_ok=True)
    missing = reused = count = 0
    required = []
    for entry in files:
        relative = Path(entry['path'])
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Unzulässiger Modellpfad bei der Platzprüfung.')
        path = (models/relative).resolve()
        if not path.is_relative_to(models):
            raise ValueError('Modellpfad verlässt das eigene Modellverzeichnis.')
        checksum = ['sha256', entry['sha256'].lower()] if entry.get('sha256') else ['git-blob-sha1', entry['git_blob_sha1'].lower()]
        valid=False
        if path.is_file():
            identity=fingerprint(path)
            old=cache.get(str(path),{})
            sized=identity['bytes']==entry['bytes']
            valid=sized and (not verify_models or (not force and isinstance(old,dict)
                  and old.get('fingerprint')==identity and old.get('checksum')==checksum))
            if sized and not valid and verify_models and validate:
                print('MODEL_CHECK:Prüfsumme WSL: '+entry['path']+' — '+('Neuprüfung angefordert' if force else 'kein passender Prüfnachweis'),flush=True)
                digest=hashlib.sha256() if checksum[0]=='sha256' else hashlib.sha1()
                if checksum[0]=='git-blob-sha1':digest.update(f"blob {identity['bytes']}\0".encode())
                with path.open('rb') as stream:
                    for block in iter(lambda:stream.read(8*1024*1024),b''):digest.update(block)
                valid=digest.hexdigest()==checksum[1] and fingerprint(path)==identity
                cache.pop(str(path),None)
                if valid:cache[str(path)]=dict(fingerprint=identity,checksum=checksum)
                save_cache()
        if valid:
            reused += entry['bytes']
            count += 1
        else:
            required.append(entry['path'])
            stage = path.with_name(path.name+'.part')
            partial = stage.stat().st_size if stage.is_file() else 0
            missing += entry['bytes'] - (partial if 0 <= partial <= entry['bytes'] else 0)
    complete = all(p.is_file() for p in [
        state/'installed.json', state/'asr-packages-1.0.json', state/'diarization-packages-1.0.json',
        state/'llama-build.json', cuda, base/'python/asr-venv/bin/python',
        base/'python/diarization-venv/bin/python', base/'bin/llama-server'])
    disk = base
    while not disk.exists():
        disk = disk.parent
    return dict(AdditionalBytes=missing, ReusedBytes=reused, ReusedFiles=count,
                RuntimeReady=complete, RequiredPaths=required, Validated=validate, VerifyModelFiles=verify_models, FreeBytes=shutil.disk_usage(disk).free)


if __name__ == '__main__':
    if (os.environ.get('WSL_DISTRO_NAME') != 'kienzledoku-server' or
            not Path('/etc/kienzledoku-server/windows-installer-owned').is_file()):
        raise ValueError('Platzprüfung nur in der eigenen WSL-Umgebung ausführen.')
    request = json.loads(base64.b64decode(sys.argv[1]).decode('utf-8-sig'))
    print('KIENZLEDOKU_STORAGE='+json.dumps(probe(request['Files'],force=request['Force'],verify_models=request.get('VerifyModelFiles',True),validate=request.get('Validate',False))))
