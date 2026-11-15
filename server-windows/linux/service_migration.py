"""Retire only the recognized configuration of the former standalone Commander."""
from pathlib import Path
import json
import re
import shutil
import tempfile


def migrate_legacy_commander(state, systemd=Path('/etc/systemd/system'),
                             tmpfiles=Path('/etc/tmpfiles.d')):
    """Caller holds the installation lock and has stopped its own services."""
    plans=[]

    def read(path):
        if path.is_symlink() or path.parent.is_symlink():
            raise ValueError('Verknüpfte alte Commander-Konfiguration wird nicht verändert.')
        if not path.exists():
            return None
        if not path.is_file() or path.stat().st_size>8192:
            raise ValueError('Unbekannte alte Commander-Konfiguration wird nicht verändert.')
        return path.read_bytes()

    for role,control in (('asr-backend','/run/kienzledoku-commander'),
                         ('diarization','/run/kienzledoku-commander-diar')):
        path=systemd/('kienzlefon-ai-'+role+'.service.d')/'90-kienzledoku-commander.conf'
        raw=read(path)
        if raw is None:
            continue
        rows=[line.strip() for line in raw.decode().splitlines() if line.strip()]
        required=['# kienzledoku-commander','[Service]',
                  'Environment=PYTHONPATH=/opt/kienzledoku-commander',
                  'Environment=KIENZLEDOKU_COMMANDER_CONTROL_DIR='+control]
        if (rows[:4]!=required or len(rows)>5 or
                len(rows)==5 and (role!='diarization' or not re.fullmatch(
                    r'Environment=KIENZLEDOKU_COMMANDER_CONTROL_GROUP=[A-Za-z0-9_.-]+',rows[4]))):
            raise ValueError('Unbekanntes Commander-Override bleibt erhalten; Migration abgebrochen.')
        plans.append((path,raw))
    path=tmpfiles/'kienzledoku-commander.conf'
    raw=read(path)
    if raw is not None:
        rows=[line.split() for line in raw.decode().splitlines() if line.strip()]
        expected={'/run/kienzledoku-commander':'0700','/run/kienzledoku-commander-diar':None}
        if (len(rows)!=2 or {r[1] for r in rows if len(r)==6}!=set(expected) or
                any(len(r)!=6 or r[0]!='d' or r[1] not in expected or r[5]!='-' or
                    r[2] not in ((expected[r[1]],) if expected[r[1]] else ('0700','0750')) or
                    any(not re.fullmatch(r'[A-Za-z0-9_.-]+',v) for v in r[3:5]) for r in rows)):
            raise ValueError('Unbekannte Commander-Verzeichnisregel bleibt erhalten; Migration abgebrochen.')
        plans.append((path,raw))
    if not plans:
        return None
    backup=Path(tempfile.mkdtemp(prefix='legacy-commander-',dir=state))
    copies=[]
    for number,(path,raw) in enumerate(plans):
        destination=backup/(str(number)+'-'+path.name)
        shutil.copy2(path,destination)
        if destination.read_bytes()!=raw or path.read_bytes()!=raw:
            raise ValueError('Commander-Konfiguration wurde während der Sicherung verändert.')
        copies.append((path,destination))
    (backup/'manifest.json').write_text(json.dumps({str(path):destination.name for path,destination in copies},indent=2)+'\n')
    removed=[]
    try:
        for path,destination in copies:
            if path.is_symlink() or path.read_bytes()!=destination.read_bytes():
                raise ValueError('Commander-Konfiguration wurde zwischenzeitlich verändert.')
            path.unlink();removed.append((path,destination))
    except Exception:
        for path,destination in removed:
            if not path.exists():shutil.copy2(destination,path)
        raise
    return backup
