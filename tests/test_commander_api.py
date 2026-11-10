import json
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

if sys.platform == "win32":
    raise unittest.SkipTest("Die Server-Tests laufen unter Linux/WSL oder macOS; der Windows-Client wird separat geprüft.")

if sys.version_info < (3, 12):
    raise unittest.SkipTest("Der optionale Linux-Commander benötigt Python 3.12+.")

from kienzledoku_commander.api import API
from kienzledoku_commander.config import Settings, load_settings
from kienzledoku_commander.errors import BackendFailure
from kienzledoku_commander.runtime import Runtime, document
from kienzledoku_commander.scheduler import Commander, Job
from test_commander import RuntimeDouble, eventually

DOC = {"anamnese": "Synthetisch: seit drei Tagen Husten.", "befund": "", "therapie": "", "prozedere": ""}


class APIRuntime(RuntimeDouble):
    def infer(self, job):
        result = super().infer(job)
        if job.role == "llm":
            result["documentation"] = DOC
            result["completion"] = {"id": "synthetic", "object": "chat.completion", "choices": [{
                "index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": json.dumps(DOC)}}]}
        return result


class APITests(unittest.TestCase):
    def setUp(self):
        self.cfg = Settings(tier=24)
        self.runtime = APIRuntime(self.cfg)
        self.commander = Commander(self.cfg, self.runtime)
        self.addCleanup(self.commander.close)
        with patch.dict(os.environ, {self.cfg.token_env: "test-token"}):
            self.server = API(("127.0.0.1", 0), self.commander)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        def cleanup():
            self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.addCleanup(cleanup)
        self.base = "http://127.0.0.1:%d" % self.server.server_port
        eventually(lambda: self.commander.status()["loaded"]["llm"] == "gruendlich")

    def call(self, path, value=None, token="test-token", headers=None, raw=None, finalized=True):
        hdr = {"Content-Type": "application/json"}
        if finalized and (value is not None or path.startswith('/v1/diarize')):
            hdr['X-Kienzledoku-Recording-Finalized'] = 'true'
        if token:hdr["Authorization"] = "Bearer " + token
        hdr.update(headers or {})
        body = json.dumps(value).encode() if value is not None else raw
        try:
            response = urlopen(Request(self.base + path, body, hdr), timeout=6)
        except HTTPError as error:response = error
        with response:
            self.assertEqual("no-store", response.headers["Cache-Control"])
            return response.status, json.load(response)

    def test_auth_and_profile_discovery_never_expose_basis_on_24gib(self):
        self.assertEqual(200, self.call("/health", token=None)[0])
        self.assertEqual(401, self.call("/v1/runtime/status", token=None)[0])
        code, models = self.call("/v1/models")
        self.assertEqual(200, code)
        self.assertEqual(["gruendlich", "sehr_gruendlich"], [m["id"] for m in models["data"]])

    def test_extraction_fallback_visible_and_idempotent(self):
        self.runtime.fail_load.add("sehr_gruendlich")
        payload = {"transcript": "ARZT: Synthetischer Test.", "quality": "sehr_gruendlich", "request_id": "same"}
        code, result = self.call("/v1/documentation/extract", payload)
        self.assertEqual(200, code)
        self.assertEqual(DOC, result["documentation"])
        self.assertEqual("gruendlich", result["commander"]["used_quality"])
        self.assertIn("Gründlich", result["commander"]["notice"])
        before = list(self.runtime.events)
        self.assertEqual(result, self.call("/v1/documentation/extract", payload)[1])
        self.assertEqual(before, self.runtime.events)
        payload["transcript"] = "Anderer synthetischer Inhalt"
        self.assertEqual(409, self.call("/v1/documentation/extract", payload)[0])

    def test_openai_response_preserves_exact_four_fields(self):
        code, response = self.call("/v1/chat/completions", {"model": "gruendlich", "max_tokens": 1600,
            "messages": [{"role": "user", "content": "Synthetisches Transkript"}]})
        self.assertEqual(200, code)
        self.assertEqual(DOC, json.loads(response["choices"][0]["message"]["content"]))
        self.assertFalse(response["commander"]["fallback_used"])
        self.assertEqual(400, self.call("/v1/chat/completions", {"stream": True})[0])

    def test_validation_and_backend_errors_do_not_echo_input(self):
        secret = "SYNTHETISCHE-VERTRAULICHE-TESTMARKE"
        self.assertEqual(400, self.call("/v1/documentation/extract", {"quality": "basis", "transcript": secret})[0])
        self.runtime.fail_infer.add("gruendlich")
        status, result = self.call("/v1/documentation/extract", {"transcript": secret})
        self.assertEqual(502, status)
        self.assertNotIn(secret, json.dumps(result))
        self.assertNotIn(secret, json.dumps(self.call("/v1/runtime/status")[1]))

    def test_asr_and_diar_proxy_with_explicit_query_validation(self):
        self.assertEqual(200, self.call("/v1/asr/final-block", raw=b"synthetic-multipart",
            headers={"Content-Type": "multipart/form-data; boundary=test"})[0])
        self.assertEqual(200, self.call("/v1/diarize?num_speakers=2", raw=b"synthetic-wav",
            headers={"Content-Type": "audio/wav"})[0])
        self.assertEqual(400, self.call("/v1/diarize?target=http://example.org", raw=b"synthetic-wav",
            headers={"Content-Type": "audio/wav"})[0])

    def test_http_audio_queues_during_serial_llm_and_health_stays_available(self):
        release = threading.Event()
        self.runtime.holds["serial"] = release
        with ThreadPoolExecutor(max_workers=2) as pool:
            try:
                llm = pool.submit(self.call, "/v1/documentation/extract", {
                    "quality": "sehr_gruendlich", "transcript": "Synthetisches Gespräch", "request_id": "serial"})
                eventually(lambda: "serial" in self.runtime.started)
                code, health = self.call("/health", token=None)
                self.assertEqual(200, code)
                self.assertFalse(health["asr_ready"])
                audio = pool.submit(self.call, "/v1/asr/final-block", raw=b"synthetic-audio-block",
                    headers={"Content-Type": "multipart/form-data; boundary=test", "Idempotency-Key": "queued-audio"})
                eventually(lambda: self.commander.status()["pending"].get("asr") == 1)
                self.assertFalse(audio.done())
                release.set()
                self.assertEqual(200, llm.result(4)[0])
                self.assertEqual(200, audio.result(4)[0])
            finally:release.set()

    def test_unfinished_recording_is_rejected_before_model_switch(self):
        events = list(self.runtime.events)
        for path, payload in (("/v1/documentation/extract", {"quality": "sehr_gruendlich", "transcript": "synthetic"}),
                              ("/v1/chat/completions", {"model": "sehr_gruendlich", "messages": [{"role": "user", "content": "synthetic"}]})):
            code, result = self.call(path, payload, finalized=False)
            self.assertEqual(409, code)
            self.assertEqual('recording_not_finalized', result['error']['code'])
        self.assertEqual(409, self.call('/v1/diarize', raw=b'synthetic', headers={'Content-Type': 'audio/wav'}, finalized=False)[0])
        self.assertEqual(409, self.call('/v1/documentation/extract', {'transcript': 'synthetic', 'recording_finalized': False})[0])
        self.assertEqual(events, self.runtime.events)
        self.assertFalse(self.commander.status()['pending'])


class RuntimeTests(unittest.TestCase):
    def test_document_rejects_partial_duplicate_null_and_trailing_output(self):
        for text in ('{"anamnese":"x"}', json.dumps({**DOC, "therapie": None}),
                     '{"anamnese":"","anamnese":"x","befund":"","therapie":"","prozedere":""}',
                     json.dumps(DOC) + " extra"):
            with self.subTest(text=text), self.assertRaises(BackendFailure):document(text)
        self.assertEqual(DOC, document("```json\n" + json.dumps(DOC) + "\n```"))

    def test_real_child_start_health_inference_and_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "synthetic.gguf"
            model.write_bytes(b"test fixture")
            binary = root / "llama-double"
            binary.write_text("#!" + sys.executable + "\n" + '''
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
args = sys.argv
class H(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_GET(self):
        if self.path == '/redirect':
            self.send_response(302); self.send_header('Location', '/health'); self.end_headers(); return
        value = {'status':'ok'} if self.path == '/health' else {'model_path': args[args.index('--model')+1]}
        raw = json.dumps(value).encode(); self.send_response(200); self.end_headers(); self.wfile.write(raw)
    def do_POST(self):
        value=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        assert value['stream'] is False and value['cache_prompt'] is False
        doc = dict(anamnese='synthetic', befund='', therapie='', prozedere='')
        raw=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(doc)}}]}).encode()
        self.send_response(200); self.end_headers(); self.wfile.write(raw)
HTTPServer(('127.0.0.1', int(args[args.index('--port')+1])), H).serve_forever()
''')
            binary.chmod(0o700)
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0)); port = probe.getsockname()[1]
            cfg = Settings(tier=8, llama_binary=str(binary), llm_url="http://127.0.0.1:%d" % port,
                model_paths={q: str(model) for q in ("basis", "gruendlich", "sehr_gruendlich")}, load_timeout=4)
            with patch.dict(os.environ, {"http_proxy": "http://127.0.0.1:1", "no_proxy": ""}):
                r = Runtime(cfg)
            try:
                r.load_llm("basis")
                process = r.process
                with self.assertRaises(BackendFailure):r._http(cfg.llm_url + "/redirect")
                value = r.infer(Job("test", "llm", {"llm": {"messages": []}}, "basis", "basis"))
                self.assertEqual("synthetic", value["documentation"]["anamnese"])
                r.stop_llm()
                self.assertIsNotNone(process.returncode)
                self.assertIsNone(r.process)
            finally:r.close()

    def test_config_rejects_remote_backends_and_invalid_types(self):
        for options in ({"llm_url": "http://example.org:8080"}, {"max_pending": "128"},
                        {"tier": True}, {"host": "0.0.0.0", "token_env": "UNSET_COMMANDER_TEST_TOKEN"}):
            with self.subTest(options=options), self.assertRaises(ValueError):Settings(**options).validate()
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.toml"
            config.write_text('[gpu]\nvram_gib=16\n[policy]\ndefault_quality="gruendlich"\n')
            self.assertIsNone(load_settings(config).baseline_llm)
