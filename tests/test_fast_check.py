"""Smoke test for the one-call, read-only MyComp Bot preflight."""
import json
import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "fast-check.ps1"


@unittest.skipUnless(os.name == "nt", "Windows PowerShell preflight")
class FastCheckTests(unittest.TestCase):
    def test_compact_read_only_preflight(self):
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(SCRIPT)],
            capture_output=True, text=True, timeout=20, check=True,
        )
        report = json.loads(result.stdout)
        self.assertEqual(report["source_version"], (ROOT / "VERSION").read_text().strip())
        self.assertEqual(report["checked"], 16)
        self.assertEqual(report["passed"], 16)
        self.assertEqual(report["missing"], [])
        self.assertIn(report["git_clean"], [True, False, None])
        self.assertNotIn("engine_health", report)
        self.assertNotIn("access_token", result.stdout.lower())
        self.assertNotIn("api_key", result.stdout.lower())


if __name__ == "__main__":
    unittest.main()
