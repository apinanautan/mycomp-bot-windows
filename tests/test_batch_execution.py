import asyncio
import os
import tempfile
import unittest
from pathlib import Path

from mycomp_bot_engine.config import Settings
from mycomp_bot_engine.server import build_server


class BatchExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "root"
        self.root.mkdir()
        (self.root / "example.txt").write_text("hello", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def server(self, level):
        return build_server(Settings(
            host="127.0.0.1", port=8645, allowed_roots=(self.root,),
            allow_shell=True, allowed_executables=(), data_dir=Path(self.temp.name) / ("state_" + level),
            capability_dir=Path(self.temp.name) / ("caps_" + level),
            redirect_uris=frozenset(), owner_consent_token=None,
            permission_level=level, auth_mode="none",
        ))

    def call(self, server, steps, **kwargs):
        tool = server._tool_manager.get_tool("batch_execute")
        return asyncio.run(tool.fn(steps=steps, **kwargs))

    def test_each_step_checks_own_permission_and_keeps_going(self):
        server = self.server("normal")
        try:
            result = self.call(server, [
                {"kind":"filesystem","operation":"read","path":"example.txt"},
                {"kind":"filesystem","operation":"write","path":"example.txt","content":"changed"},
                {"kind":"shell","executable":"cmd","arguments":["/c","hostname"]},
                {"kind":"filesystem","operation":"stat","path":"example.txt"},
            ])
            self.assertEqual(result["status"], "partial")
            self.assertEqual([v["ok"] for v in result["results"]], [True,False,False,True])
            self.assertEqual((self.root / "example.txt").read_text(), "hello")
        finally:
            server._mycomp_resources.close()

    def test_full_control_shell_and_filesystem(self):
        server = self.server("full")
        try:
            result = self.call(server, [
                {"kind":"shell","executable":"cmd","arguments":["/c","hostname"],"execution":"foreground"},
                {"kind":"filesystem","operation":"read","path":"example.txt"},
                {"kind":"shell","executable":"cmd","arguments":["/c","hostname"],"execution":"foreground"},
            ])
            self.assertEqual(result["status"], "completed",result)
            self.assertEqual(len(result["results"]),3)
            self.assertEqual(result["results"][0]["result"]["state"],"finished")
        finally:
            server._mycomp_resources.close()

    def test_stop_on_error_and_cap(self):
        server = self.server("normal")
        try:
            r=self.call(server,[{"kind":"bad"},{"kind":"filesystem","operation":"read","path":"example.txt"}],stop_on_error=True)
            self.assertEqual(r["status"],"failed")
            self.assertEqual(len(r["results"]),1)
            r=self.call(server,[{"kind":"filesystem","operation":"read","path":"example.txt"}]*13)
            self.assertEqual(r["status"],"failed")
        finally:
            server._mycomp_resources.close()

    def test_http_mcp_batch_rechecks_each_step(self):
        from starlette.testclient import TestClient
        from mycomp_bot_engine.server import create_app
        settings = Settings(
            host="127.0.0.1", port=8645, allowed_roots=(self.root,),
            allow_shell=False, allowed_executables=(),
            data_dir=Path(self.temp.name) / "http_state",
            capability_dir=Path(self.temp.name) / "http_caps",
            redirect_uris=frozenset(), owner_consent_token=None,
            auth_mode="none", permission_level="normal",
        )
        with TestClient(create_app(settings), base_url="http://127.0.0.1:8645") as client:
            headers={"Accept":"application/json, text/event-stream"}
            result=client.post("/mcp", headers=headers, json={
                "jsonrpc":"2.0", "id":3, "method":"tools/call",
                "params":{"name":"batch_execute","arguments":{"steps":[
                    {"kind":"filesystem","operation":"read","path":"example.txt"},
                    {"kind":"filesystem","operation":"write","path":"example.txt","content":"bad"},
                    {"kind":"filesystem","operation":"stat","path":"example.txt"},
                ]}},
            })
            self.assertEqual(result.status_code, 200, result.text)
            body=result.json()["result"]
            parsed=body.get("structuredContent",body)
            self.assertEqual(parsed["status"],"partial",body)
            self.assertEqual([x["ok"] for x in parsed["results"]],[True,False,True])
            self.assertEqual((self.root/"example.txt").read_text(),"hello")
if __name__ == "__main__":
    unittest.main()