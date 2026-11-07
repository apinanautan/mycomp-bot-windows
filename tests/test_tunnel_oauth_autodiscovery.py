import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock, patch

from windows.openai_tunnel import Tunnel


class TunnelOAuthAutodiscoveryTests(TestCase):
    def test_saved_funnel_origin_is_normalized_and_not_guessed(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text(
                "MYCOMP_PUBLIC_BASE_URL=https://desktop-odicjs3.example.ts.net/some/path\n",
                encoding="utf-8",
            )
            tunnel = Tunnel(root)
            with patch.dict(os.environ, {"MYCOMP_PUBLIC_BASE_URL": ""}):
                self.assertEqual(
                    tunnel._configured_oauth_origin(),
                    "https://desktop-odicjs3.example.ts.net",
                )
            with patch.dict(os.environ, {"MYCOMP_PUBLIC_BASE_URL": "http://example.com"}):
                self.assertIsNone(tunnel._configured_oauth_origin())

    def test_running_existing_tunnel_adds_scoped_oauth_discovery_settings(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text(
                "MYCOMP_PUBLIC_BASE_URL=https://desktop-odicjs3.example.ts.net\n",
                encoding="utf-8",
            )
            tunnel = Tunnel(root)
            tunnel.directory.mkdir(parents=True, exist_ok=True)
            tunnel.binary.parent.mkdir(parents=True, exist_ok=True)
            tunnel.binary.touch()
            tunnel.settings.write_text(json.dumps({
                "tunnel_id": "tunnel_" + "a" * 32, "enabled": True,
            }), encoding="utf-8")
            tunnel.secret.write_bytes(b"placeholder-encrypted")
            process = MagicMock()
            process.poll.return_value = 0
            with patch.dict(os.environ, {"MYCOMP_PUBLIC_BASE_URL": ""}), \
                 patch("windows.openai_tunnel.protect", return_value=b"sk-" + b"x" * 25), \
                 patch("windows.openai_tunnel.subprocess.Popen", return_value=process) as launch:
                tunnel.start()
            args, kwargs = launch.call_args
            env = kwargs["env"]
            self.assertEqual(env["MCP_OAUTH_TRUSTED_ORIGINS"], "https://desktop-odicjs3.example.ts.net")
            self.assertEqual(env["HARPOON_OAUTH_FORWARD_ORIGINS"], "https://desktop-odicjs3.example.ts.net")
            self.assertEqual(env["HARPOON_ALLOW_PLAINTEXT_HTTP"], "true")
            self.assertEqual(args[0][args[0].index("--mcp.server-url") + 1], "http://127.0.0.1:8645/mcp")
            self.assertNotIn("sk-", " ".join(args[0]))
            tunnel.stop()

    def test_missing_public_url_does_not_grant_any_forwarding_origin(self):
        with TemporaryDirectory() as directory:
            tunnel = Tunnel(Path(directory))
            with patch.dict(os.environ, {"MYCOMP_PUBLIC_BASE_URL": ""}):
                self.assertIsNone(tunnel._configured_oauth_origin())
