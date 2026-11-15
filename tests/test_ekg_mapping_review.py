"""Synthetic review of the UI-to-wire EKG/sonography mapping."""

import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock
import urllib.parse

import kienzledoku as record
from kienzledoku_document import empty_documentation
from kienzledoku_speech import SpeechRecognitionManager


class _FHIRResponse:
    def __init__(self, body):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, _type, _value, _traceback):
        return False

    def read(self):
        return self._body

    def getcode(self):
        return 200


class _CapturingOpener:
    def __init__(self, response):
        self.response = response
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        return self.response


class _InMemorySocket:
    def __init__(self, request):
        self.input = io.BytesIO(request)
        self.output = io.BytesIO()

    def makefile(self, mode, *_args, **_kwargs):
        if "r" in mode:
            return self.input
        return self.output

    def sendall(self, data):
        self.output.write(data)


class EKGMappingReviewTests(unittest.TestCase):
    def setUp(self):
        quiet_log = mock.patch.object(record, "safe_log")
        quiet_log.start(); self.addCleanup(quiet_log.stop)
        self.client = record.T2medFhirClient(
            "https://127.0.0.1:16567/aps/fhir/api/r4",
            "synthetic-context",
            "",
            "synthetic-key",
        )
        response = {
            "resourceType": "Bundle",
            "type": "transaction-response",
            "entry": [
                {"response": {"status": "201 Created"}},
                {"response": {"status": "201 Created"}},
            ],
        }
        self.opener = _CapturingOpener(
            _FHIRResponse(json.dumps(response).encode("utf-8"))
        )
        self.client.opener = self.opener

        link_data = {
            "context_id": "synthetic-context",
            "fhir_base_url": "https://127.0.0.1:16567/aps/fhir/api/r4",
        }
        self.state = record.SessionState(link_data, self.client, "synthetic")
        self.state.patient = {"resourceType": "Patient", "id": "synthetic-patient"}
        self.state.active_fields = ("ekg", "sonografie")
        self.state.documentation = empty_documentation(self.state.active_fields)
        self.state.speech = SpeechRecognitionManager(
            str(Path(record.__file__).parent),
            config_path=str(Path(__file__).with_name("nonexistent-review-config.json")),
        )
        self.port = 43191
        self.server = SimpleNamespace(
            server_address=("127.0.0.1", self.port), ui_token="synthetic-ui-token"
        )
        self.cookie = "record_%d=%s" % (self.port, self.server.ui_token)

    def tearDown(self):
        self.client.close()

    def _request(self, method, path, body=None, headers=None):
        data = body.encode("utf-8") if isinstance(body, str) else (body or b"")
        all_headers = {
            "Host": "127.0.0.1:%d" % self.port,
            "Content-Length": str(len(data)),
        }
        all_headers.update(headers or {})
        raw = "%s %s HTTP/1.1\r\n%s\r\n\r\n" % (
            method,
            path,
            "\r\n".join("%s: %s" % item for item in all_headers.items()),
        )
        connection = _InMemorySocket(raw.encode("ascii") + data)
        handler = record.make_handler(self.state)
        handler(connection, ("127.0.0.1", 43192), self.server)
        response = connection.output.getvalue()
        head, response_body = response.split(b"\r\n\r\n", 1)
        status = int(head.split(b"\r\n", 1)[0].split()[1])
        return status, response_body, head

    def test_form_post_keeps_distinct_values_and_codes_in_wire_json(self):
        page = self._request("GET", "/", headers={"Cookie": self.cookie})
        self.assertEqual(200, page[0])
        html = page[1].decode("utf-8")
        self.assertIn('id="ekg" name="ekg"', html)
        self.assertIn('id="sonografie" name="sonografie"', html)

        ekg_text = "SYNTHETIC-EKG-VALUE-Ä"
        sonography_text = "SYNTHETIC-SONOGRAPHY-VALUE-Ö"
        form = urllib.parse.urlencode(
            {
                "csrf": self.state.csrf,
                "do": "write",
                "ekg": ekg_text,
                "sonografie": sonography_text,
                "output_mode": "structured",
                "single_code": "KI",
            }
        )
        reply = self._request(
            "POST",
            "/action",
            form,
            {
                "Cookie": self.cookie,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        self.assertEqual(200, reply[0])
        self.assertEqual(1, len(self.opener.requests))

        request, timeout = self.opener.requests[0]
        self.assertEqual(60, timeout)
        self.assertEqual("POST", request.get_method())
        self.assertEqual(
            "https://127.0.0.1:16567/aps/fhir/api/r4", request.full_url
        )
        self.assertEqual("application/fhir+json", request.get_header("Content-type"))

        bundle = json.loads(request.data.decode("utf-8"))
        self.assertEqual("transaction", bundle["type"])
        self.assertEqual(2, len(bundle["entry"]))
        ekg, sonography = [entry["resource"] for entry in bundle["entry"]]
        self.assertEqual(["Observation", "Observation"], [
            entry["request"]["url"] for entry in bundle["entry"]
        ])
        self.assertEqual(["POST", "POST"], [
            entry["request"]["method"] for entry in bundle["entry"]
        ])
        self.assertEqual(ekg_text, ekg["valueString"])
        self.assertEqual(sonography_text, sonography["valueString"])
        self.assertEqual("EKG", ekg["extension"][0]["valueString"])
        self.assertEqual("SON", sonography["extension"][0]["valueString"])
        self.assertEqual(
            record.EXTENSION_FREITEXT_KUERZEL,
            ekg["extension"][0]["url"],
        )
        self.assertEqual(
            record.EXTENSION_FREITEXT_KUERZEL,
            sonography["extension"][0]["url"],
        )
        self.assertEqual(
            [record.PROFILE_FREITEXT], ekg["meta"]["profile"]
        )
        self.assertEqual(
            [record.PROFILE_FREITEXT], sonography["meta"]["profile"]
        )

    def test_single_mode_uses_configured_code_for_ekg_field(self):
        response = {
            "resourceType": "Bundle",
            "type": "transaction-response",
            "entry": [{"response": {"status": "201 Created"}}],
        }
        self.opener.response = _FHIRResponse(json.dumps(response).encode("utf-8"))
        form = urllib.parse.urlencode(
            {
                "csrf": self.state.csrf,
                "do": "write",
                "ekg": "SYNTHETIC-EKG-IN-SINGLE-BLOCK",
                "sonografie": "",
                "output_mode": "single",
                "single_code": "SON",
            }
        )

        reply = self._request(
            "POST",
            "/action",
            form,
            {
                "Cookie": self.cookie,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )

        self.assertEqual(200, reply[0])
        bundle = json.loads(self.opener.requests[0][0].data.decode("utf-8"))
        self.assertEqual(1, len(bundle["entry"]))
        resource = bundle["entry"][0]["resource"]
        self.assertEqual("SON", resource["extension"][0]["valueString"])
        self.assertEqual(
            "EKG\nSYNTHETIC-EKG-IN-SINGLE-BLOCK", resource["valueString"]
        )

    def test_only_ekg_in_structured_mode_never_sends_son(self):
        response = {"resourceType": "Bundle", "type": "transaction-response",
                    "entry": [{"response": {"status": "201 Created"}}]}
        self.opener.response = _FHIRResponse(json.dumps(response).encode("utf-8"))
        form = urllib.parse.urlencode({
            "csrf": self.state.csrf, "do": "write", "output_mode": "structured",
            "single_code": "KI", "ekg": "SYNTHETIC-EKG-ONLY", "sonografie": ""})
        reply = self._request("POST", "/action", form, {
            "Cookie": self.cookie, "Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(200, reply[0])
        self.assertEqual(1, len(self.opener.requests))
        bundle = json.loads(self.opener.requests[0][0].data)
        self.assertEqual(1, len(bundle["entry"]))
        resource = bundle["entry"][0]["resource"]
        self.assertEqual("SYNTHETIC-EKG-ONLY", resource["valueString"])
        self.assertEqual([{"url": record.EXTENSION_FREITEXT_KUERZEL, "valueString": "EKG"}],
                         resource["extension"])


if __name__ == "__main__":
    unittest.main()
