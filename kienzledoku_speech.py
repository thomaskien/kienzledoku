#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gekapselte Kienzlefon-ASR-Anbindung für kienzledoku record 1.3.

Der Prozess verwendet den unveränderten Final-Block-Ablauf der v6.2-Basis.
Audio, Transkript und LLM-Rohantwort liegen nur in einem geschützten temporären
Verzeichnis und werden nach Abschluss wieder entfernt.
"""

from __future__ import print_function

import json
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
from kienzledoku_session import session_dir
import kienzledoku_config as record_config
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from types import SimpleNamespace

from kienzledoku_document import parse_documentation_json
from kienzledoku_asr_v6 import EVENT_PREFIX, call_llm
from kienzledoku_commander_client import configured_client, profile_label


STATUS_IDLE = "idle"
STATUS_RECORDING = "recording"
STATUS_PROCESSING = "processing"
STATUS_READY = "ready"
STATUS_ERROR = "error"
ACTIVE_STATUSES = (STATUS_RECORDING, STATUS_PROCESSING)

DEFAULT_ASR_URL = "http://127.0.0.1:8179"
DEFAULT_DIARIZATION_URL = "http://127.0.0.1:8183"
DEFAULT_LLM_URL = "http://127.0.0.1:8080"
SERVICE_CONFIG_FILENAME = "config.json"
SERVICE_DEFINITIONS = {
    "asr": {
        "label": "ASR",
        "environment": "KIENZLEDOKU_ASR_URL",
        "default": DEFAULT_ASR_URL,
    },
    "diarization": {
        "label": "Diarisierung",
        "environment": "KIENZLEDOKU_DIARIZATION_URL",
        "default": DEFAULT_DIARIZATION_URL,
    },
    "llm": {
        "label": "LLM",
        "environment": "KIENZLEDOKU_LLM_URL",
        "default": DEFAULT_LLM_URL,
    },
}


def validate_service_url(value, label="Dienst"):
    """Return a normalized HTTP(S) service URL or raise a readable error."""
    normalized = str(value or "").strip().rstrip("/")
    try:
        parsed = urllib.parse.urlparse(normalized)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("%s-Adresse ist ungültig: %s" % (label, exc))
    if parsed.scheme not in ("http", "https"):
        raise ValueError("%s-Adresse muss mit http:// oder https:// beginnen" % label)
    if not parsed.hostname:
        raise ValueError("%s-Adresse enthält keinen Hostnamen" % label)
    if port is None:
        raise ValueError("%s-Adresse enthält keinen Port" % label)
    if parsed.username or parsed.password:
        raise ValueError("%s-Adresse darf keine Zugangsdaten enthalten" % label)
    if parsed.query or parsed.fragment:
        raise ValueError("%s-Adresse darf keine Abfrage oder Sprungmarke enthalten" % label)
    return normalized


def load_service_urls(script_dir, config_path=None, include_commander=False):
    """Load service targets; an installed config is the authoritative source."""
    config_path = os.path.abspath(
        config_path
        or os.path.join(os.path.abspath(script_dir), SERVICE_CONFIG_FILENAME)
    )
    configured = {}
    commander = None
    if config_path.endswith('.toml'):
        payload = record_config.load(config_path)
        commander = configured_client(payload.get('commander'))
        configured = payload['services']
    elif os.path.isfile(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError) as exc:
            raise ValueError("Dienstkonfiguration kann nicht gelesen werden: %s" % exc)
        if not isinstance(payload, dict):
            raise ValueError("Dienstkonfiguration ist kein JSON-Objekt")
        commander = configured_client(payload.get('commander'))
        if commander:
            urls = {name: commander.url for name in SERVICE_DEFINITIONS}
            return (urls, commander) if include_commander else urls
        if not isinstance(payload.get("services"), dict):
            raise ValueError("Dienstkonfiguration enthält keinen gültigen Block 'services'")
        configured = payload["services"]
        missing = [name for name in SERVICE_DEFINITIONS if name not in configured]
        if missing:
            raise ValueError(
                "Dienstkonfiguration ist unvollständig: %s" % ", ".join(missing)
            )

    if commander:
        urls = {name: commander.url for name in SERVICE_DEFINITIONS}
        return (urls, commander) if include_commander else urls
    urls = {}
    for name, definition in SERVICE_DEFINITIONS.items():
        if configured:
            value = configured[name]
        else:
            value = os.environ.get(
                definition["environment"], definition["default"]
            )
        urls[name] = validate_service_url(value, definition["label"])
    return (urls, commander) if include_commander else urls


def append_text(existing, addition):
    parts = [str(value or "").strip() for value in (existing, addition)]
    return "\n\n".join(value for value in parts if value)


def documentation_from_asr_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError("ASR-Ergebnis ist kein JSON-Objekt")
    llm_value = payload.get("llm")
    if llm_value is None or (isinstance(llm_value, str) and not llm_value.strip()):
        transcript = str(payload.get("transcript") or "").strip()
        if not transcript:
            raise ValueError(
                "Kein Sprachsignal erkannt. Bitte Mikrofonzugriff für kienzledoku record "
                "erlauben, das Eingabegerät prüfen und die Aufnahme wiederholen."
            )
        raise ValueError("Die Spracherkennung enthält keine LLM-Dokumentation")
    return parse_documentation_json(llm_value)


class SpeechRecognitionManager(object):
    """Run exactly one local microphone/ASR pipeline per T2med session."""

    def __init__(self, script_dir, on_document=None, config_path=None):
        self.script_dir = os.path.abspath(script_dir)
        self.config_path = os.path.abspath(
            config_path
            or os.path.join(self.script_dir, SERVICE_CONFIG_FILENAME)
        )
        self.config_source = (
            self.config_path
            if os.path.isfile(self.config_path)
            else "Lokale Standardwerte"
        )
        self.native_python = sys.platform == "win32" or importlib.util.find_spec("sounddevice") is not None
        self.runner_path = os.path.join(self.script_dir, "kienzledoku_asr_v6.py" if self.native_python else "start_kienzledoku_asr.sh")
        self.prompt_path = os.path.join(self.script_dir, "prompt_documentation.txt")
        self.on_document = on_document
        self.lock = threading.RLock()
        self.process = None
        self.thread = None
        self.work_dir = None
        self.status = STATUS_IDLE
        self.message = "Bereit für die Aufnahme."
        self.started_at = None
        self.live_blocks = {}
        self.live_transcript = ""
        self.diarized_text = ""
        self.speaker_labels = False
        self.run_base_transcript = ""
        self.run_base_diarized = ""
        self.audio_devices = []
        self.selected_device = os.environ.get(
            "KIENZLEDOKU_AUDIO_DEVICE", ""
        ).strip()
        self.audio_rms = 0
        self.interrupted_audio = ''
        self.cancelled = False
        self.record_options = record_config.defaults()['record']
        self.selected_device = self.record_options['microphone'] or self.selected_device
        self.config_error = ""
        self.commander = None
        self.quality_profiles = []
        self.selected_quality = 'auto'
        self.commander_notice = ''
        self.requested_quality = ''
        self.used_quality = ''
        try:
            if self.config_path.endswith('.toml'):
                self.record_options = record_config.load(self.config_path)['record']
                self.selected_device = self.record_options['microphone'] or self.selected_device
            self.service_urls, self.commander = load_service_urls(
                self.script_dir, config_path=self.config_path, include_commander=True
            )
            if self.commander:
                self.selected_quality = self.commander.default_quality
        except ValueError as exc:
            self.config_error = str(exc)
            self.service_urls = {
                name: definition["default"]
                for name, definition in SERVICE_DEFINITIONS.items()
            }
        self.asr_url = self.service_urls["asr"]
        self.diarization_url = self.service_urls["diarization"]
        self.llm_url = self.service_urls["llm"]
        self.services = {}
        for name, definition in SERVICE_DEFINITIONS.items():
            url = self.service_urls[name]
            self.services[name] = {
                "label": definition["label"],
                "url": url,
                "host": urllib.parse.urlparse(url).hostname or "unbekannt",
                "status": "error" if self.config_error else "checking",
                "message": self.config_error or "%s wird geprüft." % definition["label"],
            }
        self.service_status = "error" if self.config_error else "checking"
        self.service_message = self.config_error or "Kienzlefon-Dienste werden geprüft."
        self.service_host = self._configured_service_host()
        self.health_thread = None

    def snapshot(self):
        with self.lock:
            elapsed = 0
            if self.started_at is not None and self.status in ACTIVE_STATUSES:
                elapsed = max(0, int(time.time() - self.started_at))
            device_label = "System-Standardgerät"
            for item in self.audio_devices:
                if str(item.get("index")) == self.selected_device:
                    device_label = item.get("name") or device_label
                    break
            return {
                "status": self.status,
                "audio_rms": self.audio_rms,
                "interrupted_audio": self.interrupted_audio or (os.path.join(self.work_dir, "aufnahme.wav.partial.wav") if self.work_dir else ""),
                "audio_base_transcript": self.run_base_transcript,
                "audio_base_diarized": self.run_base_diarized,
                "message": self.message,
                "elapsed_seconds": elapsed,
                "active": self.status in ACTIVE_STATUSES,
                "live_transcript": self.live_transcript,
                "diarized_text": self.diarized_text,
                "speaker_labels": self.speaker_labels,
                "can_regenerate": bool(self.diarized_text.strip()) and self.status not in ACTIVE_STATUSES,
                "audio_devices": list(self.audio_devices),
                "selected_device": self.selected_device,
                "selected_device_name": device_label,
                "service_status": self.service_status,
                "service_message": self.service_message,
                "service_host": self.service_host,
                "config_source": self.config_source,
                "commander_enabled": self.commander is not None,
                "quality_profiles": [dict(profile) for profile in self.quality_profiles],
                "selected_quality": self.selected_quality,
                "commander_notice": self.commander_notice,
                "requested_quality_label": profile_label(self.requested_quality, self.quality_profiles) if self.requested_quality else '',
                "used_quality_label": profile_label(self.used_quality, self.quality_profiles) if self.used_quality else '',
                "services": {
                    name: dict(details) for name, details in self.services.items()
                },
            }

    def start_service_check(self):
        with self.lock:
            if self.health_thread is not None and self.health_thread.is_alive():
                return
            if self.config_error:
                self.service_status = "error"
                self.service_message = self.config_error
                for details in self.services.values():
                    details["status"] = "error"
                    details["message"] = self.config_error
                return
            self.service_status = "checking"
            self.service_message = "Kienzlefon-Dienste werden geprüft."
            for details in self.services.values():
                details["status"] = "checking"
                details["message"] = "%s wird geprüft." % details["label"]
            self.health_thread = threading.Thread(
                target=self._service_check_worker,
                name="Kienzledoku-Servicecheck",
            )
            self.health_thread.daemon = True
            self.health_thread.start()

    def set_audio_device(self, device):
        """Select an input device for the next recording; empty means OS default."""
        value = str(device or "").strip()
        with self.lock:
            if self.status in ACTIVE_STATUSES:
                raise ValueError("Das Mikrofon kann während einer Aufnahme nicht gewechselt werden")
            valid = {str(item.get("index")) for item in self.audio_devices}
            if value and self.audio_devices and value not in valid:
                raise ValueError("Das gewählte Mikrofon ist nicht mehr verfügbar")
            self.selected_device = value

    def set_diarized_text(self, text):
        """Keep physician edits as the base for a continued recording."""
        value = str(text or "").strip()
        with self.lock:
            if self.status in ACTIVE_STATUSES:
                raise ValueError("Das Sprechertranskript kann während der Verarbeitung nicht ersetzt werden")
            self.diarized_text = value

    def _refresh_quality_profiles(self):
        profiles = self.commander.profiles()
        with self.lock:
            self.quality_profiles = profiles
            allowed = [profile['id'] for profile in profiles]
            if self.selected_quality != 'auto' and self.selected_quality not in allowed:
                raise ValueError('Die eingestellte Qualitätsstufe ist auf diesem Server nicht erlaubt.')

    def set_quality(self, quality):
        with self.lock:
            if not self.commander:
                if quality not in (None, '', 'auto'):
                    raise ValueError('Qualitätswahl benötigt den Commander.')
                return
            if self.status == STATUS_PROCESSING:
                raise ValueError('Die Qualitätsstufe kann während der Verarbeitung nicht geändert werden.')
            value = str(quality or self.selected_quality)
            if value != 'auto' and value not in [profile['id'] for profile in self.quality_profiles]:
                raise ValueError('Diese Qualitätsstufe ist auf diesem Server nicht erlaubt.')
            self.selected_quality = value  # Selecting never sends a model-load request.

    def start(self):
        with self.lock:
            self.cancelled = False
            if self.status in ACTIVE_STATUSES:
                raise ValueError("Die Spracherkennung läuft bereits")
            if self.config_error:
                raise RuntimeError(self.config_error)
            if self.commander and not self.quality_profiles:
                self._refresh_quality_profiles()
            if self.commander:
                self.set_quality(self.selected_quality)
            if not os.path.isfile(self.runner_path):
                raise RuntimeError("ASR-Startskript fehlt")
            if not os.path.isfile(self.prompt_path):
                raise RuntimeError("Kienzledoku-LLM-Prompt fehlt")

            self.live_blocks = {}
            replay_source = self.interrupted_audio
            if not replay_source:
                self.run_base_transcript = self.live_transcript.strip()
                self.run_base_diarized = (
                    self.diarized_text.strip() or self.run_base_transcript
                )
            # A replay replaces the interrupted segment. Only text from recordings
            # completed before that segment is prepended, avoiding duplicate speech.
            is_continuation = bool(
                self.run_base_transcript or self.run_base_diarized
            )

            work_dir = tempfile.mkdtemp(prefix="audio-", dir=str(session_dir()))
            os.chmod(work_dir, 0o700)
            wav_path = os.path.join(work_dir, "aufnahme.wav")
            json_path = os.path.join(work_dir, "ergebnis.json")

            command = [
                self.runner_path,
                "--asr", self.asr_url,
                "--diarization", self.diarization_url,
                "--llm", self.llm_url,
                "--prompt-file", self.prompt_path,
                "--wav", wav_path,
                "--json", json_path,
            ]
            if self.native_python:
                # pythonw is fine for the UI; the child must expose stdin/stdout.
                executable = os.path.join(os.path.dirname(sys.executable), 'python.exe') if sys.platform == 'win32' else sys.executable
                command.insert(0, executable)
            if self.interrupted_audio:
                command.extend(['--input-wav', self.interrupted_audio, '--replay-speed', '0'])
            if not self.record_options['diarization']:
                command.append('--no-diarization')
            if is_continuation or self.commander:
                # The runner would only document the new recording. Kienzledoku
                # instead runs the LLM once on the complete accumulated text.
                command.append("--no-llm")
            if self.commander:
                command.extend([
                    '--commander', self.commander.url,
                    '--commander-token-env', self.commander.token_env,
                    '--commander-timeout', str(self.commander.timeout),
                ])
            device = self.selected_device
            if device:
                command.extend(["--device", device])
            if os.environ.get("KIENZLEDOKU_NO_DIARIZATION", "").strip().lower() in (
                "1", "true", "yes",
            ):
                command.append("--no-diarization")

            child_env = os.environ.copy()
            child_env["PYTHONUNBUFFERED"] = "1"
            child_env["PYTHONIOENCODING"] = "utf-8"
            try:
                if self.commander:
                    child_env[self.commander.token_env] = self.commander.token
                process = subprocess.Popen(
                    command,
                    cwd=self.script_dir,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=child_env,
                    start_new_session=sys.platform != "win32",
                    **({"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}),
                )
            except Exception:
                shutil.rmtree(work_dir, ignore_errors=True)
                raise

            self.process = process
            self.work_dir = work_dir
            self.status = STATUS_RECORDING
            self.commander_notice = ''
            self.requested_quality = ''
            self.used_quality = ''
            self.message = "Aufnahme läuft. Zum Beenden „Aufnahme stoppen“ drücken."
            self.started_at = time.time()
            self.thread = threading.Thread(
                target=self._wait_for_result,
                args=(
                    process,
                    json_path,
                    work_dir,
                    self.run_base_transcript,
                    self.run_base_diarized,
                    is_continuation,
                    replay_source,
                ),
                name="Kienzledoku-ASR",
            )
            self.thread.daemon = True
            self.thread.start()

    def regenerate(self, diarized_text):
        text = str(diarized_text or "").strip()
        if not text:
            raise ValueError("Das Diarisierungsfeld ist leer")
        with self.lock:
            if self.status in ACTIVE_STATUSES:
                raise ValueError("Spracherkennung oder LLM-Verarbeitung läuft bereits")
            self.diarized_text = text
            self.commander_notice = ''
            self.requested_quality = ''
            self.used_quality = ''
            self.status = STATUS_PROCESSING
            self.message = "Bearbeitetes Sprechertranskript wird erneut dokumentiert."
            self.started_at = time.time()
            self.thread = threading.Thread(
                target=self._regenerate_worker,
                args=(text,),
                name="Kienzledoku-LLM",
            )
            self.thread.daemon = True
            self.thread.start()

    def stop(self):
        with self.lock:
            if self.status != STATUS_RECORDING or self.process is None:
                raise ValueError("Es läuft keine Aufnahme")
            process = self.process
            self.status = STATUS_PROCESSING
            self.message = "Aufnahme beendet. ASR, Diarisierung und Dokumentation werden abgeschlossen."
            try:
                process.stdin.write("\n")
                process.stdin.flush()
            except Exception:
                if process.poll() is None:
                    raise RuntimeError("Die Aufnahme konnte nicht beendet werden")

    def cancel(self):
        with self.lock:
            self.cancelled = True
            self.on_document = None
            process = self.process
            if process is not None and process.poll() is None:
                try:
                    process.terminate()
                except Exception:
                    pass
        if process is not None:
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait()
        for thread in (self.thread,):
            if thread and thread.is_alive() and thread is not threading.current_thread():
                thread.join(timeout=5)

    def _wait_for_result(
        self,
        process,
        json_path,
        work_dir,
        base_transcript,
        base_diarized,
        is_continuation,
        replay_source='',
    ):
        document = None
        error_message = ""
        try:
            # Drain without storing: output can contain transcript text. Using
            # communicate() here would close stdin and stop recording at once.
            for line in process.stdout:
                if line.startswith(EVENT_PREFIX):
                    try:
                        self._handle_event(json.loads(line[len(EVENT_PREFIX):]))
                    except Exception:
                        pass
            process.wait()
            if process.returncode != 0:
                raise RuntimeError(
                    "Spracherkennung fehlgeschlagen (Prozesscode %s)"
                    % process.returncode
                )
            with open(json_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            new_transcript = str(payload.get("transcript") or "").strip()
            if not new_transcript:
                raise ValueError(
                    "Kein Sprachsignal erkannt. Bitte Mikrofonzugriff für kienzledoku record "
                    "erlauben, das Eingabegerät prüfen und die Aufnahme wiederholen."
                )
            new_diarized = str(
                payload.get("speaker_transcript") or new_transcript
            ).strip()
            combined_transcript = append_text(base_transcript, new_transcript)
            combined_diarized = append_text(base_diarized, new_diarized)
            with self.lock:
                self.live_transcript = combined_transcript
                self.diarized_text = combined_diarized
                self.speaker_labels = (
                    self.speaker_labels or bool(payload.get("speaker_transcript"))
                )
                if is_continuation:
                    self.message = "Das gesamte Sprechertranskript wird neu dokumentiert."
            if self.commander and payload.get('recording_finalized') is not True:
                raise ValueError('Aufnahme noch nicht vollständig finalisiert; es wird keine Modellumschaltung angefordert.')
            if is_continuation or self.commander:
                document = self._document_text(combined_diarized)
            else:
                document = documentation_from_asr_payload(payload)
        except Exception as exc:
            error_message = str(exc)
        finally:
            for stream in (process.stdin, process.stdout):
                try:
                    if stream is not None:
                        stream.close()
                except Exception:
                    pass
            if error_message:
                partial = os.path.join(work_dir, 'aufnahme.wav.partial.wav')
                if replay_source and os.path.isfile(replay_source):
                    self.interrupted_audio = replay_source
                elif os.path.isfile(partial):
                    self.interrupted_audio = partial
            else:
                self.interrupted_audio = ''
                if replay_source:
                    old_dir = Path(replay_source).parent
                    if old_dir.parent.resolve() == session_dir().resolve() and old_dir.name.startswith('audio-'):
                        shutil.rmtree(old_dir, ignore_errors=True)
                shutil.rmtree(work_dir, ignore_errors=True)

        callback = None
        with self.lock:
            if self.process is process:
                self.process = None
                self.work_dir = None
                self.started_at = None
                if error_message:
                    self.status = STATUS_ERROR
                    self.message = error_message
                else:
                    self.status = STATUS_READY
                    self.message = (
                        "Spracherkennung und Dokumentation abgeschlossen. Texte können "
                        "geprüft oder erneut an das LLM gesendet werden."
                    )
                    callback = None if self.cancelled else self.on_document

        if callback is not None:
            try:
                callback(document)
            except Exception:
                with self.lock:
                    self.status = STATUS_ERROR
                    self.message = "ASR-Ergebnis konnte nicht in die Oberfläche übernommen werden"

    def _handle_event(self, event):
        if not isinstance(event, dict):
            return
        event_type = event.get("type")
        with self.lock:
            if event_type == 'audio_level':
                self.audio_rms = int(event.get('rms') or 0)
            elif event_type == "final_block":
                block_id = int(event.get("block_id") or 0)
                self.live_blocks[block_id] = str(event.get("text") or "").strip()
                current_text = " ".join(
                    self.live_blocks[key]
                    for key in sorted(self.live_blocks)
                    if self.live_blocks[key]
                ).strip()
                self.live_transcript = append_text(
                    self.run_base_transcript, current_text
                )
            elif event_type == "phase":
                phase = event.get("phase")
                if phase == 'audio_stopped':
                    self.message = 'Aufnahme beendet. Letzte ASR-Blöcke werden noch abgeschlossen.'
                elif phase == 'recording_finalized':
                    self.message = 'Aufnahme beendet; letzte ASR-Blöcke abgeschlossen.'
                elif phase == "diarization":
                    self.message = "Aufnahme beendet. Sprecher werden zugeordnet."
                elif phase == "llm":
                    self.message = "Sprechertranskript wird medizinisch dokumentiert."
            elif event_type == "diarization":
                self.diarized_text = append_text(
                    self.run_base_diarized,
                    str(event.get("text") or "").strip(),
                )
                self.speaker_labels = (
                    self.speaker_labels or bool(event.get("speaker_labels"))
                )
            elif event_type == 'commander_result':
                self.commander_notice = str(event.get('notice') or '')
                self.requested_quality = str(event.get('requested_quality') or '')
                self.used_quality = str(event.get('used_quality') or '')
            elif event_type == "audio_devices":
                devices = []
                for item in event.get("devices") or []:
                    if not isinstance(item, dict):
                        continue
                    try:
                        index = str(item.get("index"))
                    except (TypeError, ValueError):
                        continue
                    name = str(item.get("name") or index).strip()
                    devices.append({"index": index, "name": name[:160]})
                self.audio_devices = devices
                if not self.selected_device and event.get("selected") is not None:
                    self.selected_device = str(event.get("selected"))

    def _regenerate_worker(self, text):
        document = None
        error_message = ""
        try:
            document = self._document_text(text)
        except Exception as exc:
            error_message = str(exc)

        callback = None
        with self.lock:
            self.started_at = None
            if error_message:
                self.status = STATUS_ERROR
                self.message = "Erneute LLM-Dokumentation fehlgeschlagen: %s" % error_message
            else:
                self.status = STATUS_READY
                self.message = "Dokumentation aus dem bearbeiteten Sprechertranskript aktualisiert."
                callback = None if self.cancelled else self.on_document
        if callback is not None:
            try:
                callback(document)
            except Exception:
                with self.lock:
                    self.status = STATUS_ERROR
                    self.message = "LLM-Ergebnis konnte nicht in die Oberfläche übernommen werden"

    def _document_text(self, text):
        if self.commander:
            with self.lock:
                if self.status == STATUS_RECORDING:
                    raise ValueError('Die Aufnahme läuft noch. Zuerst die Aufnahme beenden.')
                quality = self.selected_quality
            if not self.quality_profiles:
                self._refresh_quality_profiles()
            document, metadata = self.commander.extract(
                text, quality, self.quality_profiles, recording_finalized=True)
            with self.lock:
                self.commander_notice = metadata['notice']
                self.requested_quality = metadata['requested_quality']
                self.used_quality = metadata['used_quality']
            return document
        args = SimpleNamespace(
            llm=self.llm_url,
            llm_api_key=os.environ.get("KIENZLEDOKU_LLM_API_KEY"),
            llm_model=os.environ.get("KIENZLEDOKU_LLM_MODEL"),
            prompt_file=self.prompt_path,
            temperature=0.1,
            max_tokens=1600,
        )
        return parse_documentation_json(call_llm(args, text))

    def _configured_service_host(self):
        hosts = []
        for value in self.service_urls.values():
            host = urllib.parse.urlparse(value).hostname or ""
            if host and host not in hosts:
                hosts.append(host)
        return ", ".join(hosts) or "unbekannt"

    def _service_check_worker(self):
        if self.commander:
            try:
                self._refresh_quality_profiles()
                self.commander.request('/health', timeout=3)
                message = 'Commander erreichbar. Audioaufträge können angenommen werden.'
                status = 'ok'
            except Exception as exc:
                message, status = str(exc), 'error'
            with self.lock:
                for details in self.services.values():
                    details['status'], details['message'] = status, message
                self.service_status, self.service_message = status, message
            return
        llm_base = self.llm_url.rstrip("/")
        llm_models_url = (
            llm_base + "/models"
            if urllib.parse.urlparse(llm_base).path.rstrip("/").endswith("/v1")
            else llm_base + "/v1/models"
        )
        checks = (
            ("asr", self.asr_url.rstrip("/") + "/health"),
            ("diarization", self.diarization_url.rstrip("/") + "/health"),
            ("llm", llm_models_url),
        )
        errors = []
        for name, url in checks:
            reachable = False
            try:
                request = urllib.request.Request(
                    url, headers={"Accept": "application/json"}, method="GET"
                )
                with urllib.request.urlopen(request, timeout=3) as response:
                    reachable = 200 <= int(response.getcode()) < 300
            except Exception:
                reachable = False
            if not reachable:
                errors.append(name)
            with self.lock:
                details = self.services[name]
                details["status"] = "ok" if reachable else "error"
                details["message"] = (
                    "%s erreichbar." if reachable else "%s nicht erreichbar."
                ) % details["label"]
        with self.lock:
            if errors:
                self.service_status = "error"
                self.service_message = "Nicht alle Kienzlefon-Dienste sind erreichbar."
            else:
                self.service_status = "ok"
                self.service_message = "ASR, Diarisierung und LLM erreichbar."
