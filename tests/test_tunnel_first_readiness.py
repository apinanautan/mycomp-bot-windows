import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from windows.openai_tunnel import Tunnel


class TunnelFirstReadinessTests(unittest.TestCase):
    def test_status_distinguishes_auth_required_from_authenticated(self):
        with tempfile.TemporaryDirectory() as directory:
            tunnel = Tunnel(Path(directory))
            tunnel.process = object()
            tunnel.health.parent.mkdir(parents=True, exist_ok=True)
            tunnel.health.write_text('http://127.0.0.1:54321')
            class Response:
                status = 200
                def __enter__(self): return self
                def __exit__(self, *args): pass
                def read(self):
                    return json.dumps({'channels': [{'name': 'main', 'enabled': True, 'probe_status': 'auth-required'}]}).encode()
            with patch('windows.openai_tunnel.urllib.request.urlopen', return_value=Response()):
                result = tunnel.status()
            self.assertIn('OAuth required', result)
            self.assertIn('tools/list', result)
            self.assertNotIn('Runtime ready', result)

    def test_disabled_main_is_not_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            tunnel = Tunnel(Path(directory))
            tunnel.process = object()
            tunnel.health.parent.mkdir(parents=True, exist_ok=True)
            tunnel.health.write_text('http://127.0.0.1:54321')
            class Response:
                status = 200
                def __enter__(self): return self
                def __exit__(self, *args): pass
                def read(self): return json.dumps({'channels': [{'name': 'main', 'enabled': False}]}).encode()
            with patch('windows.openai_tunnel.urllib.request.urlopen', return_value=Response()):
                self.assertIn('disabled', tunnel.status())

    def test_rejected_api_key_is_reported_not_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            tunnel = Tunnel(Path(directory))
            tunnel.process = object()
            tunnel.directory.mkdir(parents=True, exist_ok=True)
            (tunnel.directory / 'runtime.log').write_text(
                'WARN poll failed; backing off component=controlplane error="controlplane client: unexpected status 401: invalid_api_key: Incorrect API key"\n',
                encoding='utf-8')
            self.assertTrue(tunnel.status().startswith('API key rejected'))


if __name__ == '__main__':
    unittest.main()