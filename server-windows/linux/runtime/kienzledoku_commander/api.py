"""Lokale/LAN-HTTP-Schnittstelle; Aufzeichnungen und Prompts werden nie geloggt."""
import hmac
import io
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import socket
import threading
from urllib.parse import parse_qs, urlsplit, urlencode

from .config import LABELS
from .errors import BackendFailure, CommanderError, InvalidRequest, RecordingNotFinalized, PayloadTooLarge
FINALIZED_HEADER = "X-Kienzledoku-Recording-Finalized"
from kienzledoku_document import DOCUMENT_LABELS, validate_fields

MAX_JSON = 2 * 1024 * 1024
MAX_AUDIO = 256 * 1024 * 1024  # 2 h PCM mono/16 kHz/16-bit plus WAV overhead


class Unauthorized(CommanderError):
    code, status, message = "unauthorized", 401, "Ein gültiges Bearer-Token ist erforderlich."


def validate_audio_duration(body):
    try:
        with wave.open(io.BytesIO(body), 'rb') as audio:
            if audio.getnframes() > audio.getframerate() * 7200:
                raise PayloadTooLarge()
    except (wave.Error, EOFError):
        raise InvalidRequest() from None


def technical_contract(fields):
    example = json.dumps({field: "" for field in fields}, ensure_ascii=False, indent=2)
    labels = ", ".join("%s (%s)" % (field, DOCUMENT_LABELS[field]) for field in fields)
    return ("\n\nUnveränderlicher technischer Ausgabevertrag:\n"
            "Gib ausschließlich ein gültiges JSON-Objekt ohne Markdown oder Zusatztext aus. "
            "Es muss exakt die gewählten Textfelder in dieser Reihenfolge enthalten: %s. "
            "Nicht belegte Felder bleiben leere Zeichenketten. Keine weiteren Felder.\n%s" % (labels, example))


def active_prompt(template, fields):
    return template.rstrip() + technical_contract(fields)


class API(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64

    def __init__(self, address, commander):
        self.commander = commander
        self.upload_slots = threading.BoundedSemaphore(4)
        self.connection_slots = threading.BoundedSemaphore(128)
        self.token = os.environ.get(commander.settings.token_env, "") if commander.settings.auth_enabled else ""
        self.prompt_template = Path(commander.settings.prompt_path).read_text(encoding="utf-8")
        self.fields = tuple(commander.settings.enabled_fields)
        self.prompt = active_prompt(self.prompt_template, self.fields)
        self.profiles = None
        if ":" in address[0]:
            self.address_family = socket.AF_INET6
        super().__init__(address, Handler)

    def refresh_remote(self):
        commander = self.commander
        if commander.settings.remote_llm_url:
            try:
                remote_settings = commander.runtime.remote_get("/v1/documentation/settings")
                remote_profiles = commander.runtime.remote_get("/v1/runtime/profiles")
                self.fields = validate_fields(remote_settings["fields"])
                self.prompt = remote_settings["prompt"]
                self.prompt_template = remote_settings["prompt_template"]
                self.profiles = remote_profiles["data"]
                if (not isinstance(self.prompt, str) or not self.prompt or
                        not isinstance(self.prompt_template, str) or not self.prompt_template or
                        not isinstance(self.profiles, list) or
                        any(not isinstance(item, dict) for item in self.profiles)):
                    raise ValueError()
                allowed = tuple(item["id"] for item in self.profiles)
                if not allowed or len(set(allowed)) != len(allowed) or any(q not in LABELS for q in allowed):
                    raise ValueError()
                commander.runtime.remote_allowed = allowed
                remote_default = remote_settings.get("default_quality", allowed[0])
                if remote_default not in allowed:
                    raise ValueError()
                commander.runtime.remote_default = remote_default
            except (CommanderError, KeyError, TypeError, ValueError):
                raise BackendFailure("Remote-Commander-Metadaten sind nicht verfügbar.") from None

    def handle_error(self, request, client_address):
        # Python's default traceback may include contents of a request.
        pass

    def process_request(self, request, client_address):
        if not self.connection_slots.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.connection_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.connection_slots.release()


class Handler(BaseHTTPRequestHandler):
    server_version = "kienzledoku-commander/0.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    def log_message(self, format, *args):
        pass

    def send_error(self, code, message=None, explain=None):
        self._send(code, {"error": {"code": "http_error", "message": "Ungültige HTTP-Anfrage."}})

    def _send(self, status, value):
        body = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _auth(self):
        if not self.server.commander.settings.auth_enabled:
            return
        expected = self.server.token
        supplied = self.headers.get("Authorization", "")
        if not expected or not hmac.compare_digest(supplied.encode(), ("Bearer " + expected).encode()):
            raise Unauthorized()

    def _body(self, limit):
        if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) != 1:
            raise InvalidRequest()
        try:
            length = int(self.headers["Content-Length"])
        except ValueError:
            raise InvalidRequest() from None
        if length > limit:
            raise PayloadTooLarge()
        if length <= 0:
            raise InvalidRequest()
        with self.server.upload_slots:
            body = self.rfile.read(length)
        if len(body) != length:
            raise InvalidRequest()
        return body

    def _json(self):
        if self.headers.get_content_type() != "application/json":
            raise InvalidRequest()
        try:
            value = json.loads(self._body(MAX_JSON))
        except (ValueError, UnicodeError):
            raise InvalidRequest() from None
        if not isinstance(value, dict):
            raise InvalidRequest()
        return value

    def _id(self, value=None):
        header = self.headers.get("Idempotency-Key")
        if header and value and header != value:
            raise InvalidRequest()
        return header or value

    def _llm(self, value, extraction):
        cfg = self.server.commander.settings
        finalized = value.get("recording_finalized") if "recording_finalized" in value else self.headers.get(FINALIZED_HEADER) == "true"
        if finalized is not True:
            raise RecordingNotFinalized()
        hop = self.headers.get("X-Kienzledoku-Commander-Hop")
        if hop not in (None, "1"):
            raise InvalidRequest("Ungültiger Commander-Hop.")
        if hop and cfg.remote_llm_url:
            raise BackendFailure("Eine Commander-Weiterleitung darf nicht verkettet werden.")
        self.server.refresh_remote()
        if extraction:
            if set(value) - {"quality", "transcript", "request_id", "recording_finalized"}:
                raise InvalidRequest()
            text = value.get("transcript")
            if not isinstance(text, str) or not text.strip():
                raise InvalidRequest()
            quality = value.get("quality")
            if not cfg.remote_llm_url:
                quality = cfg.quality(quality)
            payload = {"messages": [{"role": "system", "content": self.server.prompt},
                {"role": "user", "content": text}], "temperature": 0, "max_tokens": 1600,
                "response_format": {"type": "json_object"}}
        else:
            known = {"model", "quality", "request_id", "messages", "stream", "temperature", "max_tokens",
                     "top_p", "top_k", "min_p", "repeat_penalty", "seed", "response_format", "cache_prompt", "recording_finalized"}
            if set(value) - known or value.get("stream", False) is not False:
                raise InvalidRequest()
            quality = value.get("quality") or value.get("model")
            if not cfg.remote_llm_url:
                quality = cfg.quality(quality)
            if value.get("quality") and value.get("model") and value["quality"] != value["model"]:
                raise InvalidRequest()
            messages = value.get("messages")
            if not isinstance(messages, list) or not messages or len(messages) > 256:
                raise InvalidRequest()
            for message in messages:
                if not isinstance(message, dict) or set(message) != {"role", "content"} or message["role"] not in ("system", "user", "assistant") or not isinstance(message["content"], str):
                    raise InvalidRequest()
            if not any(m["role"] == "user" and m["content"].strip() for m in messages):
                raise InvalidRequest()
            payload = {k: v for k, v in value.items() if k not in ("quality", "request_id", "model", "stream", "cache_prompt", "recording_finalized")}
            bounds = {"temperature": (0, 2), "max_tokens": (1, 4096), "top_p": (0, 1),
                      "top_k": (0, 200), "min_p": (0, 1), "repeat_penalty": (0, 2), "seed": (-1, 2147483647)}
            for key, (lower, upper) in bounds.items():
                if key in payload:
                    v = payload[key]
                    if type(v) not in (float, int) or not math.isfinite(v) or not lower <= v <= upper:
                        raise InvalidRequest()
                    if key in ("max_tokens", "top_k", "seed") and type(v) is not int:
                        raise InvalidRequest()
            if "response_format" in payload and payload["response_format"] != {"type": "json_object"}:
                raise InvalidRequest()
            payload.setdefault("max_tokens", 1600)
            payload["messages"] = [{"role": "system", "content": self.server.prompt}] + payload["messages"] + [
                {"role": "system", "content": technical_contract(self.server.fields)}]
        job_payload = {"llm": payload, "fields": self.server.fields, "hop": bool(hop)}
        if cfg.remote_llm_url:
            forwarded = dict(value)
            forwarded["recording_finalized"] = True
            job_payload["remote"] = {"path": "/v1/documentation/extract" if extraction else "/v1/chat/completions", "body": forwarded}
        result = self.server.commander.submit("llm", job_payload, quality, self._id(value.get("request_id"))).future.result()
        if extraction:
            return {"documentation": result["documentation"], "commander": result["commander"]}
        # OpenAI content uses the same selected documentation fields.
        completion = result["completion"]
        completion["commander"] = result["commander"]
        completion["model"] = result["commander"]["used_quality"]
        return completion

    def do_GET(self):
        self._handle(False)

    def do_POST(self):
        self._handle(True)

    def _handle(self, post):
        try:
            url = urlsplit(self.path)
            self._auth()
            hop = self.headers.get("X-Kienzledoku-Commander-Hop")
            if hop not in (None, "1"):
                raise InvalidRequest("Ungültiger Commander-Hop.")
            if hop and self.server.commander.settings.remote_llm_url:
                raise BackendFailure("Eine Commander-Weiterleitung darf nicht verkettet werden.")
            if not post and url.path == "/health" and not url.query:
                state = self.server.commander.status()
                healthy = self.server.commander.wait_ready(0)
                # Existing clients must keep recording/queuing during a planned
                # GPU pause. A paused model does not make its queue unavailable.
                self._send(200 if healthy else 503, {"status": "ok" if healthy else "starting",
                    "asr_ready": state["asr_ready"], "phase": state["phase"]})
                return
            if url.query and url.path != "/v1/diarize":
                raise InvalidRequest()
            if not post and url.path == "/v1/runtime/status":
                value = self.server.commander.status()
                if self.server.commander.settings.remote_llm_url:
                    try:
                        remote = self.server.commander.runtime.remote_get("/v1/runtime/status")
                    except CommanderError:
                        remote = {"services": {"llm": {"state": "error", "message": "Remote-Commander ist nicht erreichbar."}}}
                    value["services"]["llm"] = remote.get("services", {}).get("llm", {
                        "state": "error", "message": "Remote-Status ist unvollständig."})
                    value["remote_llm"] = {"services": remote.get("services", {}), "phase": remote.get("phase")}
            elif not post and url.path == "/v1/documentation/settings":
                self.server.refresh_remote()
                value = {"fields": list(self.server.fields), "prompt": self.server.prompt,
                         "prompt_template": self.server.prompt_template,
                         "default_quality": getattr(self.server.commander.runtime, "remote_default", self.server.commander.settings.default)}
            elif not post and url.path in ("/v1/models", "/v1/runtime/profiles"):
                self.server.refresh_remote()
                cfg = self.server.commander.settings
                if self.server.profiles is not None:
                    data = self.server.profiles
                else:
                    order = ([cfg.default] if cfg.default else []) + [q for q in cfg.allowed if q != cfg.default]
                    loaded=self.server.commander.status()["loaded"]["llm"]
                    loaded_profile=cfg.profile_id(loaded) if hasattr(cfg,"profile_id") and loaded else loaded
                    data = [{"id": q, "object": "model", "owned_by": "kienzledoku",
                        "label": LABELS.get(q, cfg.model(q).label), "model_id": cfg.model(q).model_id,
                        "model_label": cfg.model(q).label, "persistent": cfg.persistent(q),
                        "serial_available": True, "default": q == cfg.default,
                        "resident": (cfg.profile_id(q) if hasattr(cfg,"profile_id") else q) == getattr(cfg,"resident_quality",cfg.baseline_llm),
                        "loaded": (cfg.profile_id(q) if hasattr(cfg,"profile_id") else q) == loaded_profile,
                        "context_per_slot": cfg.model(q).context_per_slot,
                        "slots": cfg.model(q).slots, "fallback": cfg.fallback(q)} for q in order]
                value = {"object": "list", "data": data}
            elif post and url.path in ("/v1/documentation/extract", "/v1/chat/completions"):
                value = self._llm(self._json(), url.path.endswith("/extract"))
            elif post and url.path in ("/v1/asr/final-block", "/v1/diarize"):
                role = "asr" if url.path.endswith("final-block") else "diar"
                if role == "diar" and self.headers.get(FINALIZED_HEADER) != "true":
                    raise RecordingNotFinalized()
                mime = self.headers.get_content_type()
                if (role == "asr" and mime != "multipart/form-data") or (role == "diar" and mime not in ("audio/wav", "audio/x-wav", "application/octet-stream")):
                    raise InvalidRequest()
                query = parse_qs(url.query, keep_blank_values=True)
                if set(query) - {"num_speakers", "min_speakers", "max_speakers"}:
                    raise InvalidRequest()
                for values in query.values():
                    if len(values) != 1 or not values[0].isascii() or not values[0].isdigit() or not 1 <= int(values[0]) <= 32:
                        raise InvalidRequest()
                if "min_speakers" in query and "max_speakers" in query and int(query["min_speakers"][0]) > int(query["max_speakers"][0]):
                    raise InvalidRequest()
                body = self._body(MAX_AUDIO)
                if role == 'diar': validate_audio_duration(body)
                payload = {"body": body, "content_type": self.headers.get("Content-Type", ""),
                    "query": "?" + urlencode(query, doseq=True) if query else ""}
                job = self.server.commander.submit(role, payload, request_id=self._id())
                value = job.future.result()
            else:
                self._send(404, {"error": {"code": "not_found", "message": "Unbekannter Endpunkt."}})
                return
            self._send(200, value)
        except CommanderError as exc:
            self._send(exc.status, {"error": {"code": exc.code, "message": exc.message}})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass  # Work and restoration continue even if the HTTP client leaves.
        except Exception:
            self._send(503, {"error": {"code": "commander_error", "message": CommanderError.message}})
