import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'linux'))
from model_verification import VerificationCache
import install_server


class ModelVerification(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root/'model.gguf'
        self.path.write_bytes(b'hello')
        self.entry = dict(bytes=5, sha256=hashlib.sha256(b'hello').hexdigest())
        self.cache_path = self.root/'cache.json'
        self.cache = VerificationCache(self.cache_path)

    def test_persisted_proof_avoids_reading_model_content(self):
        self.assertTrue(self.cache.check(self.path, self.entry))
        cache = VerificationCache(self.cache_path)
        with patch('model_verification.hashlib.sha256', side_effect=AssertionError('File rehashed')):
            self.assertTrue(cache.check(self.path, self.entry))

    def test_same_size_change_with_restored_mtime_still_invalidates_ctime(self):
        self.assertTrue(self.cache.check(self.path, self.entry))
        previous = self.path.stat()
        self.path.write_bytes(b'other')
        os.utime(self.path, ns=(previous.st_atime_ns, previous.st_mtime_ns))
        self.assertFalse(self.cache.check(self.path, self.entry))
        self.assertFalse(VerificationCache(self.cache_path).check(self.path, self.entry))

    def test_changed_expected_hash_and_replacement_inode_invalidate_proof(self):
        self.assertTrue(self.cache.check(self.path, self.entry))
        self.assertFalse(self.cache.check(self.path, dict(bytes=5, sha256='0'*64)))
        self.assertTrue(self.cache.check(self.path, self.entry))
        old = self.path.stat()
        replacement = self.root/'replacement'
        replacement.write_bytes(b'other')
        os.utime(replacement, ns=(old.st_atime_ns, old.st_mtime_ns))
        replacement.replace(self.path)
        self.assertFalse(self.cache.check(self.path, self.entry))

    def test_copy_has_own_verification_but_rename_does_not_rehash(self):
        self.assertTrue(self.cache.check(self.path, self.entry))
        stage = self.root/'new.part'
        stage.write_bytes(b'hello')
        self.assertTrue(self.cache.check(stage, self.entry))
        target = self.root/'new.gguf'
        with patch('model_verification.hashlib.sha256', side_effect=AssertionError('File rehashed')):
            self.cache.commit(stage, target, self.entry)
            self.assertTrue(VerificationCache(self.cache_path).check(target, self.entry))

    def test_forced_recheck_and_corrupt_cache_do_not_accept_stale_proof(self):
        self.assertTrue(self.cache.check(self.path, self.entry))
        forced = VerificationCache(self.cache_path, force=True)
        self.assertEqual({}, json.loads(self.cache_path.read_text())['files'])
        self.assertTrue(forced.check(self.path, self.entry))
        self.cache_path.write_text('{invalid')
        self.assertTrue(VerificationCache(self.cache_path).check(self.path, self.entry))

    def test_partial_and_bad_git_blob_never_get_success_proofs(self):
        self.assertFalse(self.cache.check(self.path, dict(bytes=8, sha256='0'*64)))
        blob = dict(bytes=5, git_blob_sha1=hashlib.sha1(b'blob 5\0hello').hexdigest())
        self.assertTrue(self.cache.check(self.path, blob))
        self.assertFalse(self.cache.check(self.path, dict(bytes=5, git_blob_sha1='0'*40)))

    def test_install_failure_records_step_command_exception_and_traceback(self):
        with patch.object(install_server, 'STATE', self.root), \
             patch.object(install_server, 'CURRENT_STEP', 'llama.cpp kompilieren'), \
             patch.object(install_server, 'CURRENT_COMMAND', ['git', 'checkout', 'FETCH_HEAD']), \
             contextlib.redirect_stderr(io.StringIO()):
            try:
                raise subprocess.CalledProcessError(17, ['git', 'checkout', 'FETCH_HEAD'])
            except Exception as error:
                install_server.report_failure(error)
        detail = json.loads((self.root/'installation-error.json').read_text())
        self.assertIn('llama.cpp', detail['step'])
        self.assertEqual('git', detail['command'][0])
        self.assertIn('CalledProcessError', detail['traceback'])

    def test_repair_reuses_imported_model_after_installer_ownership_change(self):
        source = self.root/'source'; source.mkdir()
        (source/'small.gguf').write_bytes(b'hello')
        base = self.root/'active'
        manifest = self.root/'manifest'; manifest.mkdir()
        (manifest/'audio-files.json').write_text('[]')
        entry = dict(self.entry, path='small.gguf')
        def chown(argv):
            self.assertIn('--from=root', argv)
            (base/'models/small.gguf').chmod(0o644)
        with patch.object(install_server, 'BASE', base), patch.object(install_server, 'ROOT', manifest), \
             patch.object(install_server, 'VERIFICATIONS', self.cache), \
             patch.object(install_server, 'catalog', return_value={'tiny': {'files': [entry]}}), \
             patch.object(install_server, 'run', side_effect=chown):
            cfg = dict(Models=['tiny'], LinuxModelSource=str(source))
            install_server.import_models(cfg)
            self.assertEqual(b'hello', (base/'models/small.gguf').read_bytes())
            with patch('model_verification.hashlib.sha256', side_effect=AssertionError('Repair rehashed model')):
                install_server.import_models(cfg)


if __name__ == '__main__':
    unittest.main()
