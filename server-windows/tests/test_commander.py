import threading
import time
import unittest
import sys

if sys.version_info < (3, 12):
    raise unittest.SkipTest("Der optionale Linux-Commander benötigt Python 3.12+.")

from kienzledoku_commander.config import Settings
from kienzledoku_commander.errors import BackendFailure, Busy, Conflict, InvalidRequest
from kienzledoku_commander.scheduler import Commander


def eventually(predicate, seconds=4):
    deadline = time.monotonic() + seconds
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("Zustand nicht rechtzeitig erreicht")
        time.sleep(.005)


class RuntimeDouble:
    def __init__(self, settings):
        self.settings = settings
        self.loaded = {"asr": False, "diar": False, "llm": None}
        self.events = []
        self.started = set()
        self.active = []
        self.holds = {}
        self.fail_load = set()
        self.fail_infer = set()
        self.busy_asr = 0
        self.lock = threading.Lock()
        self.reload_hold = None
        self.reload_entered = threading.Event()

    def load_asr(self):
        if self.reload_hold and not self.loaded["asr"]:
            self.reload_entered.set()
            self.reload_hold.wait(5)
        self.loaded["asr"] = True
        self.events.append("load_asr")

    def park_asr(self):
        if self.busy_asr:
            self.busy_asr -= 1
            raise Busy()
        assert "asr" not in self.active
        self.loaded["asr"] = False
        self.events.append("park_asr")

    def load_diar(self):
        self.loaded["diar"] = True
        self.events.append("load_diar")

    def park_diar(self):
        assert "diar" not in self.active
        self.loaded["diar"] = False
        self.events.append("park_diar")

    def load_llm(self, quality):
        self.events.append("load_" + quality)
        if quality in self.fail_load:
            raise BackendFailure()
        self.loaded["llm"] = quality

    def stop_llm(self):
        assert "llm" not in self.active
        if self.loaded["llm"]:
            self.events.append("stop_" + self.loaded["llm"])
        self.loaded["llm"] = None

    def infer(self, job):
        if job.role == "llm":
            assert self.loaded["llm"] == job.quality
            if not self.settings.persistent(job.quality):
                assert not self.loaded["asr"] and not self.loaded["diar"]
        else:
            assert self.loaded[job.role]
            if self.settings.tier == 8:
                assert not self.loaded["diar" if job.role == "asr" else "asr"]
        with self.lock:
            self.active.append(job.role)
            self.started.add(job.id)
        try:
            hold = self.holds.get(job.id)
            if hold:
                if not hold.wait(5):
                    raise AssertionError("Test wartet zu lange")
            if job.quality in self.fail_infer:
                raise BackendFailure()
            return {"documentation": {"anamnese": "Synthetisch", "befund": "", "therapie": "", "prozedere": ""},
                "completion": {}} if job.role == "llm" else {"text": "Synthetisch"}
        finally:
            with self.lock:
                self.active.remove(job.role)

    def close(self):
        self.stop_llm()


class ProfileTests(unittest.TestCase):
    def test_quality_defaults_and_strict_24gib_policy(self):
        self.assertEqual("basis", Settings(tier=8).default)
        self.assertEqual("basis", Settings(tier=16).default)
        cfg = Settings(tier=24).validate()
        self.assertEqual("gruendlich", cfg.default)
        self.assertEqual("gruendlich", cfg.fallback("sehr_gruendlich"))
        self.assertIsNone(cfg.fallback("gruendlich"))
        with self.assertRaises(InvalidRequest):
            cfg.model("basis")
        with self.assertRaises(ValueError):
            Settings(tier=24, default_quality="basis").validate()

    def test_serial_default_never_keeps_a_large_llm_on_standby(self):
        self.assertIsNone(Settings(tier=16, default_quality="gruendlich").baseline_llm)
        self.assertIsNone(Settings(tier=24, default_quality="sehr_gruendlich").baseline_llm)
        self.assertEqual(32768, Settings(tier=8).model("basis").context)
        self.assertEqual("q4_0", Settings(tier=24).model("sehr_gruendlich").kv)


class SchedulerTests(unittest.TestCase):
    def create(self, tier=8, **options):
        cfg = Settings(tier=tier, **options).validate()
        runtime = RuntimeDouble(cfg)
        commander = Commander(cfg, runtime)
        def cleanup():
            for event in runtime.holds.values():
                event.set()
            if runtime.reload_hold:
                runtime.reload_hold.set()
            commander.close()
        self.addCleanup(cleanup)
        eventually(lambda: commander.status()["loaded"] == commander._baseline() and not commander.status()["transition_running"])
        return commander, runtime

    def test_result_is_available_before_asr_reload_finishes(self):
        c, r = self.create()
        r.reload_hold = threading.Event()
        job = c.submit("llm", {"llm": {}}, request_id="one")
        self.assertEqual("basis", job.future.result(3)["commander"]["used_quality"])
        self.assertTrue(r.reload_entered.wait(2))
        self.assertFalse(c.status()["asr_ready"])
        r.reload_hold.set()
        eventually(lambda: c.status()["asr_ready"])

    def test_queued_same_model_is_used_again_before_unload(self):
        c, r = self.create()
        r.holds = {"one": threading.Event(), "two": threading.Event()}
        one = c.submit("llm", {"llm": {}}, request_id="one")
        eventually(lambda: "one" in r.started)
        two = c.submit("llm", {"llm": {}}, request_id="two")
        r.holds["one"].set()
        one.future.result(2)
        eventually(lambda: "two" in r.started)
        self.assertEqual(1, r.events.count("load_basis"))
        self.assertNotIn("stop_basis", r.events)
        r.holds["two"].set()
        two.future.result(2)
        eventually(lambda: c.status()["asr_ready"])
        self.assertEqual(1, r.events.count("stop_basis"))

    def test_waiting_audio_does_not_interrupt_same_model_batch(self):
        c, r = self.create(tier=24)
        r.holds = {"one": threading.Event(), "two": threading.Event()}
        one = c.submit("llm", {"llm": {}}, "sehr_gruendlich", request_id="one")
        eventually(lambda: "one" in r.started)
        audio = c.submit("asr", {}, request_id="audio")
        two = c.submit("llm", {"llm": {}}, "sehr_gruendlich", request_id="two")
        eventually(lambda: c.status()["pending"].get("llm") == 1)
        # Keep inference active while the scheduler observes both queued jobs.
        time.sleep(.15)
        r.holds["one"].set()
        one.future.result(2)
        eventually(lambda: "two" in r.started)
        self.assertEqual(1, r.events.count("load_sehr_gruendlich"))
        self.assertNotIn("stop_sehr_gruendlich", r.events)
        self.assertNotIn("audio", r.started)
        r.holds["two"].set()
        two.future.result(2)
        audio.future.result(2)
        eventually(lambda: c.status()["asr_ready"])
        self.assertEqual(1, r.events.count("stop_sehr_gruendlich"))

    def test_new_request_after_restore_loads_again(self):
        c, r = self.create()
        c.submit("llm", {"llm": {}}).future.result(2)
        eventually(lambda: c.status()["asr_ready"] and c.status()["loaded"]["llm"] is None)
        c.submit("llm", {"llm": {}}).future.result(2)
        eventually(lambda: c.status()["asr_ready"])
        self.assertEqual(2, r.events.count("load_basis"))

    def test_asr_and_diar_are_exclusive_only_on_8gib(self):
        c, r = self.create()
        c.submit("diar", {"body": b"synthetic"}).future.result(2)
        eventually(lambda: c.status()["asr_ready"])
        self.assertIn("park_asr", r.events)
        self.assertFalse(c.status()["loaded"]["diar"])

    def test_persistent_triple_load_is_not_blocked(self):
        c, r = self.create(24)
        r.holds = {key: threading.Event() for key in ("a", "d", "l")}
        a = c.submit("asr", {}, request_id="a")
        d = c.submit("diar", {}, request_id="d")
        l = c.submit("llm", {"llm": {}}, request_id="l")
        eventually(lambda: len(r.active) == 3)
        self.assertEqual({"asr", "diar", "llm"}, set(r.active))
        for event in r.holds.values():event.set()
        for j in (a, d, l):j.future.result(2)

    def test_load_failure_falls_back_only_one_permitted_level(self):
        c, r = self.create(24)
        r.fail_load.add("sehr_gruendlich")
        source = {"llm": {"messages": [{"role": "user", "content": "Synthetischer Originaltext"}]}}
        job = c.submit("llm", source, "sehr_gruendlich")
        value = job.future.result(4)
        self.assertEqual("gruendlich", value["commander"]["used_quality"])
        self.assertTrue(value["commander"]["fallback_used"])
        self.assertIn("Gründlich", value["commander"]["notice"])
        self.assertNotIn("load_basis", r.events)
        self.assertEqual("Synthetischer Originaltext", source["llm"]["messages"][0]["content"])
        eventually(lambda: c.status()["asr_ready"])

    def test_16gib_processing_failure_uses_basis(self):
        c, r = self.create(16)
        r.fail_infer.add("gruendlich")
        result = c.submit("llm", {"llm": {}}, "gruendlich").future.result(4)
        self.assertEqual("basis", result["commander"]["used_quality"])

    def test_24gib_gruendlich_failure_never_uses_basis(self):
        c, r = self.create(24)
        r.fail_infer.add("gruendlich")
        with self.assertRaises(BackendFailure):
            c.submit("llm", {"llm": {}}, "gruendlich").future.result(3)
        self.assertNotIn("load_basis", r.events)
        eventually(lambda: c.status()["asr_ready"])

    def test_busy_worker_does_not_trigger_fallback(self):
        c, r = self.create(24)
        r.busy_asr = 1
        result = c.submit("llm", {"llm": {}}, "sehr_gruendlich").future.result(3)
        self.assertEqual("sehr_gruendlich", result["commander"]["used_quality"])
        self.assertFalse(result["commander"]["fallback_used"])

    def test_request_id_deduplicates_and_rejects_other_content(self):
        c, r = self.create()
        r.holds["same"] = threading.Event()
        original = c.submit("llm", {"llm": {"x": "first"}}, request_id="same")
        duplicate = c.submit("llm", {"llm": {"x": "first"}}, request_id="same")
        self.assertIs(original, duplicate)
        with self.assertRaises(Conflict):
            c.submit("llm", {"llm": {"x": "other"}}, request_id="same")
        r.holds["same"].set()
        original.future.result(2)

    def test_pending_serial_request_drains_asr_before_new_audio(self):
        c, r = self.create()
        r.holds = {"asr1": threading.Event(), "llm": threading.Event()}
        first = c.submit("asr", {}, request_id="asr1")
        eventually(lambda: "asr1" in r.started)
        llm = c.submit("llm", {"llm": {}}, request_id="llm")
        eventually(lambda: c.status()["phase"] == "waiting_for_active_work")
        later = c.submit("asr", {}, request_id="asr2")
        r.holds["asr1"].set()
        first.future.result(2)
        eventually(lambda: "llm" in r.started)
        self.assertNotIn("asr2", r.started)
        r.holds["llm"].set()
        llm.future.result(2)
        later.future.result(2)

    def test_missing_persistent_model_still_restores_asr_and_returns_error(self):
        cfg = Settings(tier=24)
        r = RuntimeDouble(cfg)
        r.fail_load.add("gruendlich")
        c = Commander(cfg, r)
        self.addCleanup(c.close)
        self.assertTrue(c.wait_ready(2))
        c.submit("asr", {}).future.result(2)
        with self.assertRaises(BackendFailure):
            c.submit("llm", {"llm": {}}).future.result(3)
        eventually(lambda: c.status()["asr_ready"])

    def test_queue_payload_memory_is_bounded(self):
        from kienzledoku_commander.errors import QueueFull
        c, r = self.create(max_payload_mib=1)
        r.holds["held"] = threading.Event()
        job = c.submit("asr", {"body": b"x" * 700000}, request_id="held")
        eventually(lambda: "held" in r.started)
        with self.assertRaises(QueueFull):
            c.submit("asr", {"body": b"x" * 700000})
        r.holds["held"].set()
        job.future.result(2)

    def test_processing_failure_restarts_broken_persistent_model(self):
        c, r = self.create(24)
        r.fail_infer.add("gruendlich")
        with self.assertRaises(BackendFailure):c.submit("llm", {"llm": {}}).future.result(2)
        r.fail_infer.clear()
        eventually(lambda: r.events.count("load_gruendlich") == 2)
        self.assertFalse(c.submit("llm", {"llm": {}}).future.result(2)["commander"]["fallback_used"])

    def test_busy_queue_timeout_does_not_downgrade(self):
        from kienzledoku_commander.errors import QueueExpired
        c, r = self.create(24, queue_timeout=.15)
        r.busy_asr = 100
        with self.assertRaises(QueueExpired):
            c.submit("llm", {"llm": {}}, "sehr_gruendlich").future.result(2)
        self.assertNotIn("load_sehr_gruendlich", r.events)
        self.assertNotIn("load_basis", r.events)

    def test_result_cache_expires_even_without_new_requests(self):
        c, r = self.create(remember_seconds=.05)
        c.submit("asr", {}, request_id="expires").future.result(2)
        eventually(lambda: "expires" not in c._remembered)

    def test_partial_worker_change_never_dispatches_into_a_closed_gate(self):
        c, r = self.create(24)
        original = r.park_asr
        failed = False
        def partial_park():
            nonlocal failed
            if not failed:
                failed = True
                r.loaded["asr"] = False
                raise BackendFailure()
            return original()
        r.park_asr = partial_park
        r.reload_hold = threading.Event()
        llm = c.submit("llm", {"llm": {}}, "sehr_gruendlich")
        eventually(lambda: c.status()["last_error"] == "model_change_failed")
        audio = c.submit("asr", {}, request_id="after-partial-park")
        self.assertTrue(r.reload_entered.wait(2))
        self.assertFalse(audio.future.done())
        r.reload_hold.set()
        audio.future.result(2)
        self.assertEqual("gruendlich", llm.future.result(3)["commander"]["used_quality"])


if __name__ == "__main__":unittest.main()
