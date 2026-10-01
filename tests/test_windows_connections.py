import os
from pathlib import Path
import unittest


@unittest.skipUnless(os.name == "nt", "Windows host only")
class ConnectionTests(unittest.TestCase):
    def test_installer_keeps_tailscale_funnel_isolated(self):
        script = (Path(__file__).resolve().parents[1] / "windows/Install MyComp Bot.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("tailscale funnel", script)
        self.assertNotIn("Secure MCP Tunnel", script)
