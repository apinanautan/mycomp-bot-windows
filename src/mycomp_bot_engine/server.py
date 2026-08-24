from __future__ import annotations

import argparse
import base64
import ipaddress
import contextlib
import hashlib
import html
import json
import mimetypes
import os
import shutil
import socket
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import parse_qs, urlencode, urlsplit

from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyHttpUrl, Field

from .capabilities import CapabilityRegistry
from .config import CLIENT_ID, Settings
from .database import Database
from .filesystem import Filesystem
from .jobs import Shell
from .oauth import OAuthService, SQLiteTokenVerifier
from .permissions import MCP_COMPATIBILITY_SCOPE, OFFLINE_ACCESS_SCOPE, PERMISSION_LEVELS, PermissionPolicy, level_scope
from .runtime import RuntimeController

ReadOperation = Literal["list", "read", "read_many", "stat", "stat_many", "search", "search_text", "hash", "tree"]
ChangeOperation = Literal["write", "patch", "patch_many", "apply_patch", "copy", "move", "mkdir", "delete", "trash", "restore_backup"]
ShellMode = Literal["foreground", "background", "auto"]
TaskOperation = Literal["status", "wait", "result", "events", "cancel", "resume"]
ObserveMode = Literal["summary", "focused", "elements", "dialogs", "changes", "ocr", "screenshot", "windows"]
ApiMethod = Literal["GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"]
ShellOperation = Literal["run", "status", "wait", "logs", "result", "cancel", "resume", "approve", "deny"]
ShellPrivilege = Literal["user", "admin"]
DomAction = Literal["launch", "status", "list_tabs", "new_tab", "close_tab", "navigate", "evaluate", "query", "click", "type", "wait", "screenshot"]
AccessibilityAction = Literal["status", "launch_app", "activate_app", "list_windows", "observe", "observe_summary", "observe_changes", "inspect_elements", "find_element", "click", "focus", "set_value", "menu_select", "close_window", "minimize_window", "set_window_frame"]
KeyboardAction = Literal["type_text", "paste_text", "press_key", "hotkey"]
MouseAction = Literal["move", "click", "double_click", "right_click", "drag", "scroll"]
VisionAction = Literal["capture_display", "capture_region", "capture_window", "ocr"]


@dataclass
class EngineResources:
    database: Database
    oauth: OAuthService
    files: Filesystem
    shell: Shell
    capabilities: CapabilityRegistry
    runtime: RuntimeController
    maintained_capability_sync: list[dict[str, Any]] = field(default_factory=list)
    observations: dict[str, dict[str, Any]] = field(default_factory=dict)
    screenshots: dict[str, Path] = field(default_factory=dict)
    observation_ttl_seconds: float = 900.0
    _closed: bool = field(default=False, init=False, repr=False)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.shell.shutdown()
        self.runtime.shutdown()
        self.database.close()


def _sync_maintained_capabilities(settings: Settings, capabilities: CapabilityRegistry) -> list[dict[str, Any]]:
    directory = settings.maintained_capability_dir
    if directory is None:
        return []
    directory = directory.expanduser().resolve()
    manifest_path = directory / "manifest.json"
    if not manifest_path.is_file():
        return [{"state": "error", "error": f"maintained capability manifest not found: {manifest_path}"}]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("maintained capability manifest must be an object")
    active = {item["name"]: item for item in capabilities.search_metadata()}
    results: list[dict[str, Any]] = []
    for name, descriptor in sorted(manifest.items()):
        source_path = directory / f"{name}.py"
        if not source_path.is_file() or source_path.is_symlink():
            results.append({"name": name, "state": "error", "error": "source is missing or is a symlink"})
            continue
        source = source_path.read_text(encoding="utf-8")
        checksum = hashlib.sha256(source.encode()).hexdigest()
        active_item = active.get(name, {})
        if (
            active_item.get("checksum") == checksum
            and active_item.get("version") == descriptor.get("version")
            and active_item.get("description") == descriptor.get("description")
        ):
            results.append({"name": name, "state": "current", "checksum": checksum})
            continue
        try:
            installed = capabilities.manage("upsert", name, source, descriptor)
            results.append({"name": name, "state": "updated", "checksum": installed["checksum"]})
        except Exception as error:
            results.append({"name": name, "state": "error", "error": str(error)})
    return results


def _build_resources(settings: Settings) -> EngineResources:
    control_paths = (
        settings.data_dir.resolve(),
        settings.capability_dir.resolve(),
        (settings.config_dir or settings.data_dir).resolve(),
    )
    database = Database(settings.data_dir)
    oauth = OAuthService(
        database,
        settings.redirect_uris,
        settings.owner_consent_token,
        settings.permission_level,
        settings.public_mcp_endpoint,
    )
    files = Filesystem(settings.allowed_roots, settings.max_read_bytes, settings.max_search_files, settings.max_list_entries, settings.max_write_bytes, settings.max_search_directories, settings.max_search_depth, protected_paths=control_paths)
    shell = Shell(
        settings.allow_shell, settings.allowed_executables, database, settings.max_output_bytes,
        foreground_timeout=settings.shell_foreground_timeout_seconds,
        shell_path=settings.shell_path,
        auto_wait_seconds=settings.shell_auto_wait_seconds,
    )
    capabilities = CapabilityRegistry(settings.capability_dir, database, settings.allowed_roots, protected_paths=control_paths)
    maintained_sync = _sync_maintained_capabilities(settings, capabilities)
    runtime = RuntimeController(settings.data_dir, capabilities)
    return EngineResources(database, oauth, files, shell, capabilities, runtime, maintained_sync)


def build_server(settings: Settings | None = None, resources: EngineResources | None = None) -> FastMCP:
    settings = settings or Settings.from_env()
    if settings.host not in {"127.0.0.1", "::1", "localhost"}: raise ValueError("engine may bind only to a loopback address")
    resources = resources or _build_resources(settings)
    database, oauth, files = resources.database, resources.oauth, resources.files
    shell_engine, capabilities, runtime = resources.shell, resources.capabilities, resources.runtime
    policy = PermissionPolicy(settings.permission_level, settings.require_auth)
    public_host = urlsplit(settings.public_base_url).netloc
    auth_options: dict[str, Any] = {}
    if settings.require_auth:
        auth_options = {
            "token_verifier": SQLiteTokenVerifier(oauth),
            "auth": AuthSettings(
                issuer_url=AnyHttpUrl(settings.public_base_url),
                resource_server_url=AnyHttpUrl(settings.public_mcp_endpoint),
                required_scopes=["mycomp"],
            ),
        }
    mcp = FastMCP(
        "MyComp Bot",
        host=settings.host,
        port=settings.port,
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            allowed_hosts=["127.0.0.1:*", "localhost:*", public_host],
            allowed_origins=["https://chatgpt.com", settings.public_base_url],
        ),
        **auth_options,
    )

    def envelope(
        *, request_id: str | None = None, status: str = "completed", changed: bool = False,
        results: list[Any] | None = None, artifacts: list[Any] | None = None,
        resource_uris: list[str] | None = None, warnings: list[str] | None = None,
        error: dict[str, Any] | None = None, started: float | None = None, task_id: str | None = None,
    ) -> dict[str, Any]:
        elapsed = int((time.monotonic() - started) * 1000) if started is not None else 0
        return {
            "status": status, "request_id": request_id or uuid.uuid4().hex, "task_id": task_id,
            "changed": changed, "results": results or [], "artifacts": artifacts or [],
            "resources": resource_uris or [], "warnings": warnings or [], "error": error,
            "timing": {"queued_ms": 0, "execution_ms": elapsed, "total_ms": elapsed},
        }

    def failed(error: Exception, *, request_id: str | None, started: float, backend: str | None = None) -> dict[str, Any]:
        code = "PERMISSION_DENIED" if isinstance(error, PermissionError) else "NOT_FOUND" if isinstance(error, KeyError) else "EXECUTION_FAILED"
        return envelope(request_id=request_id, status="failed", error={
            "code": code, "message": str(error), "retryable": isinstance(error, (TimeoutError, ConnectionError)),
            "backend": backend, "suggested_tool": None,
        }, started=started)

    def internal_capability(name: str, payload: dict[str, Any]) -> Any:
        """Invoke a maintained capability selected by this server, never by a client."""
        return capabilities.execute(name, payload)

    def prune_observations() -> None:
        deadline = time.time() - resources.observation_ttl_seconds
        for observation_id, value in list(resources.observations.items()):
            if value.get("created_at", 0) < deadline:
                resources.observations.pop(observation_id, None)
        for snapshot_id, path in list(resources.screenshots.items()):
            try:
                if path.stat().st_mtime < deadline:
                    path.unlink(missing_ok=True); resources.screenshots.pop(snapshot_id, None)
            except FileNotFoundError:
                resources.screenshots.pop(snapshot_id, None)

    def full_control() -> bool:
        return policy.is_full_control()

    def required_command_level(argv: list[str]) -> str:
        # At full control every shell command is already permitted; the rank is informational.
        if full_control():
            return "full"
        executable, arguments = (Path(argv[0]).name.lower(), set(argv[1:])) if argv else ("", set())
        if executable == "sudo" or executable in {"bash", "zsh", "sh", "dash", "fish", "osascript"}:
            return "full"
        if executable.startswith("python") and arguments & {"-c", "-m"}:
            return "full"
        if executable in {"node", "ruby", "perl", "php"} and "-e" in arguments:
            return "full"
        return "elevated"

    def resolve_shell_cwd(cwd: str) -> Path:
        return files.resolve(cwd, must_exist=True, unrestricted=full_control())

    # The public MCP schema stays platform-neutral.  The desktop host selects
    # its local bridge explicitly; macOS remains the safe default for existing
    # installations and the Windows host sets MYCOMP_UI_CAPABILITY=windows_ui.
    ui_capability = os.getenv("MYCOMP_UI_CAPABILITY", "macos_ui").strip()
    if ui_capability not in {"macos_ui", "windows_ui"}:
        raise ValueError("MYCOMP_UI_CAPABILITY must be macos_ui or windows_ui")

    def ui_result(action: str, payload: dict[str, Any], *, backend: str) -> Any:
        response = internal_capability(ui_capability, {**payload, "action": action})
        if not isinstance(response, dict) or not response.get("ok", False):
            detail = response.get("error", f"{backend} command failed") if isinstance(response, dict) else f"{backend} command failed"
            raise RuntimeError(str(detail))
        return response.get("result", {})

    def store_observation(value: Any, *, mode: str) -> tuple[dict[str, Any], list[str]]:
        prune_observations()
        observation_id = "obs_" + uuid.uuid4().hex
        resources.observations[observation_id] = {"created_at": time.time(), "value": value, "mode": mode}
        uris = [f"mycomp://observations/{observation_id}"]
        result: dict[str, Any] = {"observation_id": observation_id, "observation": value}
        if isinstance(value, dict) and value.get("elements"):
            uris.append(f"mycomp://observations/{observation_id}/elements")
            result["elements_resource"] = uris[-1]
        screenshot_path = value.get("path") if isinstance(value, dict) else None
        if isinstance(screenshot_path, str) and Path(screenshot_path).is_file():
            snapshot_id = "snap_" + uuid.uuid4().hex
            resources.screenshots[snapshot_id] = Path(screenshot_path)
            uris.append(f"mycomp://screenshots/{snapshot_id}")
            result["screenshot_resource"] = uris[-1]
        return result, uris

    def validate_api_url(url: str, *, allow_private_network: bool) -> urllib.parse.SplitResult:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("API URL scheme must be http or https")
        if not parsed.hostname:
            raise ValueError("API URL requires a hostname")
        if parsed.username or parsed.password:
            raise ValueError("credentials must be supplied in headers, not embedded in the URL")
        if not allow_private_network:
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            try:
                addresses = {item[4][0].split("%", 1)[0] for item in socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)}
            except socket.gaierror as error:
                raise ConnectionError(f"unable to resolve API hostname: {parsed.hostname}") from error
            for address in addresses:
                ip = ipaddress.ip_address(address)
                if not ip.is_global or ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
                    raise PermissionError("private or local API targets require allow_private_network=true")
        return parsed

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        """Expose redirects to api() so every target receives SSRF validation."""
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
            return None

    def redact_headers(headers: dict[str, str]) -> dict[str, str]:
        sensitive = {"authorization", "proxy-authorization", "cookie", "set-cookie"}
        return {key: ("<redacted>" if key.lower() in sensitive else value) for key, value in headers.items()}

    @mcp.tool(description="Send exactly one HTTP API request and return the response. No browser or UI fallback is performed.")
    def api(
        url: str, method: ApiMethod = "GET", headers: dict[str, str] | None = None,
        query: dict[str, Any] | None = None, json_body: Any | None = None, body: str | None = None,
        allow_private_network: bool = False, timeout_seconds: float = 30, max_response_bytes: int = 1_000_000,
        approval: Literal["use_policy", "always_ask", "skip"] = "use_policy", dry_run: bool = False,
        request_id: str | None = None, metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        started = time.monotonic()
        try:
            method = method.upper()
            # Full control may reach private/loopback targets without a separate flag.
            private_ok = allow_private_network or full_control()
            needs_full = method not in {"GET", "HEAD", "OPTIONS"} or allow_private_network
            policy.require("full" if needs_full else "normal", "api")
            parsed = validate_api_url(url, allow_private_network=private_ok)
            if query:
                encoded = urllib.parse.urlencode(query, doseq=True)
                parsed = parsed._replace(query="&".join(part for part in (parsed.query, encoded) if part))
            target = urllib.parse.urlunsplit(parsed)
            if json_body is not None and body is not None:
                raise ValueError("provide either json_body or body, not both")
            request_headers = {str(key): str(value) for key, value in (headers or {}).items()}
            if any("\n" in key or "\r" in key or "\n" in value or "\r" in value for key, value in request_headers.items()):
                raise ValueError("API headers must not contain line breaks")
            payload: bytes | None = None
            if json_body is not None:
                payload = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
                if not any(key.lower() == "content-type" for key in request_headers):
                    request_headers["Content-Type"] = "application/json; charset=utf-8"
            elif body is not None:
                payload = body.encode("utf-8")
            if not any(key.lower() == "accept" for key in request_headers):
                request_headers["Accept"] = "application/json, text/plain, */*"
            preview = {"method": method, "url": target, "headers": redact_headers(request_headers), "body_bytes": len(payload or b"")}
            if dry_run:
                return envelope(request_id=request_id, results=[{"dry_run": True, "request": preview}], started=started)
            timeout = min(max(float(timeout_seconds), 0.1), 120)
            limit = min(max(int(max_response_bytes), 0), 10_000_000)
            opener = urllib.request.build_opener(NoRedirect())
            response = None
            for _ in range(6):
                request = urllib.request.Request(target, data=payload, headers=request_headers, method=method)
                try:
                    response = opener.open(request, timeout=timeout)
                except urllib.error.HTTPError as error:
                    response = error
                if response.code not in {301, 302, 303, 307, 308}:
                    break
                location = response.headers.get("Location")
                response.close()
                response = None
                if not location:
                    raise ConnectionError("API redirect has no Location header")
                redirected = urllib.parse.urljoin(target, location)
                prior = urllib.parse.urlsplit(target)
                next_target = validate_api_url(redirected, allow_private_network=allow_private_network)
                if (next_target.scheme, next_target.hostname, next_target.port) != (prior.scheme, prior.hostname, prior.port):
                    request_headers = {key: value for key, value in request_headers.items() if key.lower() not in {"authorization", "proxy-authorization", "cookie"}}
                target = urllib.parse.urlunsplit(next_target)
            if response is None:
                raise ConnectionError("API request exceeded redirect limit")
            try:
                data = response.read(limit + 1)
                truncated = len(data) > limit
                if truncated:
                    data = data[:limit]
                response_headers = redact_headers({str(key): str(value) for key, value in response.headers.items()})
                content_type = response.headers.get_content_type()
                charset = response.headers.get_content_charset() or "utf-8"
                textual = content_type.startswith("text/") or content_type in {"application/json", "application/xml", "application/javascript"}
                try:
                    content: dict[str, Any] = {"text": data.decode(charset)} if textual else {"base64": base64.b64encode(data).decode("ascii")}
                except (LookupError, UnicodeDecodeError):
                    content = {"base64": base64.b64encode(data).decode("ascii")}
                result = {
                    "request": preview, "status": int(getattr(response, "status", response.getcode())),
                    "reason": str(getattr(response, "reason", "")), "final_url": response.geturl(),
                    "headers": response_headers, "content_type": content_type, "body": content,
                    "bytes": len(data), "truncated": truncated,
                }
            finally:
                response.close()
            return envelope(request_id=request_id, changed=method not in {"GET", "HEAD", "OPTIONS"}, results=[result], started=started)
        except Exception as error:
            return failed(error, request_id=request_id, started=started, backend="api")

    @mcp.tool(description="Run a Shell/CLI command or control a Shell task. Elevated uses the executable allowlist; Full Control may run any executable on the configured PATH with any non-protected cwd and skips the sudo owner gate. No UI fallback is performed.")
    def shell(
        operation: ShellOperation = "run", executable: str | None = None, arguments: list[str] | None = None,
        privilege: ShellPrivilege = "user", cwd: str = ".", execution: ShellMode = "auto", task_id: str | None = None,
        timeout_seconds: float = 120, max_output_bytes: int | None = None, tail_lines: int | None = None,
        include_stdout: bool = True, include_stderr: bool = True,
        approval: Literal["use_policy", "always_ask", "skip"] = "use_policy", dry_run: bool = False,
        request_id: str | None = None, metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        started = time.monotonic()
        try:
            if operation == "run":
                if not executable:
                    raise ValueError("executable is required for shell operation=run")
                if privilege == "admin" and Path(executable).name == "sudo":
                    raise ValueError("do not pass sudo as executable when privilege=admin")
                argv = [executable, *(arguments or [])]
                if privilege == "admin":
                    argv = ["/usr/bin/sudo", "-n", *argv]
                policy.require("full" if privilege == "admin" else required_command_level(argv), "shell")
                unrestricted = full_control()
                if dry_run:
                    return envelope(
                        request_id=request_id,
                        results=[{"dry_run": True, "argv": argv, "cwd": cwd, "unrestricted": unrestricted}],
                        started=started,
                    )
                result = shell_engine.run(
                    execution, argv, resolve_shell_cwd(cwd), timeout_seconds=timeout_seconds,
                    max_output_bytes=max_output_bytes, tail_lines=tail_lines,
                    include_stdout=include_stdout, include_stderr=include_stderr,
                    unrestricted=unrestricted,
                )
                returned_task_id = result.get("job_id")
                return envelope(
                    request_id=request_id,
                    results=[{"argv": result.get("argv", argv), "result": result, "unrestricted": unrestricted}],
                    task_id=returned_task_id,
                    started=started,
                )
            if not task_id:
                raise ValueError("task_id is required for Shell task operations")
            policy.require("full" if operation in {"cancel", "resume", "approve", "deny"} else "normal", f"shell.{operation}")
            if dry_run:
                return envelope(request_id=request_id, results=[{"dry_run": True, "operation": operation, "task_id": task_id}], started=started)
            result = shell_engine.control(
                operation, task_id, timeout_seconds=timeout_seconds, max_output_bytes=max_output_bytes,
                tail_lines=tail_lines, include_stdout=include_stdout, include_stderr=include_stderr,
                unrestricted=full_control(),
            )
            returned_task_id = result.get("job_id") or result.get("id") or task_id
            return envelope(request_id=request_id, changed=operation in {"cancel", "resume", "approve", "deny"}, results=[result], task_id=returned_task_id, started=started)
        except Exception as error:
            return failed(error, request_id=request_id, started=started, backend="shell")

    @mcp.tool(description="Execute explicit Chrome DOM/CDP actions in the dedicated browser. Launch may target a configured display. No GUI, Accessibility, Mouse, or OCR fallback is performed.")
    def dom_cdp(
        action: DomAction | None = None, parameters: dict[str, Any] | None = None,
        steps: list[dict[str, Any]] | None = None, tab_id: str | None = None, display_id: str | None = None,
        timeout_seconds: float = 60, approval: Literal["use_policy", "always_ask", "skip"] = "use_policy",
        dry_run: bool = False, request_id: str | None = None, metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        started = time.monotonic()
        try:
            read_only = {"status", "list_tabs", "query", "wait", "screenshot"}
            requested_actions = [item.get("action") for item in (steps or ([{"action": action}] if action else [])) if isinstance(item, dict)]
            policy.require("normal" if requested_actions and all(item in read_only for item in requested_actions) else "elevated", "dom_cdp")
            sequence = steps or ([{"action": action, **(parameters or {})}] if action else [])
            if not sequence or len(sequence) > 100:
                raise ValueError("provide action or between 1 and 100 DOM/CDP steps")
            if dry_run:
                return envelope(request_id=request_id, results=[{"dry_run": True, "steps": sequence}], started=started)
            results: list[Any] = []
            for raw in sequence:
                if not isinstance(raw, dict) or raw.get("action") not in DomAction.__args__:
                    raise ValueError("each DOM/CDP step requires a supported action")
                payload = {**raw, "timeout_seconds": min(float(raw.get("timeout_seconds", timeout_seconds)), timeout_seconds)}
                if tab_id and "tab_id" not in payload:
                    payload["tab_id"] = tab_id
                if display_id and "display_id" not in payload:
                    payload["display_id"] = display_id
                value = internal_capability("browser_cdp", payload)
                results.append({"action": payload["action"], "result": value})
            changed = any(item["action"] not in {"status", "list_tabs", "query", "screenshot"} for item in results)
            return envelope(request_id=request_id, changed=changed, results=results, started=started)
        except Exception as error:
            return failed(error, request_id=request_id, started=started, backend="dom_cdp")

    @mcp.tool(description="Run AppleScript or JavaScript for Automation through osascript and return stdout/stderr. No Accessibility or Mouse fallback is performed.")
    def applescript(
        script: str, language: Literal["AppleScript", "JavaScript"] = "AppleScript",
        arguments: list[str] | None = None, execution: ShellMode = "foreground", timeout_seconds: float = 60,
        include_stdout: bool = True, include_stderr: bool = True,
        approval: Literal["use_policy", "always_ask", "skip"] = "use_policy", dry_run: bool = False,
        request_id: str | None = None, metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        started = time.monotonic()
        try:
            policy.require("full", "applescript")
            if not script or len(script.encode("utf-8")) > 128_000:
                raise ValueError("script must contain between 1 and 128000 UTF-8 bytes")
            argv = ["/usr/bin/osascript", "-l", language, "-e", script, *(arguments or [])]
            if dry_run:
                return envelope(request_id=request_id, results=[{"dry_run": True, "language": language, "arguments": arguments or [], "script_bytes": len(script.encode("utf-8"))}], started=started)
            result = shell_engine.run(
                execution, argv, resolve_shell_cwd("."), timeout_seconds=timeout_seconds,
                include_stdout=include_stdout, include_stderr=include_stderr,
                unrestricted=True,
            )
            return envelope(request_id=request_id, changed=True, results=[{"result": result}], task_id=result.get("job_id"), started=started)
        except Exception as error:
            return failed(error, request_id=request_id, started=started, backend="applescript")

    @mcp.tool(description="Read or act on macOS Accessibility elements only, optionally limited to a display. Coordinate and OCR fallback are explicitly.")
    def accessibility(
        action: AccessibilityAction, parameters: dict[str, Any] | None = None, display_id: str | None = None,
        timeout_seconds: float = 30, approval: Literal["use_policy", "always_ask", "skip"] = "use_policy",
        dry_run: bool = False, request_id: str | None = None, metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        started = time.monotonic()
        try:
            policy.require("normal" if action in {"status", "list_windows", "observe", "observe_summary", "observe_changes", "inspect_elements", "find_element"} else "elevated", "accessibility")
            payload = {**(parameters or {}), "timeout_seconds": timeout_seconds, "allow_ocr_fallback": False, "allow_coordinate_fallback": False}
            if display_id and "display_id" not in payload:
                payload["display_id"] = display_id
            if "x" in payload or "y" in payload:
                raise ValueError("coordinate input belongs in the mouse tool")
            if dry_run:
                return envelope(request_id=request_id, results=[{"dry_run": True, "action": action, "parameters": payload}], started=started)
            value = ui_result(action, payload, backend="accessibility")
            if action in {"status", "list_windows", "observe", "observe_summary", "observe_changes", "inspect_elements", "find_element"}:
                result, uris = store_observation(value, mode=action)
                return envelope(request_id=request_id, results=[result], resource_uris=uris, started=started)
            return envelope(request_id=request_id, changed=True, results=[{"action": action, "result": value}], started=started)
        except Exception as error:
            return failed(error, request_id=request_id, started=started, backend="accessibility")

    @mcp.tool(description="Send explicit keyboard input only: type text, paste text, press a key, or press a hotkey. display_id identifies the intended workspace but keyboard focus remains macOS-global.")
    def keyboard(
        action: KeyboardAction, text: str | None = None, key: str | None = None,
        key_code: int | None = None, modifiers: list[str] | None = None, restore_clipboard: bool = True,
        display_id: str | None = None, timeout_seconds: float = 30, approval: Literal["use_policy", "always_ask", "skip"] = "use_policy",
        dry_run: bool = False, request_id: str | None = None, metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        started = time.monotonic()
        try:
            policy.require("elevated", "keyboard")
            payload: dict[str, Any] = {"timeout_seconds": timeout_seconds}
            if display_id:
                payload["display_id"] = display_id
            if action in {"type_text", "paste_text"}:
                if text is None:
                    raise ValueError(f"{action} requires text")
                payload["text"] = text
                if action == "paste_text":
                    payload["restore_clipboard"] = restore_clipboard
            else:
                if key is None and key_code is None:
                    raise ValueError(f"{action} requires key or key_code")
                payload.update({"key": key or "recorded", "modifiers": modifiers or []})
                if key_code is not None:
                    payload["key_code"] = key_code
            if dry_run:
                return envelope(request_id=request_id, results=[{"dry_run": True, "action": action, "parameters": payload}], started=started)
            value = ui_result(action, payload, backend="keyboard")
            return envelope(request_id=request_id, changed=True, results=[{"action": action, "result": value}], started=started)
        except Exception as error:
            return failed(error, request_id=request_id, started=started, backend="keyboard")

    @mcp.tool(description="Perform direct coordinate Mouse/Trackpad actions only. With display_id, coordinates are local to that display. It does not search with Accessibility or OCR.")
    def mouse(
        action: MouseAction, x: float | None = None, y: float | None = None,
        from_point: dict[str, float] | None = None, to_point: dict[str, float] | None = None,
        vertical: int = 0, horizontal: int = 0, duration_seconds: float = 0.4,
        display_id: str | None = None, timeout_seconds: float = 30, approval: Literal["use_policy", "always_ask", "skip"] = "use_policy",
        dry_run: bool = False, request_id: str | None = None, metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        started = time.monotonic()
        try:
            policy.require("elevated", "mouse")
            mapped = {"move": "mouse_move", "click": "click", "double_click": "double_click", "right_click": "right_click", "drag": "drag", "scroll": "scroll"}[action]
            payload: dict[str, Any] = {"timeout_seconds": timeout_seconds}
            if display_id:
                payload["display_id"] = display_id
            if action in {"move", "click", "double_click", "right_click"}:
                if x is None or y is None:
                    raise ValueError(f"mouse {action} requires x and y")
                payload.update({"x": x, "y": y})
            elif action == "drag":
                if not from_point or not to_point:
                    raise ValueError("mouse drag requires from_point and to_point")
                payload.update({"from": from_point, "to": to_point, "duration_seconds": duration_seconds})
            else:
                payload.update({"vertical": vertical, "horizontal": horizontal})
            if dry_run:
                return envelope(request_id=request_id, results=[{"dry_run": True, "action": action, "parameters": payload}], started=started)
            value = ui_result(mapped, payload, backend="mouse")
            return envelope(request_id=request_id, changed=True, results=[{"action": action, "result": value}], started=started)
        except Exception as error:
            return failed(error, request_id=request_id, started=started, backend="mouse")

    @mcp.tool(description="Capture a selected display/window/region or run local OCR and return display-local coordinates/confidence. It never moves or clicks the mouse.")
    def vision(
        action: VisionAction, region: dict[str, float] | None = None, app: dict[str, Any] | None = None,
        window_index: int = 0, text: str | None = None, exact: bool = False, min_confidence: float = 0,
        display_id: str | None = None, timeout_seconds: float = 30, request_id: str | None = None, metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        started = time.monotonic()
        try:
            policy.require("normal", "vision")
            payload: dict[str, Any] = {"timeout_seconds": timeout_seconds}
            if display_id:
                payload["display_id"] = display_id
            if region:
                payload["region"] = region
            if app:
                payload.update({key: value for key, value in app.items() if key in {"bundle_id", "pid", "app_name"}})
            if action == "capture_window":
                payload["window_index"] = window_index
            value = ui_result(action, payload, backend="vision")
            if action == "ocr" and isinstance(value, dict):
                items = list(value.get("items", []))
                if text is not None:
                    def matches(item: Any) -> bool:
                        candidate = str(item.get("text", "")) if isinstance(item, dict) else ""
                        return candidate.casefold() == text.casefold() if exact else text.casefold() in candidate.casefold()
                    items = [item for item in items if matches(item)]
                items = [item for item in items if float(item.get("confidence", 0)) >= float(min_confidence)]
                value = {**value, "items": items, "count": len(items), "filter": {"text": text, "exact": exact, "min_confidence": min_confidence}}
            result, uris = store_observation(value, mode=action)
            return envelope(request_id=request_id, results=[result], resource_uris=uris, started=started)
        except Exception as error:
            return failed(error, request_id=request_id, started=started, backend="vision")

    @mcp.resource("mycomp://status", mime_type="application/json")
    def status_resource() -> dict[str, Any]:
        return {**runtime.health(), "auth_mode": settings.auth_mode, "permission": policy.describe(), "schema_version": settings.schema_version}

    @mcp.resource("mycomp://permissions", mime_type="application/json")
    def permissions_resource() -> dict[str, Any]:
        return {"permission": policy.describe(), "risk_defaults": policy.risk_defaults()}

    @mcp.resource("mycomp://capabilities", mime_type="application/json")
    def capabilities_resource() -> dict[str, Any]:
        return {"capabilities": capabilities.search_metadata(), "sync": resources.maintained_capability_sync}

    @mcp.resource("mycomp://workflows", mime_type="application/json")
    def workflows_resource() -> dict[str, Any]:
        try: return {"result": internal_capability(ui_capability, {"action": "workflow_list", "timeout_seconds": 5})}
        except Exception as error: return {"error": "workflow state unavailable", "detail": str(error)}

    @mcp.resource("mycomp://workflows/{workflow_id}", mime_type="application/json")
    def workflow_resource(workflow_id: str) -> dict[str, Any]:
        return {"workflow_id": workflow_id, "resource": "available through local MyComp Bot UI"}

    @mcp.resource("mycomp://tasks/{task_id}", mime_type="application/json")
    def task_resource(task_id: str) -> dict[str, Any]:
        item = database.job(task_id)
        if item is None: return {"error": "task not found"}
        return item

    @mcp.resource("mycomp://tasks/{task_id}/events", mime_type="application/json")
    def task_events_resource(task_id: str) -> dict[str, Any]:
        item = database.job(task_id)
        return {"task_id": task_id, "events": item.get("events", []) if item else [], "truncated": False}

    @mcp.resource("mycomp://audit/recent", mime_type="application/json")
    def audit_resource() -> dict[str, Any]: return runtime.logs()

    @mcp.resource("mycomp://observations/{observation_id}", mime_type="application/json")
    def observation_resource(observation_id: str) -> dict[str, Any]:
        prune_observations(); return resources.observations.get(observation_id, {"error": "observation not found or expired"})

    @mcp.resource("mycomp://observations/{observation_id}/elements", mime_type="application/json")
    def elements_resource(observation_id: str) -> dict[str, Any]:
        prune_observations(); value = resources.observations.get(observation_id, {}).get("value", {})
        return {"observation_id": observation_id, "elements": value.get("elements", []) if isinstance(value, dict) else []}

    @mcp.resource("mycomp://screenshots/{snapshot_id}", mime_type="image/png")
    def screenshot_resource(snapshot_id: str) -> bytes:
        prune_observations(); path = resources.screenshots.get(snapshot_id)
        if path is None or not path.is_file(): return b""
        return path.read_bytes()

    @mcp.resource("mycomp://downloads/recent", mime_type="application/json")
    def downloads_resource() -> dict[str, Any]:
        return {"downloads": []}
    mcp._mycomp_resources = resources  # type: ignore[attr-defined]
    return mcp


def create_app(settings: Settings | None = None):
    from starlette.applications import Starlette
    from starlette.middleware.cors import CORSMiddleware
    from starlette.requests import Request
    from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
    from starlette.routing import Mount, Route
    settings = settings or Settings.from_env()
    resources = _build_resources(settings)
    database, oauth = resources.database, resources.oauth
    mcp = build_server(settings, resources)
    oauth_headers = {"Cache-Control": "no-store", "Pragma": "no-cache"}

    async def bounded_form(request: Request) -> dict[str, str]:
        """Read URL-encoded OAuth POSTs with an actual byte ceiling.

        Content-Length is advisory: chunked bodies must receive the same limit.
        """
        if request.headers.get("content-type", "").split(";", 1)[0] != "application/x-www-form-urlencoded":
            raise ValueError("OAuth requests must be form encoded")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 8_192: raise ValueError("OAuth request exceeds size limit")
        try:
            parsed = parse_qs(body.decode("utf-8"), strict_parsing=True, keep_blank_values=True)
        except (UnicodeDecodeError, ValueError) as error:
            raise ValueError("invalid OAuth form") from error
        if any(len(values) != 1 for values in parsed.values()): raise ValueError("duplicate OAuth form parameter")
        return {key: values[0] for key, values in parsed.items()}

    async def register(request: Request):
        if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
            return JSONResponse({"error": "invalid_client_metadata", "error_description": "registration requests must be JSON"}, status_code=400, headers=oauth_headers)
        body = await request.body()
        if len(body) > 8_192:
            return JSONResponse({"error": "invalid_client_metadata", "error_description": "registration request exceeds size limit"}, status_code=400, headers=oauth_headers)
        try:
            metadata = json.loads(body)
            # RFC 7591 permits clients to send descriptive metadata that this
            # small local authorization server does not need.  Ignore it; the
            # redirect allowlist and public-client requirement are enforced
            # below and remain the security boundary.
            if not isinstance(metadata, dict): raise ValueError("client metadata must be an object")
            redirect_uris = metadata.get("redirect_uris")
            if not isinstance(redirect_uris, list): raise ValueError("redirect_uris is required")
            if metadata.get("token_endpoint_auth_method", "none") != "none": raise ValueError("only public clients without a client secret are supported")
            client = oauth.register_client(redirect_uris)
        except (ValueError, PermissionError, json.JSONDecodeError) as error:
            return JSONResponse({"error": "invalid_client_metadata", "error_description": str(error)}, status_code=400, headers=oauth_headers)
        return JSONResponse({
            **client, "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        }, status_code=201, headers=oauth_headers)

    async def authorize(request: Request):
        query = request.query_params
        required = ("response_type", "client_id", "redirect_uri", "code_challenge", "code_challenge_method", "state")
        if any(not query.get(key) for key in required): return JSONResponse({"error": "invalid_request", "error_description": "missing OAuth authorization parameter"}, status_code=400, headers=oauth_headers)
        # ChatGPT sends ui_locales for its own authorization-page language.
        # It is intentionally accepted but never used for authorization.
        allowed = set(required) | {"scope", "resource", "ui_locales"}
        if any(key not in allowed for key in query): return JSONResponse({"error": "invalid_request", "error_description": "unsupported authorization parameter"}, status_code=400, headers=oauth_headers)
        if any(len(query.getlist(key)) != 1 for key in query): return JSONResponse({"error": "invalid_request", "error_description": "duplicate OAuth authorization parameter"}, status_code=400, headers=oauth_headers)
        form_fields = set(required) | {"scope", "resource"}
        hidden = "".join(f'<input type="hidden" name="{html.escape(key, quote=True)}" value="{html.escape(query.get(key, ""), quote=True)}">' for key in form_fields if key in query)
        headers = {"Content-Security-Policy": "default-src 'none'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'", "X-Frame-Options": "DENY", **oauth_headers}
        return HTMLResponse(f"<!doctype html><html><body><h1>MyComp Bot authorization</h1><form method='post' action='/authorize'>{hidden}<label>Owner consent code <input type='password' name='owner_consent' required autofocus></label><input type='submit' value='Approve'></form></body></html>", headers=headers)

    async def authorize_post(request: Request):
        try: form = await bounded_form(request)
        except ValueError as error: return JSONResponse({"error": "invalid_request", "error_description": str(error)}, status_code=400, headers=oauth_headers)
        try:
            code = oauth.authorize(client_id=form.get("client_id", ""), redirect_uri=form.get("redirect_uri", ""), code_challenge=form.get("code_challenge", ""), code_challenge_method=form.get("code_challenge_method", ""), consent_token=form.get("owner_consent", ""), response_type=form.get("response_type", ""), scope=form.get("scope", "mycomp"), resource=form.get("resource", settings.public_mcp_endpoint))
        except (PermissionError, ValueError) as error: return JSONResponse({"error": "invalid_request", "error_description": str(error)}, status_code=400, headers=oauth_headers)
        callback = form["redirect_uri"] + ("&" if "?" in form["redirect_uri"] else "?") + urlencode({"code": code, "state": form.get("state", "")})
        escaped_callback = html.escape(callback, quote=True)
        return HTMLResponse(
            f"<!doctype html><html><head><meta http-equiv='refresh' content='0;url={escaped_callback}'></head>"
            f"<body><p>Authorization approved.</p><p><a href='{escaped_callback}'>Continue to ChatGPT</a></p></body></html>",
            headers={**oauth_headers, "Content-Security-Policy": "default-src 'none'; base-uri 'none'; frame-ancestors 'none'"},
        )
    async def token(request: Request):
        try: form = await bounded_form(request)
        except ValueError as error: return JSONResponse({"error": "invalid_request", "error_description": str(error)}, status_code=400, headers=oauth_headers)
        try:
            if form.get("grant_type") == "authorization_code": grant = oauth.exchange(code=str(form.get("code", "")), redirect_uri=str(form.get("redirect_uri", "")), code_verifier=str(form.get("code_verifier", "")), client_id=str(form.get("client_id", "")), audience=str(form.get("resource") or settings.public_mcp_endpoint))
            elif form.get("grant_type") == "refresh_token": grant = oauth.refresh(str(form.get("refresh_token", "")), str(form.get("resource", "")))
            else: raise ValueError("unsupported grant type")
        except (PermissionError, ValueError) as error: return JSONResponse({"error": "invalid_grant", "error_description": str(error)}, status_code=400, headers=oauth_headers)
        return JSONResponse({"access_token": grant.access_token, "refresh_token": grant.refresh_token, "token_type": "Bearer", "expires_in": grant.expires_in, "scope": grant.scope}, headers=oauth_headers)
    async def health(request: Request): return JSONResponse(resources.runtime.health())
    advertised_levels = PERMISSION_LEVELS[:PERMISSION_LEVELS.index(settings.permission_level) + 1]
    async def protected(request: Request): return JSONResponse({"resource": settings.public_mcp_endpoint, "authorization_servers": [settings.public_base_url], "scopes_supported": ["mycomp", MCP_COMPATIBILITY_SCOPE, *[level_scope(level) for level in advertised_levels]]})
    async def metadata(request: Request): return JSONResponse({"issuer": settings.public_base_url, "authorization_endpoint": settings.authorization_endpoint, "token_endpoint": settings.token_endpoint, "registration_endpoint": settings.registration_endpoint, "token_endpoint_auth_methods_supported": ["none"], "response_types_supported": ["code"], "grant_types_supported": ["authorization_code", "refresh_token"], "code_challenge_methods_supported": ["S256"], "scopes_supported": ["mycomp", MCP_COMPATIBILITY_SCOPE, *[level_scope(level) for level in advertised_levels], OFFLINE_ACCESS_SCOPE], "resource_parameter_supported": True})
    @contextlib.asynccontextmanager
    async def lifespan(app):
        try:
            async with mcp.session_manager.run():
                yield
        finally:
            resources.close()
    app = Starlette(
        routes=[
            Route("/health", health),
            Route("/.well-known/oauth-protected-resource", protected),
            Route("/.well-known/oauth-protected-resource/mcp", protected),
            Route("/mcp/.well-known/oauth-protected-resource", protected),
            Route("/.well-known/oauth-authorization-server", metadata),
            Route("/.well-known/oauth-authorization-server/mcp", metadata),
            Route("/mcp/.well-known/oauth-authorization-server", metadata),
            Route("/register", register, methods=["POST"]),
            Route("/authorize", authorize, methods=["GET"]),
            Route("/authorize", authorize_post, methods=["POST"]),
            Route("/token", token, methods=["POST"]),
            Mount("/", app=mcp.streamable_http_app()),
        ],
        lifespan=lifespan,
    )
    # ChatGPT's plugin setup verifies a remote MCP endpoint from chatgpt.com.
    # Keep the cross-origin surface limited to that first-party origin and the
    # HTTP headers used by Streamable HTTP MCP; no cookies are exposed.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["https://chatgpt.com"],
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Accept", "Authorization", "Content-Type", "Last-Event-ID", "MCP-Protocol-Version"],
        max_age=600,
    )
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run MyComp Bot's loopback MCP engine"); parser.add_argument("--host", default=None); parser.add_argument("--port", type=int, default=None); args = parser.parse_args(); settings = Settings.from_env()
    if args.host or args.port: settings = Settings(**{**settings.__dict__, **{k: v for k, v in {"host": args.host, "port": args.port}.items() if v is not None}})
    import uvicorn
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)


if __name__ == "__main__": main()
