"""Shared helpers for the ready-made Windows macros in ``scripts/win``.

Every macro is a one-shot CLI so the model can call a named script instead of
re-inventing a UIA sequence: one Shell tool call, no reasoning about selectors.

The bridge is loaded from the source checkout (``windows/UIAutomationBridge.py``)
or from the installed version directory, whichever exists first.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path


def _roots() -> list[Path]:
    here = Path(__file__).resolve()
    candidates: list[Path] = [here.parents[2]]
    if os.environ.get("MYCOMP_ROOT"):
        candidates.append(Path(os.environ["MYCOMP_ROOT"]))
    versions = Path(os.environ.get("LOCALAPPDATA", "")) / "MyComp Bot" / "versions"
    if versions.is_dir():
        candidates.extend(sorted((p for p in versions.iterdir() if p.is_dir()), reverse=True))
    return [path for path in candidates if str(path) and path.is_dir()]


def _load(name: str, relative: str):
    for root in _roots():
        candidate = root / relative
        if candidate.is_file():
            spec = importlib.util.spec_from_file_location(f"mycomp_{name}", candidate)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                return module
    raise SystemExit(f"{relative} not found; set MYCOMP_ROOT")


def bridge():
    return _load("uia_bridge", "windows/UIAutomationBridge.py")


def run(request: dict) -> dict:
    """Execute one UI Automation request through the bridge module."""
    return bridge().main(request)


def _capability(name: str):
    return _load(f"cap_{name}", f"capability_sources/{name}.py")


def run_app(request: dict) -> dict:
    """Execute one request the running app owns (OCR, capture, mouse, keyboard)."""
    response = _capability("windows_ui").execute(request)
    if not response.get("ok"):
        raise SystemExit(str(response.get("error") or "UI command failed"))
    return response.get("result") or {}


def emit(value) -> None:
    print(json.dumps(value, ensure_ascii=False))


def arg(name: str, default: str | None = None) -> str | None:
    for index, item in enumerate(sys.argv):
        if item == f"--{name}" and index + 1 < len(sys.argv):
            return sys.argv[index + 1]
        if item.startswith(f"--{name}="):
            return item.split("=", 1)[1]
    return default


def flag(name: str) -> bool:
    return f"--{name}" in sys.argv


def window_selector() -> dict:
    """Build a selector from --handle or --title; handle wins."""
    handle = arg("handle")
    if handle:
        return {"handle": int(handle, 0)}
    title = arg("title")
    if title:
        return {"name_contains": title}
    raise SystemExit("provide --handle <hwnd> or --title <substring>")
