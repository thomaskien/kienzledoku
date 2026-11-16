#!/usr/bin/env python3
"""Assemble immutable Windows x64 and Ubuntu 24.04 installer artifacts."""
import argparse
from contextlib import nullcontext
import sys
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
ROOT=Path(__file__).resolve().parents[1]
VERSION='1.8.1'
sys.path.insert(0,str(ROOT))
from installer.product_key_build import ProductKeyBuild
def run(argv,**kw): subprocess.run(list(map(str,argv)),check=True,**kw)
def copy(source,target):
    target.parent.mkdir(parents=True,exist_ok=True)
    if source.is_dir(): shutil.copytree(source,target,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc','.DS_Store'))
    else: shutil.copy2(source,target)
def ps_copy(source,target):
    copy(source,target)
    for p in ([target] if target.is_file() else target.rglob('*')):
        if p.suffix in ('.ps1','.psm1'): p.write_text(p.read_text(encoding='utf-8-sig'),encoding='utf-8-sig',newline='\r\n')
def main():
    from installer.runtime_contract import check
    check(ROOT)
    p=argparse.ArgumentParser();p.add_argument('--tools',type=Path,required=True);p.add_argument('--makensis',default='makensis');p.add_argument('--go',default='go');p.add_argument('--product-key-file',type=Path)
    args=p.parse_args();tools=args.tools.resolve();out=ROOT/'dist';win=out/'windows';linux=out/'linux'
    artifacts=[win/f'kienzledoku-{VERSION}-windows-x64-setup.exe',win/f'kienzledoku-{VERSION}-windows-x64.zip']
    if any(x.exists() for x in artifacts): raise SystemExit('Eine Ausgabe dieser Version existiert bereits. Versionsnummer erhöhen.')
    for d in (win,linux): d.mkdir(parents=True,exist_ok=True)
    lock=json.loads((ROOT/'windows/runtime-lock.json').read_text())
    for name,sha in lock['files'].items():
        path=tools/name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=sha: raise SystemExit('Build-Abhängigkeit fehlt oder verändert: '+name)
    with tempfile.TemporaryDirectory(prefix='kienzledoku-desktop-build-') as tmp:
        stage=Path(tmp);payload=stage/'windows';client=payload/'client';client.mkdir(parents=True)
        for file in ROOT.glob('kienzledoku*.py'): copy(file,client/file.name)
        for name in ('LICENSE','prompt_documentation.txt','assets'): copy(ROOT/name,client/name)
        copy(ROOT/'LICENSE',payload/'LICENSE')
        for name in ('install.ps1','uninstall.ps1','install.cmd','installer_client.py','Update.ps1','ClientRuntime.ps1'): ps_copy(ROOT/'windows'/name,client/name)
        for name in ('__init__.py','wizard.py','ui.html','options.py','windows_core.py','windows_launch.py'):
            copy(ROOT/'installer'/name,client/'installer'/name)
        for name in ('WizardConfig.psm1','WizardBridge.ps1','UninstallUI.ps1'):
            ps_copy(ROOT/'windows'/name,payload/name)
        ps_copy(ROOT/'windows/Setup.ps1',payload/'Setup.ps1')
        ps_copy(ROOT/'windows/SetupUninstall.ps1',payload/'SetupUninstall.ps1')
        ps_copy(ROOT/'windows/Update.ps1',payload/'Update.ps1')
        for name in ('t2med-drittanbieter-suche.png','t2med-drittanbieter-url.png','t2med-produktcode-aktivieren.png','t2med-produktcode-kienzledoku.png','t2med-kienzledoku-aktiv.png'):
            copy(ROOT/'docs/images'/name,payload/'docs/images'/name)
            copy(ROOT/'docs/images'/name,client/'docs/images'/name)
        with zipfile.ZipFile(tools/'python-3.12.10-embed-amd64.zip') as z:z.extractall(client/'runtime')
        (client/'runtime/python312._pth').write_text('python312.zip\n.\n..\nLib/site-packages\nimport site\n')
        for wheel in (tools/'wheels').glob('*.whl'):
            if 'wheels/'+wheel.name not in lock['files']: raise SystemExit('Ungeprüftes Wheel: '+wheel.name)
            with zipfile.ZipFile(wheel) as z:z.extractall(client/'runtime/Lib/site-packages')
        dependency_check=json.loads(subprocess.check_output([
            sys.executable,'-I',str(ROOT/'installer/verify_windows_runtime.py'),
            '--site-packages',str(client/'runtime/Lib/site-packages'),
            '--python-version',lock['python']],text=True))
        compiler=next((tools/'llvm').glob('*/bin/x86_64-w64-mingw32-clang++'));rc=compiler.with_name('x86_64-w64-mingw32-windres')
        sdk=tools/'webview2/build/native'
        run([rc,ROOT/'windows/window.rc',stage/'window.o','-I',ROOT/'windows'])
        run([compiler,'-std=c++17','-O2','-static','-municode','-mwindows','-I'+str(sdk/'include'),ROOT/'windows/KienzledokuWindow.cpp',stage/'window.o',sdk/'x64/WebView2Loader.dll.lib','-luser32','-lole32','-loleaut32','-lshell32','-lshlwapi','-ladvapi32','-lversion','-lwtsapi32','-o',client/'kienzledoku_window.exe'])
        copy(sdk/'x64/WebView2Loader.dll',client/'WebView2Loader.dll')
        env=dict(os.environ,CGO_ENABLED='0',GOARCH='amd64',GOCACHE='/private/tmp/kienzledoku-build-cache/go-cache')
        context=ProductKeyBuild(args.product_key_file,ROOT) if args.product_key_file else nullcontext(None)
        with context as product:
            go_args=[args.go,'build','-trimpath','-ldflags=-H=windowsgui -s -w']
            if product: go_args+=['-overlay',product.overlay]
            go_args+=['-o',client/'kienzleconnect.exe','.']
            if product:
                product.run(go_args,cwd=ROOT/'connect',env=dict(env,GOOS='windows',GOCACHE=str(product.path/'go-cache')))
                product.run([compiler.with_name('x86_64-w64-mingw32-clang'),'-O2','-shared','-s',product.c_source,'-o',client/'kienzledoku_product.dll'])
                for directory in (client,payload):
                    (directory/'release.json').write_text(json.dumps({'manufacturer_key':'production'}))
                product.check_tree(payload)
            else: run(go_args,cwd=ROOT/'connect',env=dict(env,GOOS='windows'))
        server=payload/'server';server.mkdir()
        copy(ROOT/'LICENSE',server/'LICENSE')
        ps_copy(ROOT/'server-windows/windows',server/'windows')
        for name in ('VERSION','models.json','audio-files.json','audio-turbo-files.json','ubuntu.json','README.md'):copy(ROOT/'server-windows'/name,server/('README.txt' if name=='README.md' else name))
        with tarfile.open(server/'linux-payload.tar','w') as tar:
            tar.add(ROOT/'LICENSE',arcname='LICENSE')
            for file in sorted((ROOT/'server-windows/linux').rglob('*')):
                if file.is_file() and '__pycache__' not in file.parts and file.suffix!='.pyc':tar.add(file,arcname=str(file.relative_to(ROOT/'server-windows/linux')))
            for name in ('VERSION','models.json','audio-files.json','audio-turbo-files.json'):tar.add(ROOT/'server-windows'/name,arcname=name)
        copy(ROOT/'windows/README.md',payload/'README.txt')
        exe=stage/artifacts[0].name
        run([args.makensis,'-V2','-DPAYLOAD='+str(payload),'-DOUTPUT='+str(exe),ROOT/'windows/setup.nsi'])
        verify=stage/'verify';run(['7z','x','-y','-o'+str(verify),exe],stdout=subprocess.DEVNULL)
        extracted=next(verify.rglob('Setup.ps1')).parent
        for file in payload.rglob('*'):
            if file.is_file() and (extracted/file.relative_to(payload)).read_bytes()!=file.read_bytes():raise SystemExit('Windows-Nutzlast verändert: '+str(file.relative_to(payload)))
        if exe.read_bytes()[:2]!=b'MZ':raise SystemExit('Ungültige Windows-EXE')
        if args.product_key_file:
            with ProductKeyBuild(args.product_key_file,ROOT) as product:
                product.check_tree(payload);product.check_tree(extracted)
                names=subprocess.check_output(['git','ls-files','-co','--exclude-standard','-z'],cwd=ROOT).decode().split('\0')
                for name in names:
                    if name and (ROOT/name).is_file():product.check_file(ROOT/name)

        copy(exe,artifacts[0])
        with zipfile.ZipFile(artifacts[1],'w',compression=zipfile.ZIP_DEFLATED) as z:
            z.write(exe,exe.name);z.write(ROOT/'windows/README.md','README.txt')
            z.write(ROOT/'LICENSE','LICENSE')
    manifest=dict(version=VERSION,manufacturer_key='production' if args.product_key_file else 'demo',plaintext_key_scan=bool(args.product_key_file),windows_server_version=(ROOT/'server-windows/VERSION').read_text().strip(),built_at=datetime.now(timezone.utc).isoformat(),windows_dependencies=dependency_check,windows_runtime_tested=False,linux_full_install_tested=False,artifacts=[])
    for file in artifacts:
        sha=hashlib.sha256(file.read_bytes()).hexdigest();file.with_suffix(file.suffix+'.sha256').write_text(sha+'  '+file.name+'\n')
        manifest['artifacts'].append(dict(file=str(file.relative_to(out)),bytes=file.stat().st_size,sha256=sha))
    (out/f'desktop-{VERSION}.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(manifest,indent=2))
if __name__=='__main__':main()
