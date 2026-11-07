"""Automatic, safe Tailscale public MCP URL discovery for MyComp Bot."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from urllib.parse import urlsplit

LOCAL_PROXY = "http://127.0.0.1:8645"


def _valid_dns_name(name: str) -> str:
    name = str(name or "").strip().rstrip(".").lower()
    if not (name.endswith(".ts.net")
            and re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.ts\.net", name)):
        raise ValueError("Tailscale MagicDNS hostname is unavailable or invalid")
    return name


def _public_origin(host: str, path: str) -> str:
    return "https://" + host + ("" if path == "/" else path)


def _is_mycomp_proxy(value: object) -> bool:
    return str(value or "").rstrip("/") == LOCAL_PROXY


def _handlers(funnel: dict, host: str) -> dict:
    record = funnel.get("Web", {}).get(host + ":443", {})
    value = record.get("Handlers", {}) if isinstance(record, dict) else {}
    return value if isinstance(value, dict) else {}


def discover_url(status: dict, funnel: dict, configured: str = "") -> tuple[str, str]:
    """Return (origin, description), never claim public reachability.

    Existing MyComp-owned route wins. Otherwise choose a free /mycomp path
    without replacing another service's root route. An unrelated manually
    configured HTTPS hostname remains authoritative.
    """
    if status.get("BackendState") != "Running":
        raise RuntimeError("Tailscale is not connected")
    host = _valid_dns_name(status.get("Self", {}).get("DNSName", ""))
    configured = str(configured or "").strip().rstrip("/")
    parsed = urlsplit(configured)
    if (configured and parsed.scheme == "https" and parsed.hostname
            and not parsed.hostname.endswith(".ts.net")):
        return configured, "Custom public HTTPS URL retained (Tailscale not substituted)"

    handlers = _handlers(funnel, host)
    # Check configured path first, preserving a working existing setup.
    desired = (parsed.path or "/").rstrip("/") or "/"
    for route in (desired, "/mycomp", "/"):
        handler = handlers.get(route, {})
        if isinstance(handler, dict) and _is_mycomp_proxy(handler.get("Proxy")):
            return _public_origin(host, route), "Existing MyComp Funnel route detected"

    # If /mycomp is used by a different service, do not silently take it.
    occupied = handlers.get("/mycomp", {})
    if occupied and not _is_mycomp_proxy(occupied.get("Proxy") if isinstance(occupied, dict) else ""):
        raise RuntimeError("Tailscale /mycomp route belongs to another service; left unchanged")

    # Prefer a dedicated route, avoiding root collisions.
    return _public_origin(host, "/mycomp"), "MyComp /mycomp Funnel route needs public verification"


def read_current_url(
    tailscale_executable: str | None = None,
    configured: str = "",
    timeout_seconds: int = 12,
) -> tuple[str, str]:
    """Observe, never change Tailscale routes or other applications."""
    executable = tailscale_executable or shutil.which("tailscale.exe") or "tailscale.exe"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    status = subprocess.run(
        [executable, "status", "--json"],
        capture_output=True, text=True, timeout=timeout_seconds,
        creationflags=flags,
    )
    if status.returncode:
        raise RuntimeError("Could not read Tailscale status: " + status.stderr.strip()[:180])
    document = json.loads(status.stdout)
    tunnel = subprocess.run(
        [executable, "funnel", "status", "--json"],
        capture_output=True, text=True, timeout=timeout_seconds,
        creationflags=flags,
    )
    if tunnel.returncode:
        # Don't claim a public route exists; the safe default is unverified.
        funnel = {}
        warning = "Funnel status unavailable; URL is not yet verified"
    else:
        funnel = json.loads(tunnel.stdout)
        warning = ""
    url, note = discover_url(document, funnel, configured)
    return url, (note + ("; " + warning if warning else ""))


def route_is_free_or_ours(status: dict, host: str, path: str) -> bool:
    record = _handlers(status, host).get(path)
    return (not record or (isinstance(record, dict) and
            _is_mycomp_proxy(record.get("Proxy"))))
