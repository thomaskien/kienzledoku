import fcntl
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from installer import linux_cli, linux_uninstall
from installer.linux_uninstall import LinuxPaths, Uninstaller
ROOT = linux_cli.ROOT  # Also exercise an extracted package from an external test directory.


class LinuxInstaller144Tests(unittest.TestCase):
    def test_only_own_protocol_associations_are_removed(self):
        self.make_client()
        mime=self.paths.config_home/'mimeapps.list'
        mime.write_text('# Keep comment\n[Default Applications]\nx-scheme-handler/kienzledoku=kienzledoku.desktop;other.desktop;\nx-scheme-handler/kienzledoku-record=kienzledoku.desktop;\ntext/plain=editor.desktop;\n')
        Uninstaller(self.paths,self.runner).execute(Uninstaller.options('client'))
        self.assertEqual('# Keep comment\n[Default Applications]\nx-scheme-handler/kienzledoku=other.desktop;\ntext/plain=editor.desktop;\n',mime.read_text())

    def test_commented_ownership_markers_do_not_authorize_foreign_unit(self):
        self.make_server()
        unit=self.paths.systemd/'kienzledoku-commander.service'
        unit.write_text('# '+unit.read_text().replace('\n','\n# ')+'\nExecStart=/usr/bin/foreign-program\n')
        with self.assertRaises(ValueError):
            Uninstaller(self.paths,self.runner).execute(Uninstaller.options('server'))
        self.assertEqual([],self.commands)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.paths = LinuxPaths(
            home=self.root / "home",
            data_home=self.root / "home/.local/share",
            config_home=self.root / "home/.config",
            state_home=self.root / "home/.local/state",
            server_base=self.root / "opt/kienzledoku-server",
            server_config=self.root / "etc/kienzledoku-server",
            server_state=self.root / "var/lib/kienzledoku-server",
            systemd=self.root / "etc/systemd/system",
        )
        self.commands = []
        patcher=mock.patch.object(linux_cli.client_config,"config_dir",return_value=self.paths.client_config)
        patcher.start();self.addCleanup(patcher.stop)

    def tearDown(self):
        self.temp.cleanup()

    def runner(self, argv, **kwargs):
        self.commands.append((argv, kwargs))
        return mock.Mock(returncode=0)

    def make_client(self):
        p = self.paths
        p.client_data.mkdir(parents=True)
        for name in ("kienzledoku.py", "kienzledoku_session.py"):
            (p.client_data / name).write_text("# Kienzledoku test payload\n")
        p.launcher.parent.mkdir(parents=True)
        p.launcher.write_text(
            "#!/bin/sh\nDATA_DIR=" + repr(str(p.client_data))
            + "\nexec python3 \"$DATA_DIR/kienzledoku.py\"\n"
        )
        p.desktop.parent.mkdir(parents=True)
        p.desktop.write_text(
            "[Desktop Entry]\nName=kienzledoku record\n"
            "Icon=kienzledoku-record\nMimeType=x-scheme-handler/kienzledoku;\n"
            "Exec=" + str(p.launcher) + " %u\n"
        )
        p.icon.parent.mkdir(parents=True)
        p.icon.write_text("<svg><!-- Kienzledoku --></svg>\n")
        p.client_config.mkdir(parents=True)
        (p.client_config / "config.toml").write_text("synthetic = true\n")
        p.client_state.mkdir(parents=True)
        (p.client_state / "client.log").write_text("synthetic log\n")

    def make_server(self):
        p = self.paths
        for name in ("runtime", "python", "scripts", "installer", "models", "downloads"):
            directory = p.server_base / name
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "synthetic").write_text(name + "\n")
        p.server_config.mkdir(parents=True)
        (p.server_config / "installer.json").write_text("{}\n")
        p.server_state.mkdir(parents=True)
        (p.server_state / "progress.json").write_text("{}\n")
        p.systemd.mkdir(parents=True)
        for name, markers in linux_uninstall.UNITS.items():
            (p.systemd / name).write_text("[Service]\n" + " ".join(markers) + "\n")
        (p.systemd / linux_uninstall.SLICE).write_text(
            "[Unit]\nDescription=Kienzledoku server memory budget\n"
        )

    def cli_context(self, argv, euid):
        return (
            mock.patch.object(sys, "argv", ["linux_cli.py", *argv]),
            mock.patch.object(linux_cli.os, "geteuid", return_value=euid),
            mock.patch.object(linux_cli.platform, "machine", return_value="x86_64"),
            mock.patch.object(
                linux_cli.Path,
                "read_text",
                return_value='ID=ubuntu\nVERSION_ID="24.04"\n',
            ),
            mock.patch.object(linux_cli.Path, "exists", return_value=True),
        )

    def test_root_server_install_reaches_engine_without_sudo(self):
        cfg = {"AuthEnabled": False}
        run = mock.Mock()
        patches = self.cli_context(["--components", "server"], 0)
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
                mock.patch.object(linux_cli, "server_answers", return_value=(cfg, "hf_test", "", "", "")), \
                mock.patch.object(linux_cli, "yes", return_value=True), \
                mock.patch.object(linux_cli, "private_write"), \
                mock.patch.object(linux_cli.subprocess, "run", run):
            linux_cli.main()
        engine = next(call.args[0] for call in run.call_args_list
                      if str(ROOT / "installer/linux_server.py") in call.args[0])
        self.assertEqual(sys.executable, engine[0])
        self.assertNotIn("sudo", engine)

    def test_nonroot_server_install_uses_sudo_only_for_engine(self):
        cfg = {"AuthEnabled": False}
        run = mock.Mock()
        patches = self.cli_context(["--components", "server"], 1000)
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
                mock.patch.object(linux_cli, "server_answers", return_value=(cfg, "hf_test", "", "", "")), \
                mock.patch.object(linux_cli, "yes", return_value=True), \
                mock.patch.object(linux_cli, "private_write"), \
                mock.patch.object(linux_cli.subprocess, "run", run):
            linux_cli.main()
        engine = next(call.args[0] for call in run.call_args_list
                      if str(ROOT / "installer/linux_server.py") in call.args[0])
        self.assertEqual(["sudo", sys.executable], engine[:2])

    def test_root_client_and_real_both_are_blocked_before_mutation(self):
        for component in ("client", "both"):
            with self.subTest(component=component):
                run = mock.Mock()
                configure = mock.Mock()
                patches = self.cli_context(["--components", component], 0)
                with patches[0], patches[1], patches[2], patches[3], patches[4], \
                        mock.patch.object(linux_cli, "configure_client", configure), \
                        mock.patch.object(linux_cli.subprocess, "run", run):
                    with self.assertRaisesRegex(ValueError, "Desktop-Benutzer"):
                        linux_cli.main()
                configure.assert_not_called()
                run.assert_not_called()

    def test_root_plan_allows_both_and_has_no_mutation(self):
        output = io.StringIO()
        with mock.patch.object(sys, "argv", ["linux_cli.py", "--components", "both", "--plan"]), \
                mock.patch.object(linux_cli.os, "geteuid", return_value=0), \
                mock.patch.object(linux_cli, "server_answers") as answers, \
                mock.patch.object(linux_cli.subprocess, "run") as run, \
                mock.patch("sys.stdout", output):
            linux_cli.main()
        self.assertIn('"components": "both"', output.getvalue())
        self.assertIn('"changes": false', output.getvalue())
        answers.assert_not_called()
        run.assert_not_called()

    def test_root_plan_defaults_to_server(self):
        output = io.StringIO()
        with mock.patch.object(sys, "argv", ["linux_cli.py", "--plan"]), \
                mock.patch.object(linux_cli.os, "geteuid", return_value=0), \
                mock.patch("builtins.input", return_value=""), \
                mock.patch("sys.stdout", output):
            linux_cli.main()
        self.assertIn('"components": "server"', output.getvalue())

    def test_server_questions_accept_mocked_rtx3090_and_input(self):
        def answer(label, default=""):
            if label == "GPU-Index":
                return "0"
            if label.startswith("Zu installierende Modelle"):
                return "qwen4-q4"
            if label.startswith("Anderer Commander"):
                return ""
            return str(default)

        def choose(label, default=False):
            if label.startswith("Feld "):
                return "Anamnese" in label
            return False

        with mock.patch.object(
                linux_cli.subprocess, "check_output",
                return_value="0, NVIDIA GeForce RTX 3090, 24576\n"), \
                mock.patch.object(linux_cli, "ask", side_effect=answer), \
                mock.patch.object(linux_cli, "yes", side_effect=choose), \
                mock.patch.object(linux_cli, "prompt_edit", return_value="synthetic prompt"), \
                mock.patch.object(linux_cli.getpass, "getpass", return_value="hf_synthetic"), \
                mock.patch.object(linux_cli.client_config, "config_dir", return_value=self.root / "empty-config"), \
                mock.patch.object(linux_cli.Path, "home", return_value=self.root / "empty-home"), \
                mock.patch.dict(os.environ, {"HF_TOKEN": ""}), \
                mock.patch.object(linux_cli.os, "sysconf", side_effect=(4096, 8 * 1024 * 1024)):
            cfg, hf, token, remote, remote_diar = linux_cli.server_answers()
        self.assertEqual(0, cfg["GpuIndex"])
        self.assertEqual(["qwen4-q4"], cfg["Models"])
        self.assertEqual(["anamnese"], cfg["EnabledFields"])
        self.assertEqual("hf_synthetic", hf)
        self.assertEqual(("", ""), (token, remote))

    def test_self_test_is_static(self):
        output = io.StringIO()
        with mock.patch.object(sys, "argv", ["linux_cli.py", "--self-test"]), \
                mock.patch.object(linux_cli.subprocess, "run") as run, \
                mock.patch("sys.stdout", output):
            linux_cli.main()
        self.assertIn("SELF-TEST OK", output.getvalue())
        run.assert_called_once_with(
            ["bash", "-n", str(ROOT / "linux/install_client.sh")], check=True
        )

    def test_client_uninstall_keeps_models_and_settings_by_default(self):
        self.make_client()
        models = self.root / "unrelated-models"
        models.mkdir()
        uninstaller = Uninstaller(self.paths, self.runner)
        uninstaller.execute(Uninstaller.options("client"))
        for path in (self.paths.client_data, self.paths.launcher,
                     self.paths.desktop, self.paths.icon):
            self.assertFalse(path.exists())
        self.assertTrue(self.paths.client_config.exists())
        self.assertTrue(self.paths.client_state.exists())
        self.assertTrue(models.exists())
        self.assertEqual([], self.commands)

    def test_server_uninstall_keeps_models_and_settings_by_default(self):
        self.make_server()
        uninstaller = Uninstaller(self.paths, self.runner)
        uninstaller.execute(Uninstaller.options("server"))
        self.assertFalse((self.paths.server_base / "runtime").exists())
        self.assertTrue((self.paths.server_base / "models").exists())
        self.assertTrue((self.paths.server_base / "downloads").exists())
        self.assertTrue(self.paths.server_config.exists())
        self.assertTrue(self.paths.server_state.exists())
        commands = [item[0] for item in self.commands]
        self.assertEqual("systemctl", commands[0][0])
        self.assertEqual(["systemctl", "daemon-reload"], commands[-1])

    def test_both_uninstall_can_remove_selected_models_and_settings(self):
        self.make_client()
        self.make_server()
        uninstaller = Uninstaller(self.paths, self.runner)
        uninstaller.execute(Uninstaller.options("both", True, True))
        self.assertFalse(self.paths.client_data.exists())
        self.assertFalse(self.paths.client_config.exists())
        self.assertFalse(self.paths.client_state.exists())
        self.assertFalse(self.paths.server_base.exists())
        self.assertFalse(self.paths.server_config.exists())
        self.assertFalse(self.paths.server_state.exists())

    def test_active_record_lock_blocks_client_removal(self):
        self.make_client()
        lock = self.paths.client_config / "sessions/desktop/record.lock"
        lock.parent.mkdir(parents=True)
        with lock.open("a+b") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError, "Aufnahme.*aktiv"):
                Uninstaller(self.paths, self.runner).execute(Uninstaller.options("client"))
        self.assertTrue(self.paths.client_data.exists())
        self.assertTrue(self.paths.launcher.exists())
        self.assertEqual([], self.commands)

    def test_active_install_lock_blocks_server_service_changes(self):
        self.make_server()
        lock = self.paths.server_state / "install.lock"
        with lock.open("a+b") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError, "Serverinstallation.*aktiv"):
                Uninstaller(self.paths, self.runner).execute(Uninstaller.options("server"))
        self.assertTrue((self.paths.server_base / "runtime").exists())
        self.assertTrue((self.paths.systemd / next(iter(linux_uninstall.UNITS))).exists())
        self.assertEqual([], self.commands)

    def test_foreign_unit_aborts_before_any_removal(self):
        self.make_server()
        unit = self.paths.systemd / next(iter(linux_uninstall.UNITS))
        unit.write_text("[Service]\nExecStart=/usr/bin/foreign-server\n")
        with self.assertRaisesRegex(ValueError, "nicht eindeutig"):
            Uninstaller(self.paths, self.runner).execute(Uninstaller.options("server"))
        self.assertTrue(unit.exists())
        self.assertTrue((self.paths.server_base / "runtime").exists())
        self.assertEqual([], self.commands)

    def test_runtime_symlink_aborts_before_service_mutation(self):
        self.make_server()
        runtime = self.paths.server_base / "runtime"
        for child in runtime.iterdir():
            child.unlink()
        runtime.rmdir()
        outside = self.root / "outside-runtime"
        outside.mkdir()
        (outside / "keep").write_text("do not remove\n")
        runtime.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "Server-Unterpfad.*Symlink"):
            Uninstaller(self.paths, self.runner).execute(Uninstaller.options("server"))
        self.assertTrue((outside / "keep").exists())
        self.assertTrue((self.paths.systemd / next(iter(linux_uninstall.UNITS))).exists())
        self.assertEqual([], self.commands)

    def test_state_symlink_aborts_before_service_mutation(self):
        self.make_server()
        outside = self.root / "outside-state"
        outside.write_text("do not remove\n")
        (self.paths.server_state / "foreign-link").symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "Status-Unterpfad.*Symlink"):
            Uninstaller(self.paths, self.runner).execute(
                Uninstaller.options("server", remove_settings=True)
            )
        self.assertTrue(outside.exists())
        self.assertTrue((self.paths.systemd / next(iter(linux_uninstall.UNITS))).exists())
        self.assertEqual([], self.commands)

    def test_service_failure_is_not_reported_as_success(self):
        self.make_server()

        def fail(argv, **kwargs):
            self.commands.append((argv, kwargs))
            raise subprocess.CalledProcessError(1, argv)

        local = Uninstaller(self.paths, fail)

        class Factory:
            options = staticmethod(Uninstaller.options)

            def __new__(cls):
                return local

        output = io.StringIO()
        with mock.patch.object(linux_cli.os, "geteuid", return_value=0), \
                mock.patch.object(linux_cli, "Uninstaller", Factory), \
                mock.patch("sys.stdout", output):
            with self.assertRaises(subprocess.CalledProcessError):
                linux_cli.uninstall("server", False, False)
        self.assertNotIn("deinstalliert", output.getvalue())
        self.assertTrue((self.paths.server_base / "runtime").exists())

    def test_nonroot_both_preflights_server_before_client_and_uses_sudo(self):
        real_options = Uninstaller.options
        local = mock.Mock()
        calls = []

        class Factory:
            options = staticmethod(real_options)

            def __new__(cls):
                return local

        def run(argv, **kwargs):
            calls.append(argv)
            return mock.Mock(returncode=0)

        with mock.patch.object(linux_cli.os, "geteuid", return_value=1000), \
                mock.patch.object(linux_cli, "Uninstaller", Factory), \
                mock.patch.object(linux_cli.subprocess, "run", side_effect=run):
            linux_cli.uninstall("both", False, False)
        self.assertEqual("sudo", calls[0][0])
        self.assertIn("--preflight", calls[0])
        self.assertEqual("sudo", calls[1][0])
        self.assertNotIn("--preflight", calls[1])
        local.execute.assert_called_once_with(real_options("client", False, False))

    def test_cli_privilege_guards_do_not_touch_paths(self):
        with mock.patch.object(linux_uninstall.os, "geteuid", return_value=0):
            with self.assertRaisesRegex(ValueError, "Desktop-Benutzer"):
                linux_uninstall.main(["--components", "client"])
        with mock.patch.object(linux_uninstall.os, "geteuid", return_value=1000):
            with self.assertRaisesRegex(ValueError, "Administratorrechte"):
                linux_uninstall.main(["--components", "server"])


if __name__ == "__main__":
    unittest.main()
