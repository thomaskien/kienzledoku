#!/usr/bin/env python3
"""Reproducible payload assembly, Linux NSIS cross-build and portable ZIP."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]
VERSION=(ROOT/'VERSION').read_text().strip()
if not re.fullmatch(r'\d+\.\d+',VERSION):
    raise SystemExit('VERSION muss Haupt- und laufende Unterversion enthalten, z. B. 1.9 oder 1.10.')
FILE_VERSION=VERSION+'.0.0'

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--makensis',default=shutil.which('makensis'))
    args=parser.parse_args()
    if not args.makensis: raise SystemExit('NSIS 3 erforderlich; --makensis /PFAD/ZU/makensis')
    # Windows PowerShell 5.1 otherwise reads BOM-less UTF-8 as the ANSI code page.
    for path in list((ROOT/'windows').glob('*'))+list((ROOT/'tests').glob('*')):
        if path.suffix in ('.ps1','.psm1'):
            text=path.read_text(encoding='utf-8-sig');path.write_text(text,encoding='utf-8-sig',newline='\r\n')
    readme=(ROOT/'README.md').read_text()
    (ROOT/'README.txt').write_text(readme,encoding='utf-8-sig',newline='\r\n')
    payload=ROOT/'linux-payload.tar'
    files=[p for p in sorted((ROOT/'linux').rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc']
    with tarfile.open(payload,'w',format=tarfile.PAX_FORMAT) as archive:
        for path in files+[ROOT/'models.json',ROOT/'audio-files.json',ROOT/'VERSION']:
            name=str(path.relative_to(ROOT/'linux')) if path.is_relative_to(ROOT/'linux') else path.name
            info=archive.gettarinfo(str(path),arcname=name)
            info.uid=info.gid=0;info.uname=info.gname='root';info.mtime=0;info.mode=0o644
            with path.open('rb') as stream: archive.addfile(info,stream)
    (ROOT/'dist').mkdir(exist_ok=True)
    process=subprocess.run([args.makensis,'-V3','-DPRODUCT_VERSION='+VERSION,'-DFILE_VERSION='+FILE_VERSION,str(ROOT/'build/setup.nsi')],text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    (ROOT/'evidence/nsis-build.log').write_text(process.stdout)
    if process.returncode: print(process.stdout);raise SystemExit(process.returncode)
    exe=ROOT/f'dist/kienzledoku-Server-Installer-{VERSION}.exe'
    if exe.read_bytes()[:2]!=b'MZ':raise SystemExit('Keine gültige PE-Datei erzeugt.')
    archive_path=ROOT/f'dist/kienzledoku-Server-Installer-{VERSION}.zip'
    prefix=f'kienzledoku-Server-Installer-{VERSION}/'
    with zipfile.ZipFile(archive_path,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for path,name in [(exe,exe.name),(ROOT/'README.txt','README.txt'),(ROOT/'models/README.txt','models/README.txt')]:
            archive.write(path,prefix+name)
    artifacts=[]
    for path in [exe,archive_path]:
        sha=hashlib.sha256(path.read_bytes()).hexdigest()
        path.with_suffix(path.suffix+'.sha256').write_text(sha+'  '+path.name+'\n')
        artifacts.append({'file':path.name,'bytes':path.stat().st_size,'sha256':sha})
    metadata={'product':'kienzledoku Server Installer','version':VERSION,'file_version':FILE_VERSION,'built_at_utc':datetime.now(timezone.utc).isoformat(),
              'nsis':subprocess.check_output([args.makensis,'-VERSION'],text=True).strip(),
              'artifacts':artifacts,'windows_runtime_tested':False}
    (ROOT/'evidence/build.json').write_text(json.dumps(metadata,indent=2)+'\n')
    if not shutil.which('7z'):raise SystemExit('7z für die abschließende Paketprüfung erforderlich.')
    with tempfile.TemporaryDirectory(prefix='kienzledoku-exe-check-') as temporary:
        subprocess.run(['7z','x','-y','-o'+temporary,str(exe)],check=True,stdout=subprocess.PIPE)
        embedded=next(Path(temporary).rglob('linux-payload.tar')).parent
        expected=['VERSION','models.json','audio-files.json','ubuntu.json','README.txt','linux-payload.tar']
        expected += ['windows/'+p.name for p in (ROOT/'windows').iterdir() if p.is_file()]
        for relative in expected:
            if (embedded/relative).read_bytes()!=(ROOT/relative).read_bytes():
                raise SystemExit('Eingebettete Datei fehlt oder verändert: '+relative)
            if relative.endswith('.py'):
                compile((embedded/relative).read_bytes(),relative,'exec')
        with tarfile.open(embedded/'linux-payload.tar') as archive:
            names=archive.getnames()
            if any('client' in name.lower() for name in names):raise SystemExit('Clientdatei im Serverpaket.')
            for member in archive.getmembers():
                if member.name.startswith('/') or '..' in Path(member.name).parts:raise SystemExit('Unsicherer Archivpfad.')
                if member.name.endswith('.py'):compile(archive.extractfile(member).read(),member.name,'exec')
        verification={'exe_sha256':artifacts[0]['sha256'],'embedded_files_match':True,
                      'embedded_files':expected,'server_payload_files':len(names),'client_payload':False,
                      'server_python_sources_compile':True,'windows_runtime_tested':False}
        verification['embedded_storage_probe_compiles']=True
        (ROOT/'evidence/package-verification.json').write_text(json.dumps(verification,indent=2)+'\n')
    entries=[]
    for path in sorted(ROOT.rglob('*')):
        if not path.is_file() or '__pycache__' in path.parts or path.name=='SHA256SUMS':continue
        if path.is_relative_to(ROOT/'models') and path.name!='README.txt':continue
        entries.append(hashlib.sha256(path.read_bytes()).hexdigest()+'  '+str(path.relative_to(ROOT)))
    (ROOT/'SHA256SUMS').write_text('\n'.join(entries)+'\n')
    print(json.dumps(metadata,indent=2))

if __name__=='__main__':main()
