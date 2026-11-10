"""Click a UI element by accessible name, automation id or handle.

Usage:
  python scripts/win/click.py --window "Notepad" --name "Save"
  python scripts/win/click.py --handle 0x1A2B3C
  python scripts/win/click.py --window Chrome --id "submit" --type Button
"""

from __future__ import annotations

import sys

import _bridge as b


def selector() -> dict:
    handle = b.arg("handle")
    if handle:
        return {"handle": int(handle, 0)}
    name = b.arg("name")
    if name:
        return {"name": name}
    contains = b.arg("contains")
    if contains:
        return {"name_contains": contains}
    automation_id = b.arg("id")
    if automation_id:
        return {"automation_id": automation_id}
    raise SystemExit("provide --handle, --name, --contains or --id")


def main() -> int:
    target = selector()
    control_type = b.arg("type")
    if control_type:
        target["control_type"] = control_type
    title = b.arg("window")
    if title and "handle" not in target:
        # Narrow the search to one window before matching descendants.
        windows = b.run({"action": "find_element", "selector": {"name_contains": title}})
        root = (windows or {}).get("element") or {}
        if root.get("handle"):
            b.run({"action": "focus", "selector": {"handle": root["handle"]}})
    result = b.run({"action": "click", "selector": target})
    b.emit(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
