"""Synthetic browser fixture: no microphone, network services or real patient data."""
import os
from pathlib import Path
import sys
import threading
import time
from unittest import mock
import urllib.parse

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import kienzledoku as record
from kienzledoku_speech import SpeechRecognitionManager, STATUS_RECORDING, STATUS_PROCESSING, STATUS_READY


class FakeSpeech(SpeechRecognitionManager):
    def start_service_check(self):
        if os.environ.get('KIENZLEDOKU_TEST_COMMANDER_UI') == '1':
            self.quality_profiles = [
                {'id': 'basis', 'label': 'Basis', 'persistent': True, 'default': True, 'fallback': None},
                {'id': 'gemma12_q8', 'label': 'Gemma 4 12B Q8_0', 'persistent': False,
                 'default': False, 'fallback': 'basis'},
            ]
        for service in self.services.values():
            service['status'] = 'ok'

    def start(self):
        self.status = STATUS_RECORDING
        self.started_at = time.time()
        self.message = 'Synthetische Aufnahme läuft.'
        self.live_transcript = 'Ärztliche Äußerung: Öl, Füße, Übelkeit – α.'

    def stop(self):
        if os.environ.get('KIENZLEDOKU_TEST_COMMANDER_UI') == '1':
            self.requested_quality = self.selected_quality
            self.used_quality = 'basis'
            self.diarized_text = '[SPEAKER_00] Synthetisches Testgespräch: Übelkeit seit gestern.'
            self.message = 'Dokumentation erstellt. Synthetischer UI-Test.'
            self.commander_notice = 'Die Verarbeitung mit „Gemma 4 12B Q8_0“ ist fehlgeschlagen. Die Dokumentation wurde mit „Basis“ erstellt.'
            self.status = STATUS_PROCESSING
            def finish():
                if self.on_document:
                    self.on_document({'anamnese': 'Synthetischer Test: Übelkeit seit gestern.',
                                      'befund': '', 'therapie': '', 'prozedere': ''})
                self.status = STATUS_READY
            threading.Thread(target=finish, daemon=True).start()
            return
        self.status = STATUS_READY


def patient():
    gate = Path(os.environ['KIENZLEDOKU_CONFIG_DIR']) / 'allow-patient'
    deadline = time.monotonic() + 20
    while not gate.exists():
        if time.monotonic() > deadline:
            raise RuntimeError('Synthetic patient timeout')
        time.sleep(0.02)
    return {'resourceType': 'Patient', 'id': 'synthetic',
            'name': [{'family': 'Testperson', 'given': ['ÄÖÜ']}], 'birthDate': '2000-01-02'}


client = mock.Mock(proxy=None)
client.get_patient_by_context.side_effect = patient
client.write_documentation.side_effect = AssertionError('Browser fixture must never write to FHIR')
url = 'kienzledoku-record://record?' + urllib.parse.urlencode({
    'kontextId': 'synthetic', 'fhirBasisUrl': 'https://127.0.0.1:16567/aps/fhir/api/r4',
    'oAuthToken': 'synthetic',
})
with mock.patch.object(record, 'T2medFhirClient', return_value=client), \
        mock.patch.object(record, 'SpeechRecognitionManager', FakeSpeech), \
        mock.patch.object(record, 'get_api_key', return_value=('synthetic', 'test')):
    record.run_session(url, no_browser=True)
