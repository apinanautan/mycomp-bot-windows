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

    def test_prompt_never_exposes_saved_id_or_secrets(self):
        # v1.1.23+ deliberately never inlines the saved tunnel id or key: the
        # recipient GPT may be signed into a different Platform account.
        import json
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            tunnel = Tunnel(Path(directory))
            tunnel.directory.mkdir(parents=True)
            tunnel.settings.write_text(json.dumps({
                "tunnel_id": "tunnel_" + "a" * 32,
                "enabled": False,
                "api_key": "sk-FAKE-API-KEY",
            }), encoding="utf-8")
            tunnel.secret.write_bytes(b"sk-FAKE-SECRET")
            with patch.object(tunnel.secret.__class__, "read_bytes", side_effect=AssertionError("secrets must not be read")):
                result = tunnel.plugin_prompt("ทดสอบปลั๊กอิน", "https://desktop.example.ts.net/mycomp")
            self.assertNotIn("tunnel_" + "a" * 32, result)
            self.assertIn(tunnel.mcp_endpoint, result)
            self.assertIn("tools/list", result)
            self.assertIn("OpenAI Secure MCP Tunnel", result)
            self.assertGreater(result.count("\n"), 5)
            self.assertNotIn("\\n", result)
            self.assertNotIn("sk-FAKE", result)
            self.assertNotIn("8455", result)

    def test_prompt_ignores_stale_saved_settings(self):
        # The prompt is generated from the entered name alone; a missing or
        # malformed saved tunnel id must never abort it.
        import json
        with tempfile.TemporaryDirectory() as directory:
            tunnel = Tunnel(Path(directory))
            for value in (None, "tunnel_" + "a" * 31, "tunnel_" + "z" * 32, "old_tunnel", "tunnel_" + "b" * 32 + "\n"):
                tunnel.directory.mkdir(parents=True, exist_ok=True)
                tunnel.settings.write_text(json.dumps({"tunnel_id": value}), encoding="utf-8")
                with self.subTest(value=value):
                    prompt = tunnel.plugin_prompt("ทดสอบปลั๊กอิน", "https://desktop.example.ts.net/mycomp")
                    self.assertIn("ทดสอบปลั๊กอิน", prompt)
            tunnel.settings.unlink()
            prompt = tunnel.plugin_prompt("ทดสอบปลั๊กอิน", "https://desktop.example.ts.net/mycomp")
            self.assertIn("ทดสอบปลั๊กอิน", prompt)

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
            self.assertIn("My Home Robot Tailscale", prompt)
            self.assertIn("My Home Robot Tunnel", prompt)
            # The saved id is never inlined.
            self.assertNotIn("tunnel_" + "c" * 32, prompt)
            self.assertIn("Tailscale", prompt)
            self.assertIn("OpenAI Secure MCP Tunnel", prompt)
            self.assertIn("fallback", prompt)
            self.assertIn("tools/list", prompt)
            self.assertIn("OAuth", prompt)
            self.assertNotIn("sk-", prompt)

    def test_prompt_includes_skills_and_tool_guidance(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            tunnel = Tunnel(Path(directory))
            tunnel.directory.mkdir(parents=True)
            tunnel.settings.write_text(json.dumps({
                "tunnel_id": "tunnel_" + "d" * 32,
                "enabled": True,
            }), encoding="utf-8")
            prompt = tunnel.plugin_prompt("User Named Bot", "https://desktop.example.ts.net/mycomp")
            self.assertIn("User Named Bot Tailscale", prompt)
            self.assertIn("User Named Bot Tunnel", prompt)
            self.assertIn("skills/operator-clarity/SKILL.md", prompt)
            for name in ("development-loop", "ponytail", "tool-routing",
                         "connection-recovery", "agent-desktop-portable"):
                self.assertIn(name, prompt)
            self.assertIn("Remote Desktop Commander", prompt)
            self.assertIn("dom_cdp.launch", prompt)
            self.assertIn("ห้ามใช้ webbrowser.open", prompt)
            self.assertLess(prompt.index("STEP 0"), prompt.index("STEP 1"))
            self.assertLess(prompt.index("STEP 1"), prompt.index("STEP 2"))
            self.assertLess(prompt.index("STEP 2"), prompt.index("STEP 3"))
            self.assertLess(prompt.index("STEP 3"), prompt.index("STEP 4"))
            self.assertLess(prompt.index("STEP 4"), prompt.index("STEP 5"))
            self.assertNotIn("\\n", prompt)
            self.assertNotIn("sk-", prompt)

    def test_prompt_validates_plugin_name_and_computer_name(self):
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
            # The tailscale base is informational and never validated.
            for base in ("", "http://desktop.example.ts.net", "https://example.com",
                         "https://desktop.example.ts.net?token=private",
                         "https://name:secret@desktop.example.ts.net",
                         "https://desktop.example.ts.net:5555"):
                with self.subTest(base=base):
                    prompt = tunnel.plugin_prompt("My Robot", base)
                    self.assertIn("My Robot", prompt)
            for machine in ("", "not a hostname", "x" * 64):
                with self.subTest(machine=machine), self.assertRaises(ValueError):
                    tunnel.plugin_prompt("My Robot", "https://desktop.example.ts.net/mycomp", computer_name=machine)

    def test_prompt_uses_local_endpoint_not_tailscale_base(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            tunnel = Tunnel(Path(directory))
            tunnel.directory.mkdir(parents=True)
            tunnel.settings.write_text(json.dumps({
                "tunnel_id": "tunnel_" + "c" * 32,
            }), encoding="utf-8")
            prompt = tunnel.plugin_prompt("Test Bot", "https://desktop.example.ts.net:8443/mycomp/")
            # The prompt points at the local MCP upstream, never the caller's base.
            self.assertIn(tunnel.mcp_endpoint, prompt)
            self.assertNotIn("https://desktop.example.ts.net:8443/mycomp/mcp", prompt)
            self.assertNotIn("//mcp", prompt)


if __name__ == "__main__":
    unittest.main()
