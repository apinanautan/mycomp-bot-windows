"""Fast, strictly read-only Windows top-level window enumeration."""
from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "capability_sources" / "windows_ui.py"


def load_module():
    spec = importlib.util.spec_from_file_location("windows_ui_fast_test", SOURCE)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load Windows capability")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(os.name == "nt", "Windows Win32 windows")
class NativeWindowListingTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()

    def test_fast_snapshot_and_handle_selector(self):
        response = self.module.execute({"action": "list_windows", "limit": 40})
        self.assertTrue(response["ok"])
        data = response["result"]
        self.assertEqual(data["backend"], "win32-top-level")
        self.assertTrue(0 < data["count"] <= 40)
        self.assertEqual(len(data["windows"]), data["count"])
        for window in data["windows"]:
            self.assertGreater(window["handle"], 0)
            self.assertGreater(window["process_id"], 0)
            self.assertGreater(window["bounds"]["width"], 0)
        first = data["windows"][0]
        single = self.module.execute({"action": "list_windows", "handle": first["handle"]})
        self.assertEqual(single["result"]["count"], 1)
        self.assertEqual(single["result"]["windows"][0]["process_id"], first["process_id"])

    def test_uia_detail_and_mutations_remain_host_supervised(self):
        with patch.object(self.module, "_request", return_value={"ok": True, "result": {"from_host": True}}) as host:
            result = self.module.execute({"action": "list_windows", "detail": True})
            self.assertTrue(result["result"]["from_host"])
            self.assertEqual(host.call_count, 1)
            result = self.module.execute({"action": "click", "handle": 1234})
            self.assertTrue(result["result"]["from_host"])
            self.assertEqual(host.call_count, 2)

    def test_owner_stop_still_blocks_list_windows(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            (runtime / "ui-stop-request.json").write_text("{}", encoding="utf-8")
            with patch.object(self.module, "_runtime", return_value=runtime):
                with patch.object(self.module, "_request", return_value={"ok": False, "stopped": True}) as host:
                    result = self.module.execute({"action": "list_windows"})
                    self.assertFalse(result["ok"])
                    self.assertTrue(result["stopped"])
                    self.assertEqual(host.call_count, 1)

    def test_status_does_not_depend_on_gui_poll(self):
        with patch.object(self.module, "_request", side_effect=AssertionError("GUI was polled")):
            result = self.module.execute({"action": "status"})
        self.assertTrue(result["ok"])
        self.assertTrue(result["result"]["available"])


if __name__ == "__main__":
    unittest.main()
