from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from mcp.server.auth.middleware.auth_context import get_access_token

PERMISSION_LEVELS: Final[tuple[str, ...]] = ("normal", "elevated", "full")
OFFLINE_ACCESS_SCOPE: Final[str] = "offline_access"
MCP_COMPATIBILITY_SCOPE: Final[str] = "mcp"
_LEVEL_RANK: Final[dict[str, int]] = {name: index for index, name in enumerate(PERMISSION_LEVELS)}
_SCOPE_TO_LEVEL: Final[dict[str, str]] = {
    "mycomp.normal": "normal",
    "mycomp.elevated": "elevated",
    "mycomp.full": "full",
}


def normalize_level(value: str) -> str:
    level = value.strip().lower()
    if level not in _LEVEL_RANK:
        raise ValueError(f"permission level must be one of {', '.join(PERMISSION_LEVELS)}")
    return level


def level_scope(level: str) -> str:
    return f"mycomp.{normalize_level(level)}"


def normalize_requested_scope(scope: str, maximum_level: str) -> str:
    """Return canonical OAuth scopes capped by the owner-selected server level.

    Legacy clients request only ``mycomp``. Such a request receives the current
    owner-selected level while retaining the base scope for MCP compatibility.
    Explicit level requests may request a lower level but never exceed the owner cap.
    """
    maximum_level = normalize_level(maximum_level)
    requested = [item for item in scope.split() if item]
    requests_offline_access = OFFLINE_ACCESS_SCOPE in requested
    requests_mcp_compatibility = MCP_COMPATIBILITY_SCOPE in requested
    resource_scopes = [
        item for item in requested
        if item not in {OFFLINE_ACCESS_SCOPE, MCP_COMPATIBILITY_SCOPE}
    ]
    if not resource_scopes:
        if not requests_mcp_compatibility:
            raise PermissionError("a MyComp resource scope is required")
        granted_level = maximum_level
    elif resource_scopes == ["mycomp"]:
        granted_level = maximum_level
    else:
        requested_levels = [_SCOPE_TO_LEVEL[item] for item in resource_scopes if item in _SCOPE_TO_LEVEL]
        unknown = [item for item in resource_scopes if item != "mycomp" and item not in _SCOPE_TO_LEVEL]
        if unknown or not requested_levels:
            raise PermissionError("scope is not approved")
        requested_level = max(requested_levels, key=_LEVEL_RANK.__getitem__)
        if _LEVEL_RANK[requested_level] > _LEVEL_RANK[maximum_level]:
            raise PermissionError("requested scope exceeds the owner-selected permission level")
        granted_level = requested_level
    granted = ["mycomp", level_scope(granted_level)]
    if requests_offline_access:
        # This scope only asks the client to retain a refresh token.  It never
        # grants an extra MyComp permission level.
        granted.append(OFFLINE_ACCESS_SCOPE)
    if requests_mcp_compatibility:
        # ChatGPT requests this generic MCP scope for some custom-app flows.
        # It is an alias only; the MyComp level above remains authoritative.
        granted.append(MCP_COMPATIBILITY_SCOPE)
    return " ".join(granted)


def level_from_scopes(scopes: list[str] | tuple[str, ...] | set[str], fallback: str) -> str:
    found = [_SCOPE_TO_LEVEL[item] for item in scopes if item in _SCOPE_TO_LEVEL]
    if not found:
        return normalize_level(fallback)
    return max(found, key=_LEVEL_RANK.__getitem__)


@dataclass(frozen=True)
class PermissionPolicy:
    configured_level: str
    auth_required: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "configured_level", normalize_level(self.configured_level))

    def effective_level(self) -> str:
        token = get_access_token()
        if token is None:
            # No-token mode deliberately uses the level chosen in the local UI.
            # Authenticated mode never reaches a tool without a verified token.
            return self.configured_level
        token_level = level_from_scopes(token.scopes, self.configured_level)
        return min((self.configured_level, token_level), key=_LEVEL_RANK.__getitem__)

    def allows(self, required: str) -> bool:
        return _LEVEL_RANK[self.effective_level()] >= _LEVEL_RANK[normalize_level(required)]

    def require(self, required: str, operation: str) -> None:
        required = normalize_level(required)
        effective = self.effective_level()
        if _LEVEL_RANK[effective] < _LEVEL_RANK[required]:
            raise PermissionError(
                f"{operation} requires {required} permission; current effective level is {effective}"
            )

    def is_full_control(self) -> bool:
        """True when the effective level is full unrestricted computer control."""
        return self.effective_level() == "full"

    def risk_defaults(self) -> dict[str, str]:
        """Policy defaults exposed to clients. Full control auto-allows every risk class."""
        if self.is_full_control():
            return {
                "read_only": "allow",
                "local_reversible": "allow",
                "local_destructive": "allow",
                "external_side_effect": "allow",
                "communication": "allow",
                "credential_use": "allow",
                "financial": "allow",
                "system_admin": "allow",
            }
        return {
            "read_only": "allow",
            "local_reversible": "allow",
            "local_destructive": "ask",
            "external_side_effect": "ask",
            "communication": "ask",
            "credential_use": "ask",
            "financial": "deny",
            "system_admin": "ask",
        }

    def describe(self) -> dict[str, object]:
        full = self.is_full_control()
        return {
            "configured": self.configured_level,
            "effective": self.effective_level(),
            "levels": list(PERMISSION_LEVELS),
            "auth_required": self.auth_required,
            "full_control": full,
            "capabilities": {
                "api_read": True,
                "api_write": full,
                "api_private_network": full,
                "shell_allowlisted": self.allows("elevated"),
                "shell_any_executable": full,
                "shell_any_cwd": full,
                "shell_inherit_environment": full,
                "shell_sudo_without_owner_gate": full,
                "dom_cdp": self.allows("elevated"),
                "applescript": full,
                "accessibility_write": self.allows("elevated"),
                "keyboard": self.allows("elevated"),
                "mouse": self.allows("elevated"),
                "vision": True,
            },
        }
