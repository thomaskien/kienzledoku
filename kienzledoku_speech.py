#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gekapselte Kienzlefon-ASR-Anbindung für Kienzledoku 1.2.1.

Der Prozess verwendet den unveränderten Final-Block-Ablauf der v6.2-Basis.
Audio, Transkript und LLM-Rohantwort liegen nur in einem geschützten temporären
Verzeichnis und werden nach Abschluss wieder entfernt.
"""

from __future__ import print_function

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from types import SimpleNamespace

from kienzledoku_document import parse_documentation_json
from kienzledoku_asr_v6 import EVENT_PREFIX, call_llm


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


def load_service_urls(script_dir, config_path=None):
    """Load service targets; an installed config is the authoritative source."""
    config_path = os.path.abspath(
        config_path
        or os.path.join(os.path.abspath(script_dir), SERVICE_CONFIG_FILENAME)
    )
    configured = {}
    if os.path.isfile(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError) as exc:
            raise ValueError("Dienstkonfiguration kann nicht gelesen werden: %s" % exc)
        if not isinstance(payload, dict) or not isinstance(payload.get("services"), dict):
            raise ValueError("Dienstkonfiguration enthält keinen gültigen Block 'services'")
        configured = payload["services"]
        missing = [name for name in SERVICE_DEFINITIONS if name not in configured]
        if missing:
            raise ValueError(
                "Dienstkonfiguration ist unvollständig: %s" % ", ".join(missing)
            )

    urls = {}
    for name, definition in SERVICE_DEFINITIONS.items():
        if configured:
            value = configured[name]
        else:
            value = os.environ.get(
                definition["environment"], definition["default"]
            )
        urls[name] = validate_service_url(value, definition["label"])
    return urls


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
                "Kein Sprachsignal erkannt. Bitte Mikrofonzugriff für Kienzledoku "
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
        self.runner_path = os.path.join(self.script_dir, "start_kienzledoku_asr.sh")
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
        self.config_error = ""
        try:
            self.service_urls = load_service_urls(
                self.script_dir, config_path=self.config_path
            )
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
            device_label = "macOS-Standardgerät"
            for item in self.audio_devices:
                if str(item.get("index")) == self.selected_device:
                    device_label = item.get("name") or device_label
                    break
            return {
                "status": self.status,
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
        """Select an input device for the next recording; empty means CoreAudio default."""
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

    def start(self):
        with self.lock:
            if self.status in ACTIVE_STATUSES:
                raise ValueError("Die Spracherkennung läuft bereits")
            if self.config_error:
                raise RuntimeError(self.config_error)
            if not os.path.isfile(self.runner_path):
                raise RuntimeError("ASR-Startskript fehlt")
            if not os.path.isfile(self.prompt_path):
                raise RuntimeError("Kienzledoku-LLM-Prompt fehlt")

            self.live_blocks = {}
            self.run_base_transcript = self.live_transcript.strip()
            self.run_base_diarized = (
                self.diarized_text.strip() or self.run_base_transcript
            )
            is_continuation = bool(
                self.run_base_transcript or self.run_base_diarized
            )

            work_dir = tempfile.mkdtemp(prefix="kienzledoku-asr-")
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
            if is_continuation:
                # The runner would only document the new recording. Kienzledoku
                # instead runs the LLM once on the complete accumulated text.
                command.append("--no-llm")
            device = self.selected_device
            if device:
                command.extend(["--device", device])
            if os.environ.get("KIENZLEDOKU_NO_DIARIZATION", "").strip().lower() in (
                "1", "true", "yes",
            ):
                command.append("--no-diarization")

            child_env = os.environ.copy()
            child_env["PYTHONUNBUFFERED"] = "1"
            try:
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
                    start_new_session=True,
                )
            except Exception:
                shutil.rmtree(work_dir, ignore_errors=True)
                raise

            self.process = process
            self.work_dir = work_dir
            self.status = STATUS_RECORDING
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
            process = self.process
            if process is not None and process.poll() is None:
                try:
                    process.terminate()
                except Exception:
                    pass

    def _wait_for_result(
        self,
        process,
        json_path,
        work_dir,
        base_transcript,
        base_diarized,
        is_continuation,
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
                    "Kein Sprachsignal erkannt. Bitte Mikrofonzugriff für Kienzledoku "
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
            if is_continuation:
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
                    callback = self.on_document

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
            if event_type == "final_block":
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
                if phase == "diarization":
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
            elif event_type == "audio_devices":
                devices = []
                for item in event.get("devices") or []:
                    if not isinstance(item, dict):
                        continue
                    try:
                        index = int(item.get("index"))
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
                callback = self.on_document
        if callback is not None:
            try:
                callback(document)
            except Exception:
                with self.lock:
                    self.status = STATUS_ERROR
                    self.message = "LLM-Ergebnis konnte nicht in die Oberfläche übernommen werden"

    def _document_text(self, text):
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
