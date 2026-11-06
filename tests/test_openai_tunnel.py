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


if __name__ == "__main__":
    unittest.main()
