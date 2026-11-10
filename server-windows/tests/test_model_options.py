import hashlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'linux'))
from model_verification import VerificationCache
import install_server
probe_module=types.ModuleType('model_probe')
source=ROOT/'windows/storage_probe.py'
exec(compile(source.read_text(),str(source),'exec'),probe_module.__dict__)


class ModelOptions(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.base=self.root/'active';self.state=self.root/'state'
        self.models=self.base/'models';self.models.mkdir(parents=True)
        self.path=self.models/'small.gguf';self.path.write_bytes(b'hello')
        self.entry=dict(path='small.gguf',bytes=5,sha256=hashlib.sha256(b'hello').hexdigest())
        self.cache_path=self.state/'model-verifications.json'

    def probe(self,**kwargs):
        return probe_module.probe([self.entry],self.base,self.state,**kwargs)

    def test_disabled_checks_accept_size_only_without_model_reads_or_success_proofs(self):
        self.path.write_bytes(b'other')
        cache=VerificationCache(self.cache_path,enabled=False,force=True)
        with patch('model_verification.hashlib.sha256',side_effect=AssertionError('Hash disabled')):
            self.assertTrue(cache.check(self.path,self.entry))
            self.assertEqual([],self.probe(verify_models=False,validate=True)['RequiredPaths'])
        self.assertEqual({},cache.entries)
        self.assertFalse(self.cache_path.exists())

    def test_disabled_checks_still_reject_missing_and_truncated_files(self):
        cache=VerificationCache(self.cache_path,enabled=False)
        self.path.write_bytes(b'hi');self.assertFalse(cache.check(self.path,self.entry))
        self.path.unlink();self.assertFalse(cache.check(self.path,self.entry))
        self.assertEqual(['small.gguf'],self.probe(verify_models=False)['RequiredPaths'])

    def test_reenabling_after_unchecked_copy_requires_a_real_checksum(self):
        cache=VerificationCache(self.cache_path)
        self.assertTrue(cache.check(self.path,self.entry))
        stage=self.models/'other.part';stage.write_bytes(b'other')
        unchecked=VerificationCache(self.cache_path,enabled=False)
        unchecked.commit(stage,self.path,self.entry)
        self.assertNotIn(str(self.path),unchecked.entries)
        self.assertFalse(VerificationCache(self.cache_path).check(self.path,self.entry))

    def test_wsl_preflight_verifies_existing_model_once_and_shares_real_proof_with_import(self):
        with patch.object(probe_module.hashlib,'sha256',wraps=hashlib.sha256) as digest:
            report=self.probe(validate=True)
            self.assertEqual([],report['RequiredPaths']);self.assertEqual(1,digest.call_count)
            self.assertTrue(VerificationCache(self.cache_path).check(self.path,self.entry))
            self.assertEqual(1,digest.call_count)

    def test_read_only_capacity_probe_never_hashes_and_forced_validation_reuses_fresh_proof(self):
        with patch.object(probe_module.hashlib,'sha256',side_effect=AssertionError('Capacity must not hash')):
            self.assertEqual(['small.gguf'],self.probe()['RequiredPaths'])
        self.assertEqual([],self.probe(validate=True,force=True)['RequiredPaths'])
        with patch.object(probe_module.hashlib,'sha256',side_effect=AssertionError('Unnecessary second hash')):
            self.assertEqual([],self.probe(validate=True)['RequiredPaths'])

    def test_bad_wsl_content_is_not_reused_when_checks_are_enabled(self):
        self.path.write_bytes(b'other')
        self.assertEqual(['small.gguf'],self.probe(validate=True)['RequiredPaths'])
        self.assertNotIn(str(self.path),json.loads(self.cache_path.read_text())['files'])

    def import_fixture(self,enabled,content=b'hello'):
        self.path.unlink(missing_ok=True)
        origin=self.root/'local-source.gguf';origin.write_bytes(content)
        manifest=self.root/'manifest';manifest.mkdir()
        (manifest/'audio-files.json').write_text('[]')
        cfg=dict(Models=['small'],LinuxModelSource='/unavailable-store',
                 LinuxModelSources={'small.gguf':str(origin)},ModelImportId='synthetic-run',VerifyModelFiles=enabled)
        cache=VerificationCache(self.cache_path,enabled=enabled)
        return origin,manifest,cfg,cache

    def run_import(self,manifest,cfg,cache):
        with patch.object(install_server,'ROOT',manifest),patch.object(install_server,'BASE',self.base), \
             patch.object(install_server,'STATE',self.state),patch.object(install_server,'VERIFICATIONS',cache), \
             patch.object(install_server,'catalog',return_value={'small':{'files':[self.entry]}}), \
             patch.object(install_server,'run'):
            install_server.import_models(cfg)

    def test_per_file_local_source_is_used_without_store_and_receipt_records_actual_mode(self):
        origin,manifest,cfg,cache=self.import_fixture(False,content=b'other')
        with patch('model_verification.hashlib.sha256',side_effect=AssertionError('Hash disabled')):
            self.run_import(manifest,cfg,cache)
        self.assertEqual(b'other',self.path.read_bytes())
        receipt=json.loads((self.state/'model-import.json').read_text())
        self.assertEqual('synthetic-run',receipt['run_id'])
        self.assertFalse(receipt['verify_model_files'])
        self.assertEqual({},cache.entries)

    def test_enabled_import_checks_new_destination_and_never_promotes_corrupt_source(self):
        _,manifest,cfg,cache=self.import_fixture(True,content=b'other')
        with self.assertRaises(ValueError):self.run_import(manifest,cfg,cache)
        self.assertFalse(self.path.exists())
        self.assertFalse((self.state/'model-import.json').exists())

    def test_enabled_import_avoids_redundant_source_hash_before_verified_destination_copy(self):
        origin,manifest,cfg,cache=self.import_fixture(True)
        original=Path.open
        def guarded(path,*a,**kw):
            if path==origin:self.fail('Source rehashed instead of checking copied destination')
            return original(path,*a,**kw)
        with patch.object(Path,'open',guarded):self.run_import(manifest,cfg,cache)
        self.assertTrue(cache.check(self.path,self.entry))
        self.assertTrue(json.loads((self.state/'model-import.json').read_text())['verify_model_files'])


if __name__=='__main__':unittest.main()
