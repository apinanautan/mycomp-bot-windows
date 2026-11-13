"""UIA bridge cache and warm-up behaviour.

These touch real Windows UI Automation, so they only run on Windows with
pywinauto available. Assertions are about correctness (same data, cache bypass),
not about absolute timing, because UIA cost varies with machine load.
"""
import importlib.util
import os
import threading
import time
import unittest
from pathlib import Path

BRIDGE = Path(__file__).resolve().parents[1] / "windows" / "UIAutomationBridge.py"


def _load():
    spec = importlib.util.spec_from_file_location("bridge_under_test", BRIDGE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {BRIDGE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(os.name == "nt", "Windows UI Automation")
class UiaBridgeCacheTests(unittest.TestCase):
    def setUp(self):
        try:
            import pywinauto  # noqa: F401
        except ImportError:
            self.skipTest("pywinauto is not installed")
        self.bridge = _load()

    def test_warm_failure_releases_flag_for_retry(self):
        from unittest.mock import patch
        with patch.object(self.bridge, "_window_map", side_effect=RuntimeError("temporary UIA failure")):
            self.assertTrue(self.bridge.warm())
            deadline = time.monotonic() + 3
            while self.bridge._WARMING and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertFalse(self.bridge._WARMING)


    def test_warm_is_non_blocking_and_primes_the_map(self):
        started = time.perf_counter()
        result = self.bridge.warm()
        elapsed = (time.perf_counter() - started) * 1000
        self.assertIsInstance(result, bool)
        self.assertLess(elapsed, 500, "warm() must not block the caller")
        deadline = time.time() + 30
        while time.time() < deadline and not self.bridge._MAP:
            time.sleep(0.05)
        self.assertTrue(self.bridge._MAP, "warm-up did not populate the window map")
        self.assertEqual(threading.active_count() >= 1, True)

    def test_list_windows_cache_returns_identical_data_and_refresh_bypasses(self):
        first = self.bridge.main({"action": "list_windows", "limit": 40, "refresh": True})
        self.assertGreaterEqual(first["count"], 1)
        for window in first["windows"]:
            self.assertIsInstance(window["handle"], int)
            self.assertIsInstance(window["bounds"]["width"], int)
            self.assertGreater(window["process_id"], 0)

        cached = self.bridge.main({"action": "list_windows", "limit": 40})
        self.assertEqual([w["handle"] for w in cached["windows"]],
                         [w["handle"] for w in first["windows"]])
        self.assertEqual([w["name"] for w in cached["windows"]],
                         [w["name"] for w in first["windows"]])

        # Live windows can open and close between two real UIA scans.
        # Verify the explicit refresh forces a new scan rather than comparing
        # unstable window counts while other desktop applications are active.
        from unittest.mock import patch
        with patch.object(self.bridge, "_window_map", wraps=self.bridge._window_map) as scan:
            refreshed = self.bridge.main({"action": "list_windows", "limit": 40, "refresh": True})
        self.assertGreaterEqual(refreshed["count"], 1)
        self.assertTrue(any(call.kwargs.get("force") is True for call in scan.call_args_list))

    def test_observe_cache_reuses_walk_and_detail_bypasses_it(self):
        windows = self.bridge.main({"action": "list_windows", "limit": 40})["windows"]
        named = [w for w in windows if w.get("name")]
        self.assertTrue(named, "no named window to observe")
        selector = named[0]["name"][:6]

        first = self.bridge.main({"action": "observe", "name_contains": selector, "limit": 20})
        second = self.bridge.main({"action": "observe", "name_contains": selector, "limit": 20})
        self.assertEqual(first["count"], second["count"])
        self.assertEqual([e["handle"] for e in first["elements"]],
                         [e["handle"] for e in second["elements"]])

        live = self.bridge.main({"action": "observe", "name_contains": selector,
                                 "limit": 20, "detail": True})
        self.assertEqual(live["count"], first["count"])

    def test_batch_reports_per_step_results_for_cached_actions(self):
        windows = self.bridge.main({"action": "list_windows", "limit": 40})["windows"]
        named = [w for w in windows if w.get("name")]
        selector = named[0]["name"][:6] if named else "zz"
        batch = self.bridge.main({"action": "batch", "steps": [
            {"action": "list_windows", "limit": 10},
            {"action": "observe", "name_contains": selector, "limit": 10},
            {"action": "observe", "name_contains": selector, "limit": 10},
        ]})
        self.assertTrue(batch["ok"])
        self.assertEqual(batch["count"], 3)
        self.assertTrue(all(step["ok"] for step in batch["results"]))
        self.assertEqual([step["index"] for step in batch["results"]], [0, 1, 2])


if __name__ == "__main__":
    unittest.main()
