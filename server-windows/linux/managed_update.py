"""Replace owned code trees; retire backups only after a verified healthy start."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

MANIFEST = '.kienzledoku-payload.json'
ALLOWED = {'runtime': 'serial_server.py', 'installer': 'install_server.py'}

def checked(path):
    path = Path(path).absolute()
    for item in (path, *path.parents):
        if item in (Path('/tmp'), Path('/var')): continue
        if item.is_symlink(): raise ValueError('Verknüpfter Installationspfad; nichts bereinigt.')
    return path

def inventory(root):
    files = {}
    for p in root.rglob('*'):
        relative = p.relative_to(root)
        if '__pycache__' in relative.parts or p.suffix == '.pyc' or p.name in (MANIFEST, '.DS_Store'): continue
        if p.is_symlink(): raise ValueError('Unerwartete Verknüpfung in Programmnutzlast.')
        if p.is_file(): files[relative.as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return files

def verify(target):
    target = checked(target)
    meta = target / MANIFEST
    if meta.is_symlink(): raise ValueError('Unsicherer Programmnachweis.')
    if json.loads(meta.read_text()) != inventory(target):
        raise ValueError('Programmdateien entsprechen nicht der neuen Nutzlast; Update unvollständig.')

def replace_tree(source, target, marker):
    source, target = checked(source), checked(target)
    if ALLOWED.get(target.name) != marker: raise ValueError('Unbekannte Kienzledoku-Komponente.')
    if source == target: verify(target); return
    if not (source / marker).is_file(): raise ValueError('Neue Programmnutzlast unvollständig.')
    if target.exists() and not (target / marker).is_file():
        raise ValueError('Vorhandenes Verzeichnis ist keine bekannte Kienzledoku-Komponente.')
    inventory(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    backups = checked(target.parent / '.update-backups')
    backups.mkdir(exist_ok=True, mode=0o700)
    work = Path(tempfile.mkdtemp(prefix=target.name + '-', dir=backups))
    promoted = False
    try:
        (work / 'transaction.json').write_text(json.dumps({'schema': 1, 'target': target.name, 'marker': marker}))
        shutil.copytree(source, work / 'candidate', ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.DS_Store'))
        (work / 'candidate' / MANIFEST).write_text(json.dumps(inventory(work / 'candidate'), sort_keys=True))
        verify(work / 'candidate')
        if target.exists(): target.rename(work / 'previous')
        try: (work / 'candidate').rename(target)
        except Exception:
            if (work / 'previous').exists(): (work / 'previous').rename(target)
            raise
        promoted = True
    finally:
        # A failed restoration must never delete the only remaining old tree.
        # Keep the transaction visible for diagnosis/recovery in that case.
        if not promoted and not (work / 'previous').exists(): shutil.rmtree(work)

def finalize(base):
    """Run only after readiness; failed or unknown transactions remain visible."""
    base = checked(base)
    backups = checked(base / '.update-backups')
    if not backups.exists(): return
    pending = list(backups.iterdir())
    for folder in pending:
        checked(folder)
        if not folder.is_dir(): raise ValueError('Unbekannte Updatesicherung.')
        meta = folder / 'transaction.json'
        if meta.is_symlink(): raise ValueError('Unsichere Updatesicherung.')
        data = json.loads(meta.read_text())
        target, marker = data.get('target'), data.get('marker')
        if data.get('schema') != 1 or ALLOWED.get(target) != marker: raise ValueError('Unbekannte Updatesicherung.')
        if not (base / target / marker).is_file(): raise ValueError('Aktive Installation unvollständig.')
        verify(base / target)
        if (folder / 'candidate').exists(): raise ValueError('Nicht aktivierter Updatekandidat vorhanden.')
        if set(p.name for p in folder.iterdir()) - {'transaction.json', 'previous'}:
            raise ValueError('Unbekannter Inhalt einer Updatesicherung.')
    for folder in pending: shutil.rmtree(folder)
    backups.rmdir()

if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('source', type=Path); p.add_argument('target', type=Path); p.add_argument('marker')
    a = p.parse_args(); replace_tree(a.source, a.target, a.marker)
