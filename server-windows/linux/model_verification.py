"""Remember successful checks of unchanged files; never trust size alone."""
import hashlib
import json
from pathlib import Path
import tempfile


class VerificationCache:
    def __init__(self, path, force=False, enabled=True):
        self.enabled = enabled
        force = force and enabled
        self.path = Path(path)
        self.entries = {}
        self.hits = 0
        if not force:
            try:
                saved = json.loads(self.path.read_text())
                if saved.get('schema') == 1 and isinstance(saved.get('files'), dict):
                    self.entries = saved['files']
            except (OSError, ValueError, TypeError):
                pass
        else:
            self.save()

    @staticmethod
    def fingerprint(path):
        path = Path(path).resolve()
        stat = path.stat()
        return dict(path=str(path), bytes=stat.st_size, device=stat.st_dev,
                    inode=stat.st_ino, mtime_ns=stat.st_mtime_ns, ctime_ns=stat.st_ctime_ns)

    @staticmethod
    def checksum(entry):
        if entry.get('sha256'):
            return 'sha256', entry['sha256'].lower()
        if entry.get('git_blob_sha1'):
            return 'git-blob-sha1', entry['git_blob_sha1'].lower()
        raise ValueError('Prüfsumme fehlt.')

    def save(self):
        # A read-only cache must not make an otherwise valid installation fail.
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w', dir=self.path.parent,
                                             prefix=self.path.name+'.', delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(dict(schema=1, files=self.entries), stream)
            temporary.replace(self.path)
        except OSError:
            pass
        finally:
            if temporary is not None:
                try: temporary.unlink(missing_ok=True)
                except OSError: pass

    def remember(self, fingerprint, checksum):
        self.entries[fingerprint['path']] = dict(fingerprint=fingerprint, checksum=list(checksum))
        self.save()

    def forget(self, path):
        key = str(Path(path).resolve())
        if key in self.entries:
            del self.entries[key]
            self.save()

    def check(self, path, entry):
        path = Path(path)
        if not path.is_file():
            return False
        before = self.fingerprint(path)
        if before['bytes'] != entry['bytes']:
            return False
        if not self.enabled:
            print('Prüfsumme deaktiviert; Größe geprüft: '+str(path), flush=True)
            return True
        checksum = self.checksum(entry)
        old = self.entries.get(before['path'])
        if isinstance(old, dict) and old.get('fingerprint') == before and old.get('checksum') == list(checksum):
            self.hits += 1
            print('Bereits geprüft, unverändert: '+str(path), flush=True)
            return True
        if before['path'] in self.entries:
            del self.entries[before['path']]
            self.save()
        print('Prüfsumme: '+str(path)+' — kein passender Prüfnachweis', flush=True)
        digest = hashlib.sha256() if checksum[0] == 'sha256' else hashlib.sha1()
        if checksum[0] == 'git-blob-sha1':
            digest.update(f"blob {before['bytes']}\0".encode())
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(8*1024*1024), b''):
                digest.update(block)
        if digest.hexdigest() != checksum[1] or self.fingerprint(path) != before:
            return False
        self.remember(before, checksum)
        return True

    def commit(self, stage, target, entry):
        """Carry a proof through our atomic rename, never through a copy."""
        stage, target = Path(stage), Path(target)
        if not self.check(stage, entry):
            raise ValueError('Prüfsumme nach Kopieren falsch: '+str(stage))
        before = self.fingerprint(stage)
        stage.replace(target)
        after = self.fingerprint(target)
        if not self.enabled:
            self.forget(stage); self.forget(target)
            return
        self.entries.pop(before['path'], None)
        if all(before[k] == after[k] for k in ('device', 'inode', 'bytes', 'mtime_ns')):
            self.remember(after, self.checksum(entry))
        elif not self.check(target, entry):
            raise ValueError('Prüfsumme nach Umbenennen falsch: '+str(target))
