"""Screenshot one window, one region or the display, as compact JPEG.

Usage:
  python scripts/win/shot.py --title "Invoice"
  python scripts/win/shot.py --handle 0x1A2B3C --scale 0.5
  python scripts/win/shot.py --region 0,0,800,600 --quality 70

Prints the file path; the file is already small, so callers can attach it
without pulling a multi-hundred-kilobyte base64 blob through the model.
"""

from __future__ import annotations

import sys

import _bridge as b


def main() -> int:
    action = "capture_display"
    request: dict = {
        "format": b.arg("format", "jpeg") or "jpeg",
        "quality": int(b.arg("quality", "80") or 80),
        "scale": float(b.arg("scale", "1") or 1),
    }
    region = b.arg("region")
    if region:
        parts = [float(item) for item in region.split(",")]
        if len(parts) != 4:
            raise SystemExit("--region expects x,y,width,height")
        request["region"] = dict(zip(("x", "y", "width", "height"), parts))
        action = "capture_region"
    target = b.window_selector() if (b.arg("handle") or b.arg("title")) else {}
    if target:
        request.update(target)
        action = "capture_window"
    request["action"] = action
    b.emit(b.run_app(request))
    return 0


if __name__ == "__main__":
    sys.exit(main())
