"""Resident model identity with the public quality mapping used by 1.5."""
from dataclasses import replace
import json
import threading
import unittest
from unittest.mock import patch

from test_gemma_models import configuration, runtime_config
from test_commander import RuntimeDouble, eventually
from serial_server import SerialCommander, SerialRuntime, model_command
from kienzledoku_commander.scheduler import Job


class ResidentAliasTests(unittest.TestCase):
    def config(self, mapping=None):
        cfg = runtime_config(configuration('gemma12-q8', ['gemma12-q8', '27b-q4'], 'gemma12-q8'))
        return replace(cfg, default_quality='gruendlich', diarization_mode='resident',
                       quality_models=mapping or {'gruendlich': 'gemma12_q8',
                                                  'sehr_gruendlich': 'sehr_gruendlich'}).validate()

    def commander(self, cfg):
        runtime = RuntimeDouble(cfg)
        commander = SerialCommander(cfg, runtime)
        self.addCleanup(commander.close)
        self.idle(commander, runtime)
        return commander, runtime

    def idle(self, commander, runtime):
        eventually(lambda: runtime.loaded == commander._baseline()
                   and not commander.status()['transition_running']
                   and not commander._return_after_llm)

    def test_resident_gemma_survives_repeated_successful_audio_and_llm_cycles(self):
        c, r = self.commander(self.config())
        self.assertEqual('@gemma12_q8', r.loaded['llm'])
        r.events.clear()
        for _ in range(3):
            c.submit('asr', {'body': b'synthetic'}).future.result(3)
            c.submit('diar', {'body': b'synthetic'}).future.result(3)
            result = c.submit('llm', {'llm': {}}, 'gruendlich').future.result(3)
            self.idle(c, r)
            self.assertEqual('gruendlich', result['commander']['used_quality'])
            self.assertFalse(result['commander']['fallback_used'])
        self.assertEqual([], r.events, 'Resident model must not unload or reload')

    def test_two_qualities_for_one_profile_share_the_loaded_process(self):
        c, r = self.commander(self.config({'basis': 'gemma12_q8', 'gruendlich': 'gemma12_q8'}))
        r.events.clear()
        for quality in ('basis', 'gruendlich', 'basis'):
            result = c.submit('llm', {'llm': {}}, quality).future.result(3)
            self.idle(c, r)
            self.assertEqual(quality, result['commander']['used_quality'])
        self.assertEqual([], r.events)

    def test_different_serial_model_still_switches_then_restores_resident(self):
        c, r = self.commander(self.config())
        r.events.clear()
        # The resident diarization is independent of the LLM mode; this double
        # tests model switching without the old fixture's all-audio-off assertion.
        def infer(job):
            self.assertEqual('@sehr_gruendlich', r.loaded['llm'])
            return {'documentation': {}, 'completion': {}}
        with patch.object(r, 'infer', side_effect=infer):
            c.submit('llm', {'llm': {}}, 'sehr_gruendlich').future.result(3)
            self.idle(c, r)
        self.assertEqual(['stop_@gemma12_q8', 'load_@sehr_gruendlich',
                          'stop_@sehr_gruendlich', 'load_@gemma12_q8'],
                         [e for e in r.events if e.startswith(('stop_', 'load_@'))])

    def test_backend_request_alias_matches_the_resident_process_alias(self):
        cfg = self.config()
        runtime = SerialRuntime(cfg)
        alias = cfg.baseline_llm
        command = model_command(cfg, cfg.model(alias), alias)
        reply = {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({
            'anamnese': 'Synthetic', 'befund': '', 'therapie': '', 'prozedere': ''})}}]}
        with patch.object(runtime, '_http', return_value=reply) as http:
            runtime.infer(Job('synthetic', 'llm', {'llm': {}}, 'gruendlich', 'gruendlich'))
        request = json.loads(http.call_args.args[1])
        self.assertEqual(command[command.index('--alias') + 1], request['model'])


if __name__ == '__main__': unittest.main()
