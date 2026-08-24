import base64
import dataclasses
import hashlib
import html
import json
import re
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from starlette.testclient import TestClient

from mycomp_bot_engine.config import CLIENT_ID, PUBLIC_MCP_ENDPOINT, Settings
from mycomp_bot_engine.schema import TOOL_NAMES
from mycomp_bot_engine.server import create_app


class HTTPIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "root"
        self.root.mkdir()
        self.redirect_uri = "https://chatgpt.example/callback"
        self.consent = "owner-consent-token-that-is-at-least-32-chars"
        self.settings = Settings(
            host="127.0.0.1",
            port=8645,
            allowed_roots=(self.root,),
            allow_shell=False,
            allowed_executables=(),
            data_dir=Path(self.temp.name) / "state",
            capability_dir=Path(self.temp.name) / "capabilities",
            redirect_uris=frozenset({self.redirect_uri}),
            owner_consent_token=self.consent,
            auth_mode="oauth",
            permission_level="full",
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_oauth_and_authenticated_mcp_tool_listing(self):
        verifier = "http-integration-pkce-verifier"
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        oauth = {
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": self.redirect_uri,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "state-123",
            "scope": "mcp",
            "ui_locales": "en-US",
        }

        with TestClient(create_app(self.settings), base_url="http://127.0.0.1:8645") as client:
            metadata = client.get("/.well-known/oauth-authorization-server")
            self.assertEqual(metadata.status_code, 200)
            for path in (
                "/.well-known/oauth-authorization-server/mcp",
                "/mcp/.well-known/oauth-authorization-server",
            ):
                discovered = client.get(path)
                self.assertEqual(discovered.status_code, 200)
                self.assertEqual(discovered.json()["registration_endpoint"], f"{PUBLIC_MCP_ENDPOINT.removesuffix('/mcp')}/register")
            self.assertEqual(metadata.json()["token_endpoint_auth_methods_supported"], ["none"])
            self.assertEqual(metadata.json()["registration_endpoint"], f"{PUBLIC_MCP_ENDPOINT.removesuffix('/mcp')}/register")
            self.assertIn("offline_access", metadata.json()["scopes_supported"])
            self.assertIn("mcp", metadata.json()["scopes_supported"])

            registration = client.post(
                "/register",
                json={"redirect_uris": [self.redirect_uri], "token_endpoint_auth_method": "none", "client_uri": "https://chatgpt.example/client"},
            )
            self.assertEqual(registration.status_code, 201, registration.text)
            self.assertTrue(registration.json()["client_id"].startswith("mycomp_"))
            chatgpt_registration = client.post(
                "/register",
                json={"redirect_uris": ["https://chatgpt.com/connector/oauth/generated"], "token_endpoint_auth_method": "none"},
            )
            self.assertEqual(chatgpt_registration.status_code, 201, chatgpt_registration.text)
            rejected_registration = client.post(
                "/register",
                json={"redirect_uris": ["https://unapproved.example/callback"], "token_endpoint_auth_method": "none"},
            )
            self.assertEqual(rejected_registration.status_code, 400)
            rejected_chatgpt_query = client.post(
                "/register",
                json={"redirect_uris": ["https://chatgpt.com/connector/oauth/generated?next=evil"], "token_endpoint_auth_method": "none"},
            )
            self.assertEqual(rejected_chatgpt_query.status_code, 400)

            consent_page = client.get("/authorize", params=oauth)
            self.assertEqual(consent_page.status_code, 200)
            self.assertIn("MyComp Bot authorization", consent_page.text)

            approval = client.post(
                "/authorize",
                data={**oauth, "scope": "mcp offline_access", "owner_consent": self.consent},
                follow_redirects=False,
            )
            self.assertEqual(approval.status_code, 200)
            callback = re.search(r"href='([^']+)'", approval.text)
            self.assertIsNotNone(callback)
            query = parse_qs(urlparse(html.unescape(callback.group(1))).query)
            self.assertEqual(query["state"], ["state-123"])
            code = query["code"][0]

            token = client.post(
                "/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.redirect_uri,
                    "code_verifier": verifier,
                    "client_id": CLIENT_ID,
                },
            )
            self.assertEqual(token.status_code, 200)
            self.assertEqual(token.json()["scope"], "mycomp mycomp.full offline_access mcp")
            access_token = token.json()["access_token"]

            protocol_headers = {"Accept": "application/json, text/event-stream"}
            unauthenticated = client.post(
                "/mcp",
                headers=protocol_headers,
                json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "integration-test", "version": "1"}}},
            )
            self.assertEqual(unauthenticated.status_code, 401)

            authenticated_headers = {**protocol_headers, "Authorization": f"Bearer {access_token}"}
            initialized = client.post(
                "/mcp",
                headers=authenticated_headers,
                json={"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "integration-test", "version": "1"}}},
            )
            self.assertEqual(initialized.status_code, 200, initialized.text)
            self.assertEqual(initialized.json()["result"]["serverInfo"]["name"], "MyComp Bot")

            tools = client.post(
                "/mcp",
                headers=authenticated_headers,
                json={"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}},
            )
            self.assertEqual(tools.status_code, 200, tools.text)
            names = {tool["name"] for tool in tools.json()["result"]["tools"]}
            self.assertEqual(names, set(TOOL_NAMES))
            self.assertEqual(len(names), 8)

            resource_list = client.post(
                "/mcp", headers=authenticated_headers,
                json={"jsonrpc": "2.0", "id": 4, "method": "resources/list", "params": {}},
            )
            self.assertEqual(resource_list.status_code, 200, resource_list.text)
            resource_uris = {item["uri"] for item in resource_list.json()["result"]["resources"]}
            self.assertIn("mycomp://status", resource_uris)
            self.assertIn("mycomp://permissions", resource_uris)

            status_resource = client.post(
                "/mcp", headers=authenticated_headers,
                json={"jsonrpc": "2.0", "id": 5, "method": "resources/read", "params": {"uri": "mycomp://status"}},
            )
            self.assertEqual(status_resource.status_code, 200, status_resource.text)
            payload = json.loads(status_resource.json()["result"]["contents"][0]["text"])
            self.assertEqual(payload["schema_version"], 4)

    def test_custom_public_domain_drives_oauth_metadata_and_resource(self):
        settings = dataclasses.replace(self.settings, public_base_url="https://mcp.example.com")
        with TestClient(create_app(settings), base_url="http://127.0.0.1:8645") as client:
            metadata = client.get("/.well-known/oauth-authorization-server")
            self.assertEqual(metadata.status_code, 200)
            self.assertEqual(metadata.json()["issuer"], "https://mcp.example.com")
            self.assertEqual(metadata.json()["authorization_endpoint"], "https://mcp.example.com/authorize")
            self.assertEqual(metadata.json()["token_endpoint"], "https://mcp.example.com/token")
            self.assertEqual(metadata.json()["registration_endpoint"], "https://mcp.example.com/register")

            protected = client.get("/.well-known/oauth-protected-resource")
            self.assertEqual(protected.status_code, 200)
            self.assertEqual(protected.json()["resource"], "https://mcp.example.com/mcp")
            self.assertEqual(protected.json()["authorization_servers"], ["https://mcp.example.com"])

    def test_unauthenticated_mcp_tool_listing_when_auth_mode_is_none(self):
        settings = dataclasses.replace(self.settings, auth_mode="none")
        protocol_headers = {"Accept": "application/json, text/event-stream"}

        with TestClient(create_app(settings), base_url="http://127.0.0.1:8645") as client:
            initialized = client.post(
                "/mcp",
                headers=protocol_headers,
                json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "no-auth-integration-test", "version": "1"}}},
            )
            self.assertEqual(initialized.status_code, 200, initialized.text)
            self.assertEqual(initialized.json()["result"]["serverInfo"]["name"], "MyComp Bot")

            tools = client.post(
                "/mcp",
                headers=protocol_headers,
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            )
            self.assertEqual(tools.status_code, 200, tools.text)
            names = {tool["name"] for tool in tools.json()["result"]["tools"]}
            self.assertEqual(names, set(TOOL_NAMES))
            self.assertEqual(len(names), 8)

            status_response = client.post(
                "/mcp", headers=protocol_headers,
                json={"jsonrpc": "2.0", "id": 3, "method": "resources/read", "params": {"uri": "mycomp://status"}},
            )
            self.assertEqual(status_response.status_code, 200, status_response.text)
            status = json.loads(status_response.json()["result"]["contents"][0]["text"])
            self.assertEqual(status["auth_mode"], "none")

    def test_chatgpt_mcp_preflight_allows_only_the_chatgpt_origin(self):
        with TestClient(create_app(self.settings), base_url="http://127.0.0.1:8645") as client:
            allowed = client.options(
                "/mcp",
                headers={
                    "Origin": "https://chatgpt.com",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "content-type,mcp-protocol-version",
                },
            )
            self.assertEqual(allowed.status_code, 200)
            self.assertEqual(allowed.headers["access-control-allow-origin"], "https://chatgpt.com")
            self.assertIn("MCP-Protocol-Version", allowed.headers["access-control-allow-headers"])

            blocked = client.options(
                "/mcp",
                headers={
                    "Origin": "https://untrusted.example",
                    "Access-Control-Request-Method": "POST",
                },
            )
            self.assertEqual(blocked.status_code, 400)


if __name__ == "__main__":
    unittest.main()
