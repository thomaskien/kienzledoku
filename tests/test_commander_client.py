import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import kienzledoku_commander_client as commander
import kienzledoku_config as config


DOC = {'anamnese': 'Synthetisch', 'befund': '', 'therapie': '', 'prozedere': ''}


class Response:
    def __init__(self, value):
        self.raw = json.dumps(value).encode('utf-8')
        self.status = 200
    def __enter__(self): return self
    def __exit__(self, *_args): return False
    def read(self, _limit=None): return self.raw


class CommanderClientTests(unittest.TestCase):
    def setUp(self):
        self.profiles = [
            {'id': 'gemma12_q8', 'label': 'Gemma 4 12B Q8_0', 'persistent': True,
             'fallback': 'basis', 'default': True},
            {'id': 'basis', 'label': 'Basis', 'persistent': False,
             'fallback': None, 'default': False},
        ]
        self.requests = []

    def opener(self, request, _timeout):
        self.requests.append(request)
        if request.full_url.endswith('/v1/runtime/profiles'):
            return Response({'object': 'list', 'data': self.profiles})
        payload = json.loads(request.data)
        return Response({'documentation': DOC, 'commander': {
            'requested_quality': payload.get('quality', 'gemma12_q8'),
            'used_quality': 'basis', 'fallback_used': True,
        }})

    def test_dynamic_windows_profiles_and_declared_fallback(self):
        client = commander.CommanderClient('http://127.0.0.1:8185')
        with mock.patch.object(commander, 'direct_open', self.opener):
            profiles = client.profiles()
            document, metadata = client.extract(
                'synthetic', 'gemma12_q8', profiles, recording_finalized=True)
        self.assertEqual(DOC, document)
        self.assertEqual('Gemma 4 12B Q8_0', profiles[0]['label'])
        self.assertEqual('basis', metadata['used_quality'])
        self.assertIn('Gemma 4 12B Q8_0', metadata['notice'])
        self.assertNotIn('Authorization', dict(self.requests[0].headers))

    def test_rejects_undeclared_fallback_and_invalid_profile_metadata(self):
        client = commander.CommanderClient('http://127.0.0.1:8185')
        bad = [dict(self.profiles[0], fallback=None), self.profiles[1]]
        with mock.patch.object(commander, 'direct_open', self.opener):
            with self.assertRaisesRegex(ValueError, 'vollständig beendet'):
                client.extract('synthetic', 'gemma12_q8', bad)
            with self.assertRaisesRegex(RuntimeError, 'gültiger Qualitätsangabe'):
                client.extract('synthetic', 'gemma12_q8', bad, recording_finalized=True)
        self.profiles[0]['persistent'] = 'yes'
        with mock.patch.object(commander, 'direct_open', self.opener), \
             self.assertRaisesRegex(RuntimeError, 'Qualitätsprofile'):
            client.profiles()

    @unittest.skipIf(os.name == 'nt', 'POSIX-Dateimodi werden unter macOS/Linux geprüft.')
    def test_private_posix_token_and_windows_without_getuid(self):
        with tempfile.TemporaryDirectory() as directory:
            token = Path(directory) / 'token'
            token.write_text('synthetic-token\n', encoding='utf-8')
            token.chmod(0o600)
            client = commander.CommanderClient(
                'http://commander.invalid:8185', token_env='UNSET_COMMANDER_TEST',
                token_file=str(token))
            with mock.patch.object(commander.os, 'getuid', None):
                self.assertEqual('synthetic-token', client.token)
            token.chmod(0o644)
            with self.assertRaisesRegex(ValueError, 'privat'):
                _ = client.token

    def test_explicit_no_fallback_is_binding_even_for_legacy_quality_ids(self):
        self.profiles = [
            {'id': 'gruendlich', 'persistent': True, 'fallback': None},
            {'id': 'basis', 'persistent': False, 'fallback': None},
        ]
        client = commander.CommanderClient('http://127.0.0.1:8185')
        with mock.patch.object(commander, 'direct_open', self.opener):
            profiles = client.profiles()
            with self.assertRaisesRegex(RuntimeError, 'gültiger Qualitätsangabe'):
                client.extract('synthetic', 'gruendlich', profiles, recording_finalized=True)
            # An actually missing field retains the original compatibility rule.
            del self.profiles[0]['fallback']
            document, metadata = client.extract('synthetic', 'gruendlich',
                client.profiles(), recording_finalized=True)
            self.assertEqual(document, DOC)
            self.assertTrue(metadata['fallback_used'])

    def test_unsaved_token_override_does_not_change_existing_credentials(self):
        with mock.patch.dict(os.environ, {'TEST_COMMANDER_TOKEN': 'stored-environment-token'}):
            client = commander.CommanderClient('http://commander.invalid:8185',
                token_env='TEST_COMMANDER_TOKEN', token_file='/missing/private/token',
                token_override='new-synthetic-token')
            self.assertEqual(client.token, 'new-synthetic-token')
            self.assertEqual(os.environ['TEST_COMMANDER_TOKEN'], 'stored-environment-token')


class CommanderConfigTests(unittest.TestCase):
    @unittest.skipIf(os.name == 'nt', 'Der POSIX-Zugangsspeicher benötigt Unix-Dateimodi.')
    def test_empty_file_uses_private_store_and_fresh_loopback_needs_no_token(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
                os.environ, {'KIENZLEDOKU_CONFIG_DIR': directory}), \
                mock.patch.object(config.sys, 'platform', 'linux'):
            block = config.defaults()['commander']
            block['token_env'] = 'UNSET_COMMANDER_TEST'
            self.assertEqual(block['token_file'], '')
            self.assertEqual(commander.configured_client(block).token, '')
            config.store_commander_token('synthetic-private-token')
            block['url'] = 'http://commander.invalid:8185'
            self.assertEqual(commander.configured_client(block).token, 'synthetic-private-token')

    def test_fresh_default_and_legacy_toml_json_migration(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
                os.environ, {'KIENZLEDOKU_CONFIG_DIR': directory}):
            self.assertTrue(config.load()['commander']['enabled'])
            legacy_toml = Path(directory) / 'legacy.toml'
            legacy_toml.write_text('''
[connection]
mode="direct"
target="https://127.0.0.1:16567/aps/fhir/api/r4"
ca_file=""
allow_insecure_tls=false
[services]
asr="http://old.local:8179"
diarization="http://old.local:8183"
llm="http://old.local:8080"
[record]
diarization=true
microphone=""
output_mode="structured"
single_code="KI"
''', encoding='utf-8')
            legacy = config.load(legacy_toml)
            self.assertFalse(legacy['commander']['enabled'])
            self.assertEqual('http://old.local:8179', legacy['services']['asr'])

            legacy_json = Path(directory) / 'legacy.json'
            legacy_json.write_text(json.dumps({
                'services': {'asr': 'http://old.local:8179',
                             'diarization': 'http://old.local:8183',
                             'llm': 'http://old.local:8080'},
                'commander': {'enabled': True, 'url': 'http://cmd.local:8185',
                              'default_quality': 'gemma12_q8'},
            }), encoding='utf-8')
            migrated = config.load(legacy_json)
            self.assertTrue(migrated['commander']['enabled'])
            self.assertEqual('gemma12_q8', migrated['commander']['default_quality'])

    @unittest.skipIf(os.name == 'nt', 'Der POSIX-Zugangsspeicher benötigt Unix-Dateimodi.')
    def test_posix_token_store_is_private_and_not_in_toml(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
                os.environ, {'KIENZLEDOKU_CONFIG_DIR': directory}), \
                mock.patch.object(config.sys, 'platform', 'linux'):
            config.store_commander_token('synthetic-secret')
            path = Path(directory) / 'commander.token'
            self.assertEqual(0, path.stat().st_mode & 0o077)
            self.assertEqual('synthetic-secret', config.read_commander_token())
            config.save(config.defaults())
            self.assertNotIn('synthetic-secret', config.config_path().read_text(encoding='utf-8'))

    def test_windows_token_uses_dpapi_helper(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
                os.environ, {'KIENZLEDOKU_CONFIG_DIR': directory}), \
                mock.patch.object(config.sys, 'platform', 'win32'), \
                mock.patch.object(config, '_windows_crypt', side_effect=lambda value, protect: b'encrypted' if protect else b'synthetic') as crypt:
            config.store_commander_token('synthetic')
            self.assertEqual('synthetic', config.read_commander_token())
            self.assertEqual(2, crypt.call_count)


if __name__ == '__main__':
    unittest.main()
