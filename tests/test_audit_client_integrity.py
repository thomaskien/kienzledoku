"""Synthetic regressions for A01/A06; no PVS or patient data."""
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import kienzledoku as record


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.client.write_documentation.return_value = (200, {}, ['Anamnese'])
        self.state = record.SessionState({}, self.client, 'synthetic')
        self.state.patient = {'resourceType': 'Patient', 'id': 'synthetic-A'}
        self.state.speech = SimpleNamespace(status='ready')
        self.logs = patch.object(record, 'safe_log')
        self.logs.start(); self.addCleanup(self.logs.stop)
        self.windows = patch.object(record, 'close_ui_window')
        self.close = self.windows.start(); self.addCleanup(self.windows.stop)

    def handler(self, action='write'):
        handler = object.__new__(record.make_handler(self.state))
        handler.path = '/action'
        handler.authorize = lambda: True
        handler.read_form = lambda: {'csrf': [self.state.csrf], 'do': [action],
            'anamnese': ['SYNTHETISCH'], 'output_mode': ['structured'], 'single_code': ['KI']}
        for name in ('_send_html', 'send_response', 'send_header', 'end_headers'):
            setattr(handler, name, Mock())
        return handler

    def test_success_survives_broken_ui_response_and_cannot_be_reset(self):
        handler = self.handler()
        handler._send_html.side_effect = BrokenPipeError('synthetic')
        handler.do_POST()
        self.assertTrue(self.state.write_succeeded)
        self.assertTrue(self.state.completed_event.is_set())
        self.assertFalse(self.state.write_uncertain)
        self.handler('write_resolved').do_POST()
        self.handler().do_POST()
        self.assertEqual(self.client.write_documentation.call_count, 1)

    def test_window_close_failure_still_completes(self):
        self.close.side_effect = OSError('synthetic')
        self.handler().do_POST()
        self.handler().do_POST()
        self.assertTrue(self.state.completed_event.is_set())
        self.assertEqual(self.client.write_documentation.call_count, 1)

    def test_parallel_posts_write_once(self):
        start = threading.Barrier(3)
        def post():
            handler = self.handler()
            start.wait()
            handler.do_POST()
        threads = [threading.Thread(target=post) for _ in range(2)]
        for thread in threads: thread.start()
        start.wait()
        for thread in threads: thread.join(2); self.assertFalse(thread.is_alive())
        self.assertEqual(self.client.write_documentation.call_count, 1)

    def test_uncertain_write_requires_explicit_resolution(self):
        self.client.write_documentation.side_effect = record.FhirError('synthetic unknown result')
        self.handler().do_POST()
        self.handler().do_POST()
        self.assertTrue(self.state.write_uncertain)
        self.assertFalse(self.state.write_succeeded)
        self.assertEqual(self.client.write_documentation.call_count, 1)
        self.handler('write_resolved').do_POST()
        self.assertFalse(self.state.write_uncertain)

    def test_confirmed_rollback_allows_retry(self):
        self.client.write_documentation.side_effect = [record.FhirTransactionRejected('synthetic rollback'), (200, {}, ['Anamnese'])]
        self.handler().do_POST()
        self.assertFalse(self.state.write_uncertain)
        self.assertFalse(self.state.write_succeeded)
        self.handler().do_POST()
        self.assertEqual(self.client.write_documentation.call_count, 2)
        self.assertTrue(self.state.write_succeeded)

    def test_failed_reload_clears_old_patient_and_blocks_write(self):
        self.client.get_patient_by_context.side_effect = record.FhirError('synthetic ambiguous result')
        thread = record.start_patient_load(self.state)
        thread.join(2)
        self.assertIsNone(self.state.patient)
        self.handler().do_POST()
        self.client.write_documentation.assert_not_called()

    def test_ambiguous_or_contradictory_patient_bundles_block_write(self):
        patient = {'resourceType': 'Patient', 'id': 'synthetic-A'}
        other = dict(patient, id='synthetic-B')
        def bundle(resources, **fields):
            return dict(resourceType='Bundle', entry=[{'resource': p} for p in resources], **fields)
        invalid = [None, {}, bundle([]), bundle([patient, other]), bundle([other, patient]),
                   bundle([patient], total=2), bundle([patient], total=0), bundle([patient], total=True),
                   bundle([patient, dict(patient, birthDate='1900-01-01')]),
                   bundle([{'resourceType': 'Encounter'}]), bundle([patient, {'resourceType': 'Encounter'}]),
                   bundle([patient], link=[{'relation': 'next', 'url': 'synthetic'}])]
        for value in invalid:
            with self.subTest(value=value):
                self.state.patient = record.normalize_patient_result(value)
                self.assertIsNone(self.state.patient)
                self.handler().do_POST()
        self.client.write_documentation.assert_not_called()
        for value in [patient, bundle([patient]), bundle([patient], total=1), bundle([patient, dict(patient)], total=1)]:
            self.assertEqual(record.normalize_patient_result(value), patient)


if __name__ == '__main__': unittest.main()
