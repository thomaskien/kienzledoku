"""Connect for fresh clients; persisted direct/Connect settings survive updates."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import kienzledoku_config as client
from installer import core, linux_cli, windows_core

MAC = dict(platform='darwin', arch='arm64', ram_gib=32, free_gib=100,
           server_supported=True)
WIN = windows_core.hardware(dict(hardware=dict(Build=26100, Architecture='AMD64',
                                               RamBytes=32 * 2**30), previous={}))


class ConnectDefaultsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        env = patch.dict(os.environ, KIENZLEDOKU_CONFIG_DIR=str(self.base),
                         LOCALAPPDATA=str(self.base / 'local'),
                         HF_HOME=str(self.base / 'hf'), HF_TOKEN='',
                         HUGGING_FACE_HUB_TOKEN='', KIENZLEDOKU_COMMANDER_TOKEN='')
        env.start(); self.addCleanup(env.stop)
        for target, value in ((client, 'read_commander_token'), (core, 'huggingface_token')):
            guard = patch.object(target, value, return_value='')
            guard.start(); self.addCleanup(guard.stop)

    def selections(self):
        mac = core.defaults(MAC, self.base)['connection_mode']
        windows = windows_core.defaults(WIN, self.base)['connection_mode']
        with patch('builtins.input', return_value=''), \
             patch.object(linux_cli.getpass, 'getpass', return_value=''):
            linux, _ = linux_cli.configure_client(False, '')
        return {'macOS': mac, 'Windows': windows,
                'Linux': linux['connection']['mode']}

    def test_fresh_installers_all_offer_connect(self):
        self.assertEqual(self.selections(), dict(macOS='connect', Windows='connect', Linux='connect'))
        self.assertFalse(client.config_path().exists())

    def test_existing_modes_and_other_settings_survive_all_installer_defaults(self):
        for mode in ('direct', 'connect'):
            with self.subTest(mode=mode):
                cfg = client.defaults()
                cfg['connection'].update(mode=mode, target='https://t2med.example:16567/aps/fhir/api/r4',
                                         allow_insecure_tls=True)
                cfg['commander']['url'] = 'http://commander.example:8185'
                cfg['record'].update(vad_enabled=False, silence_threshold_dbfs=-43)
                client.save(cfg)
                before = client.config_path().read_bytes()
                self.assertEqual(self.selections(), dict(macOS=mode, Windows=mode, Linux=mode))
                self.assertEqual(client.load(), cfg)
                self.assertEqual(client.config_path().read_bytes(), before)

    def test_missing_mode_in_existing_toml_keeps_legacy_direct(self):
        client.config_path().write_text('[connection]\ntarget = "https://t2med.example:16567/aps/fhir/api/r4"\n')
        self.assertEqual(self.selections(), dict(macOS='direct', Windows='direct', Linux='direct'))

    def test_legacy_json_migration_keeps_direct(self):
        path = client.config_path().with_suffix('.json')
        path.write_text(json.dumps({'t2med': {'fhir_host': 't2med.example'}}))
        self.assertEqual(client.load()['connection']['mode'], 'direct')
        self.assertEqual(client.load()['connection']['target'], 'https://t2med.example:16567/aps/fhir/api/r4')

    def test_mac_saved_installer_choice_survives_without_client_config(self):
        for mode in ('direct', 'connect'):
            (self.base / 'installer.json').write_text(json.dumps({'connection_mode': mode}))
            self.assertEqual(core.defaults(MAC, self.base)['connection_mode'], mode)

    def test_windows_apply_preserves_both_existing_modes_and_record_controls(self):
        spec = importlib.util.spec_from_file_location('connect_test_apply',
            Path(__file__).resolve().parents[1] / 'windows/installer_client.py')
        apply = importlib.util.module_from_spec(spec); spec.loader.exec_module(apply)
        for mode in ('direct', 'connect'):
            cfg = client.defaults(); cfg['connection']['mode'] = mode
            cfg['record'].update(vad_enabled=False, silence_threshold_dbfs=-43)
            client.save(cfg)
            selected = windows_core.defaults(WIN, self.base)
            request = self.base / 'wizard.json'; request.write_text(json.dumps(selected))
            with patch.object(sys, 'argv', ['installer_client', '--wizard-config', str(request)]):
                apply.main()
            self.assertEqual(client.load(), cfg)


if __name__ == '__main__':
    unittest.main()
