"""Blender MCP first-class tool safety and live client boundary tests."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mycomp_bot_engine.config import Settings
from mycomp_bot_engine.server import build_server
from mycomp_bot_engine import blender_mcp as bridge


class BlenderMcpToolTests(unittest.TestCase):
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
            host="127.0.0.1", port=8645,
            allowed_roots=(self.home,), allow_shell=False, allowed_executables=(),
            data_dir=self.home / ("control_" + level),
            capability_dir=self.home / ("control_" + level) / "capabilities",
            redirect_uris=frozenset(), owner_consent_token=None,
            auth_mode="none", permission_level=level,
        )
        instance = build_server(settings)
        self.instances.append(instance)
        return instance

    def invoke(self, server, **kwargs):
        result = asyncio.run(server.call_tool("blender_mcp", kwargs))
        if isinstance(result, tuple):
            import json
            return json.loads(result[0][0].text)
        return result

    def test_status_and_list_are_read_only(self):
        server = self.server()
        with patch("mycomp_bot_engine.server.run_blender_mcp",
                   return_value={"host": "127.0.0.1", "addon_listening": False}) as backend:
            answer = self.invoke(server, operation="status")
        self.assertEqual(answer["status"], "completed")
        self.assertFalse(answer["changed"])
        self.assertEqual(backend.call_args.args[0], "status")

    def test_normal_and_elevated_cannot_modify(self):
        for level in ("normal", "elevated"):
            server = self.server(level)
            with patch("mycomp_bot_engine.server.run_blender_mcp") as backend:
                answer = self.invoke(server, operation="call_tool",
                                     tool="execute_blender_code",
                                     arguments={"code": "bpy.ops.object.delete()"},
                                     allow_write=True)
            self.assertEqual(answer["status"], "failed")
            backend.assert_not_called()

    def test_full_permission_requires_explicit_allow_write(self):
        server = self.server("full")
        with patch("mycomp_bot_engine.server.run_blender_mcp") as backend:
            blocked = self.invoke(server, operation="call_tool", tool="execute_blender_code")
        self.assertEqual(blocked["status"], "failed")
        backend.assert_not_called()
        with patch("mycomp_bot_engine.server.run_blender_mcp",
                   return_value={"tool": "execute_blender_code", "isError": False}) as backend:
            allowed = self.invoke(server, operation="call_tool",
                                  tool="execute_blender_code",
                                  arguments={"code": "print(1)"}, allow_write=True)
        self.assertTrue(allowed["changed"])
        self.assertEqual(allowed["status"], "completed")
        backend.assert_called_once()

    def test_sdk_bridge_limits_endpoints_and_names(self):
        with self.assertRaises(ValueError):
            bridge.run_blender_mcp("call_tool", "not_a_blender_tool", {})
        with self.assertRaises(ValueError):
            bridge.run_blender_mcp("anything")
        with patch.object(bridge.socket, "create_connection", side_effect=OSError):
            offline = bridge.run_blender_mcp("status")
        self.assertFalse(offline["addon_listening"])


if __name__ == "__main__":
    unittest.main()
