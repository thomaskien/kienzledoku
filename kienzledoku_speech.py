#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RAM-only microphone, ASR, diarization and documentation pipeline."""

from __future__ import print_function

import asyncio
import json
import os
import re
import kienzledoku_config as record_config
import threading
import time
import urllib.parse
import urllib.request
from types import SimpleNamespace
from kienzledoku_vad import AudioControls, dbfs

from kienzledoku_document import DEFAULT_DOCUMENT_FIELDS, parse_documentation_json
from kienzledoku_asr_v6 import (
    call_llm, diarize_audio, run_recording, speaker_transcript,
    speaker_transcript_words,
)
from kienzledoku_commander_client import CommanderRequestError, configured_client, profile_label


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


def continuation_marker(section):
    return ("### Aufnahme fortgesetzt – Abschnitt %d ###\n"
            "Sprecherzuordnung kann ab hier vom vorherigen Abschnitt abweichen." % section)


_CONTINUATION_RE = re.compile(
    r"(?:^|\n)### Aufnahme fortgesetzt – Abschnitt \d+ ###\n"
    r"Sprecherzuordnung kann ab hier vom vorherigen Abschnitt abweichen\.?(?:\n|$)")


def strip_continuation_markers(document):
    return {name: _CONTINUATION_RE.sub('\n', value).strip()
            for name, value in document.items()}


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


class NoSpeechDetected(Exception):
    pass


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
        self.prompt_path = os.path.join(self.script_dir, "prompt_documentation.txt")
        self.on_document = on_document
        self.lock = threading.RLock()
        self.process = None  # compatibility: Record 1.4 does not spawn an ASR child
        self.thread = None
        self.stop_event = None
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
        self.cancelled = False
        self.section_number = 0
        self.record_options = record_config.defaults()['record']
        self.selected_device = self.record_options['microphone'] or self.selected_device
        self.config_error = ""
        self.commander = None
        self.quality_profiles = []
        self.selected_quality = 'auto'
        self.commander_notice = ''
        self.requested_quality = ''
        self.used_quality = ''
        self.active_fields = DEFAULT_DOCUMENT_FIELDS
        self.active_prompt = ''
        self.prompt_template = ''
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
        self.audio_controls = AudioControls(self.record_options['vad_enabled'], self.record_options['silence_threshold_dbfs'])
        self.asr_url = self.service_urls["asr"]
        self.diarization_url = self.service_urls["diarization"]
        self.llm_url = self.service_urls["llm"]
        self.services = {}
        self.gpu_temperatures = []
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
        self.last_service_check = 0.0

    def set_audio_controls(self, enabled, threshold):
        AudioControls.validate(enabled, threshold)
        with self.lock:
            # Read latest technical configuration only for saving; other live
            # session objects retain their own controls snapshot.
            path = self.config_path if self.config_path.endswith('.toml') else os.path.splitext(self.config_path)[0] + '.toml'
            config = record_config.load(path)
            config['record']['vad_enabled'] = enabled
            config['record']['silence_threshold_dbfs'] = threshold
            record_config.save(config, path)
            self.audio_controls.update(enabled, threshold)
            return self.audio_controls.snapshot()

    def load_documentation_settings(self):
        if not self.commander:
            return
        settings = self.commander.documentation_settings()
        with self.lock:
            self.active_fields = tuple(settings['fields'])
            self.active_prompt = settings['prompt']
            self.prompt_template = settings['prompt_template']

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
                "audio_dbfs": round(dbfs(self.audio_rms), 1),
                **self.audio_controls.snapshot(),
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
                "active_fields": list(self.active_fields),
                "active_prompt": self.active_prompt,
                "gpu_temperatures": [dict(v) for v in self.gpu_temperatures],
                "services": {
                    name: dict(details) for name, details in self.services.items()
                },
            }

    def start_service_check(self, *, background=False):
        with self.lock:
            if self.health_thread is not None and self.health_thread.is_alive():
                return
            if background and time.monotonic() - self.last_service_check < 2:
                return
            self.last_service_check = time.monotonic()
            if self.config_error:
                self.service_status = "error"
                self.service_message = self.config_error
                for details in self.services.values():
                    details["status"] = "error"
                    details["message"] = self.config_error
                return
            if not background:
                self.service_status = "checking"
                self.service_message = "Commander-Dienste werden geprüft."
                for details in self.services.values():
                    details["status"] = "checking"
                    details["message"] = "%s wird geprüft." % details["label"]
            self.health_thread = threading.Thread(
                target=self._service_check_worker,
                kwargs={'refresh_profiles': not background},
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
            if self.commander and self.quality_profiles:
                self.set_quality(self.selected_quality)
            if not self.commander and not os.path.isfile(self.prompt_path):
                raise RuntimeError("Kienzledoku-LLM-Prompt fehlt")

            self.live_blocks = {}
            self.run_base_transcript = self.live_transcript.strip()
            self.run_base_diarized = self.diarized_text.strip() or self.run_base_transcript
            self.section_number += 1
            is_continuation = bool(self.run_base_transcript or self.run_base_diarized)
            if is_continuation:
                marker = continuation_marker(self.section_number)
                self.run_base_transcript = append_text(self.run_base_transcript, marker)
                self.run_base_diarized = append_text(self.run_base_diarized, marker)
                self.live_transcript = self.run_base_transcript
                self.diarized_text = self.run_base_diarized

            self.stop_event = threading.Event()
            self.cancel_event = threading.Event()
            self.status = STATUS_RECORDING
            self.commander_notice = ''
            self.requested_quality = ''
            self.used_quality = ''
            self.message = "Aufnahme läuft. Zum Beenden „Aufnahme stoppen“ drücken."
            self.started_at = time.time()
            self.thread = threading.Thread(
                target=self._run_ram_pipeline,
                args=(self.run_base_transcript, self.run_base_diarized, is_continuation),
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
            if self.status != STATUS_RECORDING or self.stop_event is None:
                raise ValueError("Es läuft keine Aufnahme")
            self.status = STATUS_PROCESSING
            self.message = "Aufnahme beendet. ASR, Diarisierung und Dokumentation werden abgeschlossen."
            self.stop_event.set()

    def cancel(self):
        with self.lock:
            self.cancelled = True
            if getattr(self, "cancel_event", None) is not None:
                self.cancel_event.set()
            self.on_document = None
            if self.stop_event is not None:
                self.stop_event.set()
        for thread in (self.thread,):
            if thread and thread.is_alive() and thread is not threading.current_thread():
                thread.join(timeout=5)

    def _recording_args(self):
        return SimpleNamespace(
            asr=self.asr_url, language='de', asr_api_key=(self.commander.token if self.commander else
                os.environ.get('KIENZLEDOKU_ASR_API_KEY')), asr_timeout=(self.commander.timeout if self.commander else 120.0),
            pause_seconds=.8, short_block_pause_seconds=1.5, min_block_seconds=4.0,
            max_block_seconds=20.0, context_seconds=.7, segment_frame_ms=30,
            audio_chunk_ms=100, status_seconds=5.0,
            input_wav=None, replay_speed=1.0, device=self.selected_device or None,
            wav='', json='', commander=(self.commander.url if self.commander else None),
            recording_finalized=False, commander_metadata=None, ram_only=True,
            quiet=True, audio_controls=self.audio_controls,
            stop_event=self.stop_event, cancel_event=getattr(self, "cancel_event", None), event_callback=self._handle_event,
        )

    def _run_ram_pipeline(self, base_transcript, base_diarized, is_continuation):
        document = None
        error_message = ""
        phase = 'recording'
        no_speech = False
        try:
            args = self._recording_args()
            payload = asyncio.run(run_recording(args))
            if self.cancelled:
                raise RuntimeError('Vorgang wurde verworfen.')
            new_transcript = str(payload.get("transcript") or "").strip()
            if not new_transcript:
                if payload.get('metrics', {}).get('failed'):
                    failures = [b.get('error') for b in payload.get('blocks', []) if b.get('error')]
                    raise ValueError(failures[0] if failures else 'Spracherkennung fehlgeschlagen. Einstellungen und Verbindung prüfen.')
                raise NoSpeechDetected()
            new_diarized = new_transcript
            # Preserve completed ASR in the editable field before speaker
            # assignment can fail. This also keeps physician edits in the base.
            with self.lock:
                self.live_transcript = append_text(base_transcript, new_transcript)
                self.diarized_text = append_text(base_diarized, new_transcript)
            if payload.get('metrics', {}).get('failed'):
                raise ValueError('Ein Audioblock konnte nicht verarbeitet werden. Der bisher erkannte Text bleibt erhalten; keine automatische Dokumentation.')
            use_diarization = (self.record_options['diarization'] and
                os.environ.get("KIENZLEDOKU_NO_DIARIZATION", "").strip().lower() not in ("1", "true", "yes"))
            if use_diarization:
                phase = 'diarization'
                self._handle_event({'type': 'phase', 'phase': 'diarization'})
                diarization = diarize_audio(
                    self.diarization_url, payload['_audio_wav'], 1, 4, None,
                    self.commander.timeout if self.commander else 300.0,
                    api_key=self.commander.token if self.commander else None,
                    recording_finalized=payload.get('recording_finalized') is True,
                    commander=bool(self.commander),
                )
                segments = diarization.get('segments') or []
                if payload.get('words'):
                    rendered, _paragraphs = speaker_transcript_words(payload['words'], segments)
                else:
                    rendered, _paragraphs = speaker_transcript(payload.get('segments') or [], segments)
                if rendered:
                    new_diarized = rendered
            if self.cancelled:
                raise RuntimeError('Vorgang wurde verworfen.')
            phase = 'documentation'
            combined_transcript = append_text(base_transcript, new_transcript)
            combined_diarized = append_text(base_diarized, new_diarized)
            with self.lock:
                self.live_transcript = combined_transcript
                self.diarized_text = combined_diarized
                self.speaker_labels = self.speaker_labels or new_diarized != new_transcript
                if is_continuation:
                    self.message = "Das gesamte Sprechertranskript wird neu dokumentiert."
            if self.commander and payload.get('recording_finalized') is not True:
                raise ValueError('Aufnahme noch nicht vollständig finalisiert; es wird keine Modellumschaltung angefordert.')
            self._handle_event({'type': 'phase', 'phase': 'llm'})
            if self.cancelled:
                raise RuntimeError('Vorgang wurde verworfen.')
            document = self._document_text(combined_diarized)
        except NoSpeechDetected:
            no_speech = True
        except Exception as exc:
            error_message = str(exc)
            if phase == 'diarization' and not self.cancelled:
                error_message += (' Der erkannte Text bleibt im Gesprächsfeld ohne neue '
                                  'Sprecherzuordnung erhalten. Bitte prüfen; die Dokumentation '
                                  'kann aus diesem Text erneut erstellt werden.')

        callback = None
        with self.lock:
            self.stop_event = None
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
                if no_speech:
                    self.message = 'Keine Sprache erkannt. Vorhandener Text bleibt erhalten; keine neue Dokumentation erstellt.'
                callback = None if self.cancelled or no_speech else self.on_document

        if callback is not None:
            try:
                callback(document)
            except Exception:
                with self.lock:
                    self.status = STATUS_ERROR
                    self.message = "ASR-Ergebnis konnte nicht in die Oberfläche übernommen werden"

    def _handle_event(self, event):
        if self.cancelled or not isinstance(event, dict):
            return
        event_type = event.get("type")
        with self.lock:
            if event_type == 'audio_level':
                self.audio_rms = int(event.get('rms') or 0)
            elif event_type == 'asr_error':
                self.message = 'Ein Audioblock konnte nicht verarbeitet werden. Aufnahme kann gestoppt werden; bereits erkannter Text bleibt erhalten.'
            elif event_type == 'recording_limit':
                self.status = STATUS_PROCESSING
                self.commander_notice = 'Zwei Stunden erreicht. Dieser Aufnahmeabschnitt wird abgeschlossen; danach kann die Aufnahme fortgesetzt werden.'
                self.message = self.commander_notice
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
                    self.status = STATUS_PROCESSING
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
                text, quality, self.quality_profiles, recording_finalized=True,
                fields=self.active_fields)
            with self.lock:
                self.commander_notice = metadata['notice']
                self.requested_quality = metadata['requested_quality']
                self.used_quality = metadata['used_quality']
            return strip_continuation_markers(document)
        args = SimpleNamespace(
            llm=self.llm_url,
            llm_api_key=os.environ.get("KIENZLEDOKU_LLM_API_KEY"),
            llm_model=os.environ.get("KIENZLEDOKU_LLM_MODEL"),
            prompt_file=self.prompt_path,
            temperature=0.1,
            max_tokens=1600,
        )
        return strip_continuation_markers(
            parse_documentation_json(call_llm(args, text), self.active_fields))

    def _configured_service_host(self):
        hosts = []
        for value in self.service_urls.values():
            host = urllib.parse.urlparse(value).hostname or ""
            if host and host not in hosts:
                hosts.append(host)
        return ", ".join(hosts) or "unbekannt"

    def _service_check_worker(self, refresh_profiles=True):
        if self.commander:
            try:
                if not self.active_prompt:
                    self.load_documentation_settings()
                if refresh_profiles:
                    self._refresh_quality_profiles()
                try:
                    runtime = self.commander.runtime_status()
                except CommanderRequestError as exc:
                    if exc.status != 404:
                        raise
                    self.commander.request('/health', timeout=3)
                    runtime = {name: {'state': 'ready', 'message': 'Commander erreichbar.'}
                               for name in ('asr', 'diar', 'llm')}
            except Exception as exc:
                with self.lock:
                    for details in self.services.values():
                        details['status'], details['message'] = 'error', str(exc)
                    self.gpu_temperatures = []
                    self.service_status, self.service_message = 'error', str(exc)
                return
            with self.lock:
                mapping = {'asr': 'asr', 'diarization': 'diar', 'llm': 'llm'}
                for local_name, remote_name in mapping.items():
                    item = runtime[remote_name]
                    if item.get('host'): self.services[local_name]['host'] = item['host']
                    self.services[local_name]['status'] = item['state']
                    self.services[local_name]['message'] = item['message']
                self.service_status = 'ok' if all(
                    item['state'] not in ('error', 'disabled') for item in runtime.values()) else 'error'
                self.service_message = 'Commander-Dienststatus aktualisiert.'
            try:
                temperatures = self.commander.gpu_temperatures()
                if not isinstance(temperatures,list): temperatures=[]
            except Exception:
                temperatures = []
            with self.lock:
                self.gpu_temperatures = temperatures
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
