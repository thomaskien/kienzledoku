#!/usr/bin/env python3
"""Conservative macOS uninstaller for components owned by Kienzledoku."""
from __future__ import annotations

import json
import fcntl
from contextlib import ExitStack
import os
from pathlib import Path
import plistlib
import shutil
import stat
import subprocess
import threading

from installer.core import require_closed_record, support_dir


LAUNCH_AGENT = "de.kienzledoku.commander"
APP_BUNDLES = (
    ("kienzledoku record.app", "de.kienzledoku.app"),
    ("kienzledoku connect.app", "de.kienzledoku.connect"),
)
LSREGISTER = "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"


def _inside(path: Path, parent: Path) -> bool:
    """Return whether path is lexically below parent without following links."""
    try:
        if '..' in path.parts or '..' in parent.parts:
            return False
        path.absolute().relative_to(parent.absolute())
        return True
    except ValueError:
        return False


def _has_symlink(path: Path, parent: Path) -> bool:
    """Check path components below parent without resolving through a symlink."""
    if not _inside(path, parent):
        return True
    relative = path.absolute().relative_to(parent.absolute())
    current = parent.absolute()
    if current.is_symlink():
        return True
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            return True
    return False


def _read_plist(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Eine erwartete Kienzledoku-Metadatendatei ist unsicher oder fehlt.")
    try:
        value = plistlib.loads(path.read_bytes())
    except (OSError, ValueError, plistlib.InvalidFileException):
        raise ValueError("Eine erwartete Kienzledoku-Metadatendatei ist ungültig.") from None
    if not isinstance(value, dict):
        raise ValueError("Eine erwartete Kienzledoku-Metadatendatei ist ungültig.")
    return value


class Uninstaller:
    """Remove only verified app/service artifacts from an injected fake or real home."""

    def __init__(self, support=None, home=None, runner=None):
        self.support = Path(support or support_dir())
        self.home = Path(home or Path.home())
        self.runner = runner or subprocess.run
        self.lock = threading.Lock()
        self.state = dict(running=False, done=False, error="", message="", progress=0, logs=[])

    @property
    def applications(self):
        return self.home / "Applications"

    @property
    def versions(self):
        return self.support / "versions"

    @property
    def launch_agent(self):
        return self.home / "Library/LaunchAgents" / (LAUNCH_AGENT + ".plist")

    def snapshot(self):
        with self.lock:
            return dict(self.state, logs=list(self.state["logs"]))

    def report(self, message, progress=None):
        with self.lock:
            self.state["message"] = message
            if progress is not None:
                self.state["progress"] = progress
            self.state["logs"] = (self.state["logs"] + [message])[-50:]

    def _app_metadata(self, path: Path, bundle_id: str):
        if path.is_symlink() or not path.is_dir() or _has_symlink(path, self.applications):
            raise ValueError("Eine Programmverknüpfung ist ein Symlink oder liegt außerhalb von ~/Applications.")
        info_path = path / "Contents/Info.plist"
        if _has_symlink(info_path, path):
            raise ValueError("Die Metadaten einer Programmverknüpfung enthalten einen Symlink.")
        info = _read_plist(info_path)
        if info.get("CFBundleIdentifier") != bundle_id:
            raise ValueError("Eine gleichnamige fremde App wird nicht entfernt.")
        root_value = info.get("KienzledokuRoot")
        if not isinstance(root_value, str) or not root_value:
            raise ValueError("Die Herkunft einer Kienzledoku-App kann nicht sicher bestätigt werden.")
        root = Path(root_value)
        if not root.is_absolute() or not root.is_dir() or _has_symlink(root, self.versions):
            raise ValueError("Die App verweist nicht auf eine sichere Kienzledoku-Version.")
        return info

    def _server_metadata(self):
        plist = self.launch_agent
        if plist.is_symlink() or _has_symlink(plist, self.home):
            raise ValueError("Der Commander-Autostart ist ein Symlink und wird nicht verändert.")
        info = _read_plist(plist)
        if info.get("Label") != LAUNCH_AGENT:
            raise ValueError("Ein gleichnamiger fremder Autostart wird nicht entfernt.")
        arguments = info.get("ProgramArguments")
        if not isinstance(arguments, list) or len(arguments) < 4 or not all(isinstance(item, str) for item in arguments):
            raise ValueError("Der Commander-Autostart kann nicht sicher Kienzledoku zugeordnet werden.")
        runtime, service, config, credentials = map(Path, arguments[:4])
        # The separate Commander installer links its private venv to an external
        # interpreter. Only the owned service and its exact venv path are removed.
        from installer.update_macos import owned_version
        version = service.parent.parent
        external_venv = (
            version.parent == self.versions and runtime == version/'venv/bin/python'
            and service == version/'installer/service_main.py' and service.is_file()
            and not _has_symlink(runtime.parent, self.versions)
            and not _has_symlink(version/'venv/pyvenv.cfg', self.versions)
            and (version/'venv/pyvenv.cfg').is_file() and owned_version(version)
        )
        if (not _inside(runtime, self.versions) or not runtime.is_file()
                or not (_inside(runtime.resolve(), self.versions.resolve()) or external_venv)
                or _has_symlink(service, self.versions)
                or _has_symlink(config, self.support) or _has_symlink(credentials, self.support)
                or service.name != "service_main.py"
                or config != self.support / "commander/config.toml"
                or credentials != self.support / "commander/credentials.json"):
            raise ValueError("Der Commander-Autostart verweist nicht ausschließlich auf die eigene Installation.")
        return info

    def inspect(self):
        """Read-only component detection; unsafe lookalikes are reported, never trusted."""
        result = dict(client=False, server=False, models=False, settings=False, unsafe=[])
        for name, bundle_id in APP_BUNDLES:
            path = self.applications / name
            if not path.exists() and not path.is_symlink():
                continue
            try:
                self._app_metadata(path, bundle_id)
                result["client"] = True
            except ValueError as exc:
                result["unsafe"].append(str(exc))
        plist = self.launch_agent
        if plist.exists() or plist.is_symlink():
            try:
                self._server_metadata()
                result["server"] = True
            except ValueError as exc:
                result["unsafe"].append(str(exc))
        models = self.support / "models"
        result["models"] = models.is_dir() and not models.is_symlink()
        setting_paths = (self.support / "config.toml", self.support / "commander.token",
                         self.support / "installer.json", self.support / "huggingface.token",
                         self.support / "commander")
        result["settings"] = any(path.exists() or path.is_symlink() for path in setting_paths)
        return result

    def _validate_options(self, options):
        if not isinstance(options, dict) or set(options) != {"remove_client", "remove_server", "remove_models", "remove_settings"}:
            raise ValueError("Unvollständige oder unbekannte Deinstallationsauswahl.")
        if any(type(options[name]) is not bool for name in options):
            raise ValueError("Ungültige Deinstallationsauswahl.")
        if not options["remove_client"] and not options["remove_server"]:
            raise ValueError("Bitte Client, Server oder beide Komponenten auswählen.")
        if options["remove_models"] and not options["remove_server"]:
            raise ValueError("Modelle können nur zusammen mit dem lokalen Server entfernt werden.")
        return dict(options)

    def _check_root(self, root: Path, label: str):
        if root.is_symlink() or (root == self.applications and _has_symlink(root, self.home)):
            raise ValueError(label + " ist ein Symlink und wird nicht verändert.")

    def _plan(self, options):
        options = self._validate_options(options)
        self._check_root(self.support, "Der Kienzledoku-Supportordner")
        self._check_root(self.applications, "Der Programmordner")
        require_closed_record(self.support)
        apps = []
        if options["remove_client"]:
            for name, bundle_id in APP_BUNDLES:
                path = self.applications / name
                if path.exists() or path.is_symlink():
                    self._app_metadata(path, bundle_id)
                    apps.append(path)
        server = False
        if options["remove_server"] and (self.launch_agent.exists() or self.launch_agent.is_symlink()):
            self._server_metadata()
            server = True
        for path in self._optional_paths(options):
            if path.exists() or path.is_symlink():
                parent = self.support if path.parent == self.support else path.parent
                if path.is_symlink() or not _inside(path, self.support) or _has_symlink(path, parent):
                    raise ValueError("Ein zu löschender Kienzledoku-Pfad ist unsicher; es wurde nichts entfernt.")
        if not apps and not server and not any(path.exists() for path in self._optional_paths(options)):
            raise ValueError("Die ausgewählten Kienzledoku-Komponenten wurden nicht gefunden.")
        return options, apps, server

    def _optional_paths(self, options):
        paths = []
        if options["remove_models"]:
            paths += [self.support / "models", self.support / "downloads"]
        if options["remove_settings"]:
            if options["remove_client"]:
                paths += [self.support / "config.toml", self.support / "commander.token"]
            if options["remove_server"]:
                paths += [self.support / "commander", self.support / "huggingface.token"]
            if options["remove_client"] and options["remove_server"]:
                paths += [self.support / "installer.json"]
        if options["remove_client"] and options["remove_server"]:
            paths += [self.versions]
        return paths

    def _remove(self, path: Path):
        if not path.exists() and not path.is_symlink():
            return
        if path.is_symlink() or not _inside(path, self.support):
            raise ValueError("Ein unsicherer Pfad wurde nicht entfernt.")
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            shutil.rmtree(path)
        elif stat.S_ISREG(mode):
            path.unlink()
        else:
            raise ValueError("Eine unbekannte Kienzledoku-Datei wurde nicht entfernt.")

    def _run(self, argv, check=True):
        return self.runner([str(item) for item in argv], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, check=check)

    def execute(self, options):
        """Perform a synchronous uninstall. Primarily useful for tests and CLI use."""
        options, apps, server = self._plan(options)
        # Hold the same lock as Record for the entire removal so a new patient
        # cannot start between the initial check and deleting the runtime.
        with ExitStack() as stack:
            desktop = self.support / 'sessions/desktop/record.lock'
            locks = set((self.support/'sessions').glob('*/record.lock')) | {desktop}
            for path in sorted(locks):
                if _has_symlink(path, self.support):
                    raise ValueError('Die Aufnahme-Sperre liegt auf einem unsicheren Pfad.')
                path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                handle = stack.enter_context(os.fdopen(os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600), 'a+b'))
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise ValueError('Bitte zuerst das offene Patientenfenster schließen.') from None
            self._execute(options, apps, server)

    def _execute(self, options, apps, server):
        self.report("Deinstallation vorbereiten", 10)
        if server:
            self.report("Commander-Autostart entfernen", 30)
            result = self._run(["/bin/launchctl", "bootout", "gui/%s/%s" % (os.getuid(), LAUNCH_AGENT)], check=False)
            if getattr(result, "returncode", 0) not in (0, 3, 113):
                raise RuntimeError("Der eigene Commander-Dienst konnte nicht beendet werden.")
            from kienzledoku_commander.macos_processes import cleanup_after_stop
            if cleanup_after_stop(self.support/'commander/run'):
                self.report('Verwaiste eigene Modellprozesse bereinigt',40)
            self.launch_agent.unlink()
        if apps:
            self.report("Programmverknüpfungen und URL-Schemes entfernen", 55)
            for app in apps:
                self._run([LSREGISTER, "-u", app])
            for app in apps:
                shutil.rmtree(app)
        self.report("Ausgewählte Daten bereinigen", 80)
        for path in self._optional_paths(options):
            self._remove(path)
        self.report("Deinstallation abgeschlossen", 100)

    def start(self, options):
        options = self._validate_options(options)
        # Validate all paths and the Record lock before publishing a running job.
        self._plan(options)
        with self.lock:
            if self.state["running"]:
                raise ValueError("Die Deinstallation läuft bereits.")
            self.state.update(running=True, done=False, error="", message="", progress=0, logs=[])
        threading.Thread(target=self._work, args=(options,), daemon=True).start()

    def _work(self, options):
        try:
            self.execute(options)
            with self.lock:
                self.state["done"] = True
        except Exception as exc:
            message = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else "Deinstallation fehlgeschlagen. Bitte Dateirechte und Installation prüfen."
            with self.lock:
                self.state["error"] = message
            self.report(message)
        finally:
            with self.lock:
                self.state["running"] = False


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("component", choices=("client", "server", "both"))
    parser.add_argument("--remove-models", action="store_true")
    parser.add_argument("--remove-settings", action="store_true")
    args = parser.parse_args()
    choice = dict(remove_client=args.component in ("client", "both"),
                  remove_server=args.component in ("server", "both"),
                  remove_models=args.remove_models, remove_settings=args.remove_settings)
    uninstaller = Uninstaller()
    try:
        uninstaller.execute(choice)
    except (ValueError, RuntimeError) as exc:
        print(str(exc))
        return 1
    print(json.dumps({"done": True}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
