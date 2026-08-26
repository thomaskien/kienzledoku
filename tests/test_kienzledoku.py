import json
import os
import tempfile
import time
import unittest
from unittest import mock

from kienzledoku import (
    EXTENSION_FREITEXT_KUERZEL,
    PROFILE_FREITEXT,
    FhirError,
    SessionState,
    T2medFhirClient,
    close_page_html,
    page_html,
    parse_deep_link,
    validate_local_fhir_url,
    validate_transaction_response,
)
from kienzledoku_document import (
    OUTPUT_MODE_SINGLE,
    OUTPUT_MODE_STRUCTURED,
    compose_single_block,
    normalize_entry_code,
    parse_documentation_json,
)
from kienzledoku_speech import (
    STATUS_READY,
    STATUS_RECORDING,
    SpeechRecognitionManager,
    documentation_from_asr_payload,
    load_service_urls,
    validate_service_url,
)


class RecordingClient(T2medFhirClient):
    def __init__(self):
        super(RecordingClient, self).__init__(
            "https://127.0.0.1:16567/aps/fhir/api/r4",
            "ctx-test",
            "oauth-test",
            "api-test",
        )
        self.calls = []

    def _request(self, method, path, body=None, patient_profile=False):
        self.calls.append((method, path, body, patient_profile))
        entries = [
            {"response": {"status": "201 Created"}}
            for _entry in body.get("entry", [])
        ]
        return 200, {
            "resourceType": "Bundle",
            "type": "transaction-response",
            "entry": entries,
        }


class DocumentationContractTests(unittest.TestCase):
    def test_exact_four_fields_are_required(self):
        document = parse_documentation_json(
            '{"anamnese":"A","befund":"B","therapie":"T","prozedere":"P"}'
        )
        self.assertEqual(["anamnese", "befund", "therapie", "prozedere"], list(document))

        with self.assertRaisesRegex(ValueError, "Fehlende"):
            parse_documentation_json('{"anamnese":"A"}')
        with self.assertRaisesRegex(ValueError, "Unbekannte"):
            parse_documentation_json(
                '{"anamnese":"","befund":"","therapie":"","prozedere":"","diagnose":"X"}'
            )
        with self.assertRaisesRegex(ValueError, "Doppeltes"):
            parse_documentation_json(
                '{"anamnese":"","anamnese":"X","befund":"","therapie":"","prozedere":""}'
            )

    def test_single_block_is_deterministic(self):
        document = {
            "anamnese": "Kopfschmerz",
            "befund": "",
            "therapie": "Paracetamol besprochen",
            "prozedere": "",
        }
        self.assertEqual(
            "ANAMNESE\nKopfschmerz\n\nTHERAPIE\nParacetamol besprochen",
            compose_single_block(document),
        )

    def test_entry_code_validation(self):
        self.assertEqual("AI", normalize_entry_code(" AI "))
        for invalid in ("", "X" * 21, "A\nI"):
            with self.assertRaises(ValueError):
                normalize_entry_code(invalid)


class T2medTransactionTests(unittest.TestCase):
    def setUp(self):
        self.client = RecordingClient()
        self.document = {
            "anamnese": "A",
            "befund": "B",
            "therapie": "T",
            "prozedere": "P",
        }

    def test_structured_mode_is_one_four_entry_transaction(self):
        status, _response, labels = self.client.write_documentation(
            self.document, OUTPUT_MODE_STRUCTURED, "KI"
        )
        self.assertEqual(200, status)
        self.assertEqual(["Anamnese", "Befund", "Therapie", "Prozedere"], labels)
        method, path, bundle, _profile = self.client.calls[-1]
        self.assertEqual(("POST", ""), (method, path))
        self.assertEqual("transaction", bundle["type"])
        self.assertEqual(
            ["Observation", "Observation", "Procedure", "Procedure"],
            [entry["request"]["url"] for entry in bundle["entry"]],
        )

    def test_single_mode_uses_freetext_profile_and_code(self):
        _status, _response, labels = self.client.write_documentation(
            self.document, OUTPUT_MODE_SINGLE, "AI"
        )
        self.assertEqual(["Einzelblock AI"], labels)
        resource = self.client.calls[-1][2]["entry"][0]["resource"]
        self.assertEqual([PROFILE_FREITEXT], resource["meta"]["profile"])
        self.assertEqual(
            {"url": EXTENSION_FREITEXT_KUERZEL, "valueString": "AI"},
            resource["extension"][0],
        )

    def test_transaction_entry_error_is_not_accepted(self):
        response = {
            "resourceType": "Bundle",
            "type": "transaction-response",
            "entry": [{
                "response": {
                    "status": "200 OK",
                    "outcome": {
                        "resourceType": "OperationOutcome",
                        "issue": [{"severity": "error", "diagnostics": "abgelehnt"}],
                    },
                }
            }],
        }
        with self.assertRaisesRegex(FhirError, "zurückgerollt"):
            validate_transaction_response(response, ["Anamnese"])


class T2medHostConfigurationTests(unittest.TestCase):
    def test_installer_selected_fhir_host_replaces_fixed_test_ip(self):
        with tempfile.TemporaryDirectory() as config_dir:
            config_path = os.path.join(config_dir, "config.json")
            with open(config_path, "w", encoding="utf-8") as handle:
                json.dump({"t2med": {"fhir_host": "t2med-praxis.local"}}, handle)

            validate_local_fhir_url(
                "https://t2med-praxis.local:16567/aps/fhir/api/r4",
                config_path=config_path,
            )
            link = parse_deep_link(
                "kienzledoku://?kontextId=test&"
                "fhirBasisUrl=https%3A%2F%2Ft2med-praxis.local%3A16567%2Faps%2Ffhir%2Fapi%2Fr4",
                config_path=config_path,
            )
            self.assertEqual(
                "https://t2med-praxis.local:16567/aps/fhir/api/r4",
                link["fhir_base_url"],
            )

            with self.assertRaisesRegex(ValueError, "erneut ausführen"):
                validate_local_fhir_url(
                    "https://10.0.83.120:16567/aps/fhir/api/r4",
                    config_path=config_path,
                )


class SpeechIntegrationTests(unittest.TestCase):
    def test_installer_config_is_authoritative_for_all_three_targets(self):
        with tempfile.TemporaryDirectory() as script_dir:
            config_path = os.path.join(script_dir, "config.json")
            with open(config_path, "w", encoding="utf-8") as handle:
                json.dump({
                    "version": 1,
                    "services": {
                        "asr": "http://asr-praxis.local:8179",
                        "diarization": "http://10.0.0.42:8183",
                        "llm": "http://llm-praxis.local:8080",
                    },
                }, handle)
            with mock.patch.dict(os.environ, {}, clear=True):
                urls = load_service_urls(script_dir)
                manager = SpeechRecognitionManager(script_dir)
            self.assertEqual("http://asr-praxis.local:8179", urls["asr"])
            self.assertEqual("http://10.0.0.42:8183", manager.diarization_url)
            self.assertEqual("llm-praxis.local", manager.snapshot()["services"]["llm"]["host"])

            with mock.patch.dict(
                os.environ,
                {"KIENZLEDOKU_LLM_URL": "http://127.0.0.9:8088"},
                clear=True,
            ):
                authoritative = load_service_urls(script_dir)
            self.assertEqual("http://llm-praxis.local:8080", authoritative["llm"])
            self.assertEqual("http://asr-praxis.local:8179", authoritative["asr"])

        with tempfile.TemporaryDirectory() as script_dir:
            with mock.patch.dict(
                os.environ,
                {"KIENZLEDOKU_LLM_URL": "http://127.0.0.9:8088"},
                clear=True,
            ):
                fallback = load_service_urls(script_dir)
            self.assertEqual("http://127.0.0.9:8088", fallback["llm"])
            self.assertEqual("http://127.0.0.1:8179", fallback["asr"])

    def test_explicit_installer_config_is_independent_of_script_location(self):
        with tempfile.TemporaryDirectory() as root_dir:
            script_dir = os.path.join(root_dir, "programm")
            config_dir = os.path.join(root_dir, "Application Support", "Kienzledoku")
            os.makedirs(script_dir)
            os.makedirs(config_dir)
            config_path = os.path.join(config_dir, "config.json")
            with open(config_path, "w", encoding="utf-8") as handle:
                json.dump({
                    "version": 1,
                    "services": {
                        "asr": "http://10.0.83.140:8179",
                        "diarization": "http://10.0.83.140:8183",
                        "llm": "http://10.0.83.140:8080",
                    },
                }, handle)
            with mock.patch.dict(
                os.environ,
                {"KIENZLEDOKU_ASR_URL": "http://127.0.0.1:8179"},
                clear=True,
            ):
                manager = SpeechRecognitionManager(
                    script_dir, config_path=config_path
                )
            self.assertEqual("http://10.0.83.140:8179", manager.asr_url)
            self.assertEqual(config_path, manager.snapshot()["config_source"])

    def test_service_config_rejects_invalid_values_before_recording(self):
        self.assertEqual(
            "http://127.0.0.1:8179",
            validate_service_url("http://127.0.0.1:8179/", "ASR"),
        )
        with self.assertRaisesRegex(ValueError, "http://"):
            validate_service_url("127.0.0.1:8179", "ASR")
        with tempfile.TemporaryDirectory() as script_dir:
            with open(os.path.join(script_dir, "config.json"), "w", encoding="utf-8") as handle:
                handle.write("{nicht-json")
            with mock.patch.dict(os.environ, {}, clear=True):
                manager = SpeechRecognitionManager(script_dir)
            self.assertTrue(manager.config_error)
            self.assertEqual("error", manager.snapshot()["services"]["asr"]["status"])
            with self.assertRaisesRegex(RuntimeError, "Dienstkonfiguration"):
                manager.start()

    def test_health_states_are_reported_per_service(self):
        class Response(object):
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def getcode(self):
                return 200

        with tempfile.TemporaryDirectory() as script_dir:
            manager = SpeechRecognitionManager(script_dir)

            def fake_urlopen(request, timeout):
                self.assertEqual(3, timeout)
                if ":8183/health" in request.full_url:
                    raise OSError("offline")
                return Response()

            with mock.patch("kienzledoku_speech.urllib.request.urlopen", side_effect=fake_urlopen):
                manager._service_check_worker()
            services = manager.snapshot()["services"]
            self.assertEqual("ok", services["asr"]["status"])
            self.assertEqual("error", services["diarization"]["status"])
            self.assertEqual("ok", services["llm"]["status"])
            self.assertEqual("error", manager.snapshot()["service_status"])

    def test_asr_payload_uses_strict_document_contract(self):
        document = documentation_from_asr_payload({
            "llm": '{"anamnese":"A","befund":"B","therapie":"T","prozedere":"P"}'
        })
        self.assertEqual("P", document["prozedere"])
        with self.assertRaisesRegex(ValueError, "Fehlende"):
            documentation_from_asr_payload({"llm": '{"anamnese":"A"}'})
        with self.assertRaisesRegex(ValueError, "Kein Sprachsignal"):
            documentation_from_asr_payload({"transcript": "", "llm": None})

    def test_recording_stops_by_signal_and_returns_document(self):
        received = []
        with tempfile.TemporaryDirectory() as script_dir:
            runner = os.path.join(script_dir, "start_kienzledoku_asr.sh")
            prompt = os.path.join(script_dir, "prompt_documentation.txt")
            with open(prompt, "w", encoding="utf-8") as handle:
                handle.write("test")
            with open(runner, "w", encoding="utf-8") as handle:
                handle.write(
                    "#!/usr/bin/env python3\n"
                    "import json,sys\n"
                    "target=sys.argv[sys.argv.index('--json')+1]\n"
                    "print('KIENZLEDOKU_EVENT '+json.dumps({'type':'audio_devices','devices':[{'index':2,'name':'Testmikrofon'}],'selected':2}),flush=True)\n"
                    "print('KIENZLEDOKU_EVENT '+json.dumps({'type':'final_block','block_id':1,'text':'Live erkannt'}),flush=True)\n"
                    "sys.stdin.readline()\n"
                    "print('KIENZLEDOKU_EVENT '+json.dumps({'type':'diarization','text':'[SPEAKER_00] Live erkannt','speaker_labels':True}),flush=True)\n"
                    "llm=None if '--no-llm' in sys.argv else {'anamnese':'A','befund':'B','therapie':'T','prozedere':'P'}\n"
                    "with open(target,'w',encoding='utf-8') as f:\n"
                    " json.dump({'transcript':'Live erkannt','speaker_transcript':'[SPEAKER_00] Live erkannt','llm':llm},f)\n"
                )
            os.chmod(runner, 0o700)

            manager = SpeechRecognitionManager(script_dir, on_document=received.append)
            manager.start()
            self.assertEqual(STATUS_RECORDING, manager.snapshot()["status"])
            deadline = time.time() + 3
            while not manager.snapshot()["live_transcript"] and time.time() < deadline:
                time.sleep(0.02)
            self.assertEqual("Live erkannt", manager.snapshot()["live_transcript"])
            manager.stop()
            deadline = time.time() + 3
            while manager.snapshot()["status"] != STATUS_READY and time.time() < deadline:
                time.sleep(0.02)
            self.assertEqual(STATUS_READY, manager.snapshot()["status"])
            self.assertEqual("A", received[0]["anamnese"])
            self.assertEqual("[SPEAKER_00] Live erkannt", manager.snapshot()["diarized_text"])
            self.assertEqual("2", manager.snapshot()["selected_device"])
            self.assertEqual("Testmikrofon", manager.snapshot()["selected_device_name"])
            manager.set_audio_device("")
            self.assertEqual("macOS-Standardgerät", manager.snapshot()["selected_device_name"])
            with self.assertRaisesRegex(ValueError, "nicht mehr verfügbar"):
                manager.set_audio_device("99")
            self.assertIsNone(manager.work_dir)

            manager.set_diarized_text("[SPEAKER_00] ärztlich korrigiert")
            aggregate = '{"anamnese":"Gesamt","befund":"","therapie":"","prozedere":""}'
            with mock.patch("kienzledoku_speech.call_llm", return_value=aggregate) as llm:
                manager.start()
                manager.stop()
                deadline = time.time() + 3
                while manager.snapshot()["status"] != STATUS_READY and time.time() < deadline:
                    time.sleep(0.02)
            self.assertEqual(
                "[SPEAKER_00] ärztlich korrigiert\n\n[SPEAKER_00] Live erkannt",
                manager.snapshot()["diarized_text"],
            )
            self.assertEqual("Live erkannt\n\nLive erkannt", manager.snapshot()["live_transcript"])
            self.assertEqual("Gesamt", received[-1]["anamnese"])
            llm.assert_called_once_with(
                mock.ANY,
                "[SPEAKER_00] ärztlich korrigiert\n\n[SPEAKER_00] Live erkannt",
            )

    def test_edited_diarization_can_be_sent_to_llm_again(self):
        received = []
        with tempfile.TemporaryDirectory() as script_dir:
            prompt = os.path.join(script_dir, "prompt_documentation.txt")
            with open(prompt, "w", encoding="utf-8") as handle:
                handle.write("test")
            manager = SpeechRecognitionManager(script_dir, on_document=received.append)
            response = '{"anamnese":"Neu","befund":"","therapie":"","prozedere":""}'
            with mock.patch("kienzledoku_speech.call_llm", return_value=response):
                manager.regenerate("[SPEAKER_00] bearbeiteter Text")
                deadline = time.time() + 3
                while manager.snapshot()["status"] != STATUS_READY and time.time() < deadline:
                    time.sleep(0.02)
            self.assertEqual("Neu", received[0]["anamnese"])
            self.assertEqual(
                "[SPEAKER_00] bearbeiteter Text",
                manager.snapshot()["diarized_text"],
            )

    def test_ui_has_no_confirmation_and_has_close_page(self):
        client = RecordingClient()
        link = {
            "context_id": "ctx-test",
            "fhir_base_url": "https://127.0.0.1:16567/aps/fhir/api/r4",
            "oauth_token": "oauth-test",
        }
        state = SessionState(link, client, "Test")
        state.patient = {
            "resourceType": "Patient",
            "id": "p1",
            "name": [{"family": "Kienzle", "given": ["Thomas"]}],
            "birthDate": "1970-12-31",
        }
        state.t2med_status = "ok"
        state.speech = SpeechRecognitionManager(os.path.dirname(os.path.dirname(__file__)))
        rendered = page_html(state)
        self.assertIn(">kienzledoku</a>", rendered)
        self.assertIn("v1.2 · von Dr. Thomas Kienzle", rendered)
        self.assertIn('href="https://kienzledoku.de"', rendered)
        self.assertIn("Kienzle, Thomas", rendered)
        self.assertIn("31.12.1970", rendered)
        self.assertIn("Diarisiertes Gespräch", rendered)
        self.assertIn("Neu zusammenfassen", rendered)
        self.assertIn("Technische Informationen", rendered)
        self.assertIn("Mikrofon", rendered)
        self.assertIn("ASR", rendered)
        self.assertIn("Diar.", rendered)
        self.assertIn("LLM", rendered)
        self.assertIn("http://127.0.0.1:8179", rendered)
        self.assertIn("http://127.0.0.1:8183", rendered)
        self.assertIn("http://127.0.0.1:8080", rendered)
        self.assertIn("Konfiguration", rendered)
        self.assertIn("Lokale Standardwerte", rendered)
        self.assertNotIn("confirm(", rendered)
        self.assertIn("window.close()", close_page_html())

        state.speech.status = STATUS_RECORDING
        state.speech.message = "Aufnahme läuft."
        state.speech.live_transcript = "Live erkannter Text"
        active = page_html(state)
        self.assertIn("Aufnahme läuft", active)
        self.assertIn("Live erkannter Text", active)
        self.assertIn("Aufnahme stoppen", active)


if __name__ == "__main__":
    unittest.main()
