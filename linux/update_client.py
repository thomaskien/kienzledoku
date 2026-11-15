"""Run the Linux client installer in a fresh tree under an exclusive update lease."""
from contextlib import ExitStack
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kienzledoku_update import Lease


def checked(path):
    path=Path(path).absolute()
    for item in (path,*path.parents):
        if item in (Path('/tmp'),Path('/var')):continue
        if item.is_symlink():raise ValueError('Verknüpftes Installationsverzeichnis; Update abgebrochen.')
    return path


def require_closed(data):
    for entry in Path('/proc').glob('[0-9]*/cmdline'):
        if int(entry.parent.name)==os.getpid():continue
        try:
            args=entry.read_bytes().split(b'\0')
            if any(arg.startswith(os.fsencode(data)+b'/') for arg in args):
                raise ValueError('Bitte alle Kienzledoku-Aufnahme- und Einstellungsfenster schließen. Es wird nichts verworfen.')
        except (FileNotFoundError,ProcessLookupError,PermissionError):continue


def backups(data):
    found=[]
    for folder in data.parent.glob('.kienzledoku-client-update-*'):
        checked(folder)
        meta=folder/'transaction.json'
        if meta.is_symlink():raise ValueError('Unsichere Updatesicherung.')
        info=json.loads(meta.read_text())
        if info!={'schema':1,'target':str(data)}:raise ValueError('Unbekannte Updatesicherung; nichts gelöscht.')
        if set(p.name for p in folder.iterdir())-{'transaction.json','previous'}:raise ValueError('Unbekannter Inhalt einer Updatesicherung.')
        if (folder/'previous').is_symlink():raise ValueError('Unsichere Updatesicherung.')
        found.append(folder)
    return found


def install(data,config,command,runner=subprocess.run,closed=require_closed):
    data,config=checked(data),checked(config)
    if data==config or data in config.parents or config in data.parents:
        raise ValueError('Programmdateien und Einstellungen benötigen getrennte Verzeichnisse.')
    if data.exists() and any(data.iterdir()) and not (data/'kienzledoku.py').is_file():
        raise ValueError('Ziel enthält keine bekannte Kienzledoku-Installation.')
    config.mkdir(parents=True,exist_ok=True,mode=0o700)
    data.parent.mkdir(parents=True,exist_ok=True)
    with ExitStack() as stack:
        stack.enter_context(Lease(config/'update.lock',exclusive=True))
        for lock in (config/'sessions').glob('*/record.lock'):
            checked(lock)
            handle=stack.enter_context(lock.open('rb'))
            try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise ValueError('Eine Aufnahme ist geöffnet; Update abgebrochen.') from None
        closed(data)
        previous=backups(data)
        work=Path(tempfile.mkdtemp(prefix='.kienzledoku-client-update-',dir=data.parent))
        (work/'transaction.json').write_text(json.dumps({'schema':1,'target':str(data)}))
        if data.exists():data.rename(work/'previous')
        try:
            env=dict(os.environ,KIENZLEDOKU_UPDATE_CHILD=str(os.getpid()),KIENZLEDOKU_INSTALL_NONINTERACTIVE='1')
            runner(command,check=True,env=env)
            if not (data/'kienzledoku.py').is_file():raise ValueError('Neuer Client fehlt nach Installation.')
            closed(data)
        except Exception:
            if data.exists():shutil.rmtree(checked(data))
            if (work/'previous').exists():(work/'previous').rename(data)
            shutil.rmtree(work)
            raise
        # An unsuccessful cleanup must propagate, keeping the new checked client
        # active rather than rolling back to a partially deleted backup.
        for folder in [*previous,work]:shutil.rmtree(folder)


if __name__=='__main__':
    try:install(Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3:])
    except Exception as exc:
        print('Client-Update nicht abgeschlossen: '+str(exc),file=sys.stderr);sys.exit(1)
