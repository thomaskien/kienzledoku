"""Build both Finder disk images with one byte-identical Universal 1.8.3 client.

Build environment: macOS, CPython 3.12, dmgbuild 2.0.0 and Pillow.
Input: the pinned public external-Python client DMG plus two Intel wheels.
"""
import argparse
import hashlib
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import dmgbuild
from PIL import Image, ImageDraw, ImageFont

SOURCE = Path(__file__).resolve().parent
ROOT = SOURCE.parents[1]
BASE_HASH = '88ed0b0e8ffea7dd2b6506fc720a1e7322dd8d98122930c71146a4b2a068c1a3'
INTEL = {
    'numpy-1.26.4-cp312-cp312-macosx_10_9_x86_64.whl': 'b3ce300f3644fb06443ee2222c2201dd3a89ea6040541412b8fa189341847218',
    'cffi-2.1.1-cp312-cp312-macosx_10_15_x86_64.whl': 'c8c69575568085ba0b1b10c0249d779a214aea6f6522e949a0fc9fb0fcb449d0',
}
APP = 'KienzleDoku.app'
WIZARD = 'Commander installieren.app'
CLIENT_DMG = 'KienzleDoku-1.8.3-macOS-Universal-nur-Client.dmg'
SERVER_DMG = 'KienzleDoku-1.8.3-macOS-Apple-Silicon-mit-Serverkomponente.dmg'


def run(*args):
    subprocess.run(args, check=True)


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def plist(binary, identifier, name):
    return dict(CFBundleExecutable=binary, CFBundleIdentifier=identifier,
                CFBundleDisplayName=name, CFBundleName=name, CFBundlePackageType='APPL',
                CFBundleShortVersionString='1.8.3', CFBundleVersion='1.8.3', CFBundleIconFile='app.icns',
                NSHighResolutionCapable=True, LSMinimumSystemVersion='11.0',
                NSDesktopFolderUsageDescription='KienzleDoku schreibt das technische Einrichtungsprotokoll auf Ihren Schreibtisch.',
                NSLocalNetworkUsageDescription='KienzleDoku verbindet sich mit dem Commander und T2med im Praxisnetz.')


def assemble_client(base, directory, wheels):
    src = base / 'Kienzledoku Client Installation Debug.app/Contents/Resources'
    contents = directory / APP / 'Contents'
    res = contents/'Resources'
    payload = res/'payload'
    for folder in (payload, contents/'Helpers', contents/'Frameworks', contents/'MacOS'):
        folder.mkdir(parents=True)
    for path in [*ROOT.glob('kienzledoku*.py'), ROOT/'prompt_documentation.txt', ROOT/'LICENSE', src/'payload/release.json']:
        shutil.copy2(path, payload/path.name)
    shutil.copytree(ROOT/'assets', payload/'assets')
    for name, target in [('kienzleconnect', contents/'Helpers'), ('libkienzledoku_product.dylib', contents/'Frameworks')]:
        shutil.copy2(src/'payload'/name, target/name)
        (payload/name).symlink_to(os.path.relpath(target/name, payload))
    archs = ['-arch','arm64','-arch','x86_64','-mmacosx-version-min=11.0','-fobjc-arc']
    window = contents/'Helpers/kienzledoku_window'
    run('clang', *archs, '-framework', 'Cocoa', '-framework', 'WebKit', ROOT/'native/KienzledokuWindow.m', '-o', window)
    run('codesign','--force','--sign','-',window)
    (payload/window.name).symlink_to(os.path.relpath(window,payload))
    wheelhouse = directory/'wheels'
    shutil.copytree(src/'wheelhouse',wheelhouse)
    for name, expected in INTEL.items():
        if sha(wheels/name) != expected:
            raise ValueError('Unerwarteter Intel-Wheel: '+name)
        shutil.copy2(wheels/name,wheelhouse/name)
    for arch in ('arm64','x86_64'):
        vendor = res/'vendor'/arch
        run(sys.executable,'-I','-m','pip','--isolated','--disable-pip-version-check','install',
            '--no-cache-dir','--no-index','--only-binary=:all:','--no-compile',
            '--platform','macosx_11_0_'+arch,'--python-version','3.12','--abi','cp312',
            '--implementation','cp','--find-links',wheelhouse,'--target',vendor,'-r',ROOT/'requirements-asr-client.txt')
        if (vendor/'bin').is_dir():
            shutil.rmtree(vendor/'bin')
    shutil.copy2(SOURCE/'client.py',res/'client.py')
    shutil.copy2(src/'app.icns',res/'app.icns')
    info = plist('KienzleDoku','de.kienzledoku.client.unified','KienzleDoku')
    info.update(NSMicrophoneUsageDescription='Record benötigt das Mikrofon für den Audiotest und die Gesprächsaufzeichnung.',
                CFBundleURLTypes=[dict(CFBundleURLName='KienzleDoku T2med',CFBundleTypeRole='Viewer',
                                       CFBundleURLSchemes=['kienzledoku-record','kienzledoku'])])
    (contents/'Info.plist').write_bytes(plistlib.dumps(info))
    run('clang', *archs, '-Wall','-Werror','-framework','Cocoa',SOURCE/'Client.m','-o',contents/'MacOS/KienzleDoku')
    sign(contents.parent)


def sign(app):
    run('codesign','--force','--sign','-',app)
    run('codesign','--verify','--deep','--strict',app)


def assemble_commander(directory):
    contents = directory/WIZARD/'Contents'
    res = contents/'Resources'
    payload = res/'payload'
    payload.mkdir(parents=True)
    (contents/'MacOS').mkdir()
    (res/'commander-installer').touch()
    client_resources = directory/APP/'Contents/Resources'
    shutil.copy2(client_resources/'app.icns',res/'app.icns')
    shutil.copy2(client_resources/'payload/release.json',payload/'release.json')
    for path in [*ROOT.glob('kienzledoku*.py'),ROOT/'LICENSE',ROOT/'prompt_documentation.txt',ROOT/'requirements-asr-client.txt']:
        shutil.copy2(path,payload/path.name)
    for name in ('kienzledoku_commander','local-ai-macos','assets','installer','docs/images'):
        shutil.copytree(ROOT/name,payload/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc','macos_single_app'))
    shutil.copy2(SOURCE/'debug_bootstrap.py',payload/'installer/debug_bootstrap.py')
    info = plist('commander-installer','de.kienzledoku.installer.commander','Commander installieren')
    info['LSMinimumSystemVersion'] = '14.0'
    (contents/'Info.plist').write_bytes(plistlib.dumps(info))
    run('clang','-arch','arm64','-mmacosx-version-min=14.0','-fobjc-arc','-DKIENZLEDOKU_INSTALLER_DEBUG_DESKTOP=1',
        '-I', ROOT/'native','-framework','Cocoa','-framework','WebKit','-framework','Security',
        SOURCE/'Commander.m','-o', contents/'MacOS/commander-installer')
    sign(contents.parent)


def finder_background(work, server):
    image = Image.new('RGB',(760,442),'#f5f7fa')
    draw = ImageDraw.Draw(image)
    fonts = Path('/System/Library/Fonts/Supplemental')
    def line(x,y,words,size=16,bold=False,color='#24394d'):
        font = ImageFont.truetype(str(fonts/('Arial Bold.ttf' if bold else 'Arial.ttf')),size)
        draw.text((x,y),words,font=font,fill=color)
    line(32,23,'Client und Server' if server else 'Nur Client',32,True)
    line(33,74,'Ziehen Sie KienzleDoku.app in den Ordner Programme.',21,True)
    line(33,108,'Öffnen Sie die kopierte App aus Programme. Sie verwendet Ihre gespeicherten Einstellungen.')
    if server:
        line(33,143,'Öffnen Sie „Commander installieren“, um diesen Mac als Server einzurichten.')
        line(33,169,'Im Installer können Sie auch die T2med-Verbindung für diesen Arbeitsplatz konfigurieren.')
    else:
        line(33,143,'Beim ersten Start richten Sie die Verbindung zu T2med und Ihrem Commander ein.')
    draw.line((151,249,258,249), fill='#39739a', width=3)
    draw.polygon([(258,243),(270,249),(258,255)],fill='#39739a')
    draw.line((32,330,728,330),fill='#cbd6de')
    line(33,352,'Python 3.12 separat installieren',17,True)
    line(33,381,'Die Installationsanleitung erklärt die Einrichtung mit dem grafischen Python.org-Installer.',15)
    file=work/('server.png' if server else 'client.png')
    image.save(file)
    return file


def build_image(work,server):
    name=SERVER_DMG if server else CLIENT_DMG
    volume='KienzleDoku · Client und Server' if server else 'KienzleDoku · Nur Client'
    files=[str(work/APP), (str(SOURCE/'Installation.txt'),'Installationsanleitung.txt')]
    positions={APP:(98,246),'Programme':(332,246),'Installationsanleitung.txt':(666,246)}
    if server:
        files.append(str(work/WIZARD))
        positions[WIZARD]=(502,246)
    dmgbuild.build_dmg(str(work/name),volume,settings=dict(
        format='UDZO', filesystem='HFS+', files=files, symlinks={'Programme':'/Applications'},
        icon_locations=positions, icon_size=64, text_size=12, window_rect=((120,100),(760,442)),
        show_toolbar=False, show_status_bar=False, show_tab_view=False, show_pathbar=False,
        background=str(finder_background(work,server)), default_view='icon-view'))
    run('hdiutil','verify',work/name)
    mount = work/'verify-image'
    mount.mkdir(exist_ok=True)
    run('hdiutil','attach','-readonly','-nobrowse','-mountpoint',mount,work/name)
    try:
        for bundle in ([APP,WIZARD] if server else [APP]):
            run('codesign','--verify','--deep','--strict', mount/bundle)
    finally:
        run('hdiutil','detach',mount)


def build(image,wheels,output):
    if sys.platform!='darwin' or sys.version_info[:2]!=(3,12) or sha(image)!=BASE_HASH:
        raise ValueError('Build benötigt macOS, CPython 3.12 und das verifizierte Basis-Image.')
    output.mkdir(parents=True, exist_ok=True)
    names=(CLIENT_DMG, SERVER_DMG)
    if any((output/name).exists() for name in names):
        raise FileExistsError('Für einen neuen Build ein freies Ausgabeverzeichnis wählen.')
    with tempfile.TemporaryDirectory(prefix='kd183-images-',dir='/private/tmp') as temp:
        work=Path(temp)
        mount=work/'base'
        mount.mkdir()
        run('hdiutil','attach','-readonly','-nobrowse','-mountpoint',mount,image)
        try:
            assemble_client(mount,work,wheels)
        finally:
            run('hdiutil','detach',mount)
        assemble_commander(work)
        for server in (False, True):
            build_image(work,server)
        for name in names:
            shutil.copy2(work/name,output/name)
            (output/(name+'.sha256')).write_text(f'{sha(work/name)}  {name}\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for field in ('image','wheels','output'):
        parser.add_argument(field,type=Path)
    args=parser.parse_args()
    build(args.image.resolve(),args.wheels.resolve(),args.output.resolve())
