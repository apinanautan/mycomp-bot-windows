import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from windows.openai_tunnel import Tunnel


class TunnelFirstReadinessTests(unittest.TestCase):
    def test_setup_prompt_is_tunnel_first_and_resumable(self):
        with tempfile.TemporaryDirectory() as directory:
            tunnel = Tunnel(Path(directory))
            prompt = tunnel.plugin_prompt('Dino', 'https://example.ts.net/mycomp')
            for text in ('Tunnel/main', 'STEP 0', 'STATE.md', 'tools/list', 'Chrome'):
                self.assertIn(text, prompt)
            self.assertNotIn('sk-SECRET', prompt)

    def test_prompt_reuses_saved_tunnel_and_skips_completed_setup(self):
        with tempfile.TemporaryDirectory() as directory:
            tunnel = Tunnel(Path(directory))
            prompt = tunnel.plugin_prompt("MyComp Bot", "https://example.ts.net/mycomp")
            assert "MyComp Bot Tailscale" in prompt
            assert "MyComp Bot Tunnel" in prompt
            for phrase in ("key.dpapi", "ห้ามสร้าง Tunnel, Channel, Key", "เสร็จแล้ว/ข้าม",
                           "ซ่อมเฉพาะจุดเดิม", "ChatGPT ซ้าย", "Chrome ทำงานขวา",
                           "Orchestrator"):
                self.assertIn(phrase, prompt)
            self.assertLess(prompt.index("STEP 1"), prompt.index("STEP 2"))

    def test_prompt_continues_independent_work_when_chatgpt_mcp_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            tunnel = Tunnel(Path(directory))
            prompt = tunnel.plugin_prompt("MyComp BotS", "https://example.ts.net/mycomp")
            for phrase in ("blocked_permission", "operator-clarity", "ข้ามเฉพาะการผูก Tunnel",
                           "ผ่าน Tailscale", "MyComp BotS Tunnel", "MyComp BotS Tailscale"):
                self.assertIn(phrase, prompt)
            self.assertNotIn("ไม่ข้ามไปทำงานอื่นก่อน Tunnel สำเร็จ", prompt)

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


if __name__ == '__main__':
    unittest.main()