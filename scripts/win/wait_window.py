"""Wait for a window to appear before returning its handle.

Usage:
  python scripts/win/wait_window.py --filter "Export" --timeout 20

Exit code 0 with a handle means the window exists; 1 means it timed out.
"""

from __future__ import annotations

import sys
import time

import _bridge as b


def main() -> int:
    needle = b.arg("filter") or b.arg("title")
    if not needle:
        raise SystemExit("provide --filter <substring>")
    deadline = time.monotonic() + float(b.arg("timeout", "15") or 15)
    while time.monotonic() < deadline:
        result = b.run({"action": "list_windows", "limit": 200,
                        "selector": {"name_contains": needle}})
        windows = result.get("windows") or []
        if windows:
            window = windows[0]
            b.emit({"found": True, "handle": window.get("handle"), "name": window.get("name")})
            return 0
        time.sleep(0.25)
    b.emit({"found": False, "filter": needle})
    return 1


if __name__ == "__main__":
    sys.exit(main())
