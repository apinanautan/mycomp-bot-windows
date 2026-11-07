"""Read-only local Remote Desktop Commander agent/account hints for MyComp Bot.

Only the current Windows user's saved device session is inspected. Claims in
the saved JWT are NOT cryptographic proof that the cloud account is online.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess

_SESSION = Path.home() / ".desktop-commander-device" / "device.json"
_ACCOUNT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
_DEVICE_RE = re.compile(r"^[0-9a-fA-F-]{8,64}$")


@dataclass(frozen=True)
class AccountHint:
    """Claimed alias from local saved JWT, NOT a server-verified account."""

    alias: str | None = None
    device_id: str | None = None
    session_saved: bool = False


def saved_account_hint(session_file: Path | None = None) -> AccountHint:
    """Read the email's local part and device ID; never return JWTs or domain."""
    path = session_file if session_file is not None else _SESSION
    try:
        if path.stat().st_size > 65536:
            return AccountHint()
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return AccountHint()
        device = data.get("deviceId")
        if not isinstance(device, str) or not _DEVICE_RE.fullmatch(device):
            device = None
        session = data.get("session")
        if not isinstance(session, dict):
            return AccountHint(device_id=device)
        access_token = session.get("access_token")
        if not isinstance(access_token, str) or len(access_token) > 16384:
            return AccountHint(device_id=device, session_saved=True)
        parts = access_token.split(".")
        if len(parts) != 3 or len(parts[1]) > 12000:
            return AccountHint(device_id=device, session_saved=True)
        payload = parts[1] + "=" * ((-len(parts[1])) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        email = claims.get("email") if isinstance(claims, dict) else None
        local, sep, domain = email.partition("@") if isinstance(email, str) else ("", "", "")
        if sep and domain and _ACCOUNT_RE.fullmatch(local):
            return AccountHint(alias=local, device_id=device, session_saved=True)
        return AccountHint(device_id=device, session_saved=True)
    except (OSError, ValueError, TypeError, UnicodeError, OverflowError):
        return AccountHint()


def remote_agent_pids(timeout: float = 8.0) -> tuple[int, ...]:
    """Find actual Node remote agents; exclude npx wrappers and the probe shell."""
    script = (
        "Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" | "
        "Where-Object { $_.CommandLine -and "
        r"$_.CommandLine -match '(?i)desktop-commander[\\/]+dist[\\/]+index[.]js' -and "
        r"$_.CommandLine -match '(?i)(?:^|\s)remote(?:\s|$)' } | "
        "Select-Object -ExpandProperty ProcessId"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode:
            return ()
        return tuple(sorted({int(v.strip()) for v in result.stdout.splitlines() if v.strip().isdigit()}))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return ()
