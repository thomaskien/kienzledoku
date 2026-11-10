"""Synthetic HTTP regression for checking and saving Commander credentials."""
import http.client
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest import mock
import urllib.parse

import kienzledoku_config as config
import kienzledoku_settings as settings


class CommanderSettingsTests(unittest.TestCase):
    def test_check_is_temporary_and_save_replaces_the_selected_credential_store(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
                os.environ, {'KIENZLEDOKU_CONFIG_DIR': directory}):
            initial = config.defaults()
            initial['commander']['token_env'] = 'UNSET_COMMANDER_SETTINGS_TEST'
            old_file = Path(directory) / 'custom.token'
            old_file.write_text('old-synthetic-token', encoding='utf-8')
            old_file.chmod(0o600)
            initial['commander']['token_file'] = str(old_file)
            config.save(initial)
            checked = []

            def profiles(client):
                checked.append(client.token)
                return [{'id': 'basis', 'label': 'Basis', 'persistent': False}]

            def open_window(url, _script_dir):
                parsed = urllib.parse.urlsplit(url)
                connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=3)
                try:
                    def request(method, path, form=None, headers=None):
                        connection.request(method, path,
                            urllib.parse.urlencode(form) if form else None, headers or {})
                        response = connection.getresponse()
                        return response.status, response.read().decode('utf-8'), dict(response.getheaders())
                    _, _, headers = request('GET', parsed.path + '?' + parsed.query)
                    headers = {'Cookie': headers['Set-Cookie'].split(';', 1)[0],
                               'Origin': 'http://' + parsed.netloc,
                               'Content-Type': 'application/x-www-form-urlencoded'}
                    _, page, _ = request('GET', '/', headers=headers)
                    csrf = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
                    form = {'csrf': csrf, 'action': 'check', 'commander_token': 'new-synthetic-token',
                            'commander.enabled-present': '1', 'commander.enabled': 'on'}
                    status, page, _ = request('POST', '/', form, headers)
                    self.assertEqual(status, 200)
                    self.assertEqual(checked, ['new-synthetic-token'])
                    self.assertNotIn('new-synthetic-token', page)
                    self.assertEqual(config.load(), initial)
                    self.assertEqual(old_file.read_text(), 'old-synthetic-token')
                    form['action'] = 'save'
                    status, page, _ = request('POST', '/', form, headers)
                    self.assertEqual(status, 200)
                    self.assertNotIn('new-synthetic-token', page)
                finally:
                    connection.close()
                return None, 'synthetic'

            with mock.patch('kienzledoku_commander_client.CommanderClient.profiles', profiles), \
                    mock.patch('kienzledoku_commander_client.CommanderClient.request', return_value={}), \
                    mock.patch.object(config, 'store_commander_token') as store:
                self.assertTrue(settings.run_settings(window_opener=open_window, setup=True))
                store.assert_called_once_with('new-synthetic-token')
            self.assertEqual(config.load()['commander']['token_file'], '')
            self.assertEqual(old_file.read_text(), 'old-synthetic-token')


if __name__ == '__main__':
    unittest.main()
