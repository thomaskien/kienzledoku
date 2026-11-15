import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

from installer.product_key_build import ProductKeyBuild, read_key
from kienzledoku_product_key import embedded_api_key
from kienzledoku_speech import SpeechRecognitionManager

ROOT = Path(__file__).resolve().parents[1]


class Release144Tests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'darwin', 'macOS compiled key')
    def test_compiled_key_roundtrip_no_plaintext_and_private_cleanup(self):
        synthetic = b'synthetic-144-manufacturer-key-ONLY-FOR-TESTS'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            keyfile = root/'input'; keyfile.write_bytes(synthetic+b'\n')
            with ProductKeyBuild(keyfile, ROOT) as private:
                private_dir = private.path
                self.assertEqual(0o700, private_dir.stat().st_mode & 0o777)
                self.assertEqual(0o600, private.c_source.stat().st_mode & 0o777)
                lib = root/'libkienzledoku_product.dylib'
                private.run(['/usr/bin/clang','-dynamiclib','-O2',private.c_source,'-o',lib])
                private.check_file(lib)
                (root/'release.json').write_text('{"manufacturer_key":"production"}')
                self.assertEqual(synthetic.decode(), embedded_api_key(root)[0])
                leaked = root/'leaked'; leaked.write_bytes(b'prefix'+synthetic+b'suffix')
                with self.assertRaisesRegex(RuntimeError, 'Klartext'):
                    private.check_file(leaked)
                # Compile the exact generated Go decoder independently, with a
                # synthetic equality check only; no key-printing command exists.
                (private.path/'verify.go').write_text('package main\nfunc main() { if embeddedAPIKey() != '+json.dumps(synthetic.decode())+' { panic("key mismatch") } }')
                private.run(['/usr/local/bin/go','run',private.path/'api_key.go',private.path/'verify.go'],env=dict(os.environ,GOCACHE='/private/tmp/kienzledoku-go-test-cache'))
            self.assertFalse(private_dir.exists())

    def test_product_build_cannot_silently_fall_back_to_demo(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertIsNone(embedded_api_key(root))
            (root/'release.json').write_text('{"manufacturer_key":"production"}')
            with self.assertRaisesRegex(RuntimeError, 'Hersteller-Key'):
                embedded_api_key(root)

    def test_invalid_key_error_does_not_include_input(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'key'
            path.write_text('synthetic secret with whitespace')
            with self.assertRaises(ValueError) as caught:
                read_key(path)
            self.assertNotIn('synthetic', str(caught.exception))

    def test_background_status_refresh_preserves_badges_and_throttles_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = SpeechRecognitionManager(directory)
            manager.commander = mock.Mock()
            manager.active_prompt = 'synthetic'
            entered, release = threading.Event(), threading.Event()
            def status():
                entered.set(); release.wait(3)
                return {'asr':{'state':'loading','message':'Whisper lädt'},
                        'diar':{'state':'standby','message':''},
                        'llm':{'state':'standby','message':''}}
            manager.commander.runtime_status.side_effect = status
            for item in manager.services.values(): item['status'] = 'ready'
            manager.start_service_check(background=True)
            try:
                self.assertTrue(entered.wait(2))
                self.assertEqual('ready',manager.snapshot()['services']['asr']['status'])
                manager.start_service_check(background=True)
            finally:
                release.set(); manager.health_thread.join(3)
            manager.start_service_check(background=True)
            self.assertEqual(1, manager.commander.runtime_status.call_count)
            self.assertEqual('loading', manager.snapshot()['services']['asr']['status'])
            self.assertEqual('standby', manager.snapshot()['services']['llm']['status'])
            manager.commander.profiles.assert_not_called()


if __name__ == '__main__': unittest.main()
