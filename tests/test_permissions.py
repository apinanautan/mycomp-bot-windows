import base64
import hashlib
import tempfile
import unittest
from pathlib import Path

from mycomp_bot_engine.database import Database
from mycomp_bot_engine.oauth import OAuthService
from mycomp_bot_engine.permissions import PermissionPolicy, normalize_requested_scope


class PermissionTests(unittest.TestCase):
    def test_three_level_order_and_no_auth_policy(self):
        policy = PermissionPolicy("elevated", False)
        self.assertTrue(policy.allows("normal"))
        self.assertTrue(policy.allows("elevated"))
        self.assertFalse(policy.allows("full"))
        self.assertFalse(policy.is_full_control())
        with self.assertRaises(PermissionError):
            policy.require("full", "admin")

    def test_full_control_is_unrestricted(self):
        policy = PermissionPolicy("full", False)
        self.assertTrue(policy.is_full_control())
        self.assertTrue(policy.allows("full"))
        description = policy.describe()
        self.assertTrue(description["full_control"])
        self.assertTrue(description["capabilities"]["shell_any_executable"])
        self.assertTrue(description["capabilities"]["shell_sudo_without_owner_gate"])
        self.assertTrue(description["capabilities"]["api_private_network"])
        self.assertEqual(policy.risk_defaults()["financial"], "allow")
        self.assertEqual(policy.risk_defaults()["system_admin"], "allow")

    def test_legacy_scope_maps_to_owner_level_and_cannot_escalate(self):
        self.assertEqual(normalize_requested_scope("mycomp", "elevated"), "mycomp mycomp.elevated")
        self.assertEqual(normalize_requested_scope("mycomp.normal", "elevated"), "mycomp mycomp.normal")
        self.assertEqual(
            normalize_requested_scope("mycomp offline_access", "elevated"),
            "mycomp mycomp.elevated offline_access",
        )
        self.assertEqual(
            normalize_requested_scope("mcp offline_access", "elevated"),
            "mycomp mycomp.elevated offline_access mcp",
        )
        with self.assertRaises(PermissionError):
            normalize_requested_scope("offline_access", "elevated")
        with self.assertRaises(PermissionError):
            normalize_requested_scope("mycomp.full", "elevated")

    def test_oauth_refresh_preserves_level_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            database = Database(Path(temp))
            try:
                service = OAuthService(database, frozenset({"https://client/callback"}), "x" * 32, "elevated")
                verifier = "scope-verifier"
                challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
                code = service.authorize(
                    client_id="mycomp-bot-local-client",
                    redirect_uri="https://client/callback",
                    code_challenge=challenge,
                    code_challenge_method="S256",
                    consent_token="x" * 32,
                    scope="mycomp offline_access",
                )
                grant = service.exchange(
                    code=code,
                    redirect_uri="https://client/callback",
                    code_verifier=verifier,
                    client_id="mycomp-bot-local-client",
                    audience="https://mycomp.invalid/mcp",
                )
                self.assertEqual(grant.scope, "mycomp mycomp.elevated offline_access")
                replacement = service.refresh(grant.refresh_token, "https://mycomp.invalid/mcp")
                self.assertEqual(replacement.scope, grant.scope)
            finally:
                database.close()


if __name__ == "__main__":
    unittest.main()
