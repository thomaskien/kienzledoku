import asyncio
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

if sys.version_info < (3, 12):
    raise unittest.SkipTest("Der optionale Linux-Commander benötigt Python 3.12+.")

from kienzledoku_commander.errors import Busy
from kienzledoku_commander.ownership import owner
from kienzledoku_commander.config import Settings
from kienzledoku_commander.runtime import Runtime
from kienzledoku_commander.worker import (Controller, WhisperGateMiddleware, close_control,
    serve_control, start_whisper_control, start_diar_control)


class Device:
    type = "cuda"
    def __str__(self):return "cuda:0"


class TorchDouble:
    def __init__(self):
        self.cuda = self
        self.fraction = None
    def synchronize(self, device):pass
    def empty_cache(self):pass
    def device(self, name):return name
    def get_device_properties(self, device):return SimpleNamespace(total_memory=24 * 1024**3)
    def set_per_process_memory_fraction(self, value, device):self.fraction = value


class WorkerTests(unittest.TestCase):
    def test_explicit_group_socket_uses_non_writable_group_directory(self):
        import grp
        group = grp.getgrgid(os.getgid()).gr_name
        c = Controller(lambda: None, lambda r: None, lambda: {})
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"KIENZLEDOKU_COMMANDER_CONTROL_GROUP": group}):
            os.chmod(directory, 0o750)
            server = serve_control(c, "diarization.sock", directory)
            try:
                info = (Path(directory) / "diarization.sock").stat()
                self.assertEqual(0o660, info.st_mode & 0o777)
                self.assertEqual(os.getgid(), info.st_gid)
            finally:close_control(server)
            os.chmod(directory, 0o770)
            with self.assertRaises(RuntimeError):serve_control(c, "diarization.sock", directory)

    def test_runtime_and_worker_use_the_same_control_protocol(self):
        c = Controller(lambda: None, lambda r: None, lambda: {})
        with tempfile.TemporaryDirectory() as directory:
            server = serve_control(c, "whisper.sock", directory)
            r = Runtime(Settings(control_dir=directory))
            try:
                r.park_asr()
                self.assertFalse(c.loaded)
                r.load_asr()
                self.assertTrue(c.gate.ready)
                with c.gate.lease(), self.assertRaises(Busy):r.park_asr()
            finally:
                r.close()
                close_control(server)

    def test_only_one_commander_can_control_the_same_workers(self):
        with tempfile.TemporaryDirectory() as directory:
            with owner(directory):
                with self.assertRaises(BlockingIOError):
                    with owner(directory):self.fail("Zweiter Eigentümer darf nicht starten")
            with owner(directory):pass

    def test_busy_park_has_no_side_effect_and_socket_protocol_hides_exceptions(self):
        operations = []
        c = Controller(lambda: operations.append("park"), lambda r: operations.append("load"), lambda: {})
        with tempfile.TemporaryDirectory() as directory:
            server = serve_control(c, "worker.sock", directory)
            self.addCleanup(close_control, server)
            def call(value):
                with socket.socket(socket.AF_UNIX) as s:
                    s.connect(str(Path(directory) / "worker.sock"))
                    s.sendall(json.dumps(value).encode() + b"\n")
                    return json.loads(s.makefile("rb").readline())
            with c.gate.lease():
                self.assertEqual("model_in_use", call({"operation": "park"})["code"])
                self.assertTrue(c.gate.ready)
                self.assertEqual([], operations)
            self.assertTrue(call({"operation": "park"})["ok"])
            self.assertFalse(c.gate.ready)
            self.assertTrue(call({"operation": "load"})["state"]["ready"])
            self.assertEqual("worker_control_failed", call({"operation": "exec", "source": "private"})["code"])
            self.assertEqual(0o600, (Path(directory) / "worker.sock").stat().st_mode & 0o777)
            with self.assertRaises(RuntimeError):serve_control(c, "worker.sock", directory)

    def test_never_replaces_an_unknown_file(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "worker.sock"
            p.write_text("original")
            with self.assertRaises(RuntimeError):serve_control(None, "worker.sock", directory)
            self.assertEqual("original", p.read_text())

    def _check_whisper_cache(self, keep):
        calls = []
        class CT:
            model_is_loaded = True
            def unload_model(self, **kwargs):
                calls.append(("ct_park", kwargs)); self.model_is_loaded = False
            def load_model(self, **kwargs):
                calls.append(("ct_load", kwargs)); self.model_is_loaded = True
        class Shared:
            def __init__(self):self.parameter = SimpleNamespace(device=Device())
            def parameters(self):return iter([self.parameter])
            def to(self, value):calls.append(("torch_to", str(value))); self.parameter.device = value
        ct, shared = CT(), Shared()
        engine = SimpleNamespace(asr=SimpleNamespace(fw_encoder=SimpleNamespace(model=ct), shared_model=shared))
        app = SimpleNamespace(state=SimpleNamespace())
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"KIENZLEDOKU_COMMANDER_CONTROL_DIR": directory, "KIENZLEDOKU_AUDIO_CACHE": "ram" if keep else "disk"}), patch.dict(sys.modules, {"torch": TorchDouble()}):
            server = start_whisper_control(app, engine)
            try:
                c = app.state.commander_controller
                before = c.status()
                c.operate({"operation": "park"})
                self.assertFalse(c.status()["ready"])
                self.assertIn(("ct_park", {"to_cpu": keep}), calls)
                self.assertIn(("torch_to", "cpu"), calls)
                c.operate({"operation": "load"})
                self.assertIn(("ct_load", {"keep_cache": keep}), calls)
                self.assertEqual(before["ct2_object_id"], c.status()["ct2_object_id"])
                self.assertEqual(before["shared_object_id"], c.status()["shared_object_id"])
            finally:close_control(server)

    def test_whisper_moves_both_existing_parts_and_preserves_cpu_cache(self):
        self._check_whisper_cache(True)

    def test_whisper_disk_policy_releases_ct2_weights_but_retains_objects(self):
        self._check_whisper_cache(False)

    def test_diar_keeps_pipeline_and_budget_and_gates_handler(self):
        class Pipeline:
            device = Device()
            def to(self, device):self.device = device
        class Handler:
            path = "/v1/diarize"
            def do_POST(self):return "original"
        pipeline, torch = Pipeline(), TorchDouble()
        ns = {"pipeline": pipeline, "pipeline_lock": threading.Lock(), "torch": torch, "Handler": Handler}
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"KIENZLEDOKU_COMMANDER_CONTROL_DIR": directory}):
            server = start_diar_control(ns)
            try:
                c = server.controller
                c.operate({"operation": "park"})
                self.assertEqual("cpu", pipeline.device)
                c.operate({"operation": "load", "allocator_mib": 2048})
                self.assertEqual(2048 / 24576, torch.fraction)
                self.assertEqual(id(pipeline), c.status()["pipeline_object_id"])
                self.assertEqual("original", Handler().do_POST())
            finally:close_control(server)


class ASGITests(unittest.IsolatedAsyncioTestCase):
    async def test_parked_request_waits_then_uses_same_object(self):
        c = Controller(lambda: None, lambda r: None, lambda: {})
        entered, release = asyncio.Event(), asyncio.Event()
        async def app(scope, receive, send):
            entered.set()
            await release.wait()
        scope = {"type": "http", "path": "/v1/asr/final-block", "app": SimpleNamespace(state=SimpleNamespace(commander_controller=c))}
        c.operate({"operation": "park"})
        task = asyncio.create_task(WhisperGateMiddleware(app)(scope, None, None))
        await asyncio.sleep(.04)
        self.assertFalse(entered.is_set())
        c.operate({"operation": "load"})
        await asyncio.wait_for(entered.wait(), 1)
        with self.assertRaises(Busy):c.operate({"operation": "park"})
        release.set()
        await task
        self.assertEqual(0, c.gate.active)

    async def test_cancellation_while_parked_leaks_no_lease(self):
        c = Controller(lambda: None, lambda r: None, lambda: {})
        c.operate({"operation": "park"})
        async def app(*args):self.fail("Darf noch nicht aufgerufen werden")
        scope = {"type": "websocket", "path": "/asr", "app": SimpleNamespace(state=SimpleNamespace(commander_controller=c))}
        task = asyncio.create_task(WhisperGateMiddleware(app)(scope, None, None))
        await asyncio.sleep(.04)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        c.operate({"operation": "load"})
        self.assertEqual(0, c.gate.active)
