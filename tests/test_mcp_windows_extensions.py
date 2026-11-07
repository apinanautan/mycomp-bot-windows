import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from mycomp_bot_engine.config import Settings
from mycomp_bot_engine.server import build_server


class WindowsMcpExtensionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "allowed"
        self.root.mkdir()
        (self.root / "a.txt").write_text("alpha", encoding="utf-8")
        (self.root / "b.txt").write_text("beta", encoding="utf-8")
        self.server = build_server(Settings(
            host="127.0.0.1", port=8645, allowed_roots=(self.root,),
            allow_shell=False, allowed_executables=(),
            data_dir=Path(self.temp.name) / "control",
            capability_dir=Path(self.temp.name) / "control" / "capabilities",
            redirect_uris=frozenset(), owner_consent_token=None,
            auth_mode="none", permission_level="elevated",
        ))

    def tearDown(self):
        self.server._mycomp_resources.close()
        self.temp.cleanup()

    def call(self, name, **arguments):
        result = asyncio.run(self.server.call_tool(name, arguments))
        if isinstance(result, dict):
            return result
        if isinstance(result, tuple) and result[0]:
            return json.loads(result[0][0].text)
        self.fail("Unexpected MCP result " + str(result)[:250])

    def test_filesystem_read_write_and_protected_roots(self):
        read = self.call("filesystem", operation="read", path="a.txt")
        self.assertEqual(read["results"][0]["content"], "alpha")
        write = self.call("filesystem", operation="patch", path="a.txt", old="alpha", new="gamma")
        self.assertTrue(write["changed"])
        self.assertEqual((self.root / "a.txt").read_text(), "gamma")
        blocked = self.call("filesystem", operation="read", path="../control")
        self.assertEqual(blocked["status"], "failed")

    def test_batch_read_partial_failures_and_bounds(self):
        result = self.call("batch_read", paths=["a.txt", "missing.txt", "b.txt"])
        self.assertEqual([item["ok"] for item in result["results"]], [True, False, True])
        self.assertEqual(result["results"][0]["result"]["content"], "alpha")
        invalid = self.call("batch_read", paths=["a.txt"] * 21)
        self.assertEqual(invalid["status"], "failed")

    def test_vision_forwards_windows_window_selector(self):
        from unittest.mock import patch
        from mycomp_bot_engine import server as module
        with patch.object(self.server._mycomp_resources.capabilities, "execute", return_value={"ok": True, "result": {"width": 10}}) as bridge:
            result = self.call("vision", action="capture_window", app={"handle": 1234, "name_contains": "Test"})
        self.assertEqual(result["status"], "completed")
        name, payload = bridge.call_args.args
        self.assertEqual(payload["handle"], 1234)
        self.assertEqual(payload["name_contains"], "Test")
        self.assertEqual(payload["action"], "capture_window")
    def test_windows_automation_requires_full_control(self):
        denied = self.call("windows_automation", script="Write-Output ok", dry_run=True)
        self.assertEqual(denied["status"], "failed")
        self.assertEqual(denied["error"]["code"], "PERMISSION_DENIED")
    def test_diagnostics_excludes_secrets(self):
        result = self.call("diagnostics")
        item = result["results"][0]
        self.assertEqual(item["tool_count"], 12)
        self.assertEqual(item["permission_level"], "elevated")
        self.assertNotIn("token", str(item).lower())
        self.assertNotIn("api_key", str(item).lower())


if __name__ == "__main__":
    unittest.main()