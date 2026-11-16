"""Exercise the actual additional catalogue through configuration and scheduling.

No model weights, GPU processes or benchmark requests are used here.
"""
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'linux'), str(ROOT/'linux/runtime'), str(ROOT/'tests')]
import install_server
from serial_server import SerialSettings, SerialCommander, model_command
from test_commander import RuntimeDouble, eventually

CATALOG = json.loads((ROOT/'models.json').read_text())
GEMMA = ('gemma12-qat-q4', 'gemma12-q8', 'gemma26-qat-q4')


def configuration(resident='', models=None, default='9b-q4'):
    models = list(CATALOG) if models is None else models
    return dict(Models=models, DefaultModel=default, ParallelModel=resident,
                WslRamGiB=32, AudioCache='ram', GpuIndex=0, AuthEnabled=False,
                Profiles={key: {'Mode': 'parallel' if key == resident else 'serial'}
                          for key in models})


def runtime_config(cfg, vram=24576):
    with patch.object(install_server, 'ROOT', ROOT):
        install_server.validate_config(cfg, vram)
        return SerialSettings(**install_server.runtime_settings(cfg, dict(vram_mib=vram))).validate()


class DiarizationRuntime(RuntimeDouble):
    def infer(self, job):
        with self.lock:
            self.active.append(job.role)
            self.started.add(job.id)
        try:
            if not self.holds[job.id].wait(5):
                raise AssertionError('Test wartet zu lange')
            return {'documentation': {}, 'completion': {}} if job.role == 'llm' else {'text': 'synthetic'}
        finally:
            with self.lock:
                self.active.remove(job.role)


class GemmaModels(unittest.TestCase):
    def commander(self, cfg, runtime_class=RuntimeDouble):
        runtime = runtime_class(cfg)
        commander = SerialCommander(cfg, runtime)
        self.addCleanup(commander.close)
        eventually(lambda: commander.status()['loaded'] == commander._baseline() and
                   not commander.status()['transition_running'])
        return commander, runtime

    def test_all_eight_models_have_distinct_public_ids_and_verified_sources(self):
        self.assertEqual(8, len(CATALOG))
        self.assertEqual(8, len({x['quality'] for x in CATALOG.values()}))
        proof = json.loads((ROOT/'evidence/gemma-publisher-verification-1.8.json').read_text())
        for row in proof['models']:
            item = CATALOG[row['key']]
            file = item['files'][0]
            self.assertEqual(row['revision'], item['revision'])
            self.assertEqual(row['bytes'], file['bytes'])
            self.assertEqual(row['sha256'], file['sha256'])
            self.assertIn('/resolve/'+item['revision']+'/', file['url'])
            self.assertEqual(row['key']+'/'+file['filename'], file['path'])
            self.assertEqual([], item['fallbacks'])

    def test_each_gemma_can_be_resident_with_an_independent_qwen_default(self):
        for key in GEMMA:
            with self.subTest(key=key):
                cfg = runtime_config(configuration(key, default='27b-q4'))
                self.assertEqual('sehr_gruendlich', cfg.default)
                self.assertEqual(CATALOG[key]['quality'], cfg.baseline_llm)
                for other in CATALOG:
                    self.assertEqual(other == key, cfg.persistent(CATALOG[other]['quality']))

    def test_16gib_gpu_offers_qat12_parallel_and_rejects_larger_parallel_models(self):
        cfg = runtime_config(configuration('gemma12-qat-q4',
                             ['9b-q4', 'gemma12-qat-q4']), 16384)
        self.assertEqual('gemma12_qat_q4', cfg.baseline_llm)
        for key in GEMMA[1:]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                runtime_config(configuration(key, [key], key), 16384)

    def test_each_gemma_supports_all_serial_configuration(self):
        cfg = runtime_config(configuration())
        self.assertIsNone(cfg.baseline_llm)
        self.assertFalse(any(cfg.persistent(q) for q in cfg.allowed))
        self.assertEqual(8, len(cfg.allowed))

    def test_serial_gemma_request_restores_explicit_gemma_resident_and_status(self):
        cfg = runtime_config(configuration('gemma12-qat-q4'))
        commander, runtime = self.commander(cfg)
        for key in GEMMA[1:]:
            with self.subTest(key=key):
                quality = CATALOG[key]['quality']
                hold = threading.Event()
                runtime.holds[key] = hold
                self.addCleanup(hold.set)
                job = commander.submit('llm', {'llm': {}}, quality, request_id=key)
                eventually(lambda: key in runtime.started)
                self.assertEqual({'asr': False, 'diar': False, 'llm': quality}, runtime.loaded)
                status = commander.status()
                self.assertEqual(CATALOG[key]['label'], status['loaded_llm_label'])
                self.assertEqual('serial', status['loaded_llm_mode'])
                hold.set()
                job.future.result(3)
                eventually(lambda: runtime.loaded == {'asr': True, 'diar': True,
                                                     'llm': 'gemma12_qat_q4'})
        self.assertEqual('gemma12_qat_q4', commander.status()['resident_quality'])

    def test_diarization_preserves_each_gemma_parallel_selection(self):
        for key in GEMMA:
            with self.subTest(key=key):
                cfg = runtime_config(configuration(key))
                commander, runtime = self.commander(cfg)
                runtime.holds['diar'] = threading.Event()
                self.addCleanup(runtime.holds['diar'].set)
                job = commander.submit('diar', {'body': b'synthetic'}, request_id='diar')
                eventually(lambda: 'diar' in runtime.started)
                self.assertEqual({'asr': True, 'diar': True, 'llm': CATALOG[key]['quality']}, runtime.loaded)
                runtime.holds['diar'].set()
                job.future.result(3)

    def test_native_start_uses_32k_full_gpu_and_embedded_template_with_thinking_off(self):
        cfg = runtime_config(configuration())
        for key in GEMMA:
            quality = CATALOG[key]['quality']
            argv = model_command(cfg, cfg.model(quality), quality)
            for flag, value in [('--ctx-size', '32768'), ('--parallel', '1'),
                                ('--n-gpu-layers', '999'), ('--reasoning', 'off'),
                                ('--cache-type-k', 'q8_0'), ('--cache-type-v', 'q8_0')]:
                self.assertEqual(value, argv[argv.index(flag)+1])
            self.assertIn('--jinja', argv)
            self.assertEqual({'enable_thinking': False},
                             json.loads(argv[argv.index('--chat-template-kwargs')+1]))

    def test_separate_diarization_policy_reaches_linux_and_wsl_scheduler(self):
        for mode in ('resident', 'with_asr', 'serial'):
            with self.subTest(mode=mode):
                source = configuration(models=['9b-q4'])
                source.update(DiarizationMode=mode, AsrOnDemand=True)
                cfg = runtime_config(source)
                self.assertEqual(mode, cfg.diarization_mode)
                commander, runtime = self.commander(cfg, DiarizationRuntime)
                self.assertEqual(mode == 'resident', runtime.loaded['diar'])
                for role in ('asr', 'diar', 'llm'):
                    key = mode + '_' + role
                    release = threading.Event()
                    runtime.holds[key] = release
                    self.addCleanup(release.set)
                    job = commander.submit(role, {}, cfg.default if role == 'llm' else None, request_id=key)
                    eventually(lambda: key in runtime.started)
                    if role == 'asr':
                        self.assertEqual(mode != 'serial', runtime.loaded['diar'])
                    elif role == 'diar':
                        self.assertTrue(runtime.loaded['diar'])
                        self.assertEqual(mode != 'serial', runtime.loaded['asr'])
                        self.assertIsNone(runtime.loaded['llm'])
                    else:
                        self.assertEqual(mode == 'resident', runtime.loaded['diar'])
                        self.assertFalse(runtime.loaded['asr'])
                    release.set()
                    job.future.result(3)
                eventually(lambda: runtime.loaded['llm'] is None and not commander.status()['transition_running'])
                self.assertFalse(runtime.loaded['asr'])
                self.assertEqual(1, runtime.events.count('load_asr'))
                commander.close()

    def test_invalid_diarization_policy_is_rejected(self):
        source = configuration()
        source['DiarizationMode'] = 'unknown'
        with self.assertRaises(ValueError):
            runtime_config(source)


if __name__ == '__main__':
    unittest.main()
