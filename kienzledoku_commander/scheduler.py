"""Anfragen ausführen; ausschließlich echte Modellwechsel werden koordiniert."""
from collections import Counter, deque
from concurrent.futures import Future, ThreadPoolExecutor
import copy
from dataclasses import dataclass, field
import hashlib
import json
import re
import threading
import time
import uuid

from .config import LABELS
from .errors import BackendFailure, Busy, CommanderError, Conflict, InvalidRequest, QueueFull, QueueExpired


@dataclass
class Job:
    id: str
    role: str
    payload: dict = field(repr=False)
    requested_quality: str | None = None
    quality: str | None = None
    fingerprint: str = ""
    future: Future = field(default_factory=Future, repr=False)
    completed_at: float | None = None
    attempted: list = field(default_factory=list)
    payload_size: int = 0
    submitted_at: float = field(default_factory=time.monotonic)
    started_at: float | None = None


class Commander:
    def __init__(self, settings, runtime):
        self.settings, self.runtime = settings, runtime
        self._condition = threading.Condition()
        self._pending = deque()
        self._active = {}
        self._remembered = {}
        self._loaded = {"asr": False, "diar": False, "llm": None}
        self._blocked = set()
        self._transition = False
        self._change_target = None
        self._planned = None
        self._llm_fault = False
        self._baseline_retry_at = 0.0
        self._phase = "starting"
        self._last_error = None
        self._uncertain = True
        self._return_after_llm = False
        self._awaiting_documentation = False
        self._retry_at = 0.0
        self._closing = False
        self._ready_once = threading.Event()
        self._pool = ThreadPoolExecutor(max_workers=32, thread_name_prefix="commander-inference")
        self._changes = ThreadPoolExecutor(max_workers=1, thread_name_prefix="commander-models")
        self._thread = threading.Thread(target=self._loop, name="kienzledoku-commander")
        self._thread.start()

    def _baseline(self):
        if (self.settings.diarization_mode is not None and self._awaiting_documentation
                and self._loaded['diar'] and not self._uncertain):
            # The next client request follows the completed diarization result.
            # Do not reload Whisper in the gap immediately before LLM work.
            return dict(self._loaded)
        return self._runtime_target(self._diar_policy(self._baseline_legacy()))

    def _runtime_target(self, desired):
        if desired['llm']:
            desired['llm'] = self.settings.runtime_quality(desired['llm'])
        return desired

    def _baseline_legacy(self):
        roles = set(self.settings.enabled_roles)
        # Strict serial mode: cold at startup, retain Whisper between audio
        # blocks, and leave it cold after another role has unloaded it.
        asr = "asr" in roles and (not self.settings.asr_on_demand or bool(self._loaded["asr"]))
        if self.settings.memory_mode == "serial":
            return {"asr": asr,
                    "diar": False, "llm": None}
        return {"asr": asr,
                "diar": "diar" in roles and self.settings.tier != 8,
                "llm": self.settings.baseline_llm}

    def _diar_policy(self, desired, role=None):
        mode = self.settings.diarization_mode
        if mode is None:
            return desired
        if 'diar' not in self.settings.enabled_roles:
            desired['diar'] = False
        elif mode == 'resident':
            desired['diar'] = True
        elif mode == 'with_asr':
            if role == 'diar' and 'asr' in self.settings.enabled_roles:
                desired['asr'] = True
            desired['diar'] = bool(desired['asr'] or role == 'diar')
        elif role == 'diar':
            desired = {'asr': False, 'diar': True, 'llm': None}
        else:
            desired['diar'] = False
        return desired

    def _desired(self, job):
        return self._runtime_target(self._diar_policy(self._desired_legacy(job), job.role))

    def _desired_legacy(self, job):
        if job.role == "llm" and self.settings.remote_llm_url:
            return dict(self._loaded)
        if self.settings.memory_mode == "serial":
            return {"asr": job.role == "asr", "diar": job.role == "diar",
                    "llm": job.quality if job.role == "llm" else None}
        if job.role == "llm":
            if self.settings.persistent(job.quality):
                return {"asr": "asr" in self.settings.enabled_roles,
                        "diar": "diar" in self.settings.enabled_roles, "llm": job.quality}
            return {"asr": False, "diar": False, "llm": job.quality}
        if job.role == "diar" and self.settings.tier == 8:
            return {"asr": False, "diar": True, "llm": None}
        desired = self._baseline()
        desired[job.role] = True
        return desired

    @staticmethod
    def _fingerprint(role, payload, quality):
        body = payload.get("body", b"")
        meta = {k: v for k, v in payload.items() if k != "body"}
        h = hashlib.sha256(json.dumps([role, quality, meta], sort_keys=True).encode())
        h.update(body)
        return h.hexdigest()

    def _purge(self):
        now = time.monotonic()
        expired = [key for key, j in self._remembered.items()
            if j.completed_at is not None and now - j.completed_at >= self.settings.remember_seconds]
        for key in expired:
            del self._remembered[key]
        while len(self._remembered) >= self.settings.max_remembered:
            done = [(j.completed_at, key) for key, j in self._remembered.items() if j.completed_at is not None]
            if not done:
                break
            del self._remembered[min(done)[1]]

    def submit(self, role, payload, quality=None, request_id=None):
        if role not in ("asr", "diar", "llm"):
            raise InvalidRequest()
        if role not in self.settings.enabled_roles:
            raise InvalidRequest("Diese Serverrolle ist deaktiviert.")
        if role == "llm" and self.settings.remote_llm_url:
            allowed = getattr(self.runtime, "remote_allowed", self.settings.allowed)
            quality = getattr(self.runtime, "remote_default", self.settings.default) if quality is None else quality
            if quality not in allowed:
                raise InvalidRequest("Diese Verarbeitungsstufe ist am Remote-Commander nicht verfügbar.")
        else:
            quality = self.settings.quality(quality) if role == "llm" else None
        if request_id is not None and (not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", request_id)):
            raise InvalidRequest("Die Anfrage-ID ist ungültig.")
        request_id = request_id or uuid.uuid4().hex
        payload = copy.deepcopy(payload)
        fingerprint = self._fingerprint(role, payload, quality)
        size = len(payload.get("body", b"")) + len(json.dumps({k: v for k, v in payload.items() if k != "body"}).encode())
        with self._condition:
            self._purge()
            previous = self._remembered.get(request_id)
            if previous:
                if previous.fingerprint != fingerprint:
                    raise Conflict()
                return previous
            if self._closing:
                raise CommanderError("Der Commander wird beendet.")
            held_bytes = sum(j.payload_size for j in self._remembered.values() if j.completed_at is None)
            if len(self._pending) >= self.settings.max_pending or len(self._remembered) >= self.settings.max_remembered or held_bytes + size > self.settings.max_payload_mib * 1048576:
                raise QueueFull()
            job = Job(request_id, role, payload, quality, quality, fingerprint)
            job.payload_size = size
            self._remembered[request_id] = job
            self._pending.append(job)
            self._condition.notify_all()
            return job

    def status(self):
        with self._condition:
            allowed = getattr(self.runtime, "remote_allowed", self.settings.allowed)
            default = getattr(self.runtime, "remote_default", self.settings.default)
            services = {}
            for role in ("asr", "diar", "llm"):
                if role not in self.settings.enabled_roles:
                    state, message = "disabled", "Dienst ist deaktiviert."
                elif any(j.role == role for j in self._active.values()):
                    state, message = "busy", "Dienst verarbeitet einen Auftrag."
                elif (self._transition and self._change_target and self._change_target[role]
                      and (role in self._blocked or not self._loaded[role])):
                    state, message = "loading", "Modellwechsel läuft."
                elif self._loaded[role] or (role == "llm" and self.settings.remote_llm_url):
                    state, message = "ready", "Dienst ist bereit."
                elif self._last_error and self._uncertain:
                    state, message = "error", "Dienst konnte technisch nicht bereitgestellt werden."
                else:
                    state, message = "standby", "Dienst wird bei Bedarf geladen."
                services[role] = {"state": state, "message": message}
            return {
                "name": "kienzledoku-commander", "vram_gib": self.settings.tier,
                "default_quality": default, "allowed_qualities": list(allowed),
                "phase": self._phase, "asr_ready": bool(self._loaded["asr"] and "asr" not in self._blocked),
                "loaded": dict(self._loaded), "transition_running": self._transition,
                "pending": dict(Counter(j.role for j in self._pending)),
                "active": dict(Counter(j.role for j in self._active.values())),
                "last_error": self._last_error,
                "services": services,
            }

    def wait_ready(self, timeout=10):
        return self._ready_once.wait(timeout)

    def _limit(self, job):
        if job.role == "llm":
            if self.settings.remote_llm_url:
                return 1
            return self.settings.model(job.quality).slots
        return self.settings.asr_parallel if job.role == "asr" else self.settings.diar_parallel

    def _available(self, job):
        remote = job.role == "llm" and self.settings.remote_llm_url
        if job.role in self._blocked or (not remote and not self._loaded[job.role]):
            return False
        if job.role == "llm" and not remote and (self._loaded["llm"] != self.settings.runtime_quality(job.quality) or self._llm_fault):
            return False
        return sum(j.role == job.role for j in self._active.values()) < self._limit(job)

    def _complete(self, job, value=None, error=None):
        job.completed_at = time.monotonic()
        job.payload = {}  # Completed cache retains result, never raw audio/transcript inputs.
        if not job.future.done():
            if error:
                job.future.set_exception(error)
            else:
                job.future.set_result(value)

    def _failed(self, job, error):
        fallback = self.settings.fallback(job.quality) if job.role == "llm" and not self.settings.remote_llm_url else None
        if isinstance(error, BackendFailure) and fallback and fallback not in job.attempted:
            job.attempted.append(job.quality)
            job.quality = fallback
            self._pending.appendleft(job)
            self._return_after_llm = True
        else:
            self._complete(job, error=BackendFailure())

    def _finished(self, job, future):
        with self._condition:
            self._active.pop(job.id, None)
            if job.role == "llm":
                self._return_after_llm = True
            try:
                value = future.result()
                if job.role == "llm":
                    remote = value.pop("remote_commander", {}) if self.settings.remote_llm_url else {}
                    used = remote.get("used_quality", job.quality)
                    requested = remote.get("requested_quality", job.requested_quality)
                    fallback = remote.get("fallback_used", used != requested)
                    value = {**value, "commander": {
                        "request_id": job.id, "requested_quality": requested,
                        "used_quality": used, "fallback_used": fallback,
                        "notice": remote.get("notice") if remote else (("Die angeforderte Verarbeitung ist fehlgeschlagen. Die Dokumentation wurde mit %s erstellt." % LABELS[used]) if fallback else None),
                        "total_seconds": round(time.monotonic() - job.submitted_at, 4),
                        "initial_wait_seconds": round((job.started_at or time.monotonic()) - job.submitted_at, 4),
                    }}
                self._complete(job, value=value)
                if job.role == 'diar':
                    self._awaiting_documentation = True
            except Exception as error:
                if job.role == "llm" and not self.settings.remote_llm_url:
                    self._llm_fault = True
                self._failed(job, error if isinstance(error, CommanderError) else BackendFailure())
            self._condition.notify_all()

    def _dispatch(self):
        dispatched = False
        for job in list(self._pending):
            if time.monotonic() - job.submitted_at > self.settings.queue_timeout:
                self._pending.remove(job)
                self._complete(job, error=QueueExpired())
                continue
            if job.future.cancelled():
                self._pending.remove(job)
                self._complete(job, error=CommanderError())
                continue
            if self._available(job):
                if job.role in ('asr', 'llm'):
                    self._awaiting_documentation = False
                self._pending.remove(job)
                self._active[job.id] = job
                if job.started_at is None:
                    job.started_at = time.monotonic()
                future = self._pool.submit(self.runtime.infer, job)
                future.add_done_callback(lambda result, j=job: self._finished(j, result))
                dispatched = True
        return dispatched

    def _publish(self, role, value):
        with self._condition:
            self._loaded[role] = value
            if role == "llm" and value is None:
                self._llm_fault = False
            self._blocked.discard(role)
            if role == "asr" and value:
                self._ready_once.set()
            self._condition.notify_all()

    def _perform_change(self, desired, force):
        # ASR is unblocked as soon as its own reload finishes; restoring the
        # persistent LLM may continue concurrently with already queued ASR.
        with self._condition:
            loaded = dict(self._loaded)
            llm_fault = self._llm_fault
        local_llm = "llm" in self.settings.enabled_roles and not self.settings.remote_llm_url
        if local_llm and (force or (loaded["llm"] and (loaded["llm"] != desired["llm"] or llm_fault))):
            self.runtime.stop_llm()
            self._publish("llm", None)
            loaded["llm"] = None
        for role in ("asr", "diar"):
            if role in self.settings.enabled_roles and not desired[role] and (loaded[role] or force):
                self._worker_change(role, "park", False)
                loaded[role] = False
        for role in ("asr", "diar"):
            if role in self.settings.enabled_roles and desired[role] and (not loaded[role] or force):
                self._worker_change(role, "load", True)
                loaded[role] = True
        if desired["llm"] and loaded["llm"] != desired["llm"]:
            self.runtime.load_llm(desired["llm"])
            self._publish("llm", desired["llm"])

    def _worker_change(self, role, operation, value):
        try:
            getattr(self.runtime, operation + "_" + role)()
        except Busy:
            raise  # Busy guarantees no mutation and preserves the prior readiness.
        except Exception:
            # A partial copy or lost control reply invalidates prior readiness.
            # Never send work into a closed gate: that would block its own recovery.
            self._publish(role, False)
            raise
        self._publish(role, value)

    def _changed(self, desired, selected, future):
        with self._condition:
            self._transition = False
            self._change_target = None
            self._blocked.clear()
            try:
                future.result()
                self._uncertain = False
                if selected is not None or desired == self._baseline():
                    self._last_error = None
                self._phase = "asr_ready" if self._loaded["asr"] else "processing"
                if desired == self._baseline():
                    self._ready_once.set()
            except Busy:
                # Busy is not a failed load and must not lower the quality.
                self._phase = "waiting_for_model"
                self._retry_at = time.monotonic() + .1
            except Exception:
                self._uncertain = True
                self._last_error = "model_change_failed"
                self._phase = "recovering_asr"
                self._retry_at = time.monotonic() + .25
                if selected is None and desired["llm"]:
                    self._baseline_retry_at = time.monotonic() + 30
                if selected and selected in self._pending:
                    self._pending.remove(selected)
                    self._failed(selected, BackendFailure())
            self._condition.notify_all()

    def _start_change(self, desired, selected=None):
        if self._transition or time.monotonic() < self._retry_at:
            return False
        force = self._uncertain
        managed = set(self.settings.enabled_roles)
        if self.settings.remote_llm_url:
            managed.discard("llm")
        affected = {role for role in managed if self._loaded[role] != desired[role] or force}
        if self._llm_fault and "llm" in managed:
            affected.add("llm")
        # Wait until running LLM work finishes before planning its removal.
        # Otherwise a waiting ASR job blocks the next already queued LLM job,
        # forcing an unnecessary restore and second load of the same model.
        if "llm" in affected and any(job.role == "llm" for job in self._active.values()):
            return False
        if not affected:
            self._blocked.clear()
            self._planned = None
            if force:
                self._uncertain = False
                self._phase = "asr_ready" if self._loaded["asr"] else "processing"
                self._ready_once.set()
            return False
        self._blocked = affected
        if any(job.role in affected for job in self._active.values()):
            # Drain only the objects about to move. Incoming ASR is queued,
            # otherwise continuous new audio could starve a serial LLM forever.
            self._planned = (desired, selected)
            self._phase = "waiting_for_active_work"
            return True
        self._planned = None
        self._transition = True
        self._change_target = dict(desired)
        self._phase = "preparing_model" if selected else "restoring_asr"
        future = self._changes.submit(self._perform_change, desired, force)
        future.add_done_callback(lambda result: self._changed(desired, selected, result))
        return True

    def _loop(self):
        while True:
            with self._condition:
                self._purge()
                if self._closing:
                    while self._pending:
                        self._complete(self._pending.popleft(), error=CommanderError())
                    if not self._active and not self._transition:
                        break
                else:
                    self._dispatch()
                    if self._planned and self._planned[1] is not None and self._planned[1].future.done():
                        self._planned = None
                        self._blocked.clear()
                    if self._planned:
                        self._start_change(*self._planned)
                    elif not self._transition:
                        llm_active = any(j.role == "llm" for j in self._active.values())
                        # Dispatch above consumes an already waiting same-model
                        # request. There is no grace period for future arrivals.
                        if self._return_after_llm and not llm_active:
                            if self._loaded == self._baseline() and not self._uncertain and not self._llm_fault:
                                self._return_after_llm = False
                            elif self._start_change({**self._baseline(), "llm": None} if self._uncertain else self._baseline()):
                                self._return_after_llm = False
                        if not self._transition and not self._planned:
                            if self._uncertain:
                                # Worker readiness must recover even if a configured
                                # persistent GGUF is missing. Jobs then attempt their
                                # own model and receive the proper fallback/error.
                                self._start_change({**self._baseline(), "llm": None})
                            else:
                                for job in self._pending:
                                    if self._start_change(self._desired(job), job):
                                        break
                                else:
                                    if not self._pending and not self._active and time.monotonic() >= self._baseline_retry_at:
                                        self._start_change(self._baseline())
                self._condition.wait(.05)
        # Runtime.close stops only processes created by this Commander. Existing
        # Linux worker objects are deliberately not changed during shutdown.
        self.runtime.stop_llm()

    def close(self):
        cancel_loading = getattr(self.runtime, 'cancel_loading', None)
        if cancel_loading:
            cancel_loading()
        with self._condition:
            self._closing = True
            self._condition.notify_all()
        self._thread.join()
        self._pool.shutdown(wait=True)
        self._changes.shutdown(wait=True)
        self.runtime.close()
