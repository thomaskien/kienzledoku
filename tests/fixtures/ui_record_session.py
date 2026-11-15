"""Synthetic browser fixture: no microphone, network services or real patient data."""
import os
from pathlib import Path
import sys
import threading
import time
from unittest import mock
import urllib.parse

sys.path.insert(0, os.environ.get('KIENZLEDOKU_TEST_SOURCE_ROOT', str(Path(__file__).resolve().parents[2])))
import kienzledoku as record
if os.environ.get('KIENZLEDOKU_TEST_WINDOWS_LAYOUT') == '1':
    record.WINDOWS_STATUS_LAYOUT = True
from kienzledoku_speech import SpeechRecognitionManager, STATUS_RECORDING, STATUS_PROCESSING, STATUS_READY


class FakeSpeech(SpeechRecognitionManager):
    def load_documentation_settings(self):
        from kienzledoku_document import DOCUMENT_FIELDS
        self.active_fields = DOCUMENT_FIELDS
        self.active_prompt = 'Synthetischer aktiver Prompt. Nur diktierte Informationen.'
        self.prompt_template = self.active_prompt

    def start_service_check(self, background=False):
        if os.environ.get('KIENZLEDOKU_TEST_COMMANDER_UI') == '1':
            self.quality_profiles = [
                {'id': 'basis', 'label': 'Qwen3.5 4B Q4', 'persistent': True, 'default': True, 'fallback': None},
                {'id': 'gruendlich', 'label': 'Gemma 4 12B Q8', 'persistent': False,
                 'default': False, 'fallback': 'basis'},
                {'id': 'sehr_gruendlich', 'label': 'Qwen3.8 27B Q4', 'persistent': False,
                 'default': False, 'fallback': 'basis'},
            ]
        if os.environ.get('KIENZLEDOKU_TEST_COMMANDER_UI') == 'single':
            self.quality_profiles = [{'id': 'basis', 'label': 'Qwen3.5 4B Q4', 'default': True}]
        if self.commander and self.quality_profiles:
            # Older Linux/WSL servers put model names in label; exercise the real client adapter.
            with mock.patch.object(self.commander,'request',return_value={'data':self.quality_profiles}):
                self.quality_profiles = self.commander.profiles()
        for name, service in self.services.items():
            service['status'] = 'loading' if name == 'asr' else 'standby'

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
            self.commander_notice = 'Die Verarbeitung mit „Gründlich“ ist fehlgeschlagen. Die Dokumentation wurde mit „Basis“ erstellt.'
            self.status = STATUS_PROCESSING
            def finish():
                if self.on_document:
                    self.on_document({'anamnese': 'Synthetischer Test: Übelkeit seit gestern.',
                                      'befund': '', 'ekg': '', 'sonografie': '', 'therapie': '', 'prozedere': '', 'notiz': ''})
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
