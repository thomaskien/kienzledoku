import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

if sys.platform == "win32" or sys.version_info < (3, 12):
    raise unittest.SkipTest("Commander 1.4 benötigt Python 3.12 auf Linux oder macOS.")

from kienzledoku_commander.api import API, active_prompt
from kienzledoku_commander.config import Settings, load_settings
from kienzledoku_commander.errors import BackendFailure
from kienzledoku_commander.runtime import Runtime, document
from kienzledoku_commander.scheduler import Commander
from test_commander import RuntimeDouble, eventually


class ContractTests(unittest.TestCase):
    def test_auth_is_explicit_and_lan_without_auth_is_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "commander.toml"
            path.write_text('[server]\nhost="0.0.0.0"\nauth_enabled=false\n[gpu]\nvram_gib=16\n[backends]\nplatform="linux"\n')
            self.assertFalse(load_settings(path).auth_enabled)
            path.write_text('[server]\nauth_enabled=true\ntoken_env="MISSING_140_TOKEN"\n[gpu]\nvram_gib=16\n[backends]\nplatform="linux"\n')
            with patch.dict(os.environ, {}, clear=False), self.assertRaises(ValueError):
                os.environ.pop("MISSING_140_TOKEN", None)
                load_settings(path)

    def test_explicit_model_assignment_and_selected_field_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / "model.gguf"
            config = Path(directory) / "commander.toml"
            config.write_text('[gpu]\nvram_gib=24\n[backends]\nplatform="linux"\n'
                              '[models.basis]\npath=%s\nmodel_id="qwen4-q4"\nlabel="Qwen 4B"\ncontext=32768\nslots=1\nkv="q8_0"\n' % json.dumps(str(model)))
            settings = load_settings(config)
            self.assertEqual(("basis",), settings.allowed)
            self.assertEqual("qwen4-q4", settings.model("basis").model_id)
        fields = ("anamnese", "ekg", "notiz")
        prompt = active_prompt("Nur diktierte Tatsachen.", fields)
        self.assertIn('"ekg": ""', prompt)
        value = {"anamnese": "Test", "ekg": "", "notiz": ""}
        self.assertEqual(value, document(json.dumps(value), fields))
        with self.assertRaises(BackendFailure):
            document(json.dumps({"anamnese": "Test", "befund": "", "notiz": ""}), fields)

    def test_serial_on_demand_cold_start_and_no_overlap(self):
        cfg = Settings(tier=8, memory_mode="serial", asr_on_demand=True).validate()
        runtime = RuntimeDouble(cfg)
        commander = Commander(cfg, runtime)
        self.addCleanup(commander.close)
        self.assertTrue(commander.wait_ready(2))
        self.assertEqual({"asr": False, "diar": False, "llm": None}, commander.status()["loaded"])
        self.assertEqual("standby", commander.status()["services"]["asr"]["state"])
        runtime.reload_hold = threading.Event()
        first = commander.submit("asr", {})
        self.assertTrue(runtime.reload_entered.wait(2))
        self.assertEqual("loading", commander.status()["services"]["asr"]["state"])
        self.assertEqual("standby", commander.status()["services"]["llm"]["state"])
        runtime.reload_hold.set()
        first.future.result(2)
        time.sleep(.2)
        self.assertTrue(commander.status()["loaded"]["asr"])
        commander.submit("asr", {}).future.result(2)
        self.assertEqual(1, runtime.events.count("load_asr"))
        runtime.holds["llm"] = threading.Event()
        job = commander.submit("llm", {"llm": {}, "fields": cfg.enabled_fields}, request_id="llm")
        eventually(lambda: "llm" in runtime.started)
        self.assertEqual(["llm"], runtime.active)
        runtime.holds["llm"].set()
        job.future.result(2)
        eventually(lambda: commander.status()["loaded"] == {"asr": False, "diar": False, "llm": None})
        self.assertTrue(commander.wait_ready(0))
        time.sleep(.2)
        self.assertEqual(1, runtime.events.count("load_asr"))
        commander.submit("asr", {}).future.result(2)
        self.assertEqual(2, runtime.events.count("load_asr"))


class FakeProcess:
    pid = 43210
    returncode = None
    def poll(self):
        return self.returncode
    def wait(self, timeout=None):
        self.returncode = 0
        return 0


class MacOwnershipTests(unittest.TestCase):
    def settings(self):
        return Settings(tier=8, platform="macos", memory_mode="serial", enabled_roles=("asr",),
                        asr_command=(sys.executable, "/tmp/fake-asr.py"), asr_model_path="/tmp/fake-model",
                        load_timeout=.1).validate()

    def test_starts_and_stops_only_the_owned_worker(self):
        runtime = Runtime(self.settings())
        process = FakeProcess()
        with patch("kienzledoku_commander.runtime.socket.create_connection", side_effect=OSError), \
             patch("kienzledoku_commander.runtime.subprocess.Popen", return_value=process) as popen, \
             patch.object(runtime, "_http", return_value={"ok": True}), \
             patch("kienzledoku_commander.runtime.os.killpg") as killpg:
            runtime.load_asr()
            self.assertIs(process, runtime.worker_processes["asr"])
            self.assertEqual("/tmp/fake-model", popen.call_args.kwargs["env"]["KIENZLEDOKU_WHISPER_MODEL"])
            runtime.park_asr()
            killpg.assert_called_once_with(process.pid, 15)
            self.assertIsNone(runtime.worker_processes["asr"])

    def test_refuses_a_foreign_process_on_the_worker_port(self):
        runtime = Runtime(self.settings())
        connection = Mock()
        connection.__enter__ = Mock(return_value=connection)
        connection.__exit__ = Mock(return_value=False)
        with patch("kienzledoku_commander.runtime.socket.create_connection", return_value=connection), \
             patch("kienzledoku_commander.runtime.subprocess.Popen") as popen, self.assertRaises(BackendFailure):
            runtime.load_asr()
        popen.assert_not_called()


class FieldRuntime(RuntimeDouble):
    def infer(self, job):
        result = super().infer(job)
        if job.role == "llm":
            doc = {"anamnese": "Remote synthetisch", "notiz": "Explizite Notiz"}
            result["documentation"] = doc
            result["completion"] = {"id": "remote", "choices": [{"finish_reason": "stop",
                "message": {"role": "assistant", "content": json.dumps(doc)}}]}
        return result


class RemoteHTTPTests(unittest.TestCase):
    def setUp(self):
        self.token_patch = patch.dict(os.environ, {"TARGET_140_TOKEN": "remote-secret", "SOURCE_140_TOKEN": "remote-secret"})
        self.token_patch.start()
        self.addCleanup(self.token_patch.stop)
        target_cfg = Settings(tier=8, auth_enabled=True, token_env="TARGET_140_TOKEN",
                              enabled_fields=("anamnese", "notiz"))
        self.target_runtime = FieldRuntime(target_cfg)
        self.target_commander = Commander(target_cfg, self.target_runtime)
        self.addCleanup(self.target_commander.close)
        try:
            self.target = API(("127.0.0.1", 0), self.target_commander)
        except PermissionError:
            self.skipTest("Die Testumgebung erlaubt keine lokalen HTTP-Sockets.")
        self.target_thread = threading.Thread(target=self.target.serve_forever)
        self.target_thread.start()
        self.addCleanup(self._stop, self.target, self.target_thread)
        target_url = "http://127.0.0.1:%d" % self.target.server_port
        source_cfg = Settings(tier=8, remote_llm_url=target_url, remote_llm_token_env="SOURCE_140_TOKEN",
                              enabled_roles=("llm",))
        self.source_runtime = Runtime(source_cfg)
        self.source_commander = Commander(source_cfg, self.source_runtime)
        self.addCleanup(self.source_commander.close)
        self.source = API(("127.0.0.1", 0), self.source_commander)
        self.source_thread = threading.Thread(target=self.source.serve_forever)
        self.source_thread.start()
        self.addCleanup(self._stop, self.source, self.source_thread)
        self.url = "http://127.0.0.1:%d" % self.source.server_port
        eventually(lambda: self.source_commander.wait_ready(0))

    @staticmethod
    def _stop(server, thread):
        server.shutdown(); server.server_close(); thread.join()

    def call(self, path, value=None, headers=None):
        body = json.dumps(value).encode() if value is not None else None
        request = Request(self.url + path, body, {"Content-Type": "application/json", **(headers or {})})
        try:
            response = urlopen(request, timeout=4)
        except HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    def test_metadata_auth_forwarding_status_failure_and_loop_guard(self):
        code, settings = self.call("/v1/documentation/settings")
        self.assertEqual(200, code)
        self.assertEqual(["anamnese", "notiz"], settings["fields"])
        code, value = self.call("/v1/documentation/extract", {
            "transcript": "Synthetischer Remote-Test", "recording_finalized": True})
        self.assertEqual(200, code)
        self.assertEqual({"anamnese": "Remote synthetisch", "notiz": "Explizite Notiz"}, value["documentation"])
        self.assertIsNone(self.source_runtime.process)
        self.assertEqual(502, self.call("/v1/documentation/extract", {
            "transcript": "Schleifentest", "recording_finalized": True},
            {"X-Kienzledoku-Commander-Hop": "1"})[0])
        self.assertEqual(502, self.call("/v1/runtime/profiles", headers={"X-Kienzledoku-Commander-Hop": "1"})[0])
        self.target.prompt = "Geänderter aktiver Testprompt"
        self.assertEqual("Geänderter aktiver Testprompt", self.call("/v1/documentation/settings")[1]["prompt"])
        with patch.object(self.source_runtime, "remote_get", side_effect=BackendFailure):
            code, status = self.call("/v1/runtime/status")
            self.assertEqual(200, code)
            self.assertEqual("error", status["services"]["llm"]["state"])
            self.assertEqual(200, self.call("/health")[0])
        self.target_runtime.fail_infer.add("basis")
        self.assertEqual(502, self.call("/v1/documentation/extract", {
            "transcript": "Fehlertest", "recording_finalized": True, "request_id": "after-stop"})[0])
        self.assertIsNone(self.source_runtime.process)


if __name__ == "__main__":
    unittest.main()
