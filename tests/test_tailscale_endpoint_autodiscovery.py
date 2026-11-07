"""Regression tests: MyComp displays and saves its own Funnel MCP URL."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

from windows import tailscale_endpoint as ep

ROOT = Path(__file__).resolve().parents[1]
HOST = "desktop-autotest.tailb52c11.ts.net"
SELF = {"BackendState": "Running", "Self": {"DNSName": HOST + "."}}


class TailscaleAutodiscoveryTests(unittest.TestCase):
    def test_current_host_gets_public_mcp_base_when_no_saved_url(self):
        self.assertEqual(ep.discover_url(SELF, {})[0],
                         "https://" + HOST + "/mycomp")

    def test_existing_owned_mycomp_route_wins_when_root_is_another_app(self):
        routes = {"Web": {HOST + ":443": {"Handlers": {
            "/": {"Proxy": "http://127.0.0.1:8765"},
            "/mycomp": {"Proxy": "http://127.0.0.1:8645/"},
        }}}}
        self.assertEqual(
            ep.discover_url(SELF, routes)[0],
            "https://" + HOST + "/mycomp",
        )
        self.assertTrue(ep.route_is_free_or_ours(routes, HOST, "/mycomp"))
        self.assertFalse(ep.route_is_free_or_ours(routes, HOST, "/"))

    def test_preserves_legacy_root_when_the_root_is_mycomp(self):
        routes = {"Web": {HOST + ":443": {"Handlers": {
            "/": {"Proxy": "http://127.0.0.1:8645"},
        }}}}
        self.assertEqual(ep.discover_url(SELF, routes)[0],
                         "https://" + HOST)

    def test_stale_other_machine_url_is_replaced_with_this_machine(self):
        stale = "https://desktop-other.tailb52c11.ts.net"
        self.assertEqual(ep.discover_url(SELF, {}, stale)[0],
                         "https://" + HOST + "/mycomp")

    def test_custom_domain_is_preserved(self):
        url = "https://my-custom-domain.example"
        self.assertEqual(ep.discover_url(SELF, {}, url)[0], url)

    def test_does_not_steal_different_app_mycomp_route(self):
        routes = {"Web": {HOST + ":443": {"Handlers": {
            "/mycomp": {"Proxy": "http://127.0.0.1:7777"},
        }}}}
        with self.assertRaisesRegex(RuntimeError, "another service"):
            ep.discover_url(SELF, routes)
        self.assertFalse(ep.route_is_free_or_ours(routes, HOST, "/mycomp"))

    def test_offline_tailscale_does_not_pretend_public_url_exists(self):
        with self.assertRaisesRegex(RuntimeError, "not connected"):
            ep.discover_url({"BackendState": "Stopped", "Self": SELF["Self"]}, {})
        with self.assertRaises(ValueError):
            ep.discover_url({"BackendState": "Running", "Self": {"DNSName": ""}}, {})

    def test_discovery_runs_read_only_tailscale_commands(self):
        results = [
            Mock(returncode=0, stdout=json.dumps(SELF), stderr=""),
            Mock(returncode=0, stdout=json.dumps({}), stderr=""),
        ]
        with patch.object(ep.subprocess, "run", side_effect=results) as run:
            url, note = ep.read_current_url("tailscale.exe")
        self.assertEqual(url, "https://" + HOST + "/mycomp")
        self.assertIn("verification", note)
        self.assertEqual([args.args[0][1:3] for args in run.call_args_list],
                         [["status", "--json"], ["funnel", "status"]])

    def test_gui_populates_mcp_field_without_starting_temporary_tunnel(self):
        gui = (ROOT / "windows/MyCompBot.py").read_text(encoding="utf-8")
        self.assertIn("self.after(250, self._start_tailscale_discovery)", gui)
        self.assertIn("self.domain.set(url)", gui)
        self.assertIn('values["MYCOMP_PUBLIC_BASE_URL"] = url', gui)
        self.assertIn("self._refresh_endpoint()", gui)
        self.assertIn("self.tailscale_discovery_queue.get_nowait()", gui)
        self.assertIn("Tailscale MCP URL detected:", gui)
        self.assertNotIn("self.after(250, self._start_tunnel)", gui)

    def test_installer_publishes_owned_path_without_overwriting_other_root(self):
        script = (ROOT / "windows/Install MyComp Bot.ps1").read_text(encoding="utf-8")
        self.assertIn("--set-path=/mycomp", script)
        self.assertIn("MYCOMP_PUBLIC_BASE_URL", script)
        self.assertIn('Tailscale /mycomp is owned by another service', script)
