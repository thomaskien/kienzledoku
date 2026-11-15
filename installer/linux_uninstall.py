#!/usr/bin/env python3
"""Conservative, testable uninstaller for Kienzledoku on Ubuntu."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from dataclasses import dataclass
import fcntl
import os
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile


UNITS = {
    "kienzledoku-commander.service": (
        "ExecStart=/usr/bin/python3 ",
        "/opt/kienzledoku-server/runtime/serial_server.py",
        "/etc/kienzledoku-server/installer.json",
    ),
    "kienzlefon-ai-asr-backend.service": (
        "ExecStart=/opt/kienzledoku-server/python/asr-venv/bin/wlk ",
        "--model-path /opt/kienzledoku-server/models/whisper",
    ),
    "kienzlefon-ai-diarization.service": (
        "ExecStart=/opt/kienzledoku-server/python/diarization-venv/bin/python ",
        "/opt/kienzledoku-server/scripts/diarization_server.py",
    ),
}
SLICE = "kienzledoku-ai.slice"


def _absolute_xdg(name: str, fallback: Path) -> Path:
    path = Path(os.environ.get(name, str(fallback))).expanduser()
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError(name + " muss ein absoluter Pfad ohne '..' sein.")
    return path


@dataclass(frozen=True)
class LinuxPaths:
    home: Path
    data_home: Path
    config_home: Path
    state_home: Path
    server_base: Path = Path("/opt/kienzledoku-server")
    server_config: Path = Path("/etc/kienzledoku-server")
    server_state: Path = Path("/var/lib/kienzledoku-server")
    systemd: Path = Path("/etc/systemd/system")

    @classmethod
    def current(cls):
        home = Path.home().absolute()
        return cls(
            home=home,
            data_home=_absolute_xdg("XDG_DATA_HOME", home / ".local/share"),
            config_home=_absolute_xdg("XDG_CONFIG_HOME", home / ".config"),
            state_home=_absolute_xdg("XDG_STATE_HOME", home / ".local/state"),
        )

    @property
    def client_data(self):
        return self.data_home / "kienzledoku"

    @property
    def client_config(self):
        return self.config_home / "kienzledoku"

    @property
    def client_state(self):
        return self.state_home / "kienzledoku"

    @property
    def launcher(self):
        return self.home / ".local/bin/kienzledoku"

    @property
    def desktop(self):
        return self.data_home / "applications/kienzledoku.desktop"

    @property
    def icon(self):
        return self.data_home / "icons/hicolor/scalable/apps/kienzledoku-record.svg"


def _exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _inside(path: Path, parent: Path) -> bool:
    try:
        if ".." in path.parts or ".." in parent.parts:
            return False
        path.absolute().relative_to(parent.absolute())
        return True
    except ValueError:
        return False


def _has_symlink(path: Path, parent: Path) -> bool:
    if not _inside(path, parent):
        return True
    current = parent.absolute()
    if current.is_symlink():
        return True
    for part in path.absolute().relative_to(current).parts:
        current /= part
        if current.is_symlink():
            return True
    return False


class Uninstaller:
    """Remove verified Kienzledoku artifacts using injected paths and commands."""

    def __init__(self, paths=None, runner=None):
        self.paths = paths or LinuxPaths.current()
        self.runner = runner or subprocess.run

    @staticmethod
    def options(component, remove_models=False, remove_settings=False):
        if component not in ("client", "server", "both"):
            raise ValueError("Bitte Client, Server oder beide Komponenten auswählen.")
        if remove_models and component == "client":
            raise ValueError("Modelle können nur zusammen mit dem Server entfernt werden.")
        return {
            "remove_client": component in ("client", "both"),
            "remove_server": component in ("server", "both"),
            "remove_models": bool(remove_models),
            "remove_settings": bool(remove_settings),
        }

    def _validate_options(self, options):
        expected = {"remove_client", "remove_server", "remove_models", "remove_settings"}
        if not isinstance(options, dict) or set(options) != expected:
            raise ValueError("Unvollständige oder unbekannte Deinstallationsauswahl.")
        if any(type(options[name]) is not bool for name in expected):
            raise ValueError("Ungültige Deinstallationsauswahl.")
        if not options["remove_client"] and not options["remove_server"]:
            raise ValueError("Bitte Client, Server oder beide Komponenten auswählen.")
        if options["remove_models"] and not options["remove_server"]:
            raise ValueError("Modelle können nur zusammen mit dem Server entfernt werden.")
        return dict(options)

    def _safe_known_path(self, path: Path, base: Path, label: str):
        if not _inside(path, base) or _has_symlink(path, base):
            raise ValueError(label + " ist ein Symlink oder liegt außerhalb des erwarteten Ordners.")

    def _client_artifacts(self):
        p = self.paths
        return [p.client_data, p.launcher, p.desktop, p.icon]

    def _validate_client(self):
        p = self.paths
        for base, label in ((p.home, "Das Benutzerverzeichnis"),
                            (p.data_home, "Der XDG-Datenordner"),
                            (p.config_home, "Der XDG-Konfigurationsordner"),
                            (p.state_home, "Der XDG-Statusordner")):
            if not base.is_absolute() or ".." in base.parts or base.is_symlink():
                raise ValueError(label + " ist unsicher und wird nicht verändert.")
        if _exists(p.client_data):
            self._safe_known_path(p.client_data, p.data_home, "Der Client-Programmordner")
            if not p.client_data.is_dir() or not all(
                    (p.client_data / name).is_file()
                    for name in ("kienzledoku.py", "kienzledoku_session.py")):
                raise ValueError("Der Client-Programmordner kann Kienzledoku nicht sicher zugeordnet werden.")
        for path, base in ((p.client_config,p.config_home),(p.client_state,p.state_home),
                           (p.config_home/'mimeapps.list',p.config_home),
                           (p.data_home/'applications/mimeapps.list',p.data_home)):
            if _exists(path): self._safe_known_path(path,base,'Eine Client-Konfigurationsdatei')
        if _exists(p.launcher):
            self._safe_known_path(p.launcher, p.home, "Der Client-Starter")
            if not p.launcher.is_file():
                raise ValueError("Der Client-Starter ist keine reguläre Datei.")
            try:
                lines = p.launcher.read_text(encoding="utf-8").splitlines()
                assignment = next(line for line in lines if line.startswith("DATA_DIR="))
                values = shlex.split(assignment.split("=", 1)[1])
            except (OSError, ValueError, StopIteration):
                values = []
            text = "\n".join(lines) if "lines" in locals() else ""
            if values != [str(p.client_data)] or "kienzledoku.py" not in text:
                raise ValueError("Ein gleichnamiger fremder Client-Starter wird nicht entfernt.")
        if _exists(p.desktop):
            self._safe_known_path(p.desktop, p.data_home, "Der Desktop-Eintrag")
            if not p.desktop.is_file():
                raise ValueError("Der Desktop-Eintrag ist keine reguläre Datei.")
            text = p.desktop.read_text(encoding="utf-8")
            required = ("[Desktop Entry]", "Name=kienzledoku record", "Icon=kienzledoku-record",
                        "x-scheme-handler/kienzledoku", str(p.launcher))
            if not all(marker in text for marker in required):
                raise ValueError("Ein gleichnamiger fremder Desktop-Eintrag wird nicht entfernt.")
        if _exists(p.icon):
            self._safe_known_path(p.icon, p.data_home, "Das Client-Symbol")
            if not p.icon.is_file():
                raise ValueError("Das Client-Symbol ist keine reguläre Datei.")

    def _unit_paths(self):
        return {name: self.paths.systemd / name for name in UNITS}

    def _validate_server(self):
        p = self.paths
        roots = ((p.server_base, Path("/opt")), (p.server_config, Path("/etc")),
                 (p.server_state, Path("/var/lib")), (p.systemd, Path("/etc/systemd/system")))
        # Injected test roots need not live below real /opt and /etc. Their own
        # parents are the allowed base, while production paths retain strict bases.
        for path, production_parent in roots:
            parent = production_parent if path == production_parent / path.name else path.parent
            if not path.is_absolute() or ".." in path.parts or _has_symlink(path, parent):
                raise ValueError("Ein Serverpfad ist unsicher; es wurde nichts entfernt.")
        for name, path in self._unit_paths().items():
            if not _exists(path):
                continue
            self._safe_known_path(path, p.systemd, "Die systemd-Unit " + name)
            if not path.is_file():
                raise ValueError("Die systemd-Unit " + name + " ist keine reguläre Datei.")
            text = path.read_text(encoding="utf-8")
            starts = [line.strip() for line in text.splitlines() if line.strip().startswith("ExecStart=")]
            if len(starts) != 1 or not all(marker in starts[0] for marker in UNITS[name]):
                raise ValueError("Die systemd-Unit " + name + " gehört nicht eindeutig zu Kienzledoku.")
        slice_path = p.systemd / SLICE
        if _exists(slice_path):
            self._safe_known_path(slice_path, p.systemd, "Die Kienzledoku-systemd-Slice")
            text = slice_path.read_text(encoding="utf-8") if slice_path.is_file() else ""
            if "Kienzledoku server memory budget" not in text:
                raise ValueError("Die systemd-Slice gehört nicht eindeutig zu Kienzledoku.")
        if _exists(p.server_base):
            if not p.server_base.is_dir() or not any(
                    (p.server_base / name).exists()
                    for name in ("runtime", "installer", "models", "python", "scripts")):
                raise ValueError("Der Serverordner kann Kienzledoku nicht sicher zugeordnet werden.")

    def _validate_remove_target(self, path: Path, base: Path, label: str):
        if not _exists(path):
            return
        self._safe_known_path(path, base, label)
        mode = path.lstat().st_mode
        if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
            raise ValueError(label + " hat einen unbekannten Dateityp.")

    def _validate_server_removals(self, options):
        p = self.paths
        for path in self._server_runtime_paths(options):
            self._validate_remove_target(path, p.server_base,
                                         "Ein Server-Unterpfad")
        if options["remove_settings"]:
            self._validate_remove_target(p.server_config, p.server_config.parent,
                                         "Der Server-Konfigurationsordner")
            self._validate_remove_target(p.server_state, p.server_state.parent,
                                         "Der Server-Statusordner")
            if p.server_state.is_dir():
                for path in p.server_state.iterdir():
                    if path.name != "install.lock":
                        self._validate_remove_target(path, p.server_state,
                                                     "Ein Server-Status-Unterpfad")

    def inspect(self):
        result = dict(client=False, server=False, models=False, settings=False, unsafe=[])
        try:
            self._validate_client()
            result["client"] = any(_exists(path) for path in self._client_artifacts())
        except (OSError, ValueError) as exc:
            result["unsafe"].append(str(exc))
        try:
            self._validate_server()
            result["server"] = (any(_exists(path) for path in self._unit_paths().values())
                                or _exists(self.paths.server_base))
        except (OSError, ValueError) as exc:
            result["unsafe"].append(str(exc))
        result["models"] = _exists(self.paths.server_base / "models")
        result["settings"] = any(_exists(path) for path in (
            self.paths.client_config, self.paths.client_state,
            self.paths.server_config, self.paths.server_state))
        return result

    def plan(self, options):
        options = self._validate_options(options)
        if options["remove_client"]:
            self._validate_client()
        if options["remove_server"]:
            self._validate_server()
            self._validate_server_removals(options)
        selected = []
        if options["remove_client"]:
            selected += [path for path in self._client_artifacts() if _exists(path)]
        if options["remove_server"]:
            selected += [path for path in self._unit_paths().values() if _exists(path)]
            slice_path = self.paths.systemd / SLICE
            if _exists(slice_path):
                selected.append(slice_path)
            selected += [path for path in self._server_runtime_paths(options) if _exists(path)]
        if options["remove_settings"]:
            if options["remove_client"]:
                selected += [path for path in (self.paths.client_config, self.paths.client_state) if _exists(path)]
            if options["remove_server"]:
                selected += [path for path in (self.paths.server_config, self.paths.server_state) if _exists(path)]
        if not selected:
            raise ValueError("Die ausgewählten Kienzledoku-Komponenten wurden nicht gefunden.")
        return options

    def _server_runtime_paths(self, options):
        base = self.paths.server_base
        paths = [base / name for name in ("runtime", "python", "scripts", "src", "bin", "installer")]
        if options["remove_models"]:
            paths += [base / "models", base / "downloads"]
        return paths

    def _lock_file(self, stack, path: Path, label: str):
        self._safe_known_path(path, path.parent.parent if path.parent.name == "sessions" else path.parent,
                              label)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        handle = stack.enter_context(os.fdopen(os.open(path, flags, 0o600), "a+b"))
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError(label + " ist aktiv. Bitte zuerst den laufenden Vorgang beenden.") from None

    def _acquire_locks(self, stack, options):
        if options["remove_client"]:
            sessions = self.paths.client_config / "sessions"
            if sessions.is_symlink():
                raise ValueError("Der Sitzungsordner ist ein Symlink und wird nicht verändert.")
            locks = set(sessions.glob("*/record.lock")) if sessions.is_dir() else set()
            locks.add(sessions / "desktop/record.lock")
            for path in sorted(locks):
                self._lock_file(stack, path, "Eine Aufnahme")
        if options["remove_server"]:
            self._lock_file(stack, self.paths.server_state / "install.lock", "Eine Serverinstallation")

    def _remove(self, path: Path, base: Path):
        if not _exists(path):
            return
        self._safe_known_path(path, base, "Ein zu löschender Kienzledoku-Pfad")
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            shutil.rmtree(path)
        elif stat.S_ISREG(mode):
            path.unlink()
        else:
            raise ValueError("Ein unbekannter Dateityp wurde nicht entfernt.")

    def _run(self, argv):
        return self.runner([str(item) for item in argv], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _unregister_client(self):
        # Remove only this desktop entry from per-user protocol associations;
        # retain other applications and all unrelated settings/comments.
        for path in (self.paths.config_home/'mimeapps.list',self.paths.data_home/'applications/mimeapps.list'):
            if not path.is_file(): continue
            original=path.read_text();lines=[]
            for line in original.splitlines(keepends=True):
                key,sep,value=line.partition('=')
                schemes=('kienzledoku','kienzledoku-record','t2demo','whisperdoku')
                if sep and key.strip() in ('x-scheme-handler/'+name for name in schemes):
                    entries=[item for item in value.strip().split(';') if item]
                    if 'kienzledoku.desktop' in entries:
                        entries=[item for item in entries if item!='kienzledoku.desktop']
                        if entries: lines.append(key+'='+';'.join(entries)+';\n')
                        continue
                lines.append(line)
            updated=''.join(lines)
            if updated==original: continue
            fd,name=tempfile.mkstemp(prefix='.kienzledoku-mime-',dir=path.parent)
            try:
                with os.fdopen(fd,'w') as stream:stream.write(updated)
                os.chmod(name,path.stat().st_mode & 0o777);os.replace(name,path)
            finally:
                if os.path.exists(name):os.unlink(name)

    def execute(self, options):
        options = self.plan(options)
        with ExitStack() as stack:
            self._acquire_locks(stack, options)
            # Repeat all ownership checks after locks and immediately before mutation.
            self.plan(options)
            if options["remove_server"]:
                units = [name for name, path in self._unit_paths().items() if _exists(path)]
                slice_path = self.paths.systemd / SLICE
                systemd_changed = bool(units or _exists(slice_path))
                if units:
                    self._run(["systemctl", "disable", "--now", *units])
                for path in self._unit_paths().values():
                    self._remove(path, self.paths.systemd)
                self._remove(slice_path, self.paths.systemd)
                if systemd_changed:
                    self._run(["systemctl", "daemon-reload"])
                for path in self._server_runtime_paths(options):
                    self._remove(path, self.paths.server_base)
                if options["remove_settings"]:
                    self._remove(self.paths.server_config, self.paths.server_config.parent)
                    # The held install.lock keeps the state directory in place.
                    for path in list(self.paths.server_state.iterdir()):
                        if path.name != "install.lock":
                            self._remove(path, self.paths.server_state)
                try:
                    self.paths.server_base.rmdir()
                except OSError:
                    pass
            if options["remove_client"]:
                self._unregister_client()
                for path in self._client_artifacts():
                    base = self.paths.home if path == self.paths.launcher else self.paths.data_home
                    self._remove(path, base)
                if options["remove_settings"]:
                    # Do not remove the config directory while its lock is held.
                    for root, base in ((self.paths.client_config, self.paths.config_home),
                                       (self.paths.client_state, self.paths.state_home)):
                        if not _exists(root):
                            continue
                        self._safe_known_path(root, base, "Ein Client-Einstellungsordner")
                        for path in list(root.iterdir()):
                            if path.name != "sessions":
                                self._remove(path, root)
        # Locks are closed here. Remove only lock containers explicitly selected as settings.
        if options["remove_settings"] and options["remove_client"]:
            self._remove(self.paths.client_config, self.paths.config_home)
            self._remove(self.paths.client_state, self.paths.state_home)
        if options["remove_settings"] and options["remove_server"]:
            self._remove(self.paths.server_state, self.paths.server_state.parent)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--components", required=True, choices=("client", "server", "both"))
    parser.add_argument("--remove-models", action="store_true")
    parser.add_argument("--remove-settings", action="store_true")
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args(argv)
    if args.components in ("client", "both") and os.geteuid() == 0:
        raise ValueError("Den Desktop-Client als angemeldeter Desktop-Benutzer deinstallieren, nicht als root.")
    if args.components == "server" and os.geteuid() != 0:
        raise ValueError("Die Server-Deinstallation benötigt Administratorrechte.")
    options = Uninstaller.options(args.components, args.remove_models, args.remove_settings)
    uninstaller = Uninstaller()
    uninstaller.plan(options)
    if args.preflight:
        print("DEINSTALLATION_PREFLIGHT_OK")
        return 0
    uninstaller.execute(options)
    print("Kienzledoku-Deinstallation abgeschlossen.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError) as exc:
        print("Deinstallation nicht abgeschlossen: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
    except subprocess.CalledProcessError:
        print("Deinstallation nicht abgeschlossen: Ein Systemdienst konnte nicht entfernt werden.", file=sys.stderr)
        raise SystemExit(1)
    except (OSError, KeyboardInterrupt):
        print("Deinstallation nicht abgeschlossen. Bitte Pfade und Berechtigungen prüfen.", file=sys.stderr)
        raise SystemExit(1)
