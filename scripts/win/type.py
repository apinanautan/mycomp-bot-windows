"""Type text into the focused control or into a named element.

Usage:
  python scripts/win/type.py --text "hello"
  python scripts/win/type.py --window "Notepad" --name "Text editor" --text "hello"

Uses UIA ``set_value`` when an element is given (no focus stealing), otherwise
sends real keystrokes through the Windows UI bridge.
"""

from __future__ import annotations

import sys

import _bridge as b


def main() -> int:
    text = b.arg("text")
    if text is None:
        raise SystemExit("provide --text")
    if b.arg("handle") or b.arg("name") or b.arg("id"):
        target = b.window_selector() if (b.arg("handle") or b.arg("title")) else {}
        if b.arg("name"):
            target["name"] = b.arg("name")
        if b.arg("id"):
            target["automation_id"] = b.arg("id")
        b.emit(b.run({"action": "set_value", "selector": target, "value": text}))
        return 0
    b.emit(b.run_app({"action": "type_text", "text": text}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
