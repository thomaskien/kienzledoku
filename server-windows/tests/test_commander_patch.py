import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

if sys.version_info < (3, 12):
    raise unittest.SkipTest("Der optionale Linux-Commander benötigt Python 3.12+.")

from kienzledoku_commander import patch_workers as p

WHISPER = b'''"""Synthetic fixture"""
from __future__ import annotations
from contextlib import asynccontextmanager
@asynccontextmanager
async def lifespan(app):
    global transcription_engine
    transcription_engine = TranscriptionEngine()
    app.state.final_asr_lock = Lock()
    yield
app = FastAPI(lifespan=lifespan)
'''
DIAR = b'''pipeline = Pipeline()
pipeline_lock = Lock()
class Handler:
    def do_POST(self): pass
if __name__ == '__main__':
    httpd = Server(Handler)
    httpd.serve_forever()
'''


class PatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.paths = {r: root / (r + ".py") for r in ("whisper", "diar")}
        for r, text in (("whisper", WHISPER), ("diar", DIAR)):self.paths[r].write_bytes(text)
        self.hashes = {r: hashlib.sha256(path.read_bytes()).hexdigest() for r, path in self.paths.items()}
        self.backup = root / "backup"

    def test_known_files_patch_idempotently_and_rollback_exactly(self):
        self.assertIn("geprüft", p.apply(self.paths, self.backup, self.hashes, check=True))
        self.assertFalse(self.backup.exists())
        p.apply(self.paths, self.backup, self.hashes)
        self.assertIn("finally:", self.paths["whisper"].read_text())
        self.assertIn("start_diar_control(globals())", self.paths["diar"].read_text())
        self.assertEqual("bereits installiert", p.apply(self.paths, self.backup, self.hashes))
        p.rollback(self.backup)
        self.assertEqual(WHISPER, self.paths["whisper"].read_bytes())
        self.assertEqual(DIAR, self.paths["diar"].read_bytes())

    def test_one_unknown_file_prevents_both_mutations(self):
        self.paths["diar"].write_bytes(DIAR + b"# unknown\n")
        with self.assertRaises(ValueError):p.apply(self.paths, self.backup, self.hashes)
        self.assertEqual(WHISPER, self.paths["whisper"].read_bytes())
        self.assertFalse(self.backup.exists())

    def test_write_failure_rolls_back_already_patched_file(self):
        real = p.atomic_write
        failed = False
        def writing(path, data, metadata):
            nonlocal failed
            if path == self.paths["diar"] and b"start_diar_control" in data and not failed:
                failed = True
                raise OSError("synthetic write failure")
            return real(path, data, metadata)
        with patch.object(p, "atomic_write", side_effect=writing), self.assertRaises(OSError):
            p.apply(self.paths, self.backup, self.hashes)
        self.assertEqual(WHISPER, self.paths["whisper"].read_bytes())
        self.assertEqual(DIAR, self.paths["diar"].read_bytes())

    def test_rollback_refuses_later_manual_changes_before_any_write(self):
        p.apply(self.paths, self.backup, self.hashes)
        before = self.paths["whisper"].read_bytes()
        self.paths["diar"].write_bytes(b"new manual version\n")
        with self.assertRaises(ValueError):p.rollback(self.backup)
        self.assertEqual(before, self.paths["whisper"].read_bytes())
