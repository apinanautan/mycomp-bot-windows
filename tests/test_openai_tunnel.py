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
                result = tunnel.plugin_prompt()
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
                    tunnel.plugin_prompt()
            tunnel.settings.unlink()
            with self.assertRaises(ValueError):
                tunnel.plugin_prompt()

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
            self.assertIn(tunnel.mcp_endpoint, tunnel.plugin_prompt())
            self.assertNotIn("sk-", tunnel.plugin_prompt())
            tunnel.stop()


if __name__ == "__main__":
    unittest.main()
