"""Ai-iclone tool: fixed commands only, permission gates, user words for approve."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mycomp_bot_engine.config import Settings
from mycomp_bot_engine.server import build_server
from mycomp_bot_engine import ai_iclone as bridge


class AiIcloneToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.instances = []

    def tearDown(self):
        for inst in self.instances:
            inst._mycomp_resources.close()
        self.tmp.cleanup()

    def server(self, level="normal"):
        settings = Settings(
            host="127.0.0.1", port=8646,
            allowed_roots=(self.home,), allow_shell=False, allowed_executables=(),
            data_dir=self.home / ("c_" + level), capability_dir=self.home / ("c_" + level) / "capabilities",
            redirect_uris=frozenset(), owner_consent_token=None, auth_mode="none", permission_level=level,
        )
        instance = build_server(settings)
        self.instances.append(instance)
        return instance

    def invoke(self, server, **kwargs):
        result = asyncio.run(server.call_tool("ai_iclone", kwargs))
        if isinstance(result, tuple):
            return json.loads(result[0][0].text)
        return result

    def test_args_are_fixed(self):
        self.assertEqual(bridge.build_args("manual"), [])
        self.assertEqual(bridge.build_args("do", dry=True, retry=True), ["do", "--dry", "--force"])
        self.assertEqual(bridge.build_args("use", story="เรื่อง", part=3), ["use", "เรื่อง", "3"])
        self.assertEqual(bridge.build_args("range", time_range="7:14-9:00"), ["range", "7:14-9:00"])
        self.assertEqual(bridge.build_args("approve", user_said="ผ่าน"), ["approve", "--said", "ผ่าน"])
        for bad in (dict(command="approve", user_said="  "), dict(command="rules"), dict(command="rm")):
            with self.assertRaises(ValueError):
                bridge.build_args(**bad)

    def test_status_needs_only_normal(self):
        server = self.server("normal")
        with patch("mycomp_bot_engine.server.run_ai_iclone",
                   return_value={"isError": False, "exit": 0, "text": "ok"}) as backend:
            answer = self.invoke(server, command="status")
        self.assertEqual(answer["status"], "completed")
        self.assertFalse(answer["changed"])
        self.assertEqual(backend.call_args.args[0], ["status"])

    def test_do_needs_elevated(self):
        with patch("mycomp_bot_engine.server.run_ai_iclone") as backend:
            answer = self.invoke(self.server("normal"), command="do")
        self.assertEqual(answer["status"], "failed")
        backend.assert_not_called()
        with patch("mycomp_bot_engine.server.run_ai_iclone",
                   return_value={"isError": False, "exit": 2, "text": "STOP"}) as backend:
            answer = self.invoke(self.server("elevated"), command="do")
        self.assertTrue(answer["changed"])
        self.assertEqual(backend.call_args.args[0], ["do"])

    def test_missing_exe_is_reported(self):
        with patch.object(bridge, "find_exe", return_value=None):
            data = bridge.run_ai_iclone(["status"])
        self.assertTrue(data["isError"])
        self.assertIn("releases/latest", data["text"])


if __name__ == "__main__":
    unittest.main()
