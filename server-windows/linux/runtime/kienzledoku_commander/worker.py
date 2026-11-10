"""Opt-in-Steuerung vorhandener Worker-Objekte, ohne neue Modellinstanz.

Der Gate schützt nur das Objekt beim Verschieben. In residenten Profilen
bleiben ASR, Diarisierung und LLM voneinander unabhängig ausführbar.
"""
import asyncio
from contextlib import contextmanager
import json
import grp
import os
from pathlib import Path
import socket
import socketserver
import stat
import threading

from .errors import Busy

if os.environ.get('KIENZLEDOKU_SERIAL_ASR_CPU_STAGE') == '1':
    from .asr_stage import install as _stage_whisper_checkpoint
    _stage_whisper_checkpoint()


class Gate:
    def __init__(self):
        self.condition = threading.Condition()
        self.ready = True
        self.active = 0
        self.operation = threading.Lock()

    def enter_now(self):
        with self.condition:
            if not self.ready:
                return False
            self.active += 1
            return True

    def leave(self):
        with self.condition:
            self.active -= 1
            self.condition.notify_all()

    @contextmanager
    def lease(self):
        with self.condition:
            self.condition.wait_for(lambda: self.ready)
            self.active += 1
        try:
            yield
        finally:
            self.leave()

    def close_for_change(self):
        with self.condition:
            if self.active:
                raise Busy()
            self.ready = False

    def open(self):
        with self.condition:
            self.ready = True
            self.condition.notify_all()


class Controller:
    def __init__(self, park, load, describe):
        self.gate = Gate()
        self._park, self._load, self._describe = park, load, describe
        self.loaded = True

    def status(self):
        with self.gate.condition:
            return {"pid": os.getpid(), "loaded": self.loaded,
                    "ready": self.gate.ready, "active": self.gate.active,
                    **self._describe()}

    def operate(self, request):
        op = request.get("operation")
        if op not in ("park", "load", "status") or set(request) - {"operation", "allocator_mib"}:
            raise ValueError("Ungültige Steueroperation")
        with self.gate.operation:
            if op == "status":
                return self.status()
            # An active lease is checked before any CUDA operation or gate change.
            self.gate.close_for_change()
            was_loaded = self.loaded
            self.loaded = False  # A partial move must never be reported as ready.
            if op == "park":
                try:
                    self._park()
                except Busy:
                    self.loaded = was_loaded
                    if was_loaded:
                        self.gate.open()
                    raise
            else:
                self._load(request)
                self.loaded = True
                self.gate.open()
            return self.status()


class ControlServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True


class ControlHandler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(10)
        try:
            line = self.rfile.readline(4097)
            if not line.endswith(b"\n") or len(line) > 4096:
                raise ValueError()
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError()
            result = {"ok": True, "state": self.server.controller.operate(request)}
        except Busy:
            result = {"ok": False, "code": "model_in_use"}
        except Exception:
            # No exception repr: model/backend errors can contain patient data.
            result = {"ok": False, "code": "worker_control_failed"}
        try:
            self.wfile.write((json.dumps(result) + "\n").encode())
        except OSError:
            pass


def serve_control(controller, name, directory=None):
    directory = directory or os.environ.get("KIENZLEDOKU_COMMANDER_CONTROL_DIR")
    if not directory:
        return None
    root = Path(directory)
    info = root.lstat()
    group = os.environ.get("KIENZLEDOKU_COMMANDER_CONTROL_GROUP")
    gid = grp.getgrnam(group).gr_gid if group else None
    mode = 0o750 if group else 0o700
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != mode or (group and info.st_gid != gid)):
        raise RuntimeError("Steuerungsverzeichnis benötigt den Worker als Eigentümer und den konfigurierten privaten Zugriffsmodus.")
    path = root / name
    if path.exists() or path.is_symlink():
        old = path.lstat()
        if not stat.S_ISSOCK(old.st_mode) or old.st_uid != os.getuid():
            raise RuntimeError("Unbekannte Steuerdatei wird nicht ersetzt.")
        with socket.socket(socket.AF_UNIX) as probe:
            probe.settimeout(.5)
            try:
                probe.connect(str(path))
            except ConnectionRefusedError:
                path.unlink()
            else:
                raise RuntimeError("Worker-Steuerung läuft bereits.")
    # The directory is private, so no untrusted process can replace this path.
    server = ControlServer(str(path), ControlHandler)
    if group:
        os.chown(path, os.getuid(), gid)
    os.chmod(path, 0o660 if group else 0o600)
    server.controller = controller
    threading.Thread(target=server.serve_forever, daemon=True, name="commander-control").start()
    return server


def close_control(server):
    if server:
        server.shutdown()
        server.server_close()
        Path(server.server_address).unlink(missing_ok=True)


class WhisperGateMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        # Also covers streaming APIs: a connected session retains its model.
        inference = scope["type"] in ("http", "websocket") and scope.get("path", "") not in (
            "/health", "/healthz", "/v1/models", "/docs", "/openapi.json", "/")
        state = getattr(scope.get("app"), "state", None)
        controller = getattr(state, "commander_controller", None) if state else None
        if not inference or not controller:
            return await self.app(scope, receive, send)
        # No background to_thread acquisition: cancellation must never leak a lease.
        while not controller.gate.enter_now():
            await asyncio.sleep(.025)
        try:
            return await self.app(scope, receive, send)
        finally:
            controller.gate.leave()


def start_whisper_control(app, engine):
    if not os.environ.get("KIENZLEDOKU_COMMANDER_CONTROL_DIR"):
        return None
    import torch
    fw = engine.asr.fw_encoder
    ct = fw.model
    shared = engine.asr.shared_model
    device = next(shared.parameters()).device
    if getattr(device, "type", str(device).split(":")[0]) != "cuda":
        raise RuntimeError("Commander erwartet einen CUDA-Whisper-Worker.")
    if not callable(getattr(ct, "unload_model", None)) or not callable(getattr(ct, "load_model", None)):
        raise RuntimeError("CTranslate2 unterstützt keinen Modellcache.")

    def park():
        if getattr(ct, "num_active_batches", 0) or getattr(ct, "num_queued_batches", 0):
            raise Busy()
        ct.unload_model(to_cpu=os.environ.get('KIENZLEDOKU_AUDIO_CACHE', 'ram') == 'ram')
        shared.to("cpu")
        torch.cuda.synchronize(device)
        torch.cuda.empty_cache()

    def load(request):
        shared.to(device)
        ct.load_model(keep_cache=os.environ.get('KIENZLEDOKU_AUDIO_CACHE', 'ram') == 'ram')
        torch.cuda.synchronize(device)

    controller = Controller(park, load, lambda: {
        "ct2_object_id": id(ct), "shared_object_id": id(shared),
        "ct2_loaded": bool(ct.model_is_loaded), "shared_device": str(next(shared.parameters()).device)})
    server = serve_control(controller, "whisper.sock")
    app.state.commander_controller = controller
    return server


def start_diar_control(namespace):
    if not os.environ.get("KIENZLEDOKU_COMMANDER_CONTROL_DIR"):
        return None
    pipeline, lock, torch = (namespace[k] for k in ("pipeline", "pipeline_lock", "torch"))
    original_device = pipeline.device
    if getattr(original_device, "type", str(original_device).split(":")[0]) != "cuda":
        raise RuntimeError("Commander erwartet eine CUDA-Diarisierung.")

    def park():
        with lock:
            pipeline.to(torch.device("cpu"))
            torch.cuda.synchronize(original_device)
            torch.cuda.empty_cache()

    def load(request):
        mib = request.get("allocator_mib", 2048)
        if type(mib) is not int or not 256 <= mib <= 6144:
            raise ValueError("Ungültiges Speicherbudget")
        with lock:
            torch.cuda.empty_cache()
            total = torch.cuda.get_device_properties(original_device).total_memory
            torch.cuda.set_per_process_memory_fraction(min(1., mib * 1048576 / total), original_device)
            pipeline.to(original_device)
            torch.cuda.synchronize(original_device)

    controller = Controller(park, load, lambda: {"pipeline_object_id": id(pipeline), "device": str(pipeline.device)})
    original = namespace["Handler"].do_POST

    def do_post(handler):
        if handler.path.split("?", 1)[0] == "/v1/diarize":
            with controller.gate.lease():
                return original(handler)
        return original(handler)

    if os.environ.get("KIENZLEDOKU_SERIAL_BOOT") == "1":
        controller.operate({"operation": "park"})
    server = serve_control(controller, "diarization.sock")
    namespace["Handler"].do_POST = do_post
    return server
