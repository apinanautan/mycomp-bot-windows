"""Run a batch of Chrome DevTools steps from one shell call.

Usage:
  python scripts/win/cdp.py --steps steps.json
  echo '[{"action":"navigate","url":"https://example.com"},{"action":"evaluate","expression":"document.title"}]' | python scripts/win/cdp.py
  python scripts/win/cdp.py --steps steps.json --keep-warm --tab-id ABC

This is the fastest way to drive the dedicated browser from the Shell tool: one
process, one warm DevTools socket, up to 100 ordered steps, one JSON result.
"""

from __future__ import annotations

import json
import sys
import time

import _bridge as b

ACTIONS = {"status", "list_tabs", "query", "wait", "screenshot", "evaluate", "click", "type", "navigate"}


def load_steps() -> list[dict]:
    path = b.arg("steps")
    if path:
        return json.loads(sys.stdin.read()) if path == "-" else json.loads(open(path, encoding="utf-8").read())
    if not sys.stdin.isatty():
        data = sys.stdin.read().strip()
        if data:
            return json.loads(data)
    raise SystemExit("provide --steps <file|-> or pipe steps JSON")


def main() -> int:
    steps = load_steps()
    if not isinstance(steps, list) or not steps:
        raise SystemExit("steps must be a non-empty JSON array")
    for step in steps:
        if not isinstance(step, dict) or step.get("action") not in ACTIONS:
            raise SystemExit(f"unsupported step: {step}")
    payload = {"action": "batch", "steps": steps, "stop_on_error": not b.flag("keep-going")}
    tab_id = b.arg("tab-id")
    if tab_id:
        payload["tab_id"] = tab_id
    started = time.perf_counter()
    result = b._load("cap_browser_cdp", "capability_sources/browser_cdp.py").execute(payload)
    result["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
    b.emit(result)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
