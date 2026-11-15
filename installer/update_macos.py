"""Update completion: exclude recordings, retire idle launchers and old code.

No patient contents or command lines are emitted. Model/configuration roots are
never used as deletion targets. Call completion only after activation succeeded.
"""
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import signal
import subprocess
import time

APP_IDS={'record':'de.kienzledoku.app','connect':'de.kienzledoku.connect'}
VERSION_DIR=re.compile(r'\d+\.\d+(?:\.\d+)?-[0-9a-f]{8}')
OWNER='.kienzledoku-install.json'

@dataclass(frozen=True)
class Process:
    pid:int
    parent:int
    uid:int
    birth:str
    command:str


def processes():
    result=subprocess.run(['/bin/ps','-ww','-axo','pid=,ppid=,uid=,lstart=,command='],capture_output=True,text=True,timeout=10,env=dict(os.environ,LC_ALL='C'))
    if result.returncode:raise RuntimeError('Prozessprüfung nicht möglich; Update wird nicht freigegeben.')
    values=[]
    for line in result.stdout.splitlines():
        fields=line.split(None,8)
        if len(fields)==9 and all(x.isdigit() for x in fields[:3]):
            values.append(Process(int(fields[0]),int(fields[1]),int(fields[2]),' '.join(fields[3:8]),fields[8]))
    return values


def checked_directory(path):
    path=Path(path).absolute()
    for item in (path,*path.parents):
        if item in (Path('/var'),Path('/tmp')):continue
        if item.is_symlink():raise ValueError('Verknüpfte Installationspfade werden nicht automatisch bereinigt.')
    return path


def app_info(home,role):
    app=checked_directory(Path(home)/'Applications'/('kienzledoku '+role+'.app'))
    if not app.exists():return None
    info_path=app/'Contents/Info.plist'
    if info_path.is_symlink():raise ValueError('Unsichere App-Metadaten.')
    info=plistlib.loads(info_path.read_bytes())
    if info.get('CFBundleIdentifier')!=APP_IDS[role]:raise ValueError('Eine gleichnamige fremde App wird nicht verändert.')
    return info


def component_versions(support,home):
    """Only verified, actually registered component roots count as in use."""
    versions=checked_directory(Path(support)/'versions');result={}
    def accept(role,root,python):
        root=checked_directory(root)
        if (root.parent!=versions or not owned_version(root) or '..' in Path(python).parts
                or not str(python).startswith(str(root)+'/')):
            raise ValueError('Aktive Komponente verweist nicht auf einen eindeutig zugeordneten Programmstand.')
        result[role]=root
    for role in APP_IDS:
        info=app_info(home,role)
        if info:
            accept(role,info.get('KienzledokuRoot',''),info.get('KienzledokuPython',''))
            if info.get('CFBundleShortVersionString')!=result[role].name.rsplit('-',1)[0]:
                raise ValueError('Aktive App-Version und Programmstand stimmen nicht überein.')
    agent=checked_directory(Path(home)/'Library/LaunchAgents/de.kienzledoku.commander.plist')
    if agent.exists():
        data=plistlib.loads(agent.read_bytes());args=data.get('ProgramArguments',[])
        if (data.get('Label')!='de.kienzledoku.commander' or len(args)<2
                or Path(args[1]).parts[-2:]!=('installer','service_main.py')):
            raise ValueError('Commander-Autostart ist nicht eindeutig zugeordnet.')
        checked_directory(args[1])
        accept('commander',Path(args[1]).parents[1],args[0])
        if data.get('WorkingDirectory',str(result['commander']))!=str(result['commander']):
            raise ValueError('Commander-Arbeitsverzeichnis passt nicht zum Programmstand.')
    return result


def preserve_unselected(support,home,server,client):
    return {role:root for role,root in component_versions(support,home).items()
            if (role=='commander' and not server) or (role in APP_IDS and not client)}


CLIENT_FILES={'kienzleconnect','kienzledoku_window','kienzledoku_record_app',
              'kienzledoku_connect_app','libkienzledoku_product.dylib','release.json',
              'assets','requirements-asr-client.txt','start_kienzledoku_asr.sh'}
SERVER_FILES={'asr-venv','diar-venv','llama','local-ai-macos','kienzledoku_commander'}
# The HTTP API imports FINALIZED_HEADER from commander_client as a shared protocol constant.
SHARED_FILES={'runtime','venv','kienzledoku_document.py','kienzledoku_commander_client.py','prompt_documentation.txt','LICENSE','NOTICE',OWNER}


def unused_component_files(root,roles):
    """Remove superseded client code even from a still-used server directory."""
    client=bool(set(roles)&set(APP_IDS));server='commander' in roles
    retired=[]
    for path in root.iterdir():
        checked_directory(path)
        name=path.name
        if name in SHARED_FILES:continue
        if name=='installer':
            for item in path.iterdir():
                if server and item.name in ('service_main.py','__init__.py'):continue
                retired.append(item)
            continue
        if name in SERVER_FILES:
            if not server:retired.append(path)
        elif name in CLIENT_FILES or re.fullmatch(r'kienzledoku(?:_[a-z0-9_]+)?\.py',name):
            if not client:retired.append(path)
        elif name in ('__pycache__','commander-candidate.toml','llama-unpack') or name.endswith('-previous.app'):
            retired.append(path)
        else:
            raise ValueError('Unbekannter Inhalt im aktiven Programmstand; keine automatische Bereinigung.')
    for path in retired:checked_directory(path)
    return retired


@contextmanager
def update_guard(support):
    support=checked_directory(support);support.mkdir(parents=True,exist_ok=True,mode=0o700)
    with ExitStack() as stack:
        update=support/'update.lock'
        if update.is_symlink():raise ValueError('Unsichere Updatesperre.')
        fd=os.open(update,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
        handle=stack.enter_context(os.fdopen(fd,'r+b'))
        try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('Eine Aufnahme oder ein anderes Update ist geöffnet. Bitte zuerst schließen.') from None
        sessions=support/'sessions'
        if sessions.is_symlink():raise ValueError('Unsicheres Sitzungsverzeichnis.')
        # Also covers pre-update clients which do not yet participate in update.lock.
        for path in sessions.glob('*/record.lock'):
            checked_directory(path.parent)
            fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
            handle=stack.enter_context(os.fdopen(fd,'rb'))
            try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise ValueError('Bitte zuerst das offene Aufnahmefenster schließen. Es wird nichts verworfen.') from None
        yield


def stop_idle_launchers(home,reader=processes,send=os.kill,sleep=time.sleep):
    paths={str(Path(home)/'Applications'/('kienzledoku '+role+'.app')/'Contents/MacOS/kienzledoku') for role in APP_IDS}
    for row in reader():
        if row.uid!=os.getuid() or row.command not in paths:continue
        role='connect' if 'kienzledoku connect.app' in row.command else 'record'
        if app_info(home,role) is None:raise ValueError("Starter ohne gültige App-Metadaten; nichts beendet.")
        current=reader()
        if row not in current:continue
        if any(p.parent==row.pid for p in current):raise ValueError('Ein Kienzledoku-Fenster ist noch geöffnet. Bitte schließen; Update bleibt angehalten.')
        # Freeze only the already idle launcher so it cannot accept a new URL
        # between the final child check and termination. Never freeze its children.
        send(row.pid,signal.SIGSTOP)
        try:
            current=reader()
            if row not in current:continue
            if any(p.parent==row.pid for p in current):raise ValueError('Ein Kienzledoku-Fenster wurde geöffnet. Update wird nicht fortgesetzt.')
            send(row.pid,signal.SIGTERM)
        finally:
            if row in reader():send(row.pid,signal.SIGCONT)
        for _ in range(50):
            if row not in reader():break
            sleep(.1)
        else:raise RuntimeError('Alter Kienzledoku-Starter wurde nicht beendet. Update wird nicht als abgeschlossen gemeldet.')


def mark_version(version):
    (Path(version)/OWNER).write_text(json.dumps({'product':'kienzledoku','schema':1}))


def owned_version(path):
    checked_directory(path)
    if not VERSION_DIR.fullmatch(path.name) or not path.is_dir():return False
    marker=path/OWNER
    if marker.is_symlink():return False
    if marker.is_file():return json.loads(marker.read_text())=={'product':'kienzledoku','schema':1}
    # Migration of pre-manifest installations: both independent source markers.
    source=path/'kienzledoku.py';installer=path/'installer/core.py'
    if source.is_symlink() or installer.is_symlink():return False
    if not source.is_file() or not installer.is_file():return False
    version=path.name.rsplit('-',1)[0]
    pattern=r'^VERSION\s*=\s*[\"\x27]'+re.escape(version)+r'[\"\x27]'
    return bool(re.search(pattern,source.read_text(),re.M) and re.search(pattern,installer.read_text(),re.M))


def legacy_code(support):
    """Recognize the pre-version-directory client; exclude user test folders."""
    main=support/'kienzledoku.py'
    fixed={'prompt_documentation.txt','requirements-asr-client.txt','start_kienzledoku_asr.sh',
           'kienzledoku_window','kienzleconnect','assets','venv','__pycache__'}
    candidates=[p for p in support.iterdir() if p.name in fixed or re.fullmatch(
        r'kienzledoku(?:_[a-z0-9_]+)?\.py(?:\.before-read-test-\d{8})?',p.name)]
    if candidates:
        checked_directory(main)
        if not main.is_file() or not re.search(r'^VERSION\s*=\s*["\x27]\d+\.\d+(?:\.\d+)?["\x27]',main.read_text(),re.M):
            raise ValueError('Alte Clientdateien sind nicht eindeutig zugeordnet; Bereinigung abgebrochen.')
        if not (support/'kienzledoku_config.py').is_file():raise ValueError('Unvollständiger alter Client; keine Löschfreigabe.')
    for path in candidates:checked_directory(path)
    return candidates


def unregister_old_app(app,runner=subprocess.run):
    """An already absent Launch Services registration needs no further removal."""
    try:
        result=runner(['/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister','-u',str(app)],
                      capture_output=True,text=True,timeout=20,env=dict(os.environ,LC_ALL='C'))
    except (OSError,subprocess.TimeoutExpired) as exc:
        raise RuntimeError('Alte App-Registrierung konnte nicht geprüft werden. Neue Programme sind bereits aktiviert; Bereinigung nicht abgeschlossen.') from exc
    if result.returncode==0:return
    # Apple LSConstants.h: -10814 == kLSApplicationNotFoundErr. Copies made
    # solely as rollback backups have often never been registered at all.
    lines=(result.stderr or '').strip().splitlines()
    if (result.returncode==1 and lines and lines[0]=='failed to scan '+str(app)+': -10814'
            and all(line.strip()=='from spotlight' for line in lines[1:])):
        return
    raise RuntimeError('Alte App-Registrierung konnte nicht entfernt werden (lsregister, Exit '+str(result.returncode)+'). Neue Programme sind bereits aktiviert; Bereinigung nicht abgeschlossen.')


def complete_update(support,home,version,reader=processes,remove=shutil.rmtree,runner=subprocess.run,preserved=None,expected_roles=()):
    support=checked_directory(support);versions=checked_directory(support/'versions');version=checked_directory(version)
    if version.parent!=versions or not owned_version(version):raise ValueError('Neue Installation ist nicht eindeutig zugeordnet.')
    preserved=preserved or {}
    references=component_versions(support,home)
    if set(expected_roles)-set(references):
        raise RuntimeError('Eine ausgewählte Komponente wurde nicht vollständig registriert.')
    for role,root in references.items():
        if root!=preserved.get(role,version):
            raise RuntimeError('Eine Komponente verweist nicht auf ihren geprüften Programmstand; Bereinigung nicht freigegeben.')
    if any(references.get(role)!=root for role,root in preserved.items()):
        raise RuntimeError('Eine nicht ausgewählte Komponente hat sich während des Updates verändert.')
    retained={version,*preserved.values()}
    obsolete=[p for p in versions.iterdir() if p not in retained]
    trims={root:unused_component_files(root,{role for role,path in references.items() if path==root})
           for root in retained}
    for path in obsolete:
        if not owned_version(path):raise ValueError('Unbekannter Eintrag im Versionsverzeichnis; keine automatische Löschfreigabe.')
    legacy=legacy_code(support)
    hotfix=support/'hotfix-backups'
    if hotfix.exists():checked_directory(hotfix)
    rows=reader()
    retired=[*obsolete,*legacy,*([hotfix] if hotfix.exists() else []),*(p for paths in trims.values() for p in paths)]
    if any(str(path) in row.command for path in retired for row in rows):
        raise RuntimeError('Ein Prozess verwendet noch alte Programmdateien. Neue Installation aktiv, Bereinigung nicht abgeschlossen.')
    # Unregister old embedded app backups before removing their trees.
    unregister=[]
    for base in [*retained,*obsolete]:
        for app in base.glob('*.app'):
            info_path=app/'Contents/Info.plist'
            if app.is_symlink() or info_path.is_symlink():raise ValueError('Unsichere alte App-Verknüpfung.')
            data=plistlib.loads(info_path.read_bytes())
            if data.get('CFBundleIdentifier') not in APP_IDS.values():raise ValueError('Fremde App in Versionsverzeichnis; Bereinigung abgebrochen.')
            unregister.append(app)
    if hotfix.exists():
        for folder in hotfix.iterdir():
            checked_directory(folder)
            if not folder.is_dir() or not re.fullmatch(r'local-network-\d+',folder.name):raise ValueError('Unbekannte alte Reparatursicherung.')
            for app in folder.iterdir():
                checked_directory(app)
                info_path=app/'Contents/Info.plist'
                checked_directory(info_path)
                info=plistlib.loads(info_path.read_bytes())
                if info.get('CFBundleIdentifier') not in APP_IDS.values():raise ValueError('Fremde App in Reparatursicherung.')
                unregister.append(app)
    for app in unregister:
        unregister_old_app(app,runner)
    for path in obsolete:
        if any(str(path)+'/' in p.command for p in reader()):raise RuntimeError('Alte Version wird wieder verwendet; Bereinigung abgebrochen.')
        remove(path)
    for path in legacy:
        if any(str(path) in row.command for row in reader()):raise RuntimeError('Alter Client wird wieder verwendet; Bereinigung abgebrochen.')
        if path.is_dir():remove(path)
        else:path.unlink()
    if hotfix.exists():remove(hotfix)
    for root,paths in trims.items():
        # Older installers used the main client and installer source as ownership
        # markers; record ownership before retiring those now-unneeded files.
        mark_version(root)
        for path in paths:
            if any(str(path) in row.command for row in reader()):
                raise RuntimeError('Eine zu ersetzende Programmdatei wird noch verwendet; Bereinigung angehalten.')
            if path.is_dir():remove(path)
            else:path.unlink()
        folder=root/'installer'
        if folder.exists() and not any(folder.iterdir()):folder.rmdir()
    for path in (version/'commander-candidate.toml',):path.unlink(missing_ok=True)
    # Own runtime archives are reproducible; all downloaded models are outside.
    downloads=support/'downloads'
    if downloads.exists():
        checked_directory(downloads)
        for name in ('python.tar.gz','llama.tar.gz','python.tar.gz.part','llama.tar.gz.part'):
            path=downloads/name
            if path.is_symlink():raise ValueError('Unsicheres Downloadarchiv.')
            path.unlink(missing_ok=True)
        if not any(downloads.iterdir()):downloads.rmdir()
    unpacked=version/'llama-unpack'
    if unpacked.exists():checked_directory(unpacked);remove(unpacked)
    if set(versions.iterdir())!=retained:raise RuntimeError('Unbenutzte Programmverzeichnisse sind noch vorhanden; Update nicht abgeschlossen.')
    return len(obsolete)
