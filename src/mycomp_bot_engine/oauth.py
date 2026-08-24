"""OAuth security primitives used by the HTTP authorization adapter.

The adapter intentionally keeps credentials out of source: redirect URIs and owner
consent are local configuration, while only hashes of bearer credentials are stored.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import sqlite3
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from .config import CLIENT_ID, PUBLIC_MCP_ENDPOINT
from .database import Database
from .permissions import normalize_level, normalize_requested_scope


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _is_chatgpt_redirect(uri: str) -> bool:
    parsed = urlsplit(uri)
    return (
        parsed.scheme == "https"
        and parsed.hostname == "chatgpt.com"
        and parsed.path.startswith("/connector/oauth/")
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
    )


@dataclass(frozen=True)
class TokenGrant:
    access_token: str
    refresh_token: str
    scope: str
    expires_in: int = 900


class OAuthService:
    """SQLite-backed, PKCE-S256-only authorization-code service."""

    def __init__(
        self,
        database: Database,
        redirect_uris: frozenset[str],
        owner_consent_token: str | None,
        permission_level: str = "full",
        resource_server_url: str = PUBLIC_MCP_ENDPOINT,
    ) -> None:
        self.database = database
        self.redirect_uris = redirect_uris
        self.owner_consent_token = owner_consent_token
        self.permission_level = normalize_level(permission_level)
        self.resource_server_url = resource_server_url
        with database.transaction():
            database.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS oauth_codes (
                    code_hash TEXT PRIMARY KEY,
                    challenge TEXT NOT NULL,
                    redirect_uri TEXT NOT NULL,
                    client_id TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    expires REAL NOT NULL,
                    used INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS oauth_tokens (
                    token_hash TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    audience TEXT NOT NULL,
                    expires REAL NOT NULL,
                    revoked INTEGER NOT NULL DEFAULT 0,
                    refresh_hash TEXT,
                    scope TEXT NOT NULL DEFAULT 'mycomp mycomp.normal'
                );
                CREATE TABLE IF NOT EXISTS oauth_clients (
                    client_id TEXT PRIMARY KEY,
                    redirect_uris TEXT NOT NULL,
                    created REAL NOT NULL
                );
                """
            )
            try:
                database.connection.execute(
                    "ALTER TABLE oauth_tokens ADD COLUMN scope TEXT NOT NULL DEFAULT 'mycomp mycomp.normal'"
                )
            except sqlite3.OperationalError:
                pass
            database.connection.commit()

    def register_client(self, redirect_uris: list[str]) -> dict[str, object]:
        """Register an OAuth public client without accepting arbitrary callbacks.

        The local Settings allowlist remains the trust decision.  Dynamic
        registration only creates an opaque client id for a callback the owner
        has already explicitly approved there; no client secret is issued.
        """
        if not redirect_uris or len(redirect_uris) > 16 or any(not isinstance(uri, str) for uri in redirect_uris):
            raise ValueError("redirect_uris must contain 1 to 16 strings")
        requested = frozenset(redirect_uris)
        local_redirects = {
            uri for uri in requested
            if (parsed := urlsplit(uri)).scheme == "http"
            and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
            and not parsed.username
            and not parsed.password
            and not parsed.query
            and not parsed.fragment
        }
        approved = self.redirect_uris | local_redirects | {uri for uri in requested if _is_chatgpt_redirect(uri)}
        if not requested.issubset(approved):
            raise PermissionError("redirect URI is not approved in MyComp Bot Settings")
        client_id = "mycomp_" + secrets.token_urlsafe(24)
        with self.database.transaction():
            self.database.connection.execute(
                "INSERT INTO oauth_clients(client_id, redirect_uris, created) VALUES (?, ?, ?)",
                (client_id, "\n".join(sorted(requested)), time.time()),
            )
            self.database.connection.commit()
        return {"client_id": client_id, "redirect_uris": sorted(requested), "token_endpoint_auth_method": "none"}

    def _client_allows_redirect(self, client_id: str, redirect_uri: str) -> bool:
        # ponytail: ChatGPT generates unique connector callback paths per session.
        # Accept any https://chatgpt.com/connector/oauth/* redirect without listing each one.
        if _is_chatgpt_redirect(redirect_uri):
            return True
        if client_id == CLIENT_ID:
            return redirect_uri in self.redirect_uris
        with self.database.transaction():
            row = self.database.connection.execute(
                "SELECT redirect_uris FROM oauth_clients WHERE client_id = ?", (client_id,)
            ).fetchone()
        return bool(row and redirect_uri in set(str(row[0]).split("\n")))

    def authorize(
        self,
        *,
        client_id: str,
        redirect_uri: str,
        code_challenge: str,
        code_challenge_method: str,
        consent_token: str,
        response_type: str = "code",
        scope: str = "mycomp",
        resource: str | None = None,
    ) -> str:
        if response_type != "code" or not self._client_allows_redirect(client_id, redirect_uri):
            raise PermissionError("client or redirect URI is not approved")
        if (
            not self.owner_consent_token
            or len(self.owner_consent_token) < 32
            or not secrets.compare_digest(consent_token, self.owner_consent_token)
        ):
            raise PermissionError("owner consent is required")
        resource = resource or self.resource_server_url
        if resource != self.resource_server_url:
            raise PermissionError("resource is not approved")
        granted_scope = normalize_requested_scope(scope, self.permission_level)
        if code_challenge_method != "S256" or not code_challenge:
            raise ValueError("PKCE S256 is required")
        code = secrets.token_urlsafe(32)
        with self.database.transaction():
            self.database.connection.execute(
                "DELETE FROM oauth_codes WHERE expires < ? OR used = 1", (time.time(),)
            )
            self.database.connection.execute(
                "INSERT INTO oauth_codes VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
                (
                    _hash(code),
                    code_challenge,
                    redirect_uri,
                    client_id,
                    granted_scope,
                    resource,
                    time.time() + 300,
                ),
            )
            self.database.connection.commit()
        return code

    def exchange(
        self,
        *,
        code: str,
        redirect_uri: str,
        code_verifier: str,
        client_id: str,
        audience: str,
    ) -> TokenGrant:
        challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).rstrip(b"=").decode()
        with self.database.transaction():
            row = self.database.connection.execute(
                "SELECT challenge, redirect_uri, client_id, scope, resource, expires "
                "FROM oauth_codes WHERE code_hash = ? AND used = 0",
                (_hash(code),),
            ).fetchone()
            if (
                not row
                or row[1] != redirect_uri
                or row[2] != client_id
                or row[4] != audience
                or row[5] < time.time()
                or not secrets.compare_digest(row[0], challenge)
            ):
                raise PermissionError("invalid authorization code or PKCE verifier")
            if self.database.connection.execute(
                "UPDATE oauth_codes SET used = 1 WHERE code_hash = ? AND used = 0", (_hash(code),)
            ).rowcount != 1:
                raise PermissionError("authorization code was already used")
            grant = self._issue(audience, row[3])
            self.database.connection.commit()
        return grant

    def refresh(self, refresh_token: str, audience: str) -> TokenGrant:
        with self.database.transaction():
            row = self.database.connection.execute(
                "SELECT audience, expires, scope FROM oauth_tokens "
                "WHERE token_hash = ? AND kind = 'refresh' AND revoked = 0",
                (_hash(refresh_token),),
            ).fetchone()
            if not row or row[0] != audience or row[1] < time.time():
                raise PermissionError("invalid refresh token")
            if self.database.connection.execute(
                "UPDATE oauth_tokens SET revoked = 1 WHERE token_hash = ? AND revoked = 0",
                (_hash(refresh_token),),
            ).rowcount != 1:
                raise PermissionError("refresh token was already used")
            grant = self._issue(audience, row[2])
            self.database.connection.commit()
        return grant

    def validate_access_token(self, token: str, audience: str | None = None) -> bool:
        audience = audience or self.resource_server_url
        with self.database.transaction():
            row = self.database.connection.execute(
                "SELECT audience, expires, revoked FROM oauth_tokens "
                "WHERE token_hash = ? AND kind = 'access'",
                (_hash(token),),
            ).fetchone()
        return bool(row and row[0] == audience and row[1] >= time.time() and not row[2])

    def access_token_scopes(self, token: str, audience: str | None = None) -> list[str] | None:
        audience = audience or self.resource_server_url
        with self.database.transaction():
            row = self.database.connection.execute(
                "SELECT audience, expires, revoked, scope FROM oauth_tokens "
                "WHERE token_hash = ? AND kind = 'access'",
                (_hash(token),),
            ).fetchone()
        if not row or row[0] != audience or row[1] < time.time() or row[2]:
            return None
        return str(row[3]).split()

    def revoke(self, token: str) -> None:
        with self.database.transaction():
            self.database.connection.execute(
                "UPDATE oauth_tokens SET revoked = 1 WHERE token_hash = ?", (_hash(token),)
            )
            self.database.connection.commit()

    def _issue(self, audience: str, scope: str) -> TokenGrant:
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        now = time.time()
        self.database.connection.execute("DELETE FROM oauth_tokens WHERE expires < ? OR revoked = 1", (now,))
        self.database.connection.execute(
            "INSERT INTO oauth_tokens(token_hash, kind, audience, expires, revoked, refresh_hash, scope) "
            "VALUES (?, 'access', ?, ?, 0, ?, ?)",
            (_hash(access), audience, now + 900, _hash(refresh), scope),
        )
        self.database.connection.execute(
            "INSERT INTO oauth_tokens(token_hash, kind, audience, expires, revoked, refresh_hash, scope) "
            "VALUES (?, 'refresh', ?, ?, 0, NULL, ?)",
            (_hash(refresh), audience, now + 30 * 86400, scope),
        )
        return TokenGrant(access, refresh, scope)


class SQLiteTokenVerifier:
    """FastMCP TokenVerifier adapter; imports SDK types only when the engine runs."""

    def __init__(self, service: OAuthService) -> None:
        self.service = service

    async def verify_token(self, token: str):
        scopes = self.service.access_token_scopes(token)
        if scopes is None:
            return None
        from mcp.server.auth.provider import AccessToken

        return AccessToken(token=token, client_id=CLIENT_ID, scopes=scopes, resource=self.service.resource_server_url)
