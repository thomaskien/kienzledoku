import fcntl
from http.cookiejar import CookieJar
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, build_opener, HTTPCookieProcessor

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from installer import core, wizard
from installer.uninstall_macos import LAUNCH_AGENT, Uninstaller
from kienzledoku_http import configure_server


HW = dict(platform="darwin", arch="arm64", ram_gib=32, free_gib=100, server_supported=True)


class FakeRunner:
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), dict(kwargs)))
        if self.fail and self.fail in " ".join(map(str, argv)):
            raise subprocess.CalledProcessError(1, argv)
        return subprocess.CompletedProcess(argv, 0)


class MacUninstallerTests(unittest.TestCase):
    def test_bundled_python_symlink_is_accepted_but_external_target_is_refused(self):
        runtime=self.version/'venv/bin/python';runtime.unlink()
        real=self.version/'runtime/bin/python';real.parent.mkdir(parents=True);real.write_text('synthetic')
        runtime.symlink_to(real)
        self.assertTrue(self.uninstaller.inspect()['server'])
        runtime.unlink();runtime.symlink_to(Path(sys.executable))
        self.assertFalse(self.uninstaller.inspect()['server'])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.support = self.root / "support"
        (self.home / "Applications").mkdir(parents=True)
        (self.home / "Library/LaunchAgents").mkdir(parents=True)
        self.version = self.support / "versions/1.4.4-test"
        (self.version / "venv/bin").mkdir(parents=True)
        (self.version / "installer").mkdir()
        (self.version / "venv/bin/python").write_text("runtime")
        (self.version / "installer/service_main.py").write_text("service")
        (self.support / "models/model-a").mkdir(parents=True)
        (self.support / "models/model-a/model.gguf").write_text("model")
        (self.support / "downloads").mkdir()
        (self.support / "downloads/python.tar.gz").write_text("archive")
        (self.support / "config.toml").write_text("client settings")
        (self.support / "commander.token").write_text("synthetic-private-token")
        (self.support / "installer.json").write_text("{}")
        (self.support / "huggingface.token").write_text("synthetic-hf-token")
        (self.support / "commander").mkdir()
        (self.support / "commander/config.toml").write_text("server settings")
        (self.support / "commander/credentials.json").write_text("{}")
        (self.support / "commander/prompt.txt").write_text("prompt")
        self._make_apps()
        self._make_server()
        self.runner = FakeRunner()
        self.uninstaller = Uninstaller(self.support, self.home, self.runner)

    def tearDown(self):
        self.temp.cleanup()

    def _make_apps(self):
        for name, bundle_id in (("kienzledoku record.app", "de.kienzledoku.app"),
                                ("kienzledoku connect.app", "de.kienzledoku.connect")):
            contents = self.home / "Applications" / name / "Contents"
            contents.mkdir(parents=True)
            info = {"CFBundleIdentifier": bundle_id, "KienzledokuRoot": str(self.version)}
            (contents / "Info.plist").write_bytes(plistlib.dumps(info))

    def _make_server(self):
        info = {
            "Label": LAUNCH_AGENT,
            "ProgramArguments": [str(self.version / "venv/bin/python"),
                                 str(self.version / "installer/service_main.py"),
                                 str(self.support / "commander/config.toml"),
                                 str(self.support / "commander/credentials.json")],
            "WorkingDirectory": str(self.version),
        }
        (self.home / "Library/LaunchAgents" / (LAUNCH_AGENT + ".plist")).write_bytes(plistlib.dumps(info))

    @staticmethod
    def options(client=False, server=False, models=False, settings=False):
        return dict(remove_client=client, remove_server=server,
                    remove_models=models, remove_settings=settings)

    def test_read_only_detection_and_client_partial_preserve_defaults(self):
        before = sorted(str(path.relative_to(self.root)) for path in self.root.rglob("*"))
        self.assertEqual({"client": True, "server": True, "models": True, "settings": True, "unsafe": []},
                         self.uninstaller.inspect())
        self.assertEqual(before, sorted(str(path.relative_to(self.root)) for path in self.root.rglob("*")))
        self.uninstaller.execute(self.options(client=True))
        self.assertFalse((self.home / "Applications/kienzledoku record.app").exists())
        self.assertFalse((self.home / "Applications/kienzledoku connect.app").exists())
        self.assertTrue(self.uninstaller.launch_agent.exists())
        self.assertTrue(self.version.exists())
        self.assertTrue((self.support / "models/model-a/model.gguf").exists())
        self.assertTrue((self.support / "config.toml").exists())
        commands = [call[0] for call in self.runner.calls]
        self.assertEqual(2, sum("lsregister" in command[0] for command in commands))
        self.assertFalse(any("launchctl" in command[0] for command in commands))

    def test_server_partial_stops_only_owned_agent_and_preserves_shared_data(self):
        self.uninstaller.execute(self.options(server=True))
        self.assertFalse(self.uninstaller.launch_agent.exists())
        self.assertTrue((self.home / "Applications/kienzledoku record.app").exists())
        self.assertTrue(self.version.exists())
        self.assertTrue((self.support / "models").exists())
        self.assertTrue((self.support / "commander/config.toml").exists())
        commands = [call[0] for call in self.runner.calls]
        self.assertEqual(1, len(commands))
        self.assertEqual(["/bin/launchctl", "bootout", "gui/%s/%s" % (os.getuid(), LAUNCH_AGENT)], commands[0])

    def test_both_with_explicit_optional_removal(self):
        external_hf = self.home / ".cache/huggingface/hub/external-model"
        external_hf.mkdir(parents=True)
        old_local_ai = self.home / "local-ai"
        old_local_ai.mkdir()
        self.uninstaller.execute(self.options(client=True, server=True, models=True, settings=True))
        self.assertFalse(self.version.exists())
        self.assertFalse((self.support / "models").exists())
        self.assertFalse((self.support / "downloads").exists())
        for path in ("config.toml", "commander.token", "installer.json", "huggingface.token", "commander"):
            self.assertFalse((self.support / path).exists())
        self.assertTrue(external_hf.exists())
        self.assertTrue(old_local_ai.exists())

    def test_both_keeps_models_and_settings_by_default(self):
        self.uninstaller.execute(self.options(client=True, server=True))
        self.assertFalse(self.version.exists())
        self.assertTrue((self.support / "models/model-a/model.gguf").exists())
        self.assertTrue((self.support / "downloads/python.tar.gz").exists())
        self.assertTrue((self.support / "config.toml").exists())
        self.assertTrue((self.support / "commander/credentials.json").exists())

    def test_server_model_removal_is_explicit_and_client_cannot_remove_models(self):
        self.uninstaller.execute(self.options(server=True, models=True))
        self.assertFalse((self.support / "models").exists())
        with self.assertRaisesRegex(ValueError, "Modelle"):
            Uninstaller(self.support, self.home, self.runner).execute(self.options(client=True, models=True))

    def test_partial_settings_are_scoped_to_selected_component(self):
        self.uninstaller.execute(self.options(client=True, settings=True))
        self.assertFalse((self.support / "config.toml").exists())
        self.assertFalse((self.support / "commander.token").exists())
        self.assertTrue((self.support / "commander/credentials.json").exists())
        self.assertTrue((self.support / "huggingface.token").exists())
        self.assertTrue((self.support / "installer.json").exists())
        self.assertTrue(self.version.exists())

    def test_active_record_blocks_before_commands_or_deletion(self):
        lock = self.support / "sessions/desktop/record.lock"
        lock.parent.mkdir(parents=True)
        with lock.open("w") as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError, "Patientenfenster"):
                self.uninstaller.execute(self.options(client=True, server=True))
        self.assertEqual([], self.runner.calls)
        self.assertTrue((self.home / "Applications/kienzledoku record.app").exists())
        self.assertTrue(self.uninstaller.launch_agent.exists())

    def test_foreign_bundle_and_symlink_are_refused(self):
        info_path = self.home / "Applications/kienzledoku record.app/Contents/Info.plist"
        info = plistlib.loads(info_path.read_bytes())
        info["CFBundleIdentifier"] = "example.foreign.app"
        info_path.write_bytes(plistlib.dumps(info))
        with self.assertRaisesRegex(ValueError, "fremde App"):
            self.uninstaller.execute(self.options(client=True))
        self.assertTrue(info_path.exists())
        info["CFBundleIdentifier"] = "de.kienzledoku.app"
        info_path.write_bytes(plistlib.dumps(info))
        shutil_target = self.root / "must-survive"
        shutil_target.mkdir()
        connect = self.home / "Applications/kienzledoku connect.app"
        import shutil
        shutil.rmtree(connect)
        connect.symlink_to(shutil_target, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "Symlink"):
            self.uninstaller.execute(self.options(client=True))
        self.assertTrue(shutil_target.exists())

    def test_worker_error_never_reports_success(self):
        failed = Uninstaller(self.support, self.home, FakeRunner("lsregister"))
        failed.start(self.options(client=True))
        deadline = time.monotonic() + 5
        while failed.snapshot()["running"] and time.monotonic() < deadline:
            time.sleep(.01)
        status = failed.snapshot()
        self.assertFalse(status["done"])
        self.assertTrue(status["error"])
        self.assertNotEqual("Deinstallation abgeschlossen", status["message"])

    def test_http_auth_csrf_read_only_and_mutual_exclusion(self):
        installer = core.Installer(self.support, HW)
        server = ThreadingHTTPServer(("127.0.0.1", 0), wizard.handler(installer, "synthetic-csrf", self.uninstaller))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = configure_server(server)
        origin = url.split("/open")[0]
        opener = build_opener(HTTPCookieProcessor(CookieJar()))
        try:
            with self.assertRaises(HTTPError) as denied:
                opener.open(origin + "/api/uninstall")
            self.assertEqual(403, denied.exception.code)
            opener.open(url).close()
            before = self.uninstaller.inspect()
            data = json.load(opener.open(origin + "/api/uninstall"))
            self.assertTrue(data["client"] and data["server"])
            self.assertEqual(before, self.uninstaller.inspect())
            body = json.dumps(self.options(client=True)).encode()
            with self.assertRaises(HTTPError) as csrf_denied:
                opener.open(Request(origin + "/api/uninstall", body, {"Content-Type": "application/json"}))
            self.assertEqual(403, csrf_denied.exception.code)
            headers = {"Content-Type": "application/json", "X-CSRF-Token": "synthetic-csrf", "Origin": origin}
            result = json.load(opener.open(Request(origin + "/api/uninstall", body, headers)))
            self.assertTrue(result["started"])
            deadline = time.monotonic() + 5
            while json.load(opener.open(origin + "/api/uninstall/status"))["running"] and time.monotonic() < deadline:
                time.sleep(.01)
            status = json.load(opener.open(origin + "/api/uninstall/status"))
            self.assertTrue(status["done"], status)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
