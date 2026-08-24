from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .permissions import normalize_level

PUBLIC_BASE_URL = "https://mycomp.invalid"
PUBLIC_MCP_ENDPOINT = f"{PUBLIC_BASE_URL}/mcp"
AUTHORIZATION_ENDPOINT = f"{PUBLIC_BASE_URL}/authorize"
TOKEN_ENDPOINT = f"{PUBLIC_BASE_URL}/token"
CLIENT_ID = "mycomp-bot-local-client"
WINDOWS = os.name == "nt"
DEFAULT_SHELL_PATH = (
    r"C:\Windows\System32;C:\Windows;C:\Windows\System32\WindowsPowerShell\v1.0"
    if WINDOWS else "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
)


def _paths(value: str) -> tuple[Path, ...]:
    return tuple(Path(item.strip()).expanduser().resolve() for item in value.split(",") if item.strip())


def _validated_shell_path(value: str) -> str:
    separator = ";" if WINDOWS else ":"
    entries = value.split(separator)
    if not entries or any(not entry or not Path(entry).is_absolute() for entry in entries):
        raise ValueError("MYCOMP_SHELL_PATH must contain only absolute, non-empty directories")
    return separator.join(entries)


def _default_app_data() -> Path:
    if WINDOWS:
        return Path(os.getenv("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "MyComp Bot"
    return Path("~/Library/Application Support/MyComp Bot").expanduser()


def _validated_public_base_url(value: str) -> str:
    """Return a canonical HTTPS origin used for all public OAuth endpoints."""
    normalized = value.strip() or PUBLIC_BASE_URL
    parsed = urlsplit(normalized)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("MYCOMP_PUBLIC_BASE_URL must be an HTTPS origin without a path, query, or fragment")
    return urlunsplit(("https", parsed.netloc, "", "", ""))


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    allowed_roots: tuple[Path, ...]
    allow_shell: bool
    allowed_executables: tuple[Path, ...]
    data_dir: Path
    capability_dir: Path
    redirect_uris: frozenset[str]
    owner_consent_token: str | None
    auth_mode: str = "oauth"
    permission_level: str = "normal"
    config_dir: Path | None = None
    maintained_capability_dir: Path | None = None
    max_output_bytes: int = 64_000
    max_read_bytes: int = 1_000_000
    max_search_files: int = 1_000
    max_list_entries: int = 1_000
    max_write_bytes: int = 1_000_000
    max_search_directories: int = 1_000
    max_search_depth: int = 32
    shell_path: str = DEFAULT_SHELL_PATH
    shell_foreground_timeout_seconds: float = 30.0
    shell_auto_wait_seconds: float = 5.0
    schema_version: int = 4
    public_base_url: str = PUBLIC_BASE_URL

    def __post_init__(self) -> None:
        if self.auth_mode not in {"none", "oauth"}:
            raise ValueError("MYCOMP_AUTH_MODE must be 'none' or 'oauth'")
        object.__setattr__(self, "permission_level", normalize_level(self.permission_level))
        object.__setattr__(self, "shell_path", _validated_shell_path(self.shell_path))
        object.__setattr__(self, "public_base_url", _validated_public_base_url(self.public_base_url))
        if self.shell_foreground_timeout_seconds <= 0:
            raise ValueError("MYCOMP_SHELL_FOREGROUND_TIMEOUT_SECONDS must be positive")
        if not 0 <= self.shell_auto_wait_seconds <= 60:
            raise ValueError("MYCOMP_SHELL_AUTO_WAIT_SECONDS must be between 0 and 60")
        if self.schema_version != 4:
            raise ValueError("MYCOMP_SCHEMA_VERSION must be 4; open MyComp Bot to migrate local settings")

    @property
    def require_auth(self) -> bool:
        return self.auth_mode == "oauth"

    @property
    def public_mcp_endpoint(self) -> str:
        return f"{self.public_base_url}/mcp"

    @property
    def authorization_endpoint(self) -> str:
        return f"{self.public_base_url}/authorize"

    @property
    def token_endpoint(self) -> str:
        return f"{self.public_base_url}/token"

    @property
    def registration_endpoint(self) -> str:
        return f"{self.public_base_url}/register"

    @classmethod
    def from_env(cls) -> "Settings":
        default_data_dir = _default_app_data()
        data_dir = Path(os.getenv("MYCOMP_DATA_DIR", str(default_data_dir))).expanduser()
        roots = _paths(os.getenv("MYCOMP_ALLOWED_ROOTS", ""))
        host = os.getenv("MYCOMP_HOST", "127.0.0.1")
        if host not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError("MYCOMP_HOST must be a loopback address")
        return cls(
            host=host,
            port=int(os.getenv("MYCOMP_PORT", "8645")),
            allowed_roots=roots,
            allow_shell=os.getenv("MYCOMP_ALLOW_SHELL", "false").lower() in {"1", "true", "yes", "on"},
            allowed_executables=_paths(os.getenv("MYCOMP_ALLOWED_EXECUTABLES", "")),
            data_dir=data_dir,
            capability_dir=Path(os.getenv("MYCOMP_CAPABILITY_DIR", str(data_dir / "capabilities"))).expanduser(),
            redirect_uris=frozenset(
                uri for item in os.getenv("MYCOMP_OAUTH_REDIRECT_URIS", "").split(",")
                if (uri := item.strip())
            ),
            owner_consent_token=os.getenv("MYCOMP_OWNER_CONSENT_TOKEN") or None,
            auth_mode=os.getenv("MYCOMP_AUTH_MODE", "oauth").strip().lower(),
            permission_level=os.getenv("MYCOMP_PERMISSION_LEVEL", "normal").strip().lower(),
            config_dir=Path(os.getenv("MYCOMP_CONFIG_DIR", str(default_data_dir))).expanduser(),
            maintained_capability_dir=(Path(os.environ["MYCOMP_MAINTAINED_CAPABILITIES_DIR"]).expanduser() if os.getenv("MYCOMP_MAINTAINED_CAPABILITIES_DIR") else None),
            max_output_bytes=int(os.getenv("MYCOMP_MAX_OUTPUT_BYTES", "64000")),
            max_read_bytes=int(os.getenv("MYCOMP_MAX_READ_BYTES", "1000000")),
            max_search_files=int(os.getenv("MYCOMP_MAX_SEARCH_FILES", "1000")),
            max_list_entries=int(os.getenv("MYCOMP_MAX_LIST_ENTRIES", "1000")),
            max_write_bytes=int(os.getenv("MYCOMP_MAX_WRITE_BYTES", "1000000")),
            max_search_directories=int(os.getenv("MYCOMP_MAX_SEARCH_DIRECTORIES", "1000")),
            max_search_depth=int(os.getenv("MYCOMP_MAX_SEARCH_DEPTH", "32")),
            shell_path=os.getenv("MYCOMP_SHELL_PATH", DEFAULT_SHELL_PATH),
            shell_foreground_timeout_seconds=float(os.getenv("MYCOMP_SHELL_FOREGROUND_TIMEOUT_SECONDS", "30")),
            shell_auto_wait_seconds=float(os.getenv("MYCOMP_SHELL_AUTO_WAIT_SECONDS", "5")),
            schema_version=int(os.getenv("MYCOMP_SCHEMA_VERSION", "4")),
            public_base_url=os.getenv("MYCOMP_PUBLIC_BASE_URL", PUBLIC_BASE_URL),
        )
