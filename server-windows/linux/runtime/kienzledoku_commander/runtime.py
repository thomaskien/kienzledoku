"""Echte Worker-Sockets und ein ausschließlich vom Commander verwaltetes LLM."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import threading
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


def document(raw, fields=None):
    try:
        parsed = parse_documentation_json(raw, fields)
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
        raise BackendFailure("Das LLM hat keine vollständige Dokumentation geliefert.") from None


class Runtime:
    def __init__(self, settings):
        self.settings = settings
        self.process = None
        self.model = None
        self.log = None
        self.worker_processes = {"asr": None, "diar": None}
        self._shutdown = threading.Event()
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
        if self.settings.platform == "macos":
            self._start_worker("asr")
        else:
            self.control("asr", "load")

    def park_asr(self):
        if self.settings.platform == "macos":
            self._stop_worker("asr")
        else:
            self.control("asr", "park")

    def load_diar(self):
        if self.settings.platform == "macos":
            self._start_worker("diar")
        else:
            self.control("diar", "load")

    def park_diar(self):
        if self.settings.platform == "macos":
            self._stop_worker("diar")
        else:
            self.control("diar", "park")

    def _start_worker(self, role):
        if self._shutdown.is_set():
            raise BackendFailure('Commander wird beendet.')
        proc = self.worker_processes[role]
        if proc is not None and proc.poll() is None:
            return
        command = self.settings.asr_command if role == "asr" else self.settings.diar_command
        url = self.settings.asr_url if role == "asr" else self.settings.diar_url
        address = urlsplit(url)
        try:
            with socket.create_connection((address.hostname, address.port), timeout=.2):
                raise BackendFailure("Der Worker-Port wird bereits von einem fremden Prozess verwendet.")
        except OSError:
            pass
        env = dict(os.environ)
        if role == "asr":
            env.update(KIENZLEDOKU_WHISPER_MODEL=self.settings.asr_model_path,
                       KIENZLEDOKU_ASR_HOST=address.hostname, KIENZLEDOKU_ASR_PORT=str(address.port))
        else:
            env.update(KIENZLEDOKU_PYANNOTE_MODEL=self.settings.diar_model_path,
                       KIENZLEDOKU_DIARIZATION_HOST=address.hostname, KIENZLEDOKU_DIARIZATION_PORT=str(address.port),
                       PYTORCH_ENABLE_MPS_FALLBACK="0", PYANNOTE_METRICS_ENABLED="0")
        try:
            proc = subprocess.Popen(list(command), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, start_new_session=True, env=env)
            self.worker_processes[role] = proc
            deadline = time.monotonic() + self.settings.load_timeout
            while time.monotonic() < deadline and not self._shutdown.is_set():
                if proc.poll() is not None:
                    raise BackendFailure()
                try:
                    health = self._http(url + "/health", timeout=1)
                    if health.get("ok") is True or health.get("status") == "ok":
                        return
                except BackendFailure:
                    pass
                time.sleep(.05)
            self._stop_worker(role)
        except (OSError, BackendFailure):
            self._stop_worker(role)
        raise BackendFailure("Der Worker konnte nicht geladen werden.")

    def _stop_worker(self, role):
        proc = self.worker_processes[role]
        if proc is None:
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
        self.worker_processes[role] = None

    def _http(self, url, body=None, content_type="application/json", timeout=None, token=None, extra_headers=None):
        headers = {"Content-Type": content_type}
        if token:
            headers["Authorization"] = "Bearer " + token
        headers.update(extra_headers or {})
        try:
            with self.http.open(Request(url, data=body, headers=headers), timeout=timeout or self.settings.backend_timeout) as response:
                result = response.read(MAX_REPLY + 1)
                if len(result) > MAX_REPLY:
                    raise BackendFailure()
                return json.loads(result)
        except (OSError, ValueError, HTTPError, URLError):
            # Backend errors can echo a prompt, filename or transcript. Never expose them.
            raise BackendFailure() from None

    def remote_get(self, path, role="llm"):
        target = getattr(self.settings, "remote_" + role + "_url", "")
        if not target:
            raise BackendFailure()
        return self._http(target.rstrip("/") + path,
                          timeout=self.settings.metadata_timeout,
                          token=os.environ.get(getattr(self.settings, "remote_" + role + "_token_env")),
                          extra_headers={"X-Kienzledoku-Commander-Hop": "1"})

    def _remote_post(self, path, value):
        return self._http(self.settings.remote_llm_url.rstrip("/") + path,
                          json.dumps(value).encode(), timeout=self.settings.backend_timeout,
                          token=os.environ.get(self.settings.remote_llm_token_env),
                          extra_headers={"X-Kienzledoku-Commander-Hop": "1"})

    def load_llm(self, quality):
        if self._shutdown.is_set():
            raise BackendFailure('Commander wird beendet.')
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
        if self.settings.platform == "linux":
            env["CUDA_VISIBLE_DEVICES"] = str(self.settings.gpu_index)
        try:
            self.process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, start_new_session=True, env=env)
            start = time.monotonic()
            while True:
                if self._shutdown.is_set():
                    raise BackendFailure('Commander wird beendet.')
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
        if job.role == "diar" and self.settings.remote_diar_url:
            if job.payload.get("hop"):
                raise BackendFailure("Eine Commander-Weiterleitung darf nicht verkettet werden.")
            return self._http(self.settings.remote_diar_url.rstrip("/") + "/v1/diarize" + job.payload.get("query", ""),
                job.payload["body"], job.payload["content_type"],
                token=os.environ.get(self.settings.remote_diar_token_env),
                extra_headers={"X-Kienzledoku-Commander-Hop": "1",
                    "X-Kienzledoku-Recording-Finalized": "true", "Idempotency-Key": job.id})
        if job.role == "diar":
            return self._http(self.settings.diar_url + "/v1/diarize" + job.payload.get("query", ""),
                job.payload["body"], job.payload["content_type"])
        if self.settings.remote_llm_url:
            remote = job.payload.get("remote")
            if not remote or job.payload.get("hop"):
                raise BackendFailure("Die Remote-Weiterleitung wurde wegen einer Schleife abgelehnt.")
            value = self._remote_post(remote["path"], remote["body"])
            if remote["path"].endswith("/extract"):
                parsed = value["documentation"]
                parsed = parse_documentation_json(parsed, job.payload["fields"])
                completion = {"choices": [{"finish_reason": "stop", "message": {
                    "role": "assistant", "content": json.dumps(parsed, ensure_ascii=False)}}]}
                return {"documentation": parsed, "completion": completion,
                        "remote_commander": value.get("commander", {})}
            choice = value["choices"][0]
            parsed = document(choice["message"]["content"], job.payload["fields"])
            choice["message"]["content"] = json.dumps(parsed, ensure_ascii=False)
            return {"documentation": parsed, "completion": value,
                    "remote_commander": value.get("commander", {})}
        request = dict(job.payload["llm"])
        request.update(model=self.settings.runtime_quality(job.quality), stream=False, cache_prompt=False)
        value = self._http(self.settings.llm_url + "/v1/chat/completions", json.dumps(request).encode())
        if getattr(job, 'benchmark_session', None):
            # Explicit raw-prompt endpoint: no production prompt or JSON rewriting.
            try:
                if not isinstance(value['choices'][0]['message']['content'], str):
                    raise ValueError()
            except (KeyError, IndexError, TypeError, ValueError):
                raise BackendFailure() from None
            return value
        try:
            choice = value["choices"][0]
            if choice.get("finish_reason") != "stop":
                raise BackendFailure("Die LLM-Antwort wurde nicht vollständig abgeschlossen.")
            parsed = document(choice["message"]["content"], job.payload.get("fields"))
            choice["message"]["content"] = json.dumps(parsed, ensure_ascii=False)
        except (KeyError, IndexError, TypeError):
            raise BackendFailure("Das LLM hat keine vollständige Dokumentation geliefert.") from None
        return {"documentation": parsed, "completion": value}

    def cancel_loading(self):
        """Interrupt cold starts when shutting down; never abandon children."""
        self._shutdown.set()

    def close(self):
        self.cancel_loading()
        self.stop_llm()
        for role in ("asr", "diar"):
            self._stop_worker(role)
