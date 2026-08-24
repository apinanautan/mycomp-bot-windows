from __future__ import annotations

"""Owner-supervised Windows UI bridge.

The MCP engine writes a short-lived command into the local runtime directory.
The Windows desktop app is the only process that consumes it and performs the
input operation.  Nothing listens on a network socket and this module never
falls back to Shell commands.
"""

import json
import os
import time
import uuid
from pathlib import Path


def _runtime() -> Path:
    root = Path(os.environ.get("MYCOMP_DATA_DIR", Path.home() / "AppData/Local/MyComp Bot"))
    return root.expanduser() / "runtime"


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def _request(payload: dict) -> dict:
    runtime = _runtime()
    commands, results = runtime / "ui-commands", runtime / "ui-results"
    stop = runtime / "ui-stop-request.json"
    if stop.exists() and payload.get("action") not in {"status", "clear_stop"}:
        return {"ok": False, "error": "UI control is stopped by the owner", "stopped": True}
    if payload.get("action") == "clear_stop":
        stop.unlink(missing_ok=True)
        return {"ok": True, "result": {"cleared": True}}
    request_id = uuid.uuid4().hex
    command_path, result_path = commands / f"{request_id}.json", results / f"{request_id}.json"
    result_path.unlink(missing_ok=True)
    _atomic_json(command_path, {**payload, "id": request_id, "requested_at": time.time()})
    deadline = time.monotonic() + min(max(float(payload.get("timeout_seconds", 30)), 0.1), 600)
    while time.monotonic() < deadline:
        if result_path.is_file():
            try:
                return json.loads(result_path.read_text(encoding="utf-8"))
            finally:
                result_path.unlink(missing_ok=True)
        if stop.exists():
            command_path.unlink(missing_ok=True)
            return {"ok": False, "error": "UI control stopped while command was pending", "stopped": True}
        time.sleep(0.05)
    command_path.unlink(missing_ok=True)
    raise TimeoutError(f"Windows UI command {payload.get('action')!r} timed out after {payload.get('timeout_seconds', 30)} seconds")


def execute(payload):
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    action = str(payload.get("action", "status"))
    supported = {
        "status", "clear_stop", "list_windows", "observe", "observe_summary", "observe_changes",
        "mouse_move", "click", "double_click", "right_click", "drag", "scroll",
        "type_text", "paste_text", "press_key", "hotkey",
        "capture_display", "capture_region", "capture_window", "ocr",
        "launch_app", "activate_app", "inspect_elements", "find_element", "focus", "set_value", "menu_select", "set_window_frame", "close_window", "minimize_window",
    }
    if action not in supported:
        raise ValueError(f"unsupported Windows UI action: {action}")
    return _request({**payload, "action": action})


def self_test():
    if os.name != "nt":
        return True
    commands, results = _runtime() / "ui-commands", _runtime() / "ui-results"
    commands.mkdir(parents=True, exist_ok=True)
    results.mkdir(parents=True, exist_ok=True)
    probe = commands / f".self-test-{uuid.uuid4().hex}"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink()
    return True
