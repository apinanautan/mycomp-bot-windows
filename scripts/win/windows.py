"""List top-level windows, or print one window's element tree.

Usage:
  python scripts/win/windows.py                 # windows only (fast, no details)
  python scripts/win/windows.py --filter Chrome
  python scripts/win/windows.py --handle 0x1A2B3C --tree
"""

from __future__ import annotations

import sys

import _bridge as b


def main() -> int:
    handle = b.arg("handle")
    if handle:
        selector = {"handle": int(handle, 0)}
        if b.flag("tree"):
            result = b.run({"action": "observe", "selector": selector,
                            "limit": int(b.arg("limit", "200") or 200),
                            "max_depth": int(b.arg("depth", "4") or 4)})
        else:
            result = b.run({"action": "find_element", "selector": selector})
        b.emit(result)
        return 0
    request = {"action": "list_windows", "limit": int(b.arg("limit", "200") or 200)}
    query = b.arg("filter")
    if query:
        request.update(name_contains=query, selector={"name_contains": query})
    if b.flag("detail"):
        request["detail"] = True
    b.emit(b.run(request))
    return 0


if __name__ == "__main__":
    sys.exit(main())
