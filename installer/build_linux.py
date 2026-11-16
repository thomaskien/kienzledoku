#!/usr/bin/env python3
"""Stage Linux installers for verification; publish only the verified stage."""
import argparse
from contextlib import nullcontext
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from installer.build_desktop import VERSION, copy
from installer.product_key_build import ProductKeyBuild


def stage(output, llvm, key_file=None, go='/usr/local/bin/go'):
    from installer.runtime_contract import check
    check(ROOT)
    native=(ROOT/'native/KienzledokuWindowLinux.c').read_text(encoding='utf-8')
    if f'"kienzledoku record {VERSION}"' not in native or f'"kienzledoku-record/{VERSION}"' not in native:
        raise ValueError('Native Linux-Versionsanzeige passt nicht zu '+VERSION)
    payload = output / f'kienzledoku-{VERSION}-linux-x86_64'
    if payload.exists():
        raise FileExistsError('Prüfverzeichnis existiert bereits.')
    payload.mkdir(parents=True)
    for path in ROOT.glob('kienzledoku*.py'):
        copy(path, payload/path.name)
    for name in ('LICENSE', 'assets', 'native/KienzledokuWindowLinux.c', 'linux',
                 'install_linux.sh', 'uninstall_linux.sh', 'build_native_window_linux.sh',
                 'build_connect.sh', 'start_kienzledoku_asr.sh', 'requirements-asr-client.txt',
                 'prompt_documentation.txt', 'config.example.toml', 'installer/linux_cli.py',
                 'installer/linux_server.py', 'installer/linux_uninstall.py', 'installer/models.json',
                 'server-windows/linux', 'server-windows/models.json', 'server-windows/audio-files.json', 'server-windows/audio-turbo-files.json',
                 'server-windows/VERSION', 'connect'):
        copy(ROOT/name, payload/name)
    copy(ROOT/'linux/README.md', payload/'README.md')
    copy(ROOT/'LICENSE', payload/'server-windows/LICENSE')
    (payload/'installer/__init__.py').touch()
    context = ProductKeyBuild(key_file, ROOT) if key_file else nullcontext(None)
    with context as product:
        env = dict(os.environ, CGO_ENABLED='0', GOOS='linux', GOARCH='amd64',
                   GOCACHE=str(product.path/'go-cache') if product else '/private/tmp/kienzledoku-build-cache/go-cache')
        args = [go, 'build', '-trimpath', '-ldflags=-s -w']
        if product:
            args += ['-overlay', product.overlay]
        args += ['-o', payload/'kienzleconnect', '.']
        if product:
            product.run(args, cwd=ROOT/'connect', env=env)
            product.run([llvm/'clang-23', '--target=x86_64-linux-gnu', '-fPIC', '-O2',
                         '-fvisibility=hidden', '-c', product.c_source, '-o', product.path/'product.o'])
            product.run([llvm/'ld.lld', '-shared', '--strip-all', '-soname', 'libkienzledoku_product.so',
                         '-o', payload/'libkienzledoku_product.so', product.path/'product.o'])
            (payload/'release.json').write_text(json.dumps({'manufacturer_key':'production'}))
            product.check_tree(payload)
            names = subprocess.check_output(['git','ls-files','-co','--exclude-standard','-z'],cwd=ROOT).decode().split('\0')
            for name in names:
                if name and (ROOT/name).is_file(): product.check_file(ROOT/name)
        else:
            subprocess.run(list(map(str, args)), cwd=ROOT/'connect', env=env, check=True)
    for path in payload.rglob('*.py'):
        compile(path.read_bytes(),str(path),'exec')
    subprocess.run(['bash',str(payload/'install_linux.sh'),'--self-test'],check=True,
                   env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'))
    manifest = {'version':VERSION,'manufacturer_key':'production' if key_file else 'demo',
                'stage':str(payload),'built_at':datetime.now(timezone.utc).isoformat(),
                'plaintext_scan':bool(key_file)}
    # Bind later publication to the exact files exercised by target-host tests.
    manifest['files'] = {str(p.relative_to(payload)):hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in sorted(payload.rglob('*')) if p.is_file()}
    (output/'stage.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(payload)
    return payload


def publish(stage_manifest, validation, output):
    meta=json.loads(stage_manifest.read_text());payload=Path(meta['stage'])
    evidence=json.loads(validation.read_text())
    if meta['version']!=VERSION or evidence.get('version')!=VERSION or evidence.get('passed') is not True:
        raise ValueError('Prüfnachweis für diese Version fehlt.')
    actual={str(p.relative_to(payload)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(payload.rglob('*')) if p.is_file()}
    if actual!=meta['files']:
        raise ValueError('Nutzlast hat sich seit dem Prüfaufbau geändert.')
    if evidence.get('files')!=actual:
        raise ValueError('Die auf dem Zielsystem geprüfte Nutzlast stimmt nicht überein.')
    output.mkdir(parents=True,exist_ok=True)
    archive=output/(payload.name+'.tar.gz')
    if archive.exists():
        raise FileExistsError('Diese Version ist bereits bereitgestellt.')
    with tempfile.TemporaryDirectory(dir=output) as temp:
        candidate=Path(temp)/archive.name
        with tarfile.open(candidate,'w:gz') as handle: handle.add(payload,arcname=payload.name)
        with tarfile.open(candidate) as handle:
            for member in handle.getmembers():
                if member.name.startswith('/') or '..' in Path(member.name).parts or member.issym() or member.islnk():
                    raise ValueError('Ungültiger Archivpfad.')
                if member.isfile():
                    relative=str(Path(member.name).relative_to(payload.name))
                    if hashlib.sha256(handle.extractfile(member).read()).hexdigest()!=actual[relative]:
                        raise ValueError('Veränderte Archivdatei.')
        # Exclusive creation: never overwrite a previously published artifact.
        with archive.open('xb') as target, candidate.open('rb') as source: shutil.copyfileobj(source,target)
    digest=hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(archive.suffix+'.sha256').write_text(digest+'  '+archive.name+'\n')
    meta.update(archive=str(archive),sha256=digest,bytes=archive.stat().st_size,validation=evidence)
    (output/f'build-{VERSION}.json').write_text(json.dumps(meta,indent=2)+'\n')
    print(archive)


if __name__=='__main__':
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='command',required=True)
    create=sub.add_parser('stage');create.add_argument('--output',type=Path,required=True)
    create.add_argument('--llvm',type=Path,required=True);create.add_argument('--product-key-file',type=Path)
    release=sub.add_parser('publish');release.add_argument('--manifest',type=Path,required=True)
    release.add_argument('--validation',type=Path,required=True);release.add_argument('--output',type=Path,default=ROOT/'dist/linux')
    args=parser.parse_args()
    if args.command=='stage':stage(args.output,args.llvm,args.product_key_file)
    else:publish(args.manifest,args.validation,args.output)
