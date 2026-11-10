"""Capacity accounting using real tiny files and the existing proof format."""
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'linux'))
from model_verification import VerificationCache

probe_module = types.ModuleType('storage_probe')
source = ROOT/'windows/storage_probe.py'
exec(compile(source.read_text(), str(source), 'exec'), probe_module.__dict__)


class StorageProbe(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.base, self.state = self.root/'active', self.root/'state'
        self.target = self.base/'models/gemma/model.gguf'
        self.target.parent.mkdir(parents=True)
        self.entry = dict(path='gemma/model.gguf', bytes=10,
                          sha256=hashlib.sha256(b'0123456789').hexdigest())

    def saved(self):
        self.target.write_bytes(b'0123456789')
        cache = VerificationCache(self.state/'model-verifications.json')
        self.assertTrue(cache.check(self.target, self.entry))

    def probe(self, **kw):
        return probe_module.probe([self.entry], self.base, self.state, cuda=self.root/'cuda/nvcc', **kw)

    def test_cached_complete_model_needs_no_second_copy_and_no_weight_read(self):
        self.saved()
        original = Path.open
        def guarded(path, *args, **kwargs):
            if path == self.target:
                self.fail('Space estimate read model weights again')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'open', guarded):
            result = self.probe()
        self.assertEqual(0, result['AdditionalBytes'])
        self.assertEqual(10, result['ReusedBytes'])
        self.assertEqual([], result['RequiredPaths'])

    def test_same_size_without_proof_still_reserves_a_replacement(self):
        self.target.write_bytes(b'0123456789')
        self.assertEqual(10, self.probe()['AdditionalBytes'])

    def test_same_size_change_with_restored_mtime_invalidates_proof(self):
        self.saved()
        old = self.target.stat()
        self.target.write_bytes(b'other-data')
        os.utime(self.target, ns=(old.st_atime_ns, old.st_mtime_ns))
        self.assertEqual(10, self.probe()['AdditionalBytes'])
        self.assertEqual(['gemma/model.gguf'], self.probe()['RequiredPaths'])

    def test_partial_copy_only_requires_remaining_growth(self):
        stage = self.target.with_name('model.gguf.part')
        stage.write_bytes(b'0123')
        self.assertEqual(6, self.probe()['AdditionalBytes'])
        self.assertEqual(b'0123', stage.read_bytes())

    def test_corrupt_cache_is_conservative_and_force_requires_source_staging(self):
        self.saved()
        self.assertEqual(10, self.probe(force=True)['AdditionalBytes'])
        (self.state/'model-verifications.json').write_text('{invalid')
        self.assertEqual(10, self.probe()['AdditionalBytes'])

    def test_runtime_reserve_eligibility_requires_every_prepared_component(self):
        self.assertFalse(self.probe()['RuntimeReady'])
        files = [self.state/name for name in ['installed.json', 'asr-packages-1.0.json',
                 'diarization-packages-1.0.json', 'llama-build.json']]
        files += [self.root/'cuda/nvcc']
        files += [self.base/name for name in ['python/asr-venv/bin/python',
                  'python/diarization-venv/bin/python', 'bin/llama-server']]
        for path in files:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{}')
        self.assertTrue(self.probe()['RuntimeReady'])
        files[-1].unlink()
        self.assertFalse(self.probe()['RuntimeReady'])

    def test_changed_checksum_and_escaping_paths_cannot_reuse_an_existing_proof(self):
        self.saved()
        self.entry['sha256'] = '0'*64
        self.assertEqual(10, self.probe()['AdditionalBytes'])
        self.entry['path'] = '../outside.gguf'
        with self.assertRaises(ValueError): self.probe()
        self.entry['path'] = 'escape.gguf'
        (self.base/'models/escape.gguf').symlink_to(self.root/'outside.gguf')
        with self.assertRaises(ValueError): self.probe()


if __name__ == '__main__':
    unittest.main()
