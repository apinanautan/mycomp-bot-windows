"""Compact OCR of a region or a single window.

Usage:
  python scripts/win/ocr.py --window "Invoice"
  python scripts/win/ocr.py --handle 0x1A2B3C --grep "Total"
  python scripts/win/ocr.py --region 0,0,800,600 --text "Save"

The UI bridge is asked through the app's OCR path so the model stays warm and
only the requested window or region is captured.
"""

from __future__ import annotations

import sys

import _bridge as b


def main() -> int:
    request: dict = {"action": "ocr", "timeout_seconds": float(b.arg("timeout", "90") or 90)}
    handle = b.arg("handle")
    title = b.arg("title")
    if handle:
        request["window"] = {"handle": int(handle, 0)}
    elif title:
        request["window"] = {"name_contains": title}
    region = b.arg("region")
    if region:
        parts = [float(item) for item in region.split(",")]
        if len(parts) != 4:
            raise SystemExit("--region expects x,y,width,height")
        request["region"] = dict(zip(("x", "y", "width", "height"), parts))
    if b.arg("text"):
        request["text"] = b.arg("text")
        request["exact"] = b.flag("exact")
    if b.arg("min-confidence"):
        request["min_confidence"] = float(b.arg("min-confidence"))
    result = b.run_app(request)
    items = result.get("items") or []
    lines = [item.get("text") for item in items]
    b.emit({"count": len(items), "text": lines[:200]})
    return 0 if lines else 1


if __name__ == "__main__":
    sys.exit(main())
