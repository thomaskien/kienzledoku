#!/usr/bin/env python3
"""Build the self-contained clickable macOS installer, without installing it."""
import argparse
from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from installer.core import VERSION, LOCKS, download, extract_archive


def run(argv,**kwargs):
    subprocess.run([str(x) for x in argv],check=True,**kwargs)


def compile_native(source,target,extra=()):
    run(['/usr/bin/clang','-arch','arm64','-arch','x86_64','-mmacosx-version-min=11.0','-fobjc-arc','-framework','Cocoa','-framework','WebKit',*extra,ROOT/'native'/source,'-o',target])
    run(['/usr/bin/codesign','--force','--sign','-',target])


def build(arch,output,cache,product_key_file=None):
    from installer.runtime_contract import check
    check(ROOT)
    from installer.product_key_build import ProductKeyBuild
    context = ProductKeyBuild(product_key_file,ROOT) if product_key_file else nullcontext(None)
    with context as product:
        return _build(arch,output,cache,product)


def _build(arch,output,cache,product):
    for source, marker in (
        ('KienzledokuInstaller.m', f'KienzledokuInstallerVersion = @"{VERSION}"'),
        ('KienzledokuWindow.m', f'self.window.title = @"kienzledoku record {VERSION}"'),
        ('KienzledokuWindow.m', f'@"kienzledoku-record/{VERSION}"'),
    ):
        if marker not in (ROOT/'native'/source).read_text(encoding='utf-8'):
            raise ValueError('Native Versionsanzeige passt nicht zu '+VERSION+': '+source)
    output.mkdir(parents=True,exist_ok=True); cache.mkdir(parents=True,exist_ok=True)
    dmg=output/('kienzledoku-'+VERSION+'-macOS-'+arch+'.dmg')
    if dmg.exists():
        raise FileExistsError('Diese DMG-Version existiert bereits. Vor einem neuen Build die Versionsnummer erhöhen: '+str(dmg))
    stage=Path(tempfile.mkdtemp(prefix='kienzledoku-package-',dir='/private/tmp'))
    app=stage/'kienzledoku Installation.app'; contents=app/'Contents'; resources=contents/'Resources'
    (contents/'MacOS').mkdir(parents=True); resources.mkdir()
    payload=resources/'payload'; payload.mkdir()
    for path in ROOT.glob('kienzledoku*.py'): shutil.copy2(path,payload/path.name)
    for name in ('kienzledoku_commander','local-ai-macos','assets','installer'):
        shutil.copytree(ROOT/name,payload/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for name in ('prompt_documentation.txt','requirements-asr-client.txt','config.example.toml'):
        shutil.copy2(ROOT/name,payload/name)
    (payload/'docs/images').mkdir(parents=True)
    for name in ('t2med-drittanbieter-suche.png','t2med-drittanbieter-url.png','t2med-produktcode-aktivieren.png','t2med-produktcode-kienzledoku.png','t2med-kienzledoku-aktiv.png'):
        shutil.copy2(ROOT/'docs/images'/name,payload/'docs/images'/name)
    shutil.copy2(ROOT/'LICENSE',payload/'LICENSE')
    shutil.copy2(ROOT/'LICENSE',stage/'LICENSE')
    for name in ('NOTICE',):
        if (ROOT/name).exists(): shutil.copy2(ROOT/name,payload/name)
    for source,target in [('KienzledokuInstaller.m',contents/'MacOS/kienzledoku-installer'),('KienzledokuWindow.m',payload/'kienzledoku_window')]: compile_native(source,target)
    for role in ('record','connect'):
        compile_native('KienzledokuApp.m',payload/f'kienzledoku_{role}_app',
                       [f'-DKIENZLEDOKU_LAUNCHER_MODE="{role}"'])
    if product:
        library=payload/'libkienzledoku_product.dylib'
        product.run(['/usr/bin/clang','-dynamiclib','-arch','arm64','-arch','x86_64','-mmacosx-version-min=11.0','-O2','-fvisibility=hidden',product.c_source,'-o',library])
        run(['/usr/bin/codesign','--force','--sign','-',library])
        (payload/'release.json').write_text(json.dumps({'manufacturer_key':'production'}))
        from kienzledoku_product_key import embedded_api_key
        if embedded_api_key(payload)[0].encode()!=product.key:
            raise RuntimeError('Privater Hersteller-Key konnte nicht korrekt eingebunden werden.')
    go=shutil.which('go') or '/usr/local/bin/go'
    binaries=[]
    for cpu in ('arm64','amd64'):
        target=stage/('connect-'+cpu); binaries.append(target)
        env=dict(os.environ,GOOS='darwin',GOARCH=cpu,CGO_ENABLED='0',GOCACHE=str(product.path/'go-cache' if product else cache/'go-cache'))
        options=['-overlay',product.overlay,'-ldflags=-s -w'] if product else []
        (product.run if product else run)([go,'build','-trimpath',*options,'-o',target,'.'],cwd=ROOT/'connect',env=env)
    run(['/usr/bin/lipo','-create',*binaries,'-output',payload/'kienzleconnect'])
    run(['/usr/bin/codesign','--force','--sign','-',payload/'kienzleconnect'])
    for binary in binaries: binary.unlink()
    info=LOCKS['python_'+arch]; archive=cache/('python-'+arch+'.tar.gz')
    download(info['url'],archive,info['sha256'],print)
    extract_archive(archive,resources/'runtime')
    # Bundle small client wheels so installing only Record needs no additional network.
    wheelhouse=resources/'wheelhouse'; wheelhouse.mkdir()
    run([sys.executable,'-m','pip','download','--only-binary=:all:','--platform','macosx_11_0_'+arch,'--python-version','3.12','--implementation','cp','--abi','cp312','--dest',wheelhouse,'sounddevice==0.5.5','numpy==1.26.4','onnxruntime==1.19.2'])
    shutil.copy2(ROOT/'assets/kienzledoku-record.icns',resources/'app.icns')
    plist=dict(CFBundleIdentifier='de.kienzledoku.installer',CFBundleName='kienzledoku Installation',CFBundleDisplayName='kienzledoku Installation',CFBundleExecutable='kienzledoku-installer',CFBundlePackageType='APPL',CFBundleShortVersionString=VERSION,CFBundleVersion=VERSION,CFBundleIconFile='app.icns',LSMinimumSystemVersion='11.0',NSHighResolutionCapable=True)
    plist['NSLocalNetworkUsageDescription']='Der Installer prüft die Verbindung zu T2med und Commander im Praxisnetz.'
    (contents/'Info.plist').write_bytes(plistlib.dumps(plist))
    # Python's relocatable dylibs and executable must all be covered by the local signature.
    run(['/usr/bin/xattr','-cr',app])
    run(['/usr/bin/codesign','--force','--deep','--sign','-',app])
    run(['/usr/bin/codesign','--verify','--deep','--strict',app])
    if product:
        product.check_tree(stage)
        # Public source must never contain private key values either.
        files=subprocess.check_output(['git','ls-files','-co','--exclude-standard','-z'],cwd=ROOT).decode().split('\0')
        for name in files:
            path=ROOT/name
            if name and path.is_file(): product.check_file(path)
    (stage/'Installation.txt').write_text('kienzledoku '+VERSION+'\n\nDie App „kienzledoku Installation“ doppelklicken und durch den Assistenten gehen.\nClient und Server können zusammen auf diesem Mac installiert werden.\nModelle werden nur nach der Auswahl heruntergeladen.\n\nDieses Testpaket ist lokal signiert, noch nicht von Apple notarisiert.\nDie bestehenden Programme werden erst beim Abschluss der Installation aktualisiert.\n')
    run(['/usr/bin/hdiutil','create','-volname','kienzledoku '+VERSION,'-srcfolder',stage,'-format','UDZO',dmg])
    digest=hashlib.sha256(dmg.read_bytes()).hexdigest()
    (dmg.with_suffix('.dmg.sha256')).write_text(digest+'  '+dmg.name+'\n')
    (output/('build-'+VERSION+'-'+arch+'.json')).write_text(json.dumps({'version':VERSION,'architecture':arch,'dmg':str(dmg),'sha256':digest,'app':str(app),'python':info,'manufacturer_key':'production' if product else 'demo','plaintext_key_scan':'passed' if product else 'not_applicable'},indent=2)+'\n')
    print(str(dmg),flush=True)
    return dmg

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--arch',choices=['arm64','x86_64'],default='arm64'); parser.add_argument('--output',type=Path,default=ROOT/'dist/macos'); parser.add_argument('--cache',type=Path,default=Path('/private/tmp/kienzledoku-build-cache')); parser.add_argument('--product-key-file',type=Path)
    args=parser.parse_args(); build(args.arch,args.output,args.cache,args.product_key_file)
