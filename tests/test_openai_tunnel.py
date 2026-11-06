import os
from pathlib import Path
import tempfile
import unittest
from windows.openai_tunnel import Tunnel, protect, validate


class TunnelTests(unittest.TestCase):
    def test_validation(self):
        validate("tunnel_" + "a" * 32, "sk-" + "x" * 30)
        for tunnel, key in [("bad", "sk-" + "x" * 30), ("tunnel_" + "a" * 32, "bad")]:
            with self.assertRaises(ValueError):
                validate(tunnel, key)

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI")
    def test_secret_round_trip_and_settings(self):
        secret = "sk-" + "x" * 30
        self.assertEqual(protect(protect(secret.encode()), True), secret.encode())
        with tempfile.TemporaryDirectory() as directory:
            tunnel = Tunnel(Path(directory))
            tunnel.save("tunnel_" + "a" * 32, secret, False)
            self.assertNotIn(secret.encode(), tunnel.secret.read_bytes())
            self.assertNotIn(secret, tunnel.settings.read_text())
            tunnel.save("tunnel_" + "b" * 32, "", False)
            self.assertEqual(protect(tunnel.secret.read_bytes(), True).decode(), secret)
            tunnel.tick()
            self.assertIsNone(tunnel.process)

    def test_prompt_uses_saved_id_and_runtime_endpoint_without_secrets(self):
        import json
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            tunnel = Tunnel(Path(directory))
            tunnel.directory.mkdir(parents=True)
            tunnel.settings.write_text(json.dumps({
                "tunnel_id": "tunnel_" + "a" * 32,
                "enabled": False,
                "api_key": "sk-NEVER-EXPOSE-THIS-SECRET-000",
            }), encoding="utf-8")
            tunnel.secret.write_bytes(b"sk-ALSO-NEVER-EXPOSE")
            with patch.object(tunnel.secret.__class__, "read_bytes", side_effect=AssertionError("secrets must not be read")):
                result = tunnel.plugin_prompt("ทดสอบปลั๊กอิน", "https://desktop.example.ts.net/mycomp")
            self.assertIn("tunnel_" + "a" * 32, result)
            self.assertIn(tunnel.mcp_endpoint, result)
            self.assertIn("tools/list", result)
            self.assertIn("authentication", result)
            self.assertIn("Runtime ready", result)
            self.assertGreater(result.count("\n"), 5)
            self.assertNotIn("\\n", result)
            self.assertNotIn("sk-NEVER", result)
            self.assertNotIn("sk-ALSO", result)
            self.assertNotIn("8455", result)

    def test_missing_or_invalid_saved_id_is_rejected_and_not_replaced(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            tunnel = Tunnel(Path(directory))
            for value in (None, "tunnel_" + "a" * 31, "tunnel_" + "z" * 32, "old_tunnel", "tunnel_" + "b" * 32 + "\\n"):
                tunnel.directory.mkdir(parents=True, exist_ok=True)
                tunnel.settings.write_text(json.dumps({"tunnel_id": value}), encoding="utf-8")
                with self.subTest(value=value), self.assertRaises(ValueError):
                    tunnel.plugin_prompt("ทดสอบปลั๊กอิน", "https://desktop.example.ts.net/mycomp")
            tunnel.settings.unlink()
            with self.assertRaises(ValueError):
                tunnel.plugin_prompt("ทดสอบปลั๊กอิน", "https://desktop.example.ts.net/mycomp")

    def test_runtime_process_and_prompt_use_same_binding(self):
        import json
        from unittest.mock import patch, MagicMock
        with tempfile.TemporaryDirectory() as directory:
            tunnel = Tunnel(Path(directory))
            tunnel.directory.mkdir(parents=True)
            tunnel.binary.parent.mkdir(parents=True)
            tunnel.binary.touch()
            tunnel.settings.write_text(json.dumps({
                "tunnel_id": "tunnel_" + "a" * 32, "enabled": True,
            }), encoding="utf-8")
            tunnel.secret.write_bytes(b"fake-encrypted-key")
            process = MagicMock()
            with patch("windows.openai_tunnel.protect", return_value=b"sk-" + b"x" * 25), \
                 patch("windows.openai_tunnel.subprocess.Popen", return_value=process) as start:
                tunnel.start()
            args = start.call_args.args[0]
            self.assertEqual(args[args.index("--mcp.server-url") + 1], tunnel.mcp_endpoint)
            self.assertIn(tunnel.mcp_endpoint, tunnel.plugin_prompt("ทดสอบปลั๊กอิน", "https://desktop.example.ts.net/mycomp"))
            self.assertNotIn("sk-", tunnel.plugin_prompt("ทดสอบปลั๊กอิน", "https://desktop.example.ts.net/mycomp"))
            tunnel.stop()


    def test_dual_transport_prompt_and_name_and_failover(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            tunnel = Tunnel(Path(directory))
            tunnel.directory.mkdir(parents=True)
            tunnel.settings.write_text(json.dumps({
                "tunnel_id": "tunnel_" + "c" * 32,
                "enabled": True,
            }), encoding="utf-8")
            prompt = tunnel.plugin_prompt("My Home Robot", "https://desktop.example.ts.net/mycomp")
            self.assertIn("My Home Robot", prompt)
            self.assertIn("https://desktop.example.ts.net/mycomp/mcp", prompt)
            self.assertIn("tunnel_" + "c" * 32, prompt)
            self.assertIn("Tailscale", prompt)
            self.assertIn("OpenAI Secure MCP Tunnel", prompt)
            self.assertIn("failover", prompt)
            self.assertIn("tools/list", prompt)
            self.assertIn("OAuth", prompt)
            self.assertIn("Runtime ready", prompt)
            self.assertNotIn("sk-", prompt)

    def test_prompt_includes_per_machine_agent_desktop_after_dual_plugins(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            tunnel = Tunnel(Path(directory))
            tunnel.directory.mkdir(parents=True)
            tunnel.settings.write_text(json.dumps({
                "tunnel_id": "tunnel_" + "d" * 32,
                "enabled": True,
            }), encoding="utf-8")
            prompt = tunnel.plugin_prompt("User Named Bot", "https://desktop.example.ts.net/mycomp")
            self.assertIn("User Named Bot (Tailscale)", prompt)
            self.assertIn("User Named Bot (Tunnel)", prompt)
            self.assertIn("https://github.com/vercel-labs/agent-desktop", prompt)
            self.assertIn("agent-desktop version", prompt)
            self.assertIn("agent-desktop status", prompt)
            self.assertIn("agent-desktop mcp", prompt)
            self.assertIn("stdio", prompt)
            self.assertIn("list-windows", prompt)
            self.assertIn("snapshot", prompt)
            self.assertIn("ref ID", prompt)
            self.assertIn("bridge", prompt)
            self.assertIn("ยินยอม", prompt)
            self.assertLess(prompt.index("ขั้นที่ 1:"), prompt.index("ขั้นที่ 2:"))
            self.assertLess(prompt.index("ขั้นที่ 2:"), prompt.index("ขั้นที่ 3:"))
            self.assertLess(prompt.index("ขั้นที่ 3:"), prompt.index("ขั้นที่ 4:"))
            self.assertNotIn("\\n", prompt)
            self.assertNotIn("sk-", prompt)

    def test_prompt_validates_plugin_name_and_tailscale_base(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            tunnel = Tunnel(Path(directory))
            tunnel.directory.mkdir(parents=True)
            tunnel.settings.write_text(json.dumps({
                "tunnel_id": "tunnel_" + "b" * 32,
            }), encoding="utf-8")
            for name in ("", " ", "x" * 81, "invalid\nname", None):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    tunnel.plugin_prompt(name, "https://desktop.example.ts.net/mycomp")
            for base in ("", "http://desktop.example.ts.net", "https://example.com",
                         "https://desktop.example.ts.net?token=private",
                         "https://name:secret@desktop.example.ts.net",
                         "https://desktop.example.ts.net:5555"):
                with self.subTest(base=base), self.assertRaises(ValueError):
                    tunnel.plugin_prompt("My Robot", base)

    def test_tailscale_port_and_subpath_preserved(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            tunnel = Tunnel(Path(directory))
            tunnel.directory.mkdir(parents=True)
            tunnel.settings.write_text(json.dumps({
                "tunnel_id": "tunnel_" + "c" * 32,
            }), encoding="utf-8")
            prompt = tunnel.plugin_prompt("Test Bot", "https://desktop.example.ts.net:8443/mycomp/")
            self.assertIn("https://desktop.example.ts.net:8443/mycomp/mcp", prompt)
            self.assertNotIn("https://desktop.example.ts.net:8443/mycomp//mcp", prompt)


if __name__ == "__main__":
    unittest.main()
