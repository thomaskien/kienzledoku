"""Record transport against the unmodified Windows/WSL API and model catalogue."""
from pathlib import Path
import subprocess
import sys
import unittest


@unittest.skipUnless(sys.version_info >= (3, 12) and sys.platform != "win32",
                     "Die mitgelieferte Server-Laufzeit benötigt Python 3.12 und Unix/WSL.")
class WindowsCommanderContract(unittest.TestCase):
    def test_record_accepts_the_shipped_catalogue_and_extracts_each_model(self):
        # A separate interpreter keeps the two versions of the server package
        # isolated. Only the runtime double from the original suite uses models.
        source = r'''
from pathlib import Path
import json, os, sys, threading
root = Path.cwd()
server_root = root / 'server-windows'
sys.path[:0] = [str(server_root/'linux/runtime'), str(server_root/'tests'), str(root)]
from serial_server import SerialSettings, SerialCommander
from kienzledoku_commander.api import API
from test_commander import RuntimeDouble, eventually
from kienzledoku_commander_client import CommanderClient

catalogue = json.loads((server_root/'models.json').read_text())
profiles = {}
for item in catalogue.values():
    profiles[item['quality']] = dict(item['profile'],
        path='/synthetic-models/'+item['files'][0]['filename'],
        label=item['label'], mode='serial', fallbacks=item.get('fallbacks', []))
settings = SerialSettings(tier=24, default_quality='gemma12_q8',
    resident_quality='', profiles=profiles,
    prompt_path=str(root/'prompt_documentation.txt')).validate()
runtime = RuntimeDouble(settings)
commander = SerialCommander(settings, runtime)
os.environ[settings.token_env] = 'synthetic-contract-token'
api = None
thread = None
try:
    eventually(lambda: commander.status()['asr_ready'])
    api = API(('127.0.0.1', 0), commander)
    thread = threading.Thread(target=api.serve_forever, daemon=True)
    thread.start()
    client = CommanderClient('http://127.0.0.1:%d' % api.server_port)
    offered = client.profiles()
    assert offered[0]['id'] == 'gemma12_q8', offered
    assert {p['id'] for p in offered} == set(profiles), offered
    for item in offered:
        assert item['label'] == profiles[item['id']]['label']
        result, meta = client.extract('Synthetisches Testgespräch.', item['id'], offered,
                                      recording_finalized=True)
        assert set(result) == {'anamnese', 'befund', 'therapie', 'prozedere'}
        assert meta['used_quality'] == item['id']
        assert meta['fallback_used'] is False
    result, meta = client.extract('Synthetischer Standardauftrag.', 'auto', offered,
                                  recording_finalized=True)
    assert meta['requested_quality'] == 'gemma12_q8'
    print('Unchanged Windows API: all six catalogue models and server default accepted.')
finally:
    if api:
        api.shutdown()
        api.server_close()
    if thread:
        thread.join()
    commander.close()
'''
        result = subprocess.run([sys.executable, "-c", source],
                                cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
