"""Echte Worker-Sockets und ein ausschließlich vom Commander verwaltetes LLM."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, ProxyHandler, HTTPRedirectHandler, build_opener

from kienzledoku_document import parse_documentation_json
from .errors import BackendFailure, Busy

MAX_REPLY = 32 * 1024 * 1024


class LocalOnly(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Validated local destinations must not redirect medical data elsewhere.


def document(raw):
    try:
        parsed = parse_documentation_json(raw)
        text = raw.strip()
        if text.startswith("```") and text.endswith("```"):
            text = "\n".join(text.splitlines()[1:-1]).strip()
        original = json.loads(text)
        if any(not isinstance(v, str) for v in original.values()):
            raise ValueError("Nicht alle Werte sind Text")
        for value in parsed.values():
            value.encode("utf-8")
        return parsed
    except (ValueError, TypeError, AttributeError):
        raise BackendFailure("Das LLM hat keine vollständige Vier-Felder-Dokumentation geliefert.") from None


class Runtime:
    def __init__(self, settings):
        self.settings = settings
        self.process = None
        self.model = None
        self.log = None
        self.http = build_opener(ProxyHandler({}), LocalOnly())

    def control(self, role, operation):
        payload = {"operation": operation}
        if role == "diar" and operation == "load":
            payload["allocator_mib"] = self.settings.diar_allocator_mib
        directory = self.settings.diar_control_dir if role == "diar" and self.settings.diar_control_dir else self.settings.control_dir
        path = str(Path(directory) / ("whisper.sock" if role == "asr" else "diarization.sock"))
        try:
            with socket.socket(socket.AF_UNIX) as connection:
                connection.settimeout(self.settings.control_timeout)
                connection.connect(path)
                connection.sendall((json.dumps(payload) + "\n").encode())
                with connection.makefile("rb") as f:
                    line = f.readline(65537)
                if not line or len(line) > 65536:
                    raise ValueError("Ungültige Steuerantwort")
                response = json.loads(line)
            if response.get("code") == "model_in_use":
                raise Busy()
            if response.get("ok") is not True:
                raise BackendFailure("Die Worker-Steuerung konnte den Modellwechsel nicht abschließen.")
            state = response["state"]
            if not isinstance(state, dict):
                raise ValueError("Ungültiger Worker-Zustand")
            if operation in ("load", "park") and (state.get("loaded") is not (operation == "load") or state.get("ready") is not (operation == "load")):
                raise ValueError("Worker bestätigt den gewünschten Zustand nicht")
            return state
        except Busy:
            raise
        except (OSError, ValueError, KeyError, BackendFailure):
            raise BackendFailure("Die Worker-Steuerung ist nicht verfügbar.") from None

    def load_asr(self):
        self.control("asr", "load")

    def park_asr(self):
        self.control("asr", "park")

    def load_diar(self):
        self.control("diar", "load")

    def park_diar(self):
        self.control("diar", "park")

    def _http(self, url, body=None, content_type="application/json", timeout=None, token=None):
        headers = {"Content-Type": content_type}
        if token:
            headers["Authorization"] = "Bearer " + token
        try:
            with self.http.open(Request(url, data=body, headers=headers), timeout=timeout or self.settings.backend_timeout) as response:
                result = response.read(MAX_REPLY + 1)
                if len(result) > MAX_REPLY:
                    raise BackendFailure()
                return json.loads(result)
        except (OSError, ValueError, HTTPError, URLError):
            # Backend errors can echo a prompt, filename or transcript. Never expose them.
            raise BackendFailure() from None

    def load_llm(self, quality):
        if self.process is not None:
            if self.model == quality and self.process.poll() is None:
                return
            raise BackendFailure("Vor dem Modellstart muss das vorherige LLM freigegeben sein.")
        spec = self.settings.model(quality)
        if not Path(spec.path).is_file() or not os.access(spec.path, os.R_OK):
            raise BackendFailure("Die Modelldatei ist nicht verfügbar.")
        address = urlsplit(self.settings.llm_url)
        # Never attach to or kill a process started by another service.
        try:
            with socket.create_connection((address.hostname, address.port), timeout=.2):
                raise BackendFailure("Der interne LLM-Port wird bereits von einem anderen Dienst verwendet.")
        except OSError:
            pass
        argv = [self.settings.llama_binary, "--model", spec.path, "--alias", quality,
            "--host", address.hostname, "--port", str(address.port),
            "--parallel", str(spec.slots), "--ctx-size", str(spec.context), "--n-gpu-layers", "999",
            "--reasoning", "off", "--reasoning-format", "deepseek",
            "--chat-template-kwargs", '{"enable_thinking":false}', "--no-mmproj", "--jinja",
            "--cache-type-k", spec.kv, "--cache-type-v", spec.kv,
            "--flash-attn", "on", "--fit", "off", "--cont-batching",
            "--top-k", "40", "--top-p", "0.95", "--min-p", "0.05", "--repeat-penalty", "1.0",
            "--log-disable"]
        # llama.cpp can log request bodies at verbose levels. No medical server output is retained.
        env = dict(os.environ)
        env["CUDA_VISIBLE_DEVICES"] = str(self.settings.gpu_index)
        try:
            self.process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, start_new_session=True, env=env)
            start = time.monotonic()
            while True:
                if self.process.poll() is not None:
                    raise BackendFailure("Das LLM konnte nicht gestartet werden.")
                try:
                    health = self._http(self.settings.llm_url + "/health", timeout=1)
                    if health.get("status") == "ok":
                        props = self._http(self.settings.llm_url + "/props", timeout=1)
                        if Path(props.get("model_path", "")).resolve() != Path(spec.path).resolve():
                            raise BackendFailure("Das Backend meldet ein anderes Modell.")
                        self.model = quality
                        return
                except BackendFailure:
                    pass
                if time.monotonic() - start > self.settings.load_timeout:
                    raise BackendFailure("Das LLM wurde nicht rechtzeitig bereit.")
                time.sleep(.05)
        except (OSError, BackendFailure):
            self.stop_llm()
            raise BackendFailure("Das LLM konnte nicht geladen werden.") from None

    def stop_llm(self):
        proc = self.process
        if proc is None:
            self.model = None
            return
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait(timeout=15)
        else:
            proc.wait()
        self.process = None
        self.model = None

    def infer(self, job):
        if job.role == "asr":
            return self._http(self.settings.asr_url + "/v1/asr/final-block", job.payload["body"],
                job.payload["content_type"], token=os.environ.get("KIENZLEDOKU_COMMANDER_ASR_TOKEN"))
        if job.role == "diar":
            return self._http(self.settings.diar_url + "/v1/diarize" + job.payload.get("query", ""),
                job.payload["body"], job.payload["content_type"])
        request = dict(job.payload["llm"])
        request.update(model=job.quality, stream=False, cache_prompt=False)
        value = self._http(self.settings.llm_url + "/v1/chat/completions", json.dumps(request).encode())
        try:
            choice = value["choices"][0]
            if choice.get("finish_reason") != "stop":
                raise BackendFailure("Die LLM-Antwort wurde nicht vollständig abgeschlossen.")
            parsed = document(choice["message"]["content"])
            choice["message"]["content"] = json.dumps(parsed, ensure_ascii=False)
        except (KeyError, IndexError, TypeError):
            raise BackendFailure("Das LLM hat keine vollständige Dokumentation geliefert.") from None
        return {"documentation": parsed, "completion": value}

    def close(self):
        self.stop_llm()
