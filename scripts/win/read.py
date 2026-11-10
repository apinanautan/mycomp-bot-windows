"""Print the accessible text of a window or of one element, compactly.

Usage:
  python scripts/win/read.py --title "Notepad"
  python scripts/win/read.py --title "Chrome" --grep "Total"
  python scripts/win/read.py --handle 0x1A2B3C --names-only

Exit code 1 means ``--grep`` found nothing, so it doubles as a wait/assert.
"""

from __future__ import annotations

import sys

import _bridge as b


def main() -> int:
    selector = b.window_selector()
    result = b.run({"action": "observe", "selector": selector,
                    "limit": int(b.arg("limit", "400") or 400),
                    "max_depth": int(b.arg("depth", "6") or 6)})
    elements = result.get("elements") or []
    needle = b.arg("grep")
    names_only = b.flag("names-only")
    lines = []
    for element in elements:
        name = (element.get("name") or "").strip()
        if not name:
            continue
        if needle and needle.lower() not in name.lower():
            continue
        if names_only:
            lines.append(name)
        else:
            kind = element.get("control_type") or "?"
            lines.append(f"{kind}\t{name}")
    b.emit({"count": len(elements), "matched": len(lines), "text": lines[:200]})
    return 0 if (lines or not needle) else 1


if __name__ == "__main__":
    sys.exit(main())
