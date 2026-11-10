"""Windows UI Automation bridge (pywinauto / UIA backend).

Two execution modes share one code path:

* one-shot CLI - JSON request on stdin, single JSON response on stdout
  (used by ``scripts/win`` macros and by the engine when the app is not running);
* in-process module - the desktop app imports this file and keeps the module
  resident, so the warm UIA desktop, the window map and the element cache survive
  between MCP calls.

Speed rule: a caller that already knows a ``handle`` must never trigger a
virtual-desktop scan. Handle resolution is a direct ``window(handle=...)`` call,
and window/element maps are cached for a short, bounded time.
"""

from __future__ import annotations

import json
import sys
import threading
import time

from pywinauto import Desktop

_MAP_TTL = 20.0         # window map lifetime for selector scans
_HANDLE_TTL = 300.0     # resolved handle lifetime
_ELEMENT_TTL = 60.0     # resolved element lifetime
_ELEM_CACHE_TTL = 1.0   # short-lived element records for list_windows
_LOCK = threading.RLock()
_DESKTOP = None
_MAP: list = []
_MAP_AT = 0.0
_HANDLES: dict = {}
_ELEMENTS: dict = {}
_ELEM_CACHE: dict = {}
_OBSERVE_CACHE: dict = {}
_WARMING = False


def _desktop():
    global _DESKTOP
    if _DESKTOP is None:
        _DESKTOP = Desktop(backend="uia")
    return _DESKTOP


def reset_cache() -> None:
    global _MAP, _MAP_AT
    with _LOCK:
        _MAP, _MAP_AT = [], 0.0
        _HANDLES.clear()
        _ELEMENTS.clear()
        _ELEM_CACHE.clear()
        _OBSERVE_CACHE.clear()


def _cached_elem(window) -> dict:
    """Element record for a top-level window, reused for a short interval.

    Every field crosses the UIA boundary, so re-reading all of them for every
    window on every list_windows call dominates the cost and makes the timing
    jitter between roughly 13 and 55 ms. Window titles/bounds do not change
    meaningfully inside one second.
    """
    handle = int(window.handle or 0)
    if not handle:
        # Never cache on a missing handle: every such window would share key 0
        # and later calls would report another window's title and bounds.
        return elem(window, detail=False)
    now = time.monotonic()
    cached = _ELEM_CACHE.get(handle)
    if cached is not None and now - cached[1] <= _ELEM_CACHE_TTL:
        return dict(cached[0])
    record = elem(window, detail=False)
    with _LOCK:
        if len(_ELEM_CACHE) > 512:
            _ELEM_CACHE.clear()
        _ELEM_CACHE[handle] = (dict(record), now)
    return record


def elem(w, detail: bool = True) -> dict:
    r = w.rectangle()
    info = w.element_info
    data = {
        "name": w.window_text(),
        "automation_id": getattr(info, "automation_id", "") or "",
        "control_type": getattr(info, "control_type", "") or "",
        "process_id": w.process_id(),
        "handle": int(w.handle or 0),
        "bounds": {"x": r.left, "y": r.top, "width": r.width(), "height": r.height()},
        "value": None,
    }
    if detail:
        # These two cross the UIA boundary per element and dominate scan cost.
        try:
            data["is_enabled"] = w.is_enabled()
            data["is_offscreen"] = not w.is_visible()
        except Exception:
            data["is_enabled"], data["is_offscreen"] = True, False
    return data


def _selector(req) -> dict:
    selector = req.get("selector") if isinstance(req, dict) else None
    return selector if isinstance(selector, dict) else req


def _has_selector(sel) -> bool:
    return any(key in sel for key in
               ("handle", "process_id", "pid", "name", "name_contains", "app_name", "automation_id", "control_type"))


def _matches_name(name: str, sel: dict) -> bool:
    if sel.get("name") and name != str(sel["name"]):
        return False
    query = sel.get("name_contains") or sel.get("app_name")
    if query and str(query).lower() not in name.lower():
        return False
    return True


def warm() -> bool:
    """Prime the UIA layer off the caller's critical path.

    The first ``Desktop().windows()`` call in a process costs ~1.7 s (UIA COM
    initialisation and pywinauto's tree cache); every later call is ~2 ms. Paying
    that during app startup keeps the first MCP call fast instead of making it
    look like a per-call regression.
    """
    global _WARMING
    with _LOCK:
        if _MAP:
            return True
        if _WARMING:
            return False
        _WARMING = True

    def prime() -> None:
        try:
            _window_map(force=True)
        except Exception:
            pass

    threading.Thread(target=prime, daemon=True, name="uia-warm").start()
    return True


def _window_map(force: bool = False) -> list:
    """Top-level windows, reused for a short window so scan cost is amortised."""
    global _MAP, _MAP_AT, _WARMING
    with _LOCK:
        if not force and _MAP and time.monotonic() - _MAP_AT <= _MAP_TTL:
            return list(_MAP)
        windows = []
        for window in _desktop().windows():
            try:
                if window.handle:
                    windows.append(window)
            except Exception:
                continue
        _MAP, _MAP_AT = windows, time.monotonic()
        _WARMING = False
        return list(_MAP)


def _window_by_handle(handle: int):
    key = ("h", handle)
    with _LOCK:
        cached = _HANDLES.get(key)
    if cached is not None and time.monotonic() - cached[1] <= _HANDLE_TTL:
        window = cached[0]
        try:
            window.handle
            return window
        except Exception:
            pass
    window = _desktop().window(handle=handle)
    with _LOCK:
        _HANDLES[key] = (window, time.monotonic())
    return window


def _scan(sel: dict, include_descendants: bool):
    for window in _window_map():
        try:
            if not _matches_name(window.window_text() or "", sel):
                continue
            info = window.element_info
            if sel.get("automation_id") and (getattr(info, "automation_id", "") or "") != str(sel["automation_id"]):
                continue
            if sel.get("control_type") and (getattr(info, "control_type", "") or "") != str(sel["control_type"]).replace("ControlType.", ""):
                continue
            if sel.get("process_id") is not None or sel.get("pid") is not None:
                wanted = sel.get("process_id", sel.get("pid"))
                if int(window.process_id()) != int(wanted):
                    continue
            return window, True
        except Exception:
            continue
    if not include_descendants:
        return None, False
    for window in _window_map():
        try:
            for child in window.descendants():
                try:
                    if not _matches_name(child.window_text() or "", sel):
                        continue
                    info = child.element_info
                    if sel.get("automation_id") and (getattr(info, "automation_id", "") or "") != str(sel["automation_id"]):
                        continue
                    if sel.get("control_type") and (getattr(info, "control_type", "") or "") != str(sel["control_type"]).replace("ControlType.", ""):
                        continue
                    return child, False
                except Exception:
                    continue
        except Exception:
            continue
    return None, False


def find(sel: dict, include_descendants: bool = True):
    """Resolve a selector. A known handle short-circuits every scan."""
    handle = sel.get("handle")
    if handle:
        return _window_by_handle(int(handle)), True
    key = json.dumps(sel, sort_keys=True, default=str)
    with _LOCK:
        cached = _ELEMENTS.get(key)
    if cached is not None and time.monotonic() - cached[1] <= _ELEMENT_TTL:
        try:
            cached[0].handle
            return cached[0], cached[2]
        except Exception:
            pass
    found, is_window = _scan(sel, include_descendants)
    if found is None:
        raise RuntimeError("No Windows UI Automation element matched the selector.")
    with _LOCK:
        _ELEMENTS[key] = (found, time.monotonic(), is_window)
    return found, is_window


def _run_action(req: dict) -> dict:
    action = req.get("action", "status")
    sel = _selector(req)
    if action == "status":
        return {"backend": "pywinauto-uia", "available": True, "cached_windows": len(_MAP)}
    if action == "list_windows":
        limit = max(1, min(int(req.get("max_items", req.get("limit", 200))), 500))
        detail = bool(req.get("detail", False))
        refresh = bool(req.get("refresh", False))
        if refresh:
            with _LOCK:
                _ELEM_CACHE.clear()
        windows = []
        for window in _window_map(force=refresh):
            try:
                if _has_selector(sel) and not _matches_name(window.window_text() or "", sel):
                    continue
                windows.append(elem(window, detail=True) if detail else _cached_elem(window))
            except Exception:
                continue
            if len(windows) >= limit:
                break
        return {"backend": "pywinauto-uia", "windows": windows, "count": len(windows)}
    if action == "wait_until":
        if not _has_selector(sel):
            raise ValueError("wait_until requires a selector (handle, name, name_contains, automation_id or control_type)")
        timeout = max(0.1, min(float(req.get("timeout_seconds", 15)), 120))
        interval = max(0.05, min(float(req.get("interval", 0.2)), 2.0))
        needle = str(req.get("text") or "")
        start = time.monotonic()
        deadline = start + timeout
        last_refresh = start
        handle = sel.get("handle")
        while True:
            found = None
            if handle:
                try:
                    candidate = _window_by_handle(int(handle))
                    candidate.handle
                    found = candidate
                except Exception:
                    found = None
            else:
                # Top-level match is cheap and cached; only re-scan once per second
                # so a genuinely new window is noticed.
                if time.monotonic() - last_refresh > 1.0:
                    _window_map(force=True)
                    last_refresh = time.monotonic()
                for window in _window_map():
                    try:
                        if _matches_name(window.window_text() or "", sel):
                            found = window
                            break
                    except Exception:
                        continue
                # A text needle means "wait until a descendant containing this
                # text appears"; walk only matched candidates, not the desktop.
                if found is None and needle:
                    for window in _window_map():
                        try:
                            for child in window.descendants():
                                if needle.lower() in (child.window_text() or "").lower():
                                    found = child
                                    break
                            if found is not None:
                                break
                        except Exception:
                            continue
            if found is not None:
                try:
                    data = elem(found)
                    name = data.get("name") or ""
                    if not needle or needle.lower() in name.lower():
                        return {"backend": "pywinauto-uia", "matched": True, "element": data,
                                "waited_ms": int((time.monotonic() - start) * 1000)}
                except Exception:
                    pass
            if time.monotonic() >= deadline:
                break
            time.sleep(interval)
        raise TimeoutError(f"wait_until: selector did not match within {timeout:.1f}s")
    if action in ("observe", "observe_summary", "observe_changes", "inspect_elements"):
        if not _has_selector(sel):
            raise RuntimeError("A window selector is required for element inspection on Windows.")
        target, _ = find(sel, include_descendants=False)
        limit = max(1, min(int(req.get("max_items", req.get("limit", 100))), 300))
        max_depth = max(0, min(int(req.get("max_depth", 4)), 8))
        # Walking a heavy window's tree (the taskbar has hundreds of children) is
        # the dominant cost inside a batch. Reuse the walk for a second unless the
        # caller asked for the full detail fields.
        cache_key = None
        if not bool(req.get("detail", False)):
            try:
                cache_key = (json.dumps(sel, sort_keys=True, default=str), limit, max_depth)
            except Exception:
                cache_key = None
            if cache_key is not None:
                cached = _OBSERVE_CACHE.get(cache_key)
                if cached is not None and time.monotonic() - cached[1] <= _ELEM_CACHE_TTL:
                    return dict(cached[0])
        out = [elem(target)]
        queue = [(target, 0)]
        index = 0
        while index < len(queue) and len(out) < limit:
            parent, depth = queue[index]
            index += 1
            if depth >= max_depth:
                continue
            try:
                children = parent.children()
            except Exception:
                continue
            for child in children:
                try:
                    out.append(elem(child))
                except Exception:
                    continue
                if len(out) >= limit:
                    break
                queue.append((child, depth + 1))
        result = {"backend": "pywinauto-uia", "root": out[0], "elements": out, "count": len(out)}
        if cache_key is not None:
            with _LOCK:
                if len(_OBSERVE_CACHE) > 128:
                    _OBSERVE_CACHE.clear()
                _OBSERVE_CACHE[cache_key] = (dict(result), time.monotonic())
        return result
    if action == "batch":
        steps = req.get("steps") or []
        if not isinstance(steps, list) or not 1 <= len(steps) <= 40:
            raise ValueError("batch steps must contain between 1 and 40 entries")
        results = []
        for index, step in enumerate(steps):
            started = time.monotonic()
            try:
                if not isinstance(step, dict):
                    raise ValueError("each batch step must be an object")
                value = _run_action({**req, **step})
                results.append({"index": index, "ok": True, "result": value,
                                "duration_ms": int((time.monotonic() - started) * 1000)})
            except Exception as error:
                results.append({"index": index, "ok": False,
                                "error": {"type": type(error).__name__, "message": str(error)},
                                "duration_ms": int((time.monotonic() - started) * 1000)})
                if req.get("stop_on_error", True):
                    break
        return {"backend": "pywinauto-uia", "action": "batch", "results": results,
                "count": len(results), "ok": all(item["ok"] for item in results)}
    target, _ = find(sel)
    if action == "find_element":
        return {"backend": "pywinauto-uia", "found": True, "element": elem(target)}
    if action in ("focus", "activate_app"):
        target.set_focus()
        return {"backend": "pywinauto-uia", "element": elem(target, detail=False)}
    if action in ("click", "menu_select"):
        target.click_input()
        return {"backend": "pywinauto-uia", "invoked": True, "method": "click_input", "element": elem(target, detail=False)}
    if action == "set_value":
        target.set_edit_text(str(req.get("value", "")))
        return {"backend": "pywinauto-uia", "value_set": True, "element": elem(target, detail=False)}
    if action == "set_window_frame":
        # Explicitly selected window only; no coordinate-based fallback.
        if not _has_selector(sel):
            raise ValueError("set_window_frame requires an explicit window selector")
        frame = req.get("frame") or req.get("bounds") or {}
        if not isinstance(frame, dict) or not all(key in frame for key in ("x", "y", "width", "height")):
            raise ValueError("set_window_frame requires frame with x, y, width, height")
        x, y, width, height = (int(frame[key]) for key in ("x", "y", "width", "height"))
        if width < 100 or height < 100 or width > 16384 or height > 16384:
            raise ValueError("invalid window dimensions")
        target.move_window(x, y, width, height, repaint=True)
        return {"backend": "pywinauto-uia", "action": action, "element": elem(target, detail=False)}
    if action == "close_window":
        target.close()
        reset_cache()
        return {"backend": "pywinauto-uia", "action": action}
    if action == "minimize_window":
        target.minimize()
        return {"backend": "pywinauto-uia", "action": action}
    raise RuntimeError(f"Unsupported action: {action}")


def main(req: dict) -> dict:
    """Run one request under the module lock; ``batch`` recurses in-process."""
    with _LOCK:
        return _run_action(req)


def serve() -> None:
    """Line protocol for a resident bridge process (optional)."""
    for line in sys.stdin:
        try:
            request = json.loads(line.lstrip("\ufeff"))
            print(json.dumps({"ok": True, "result": main(request), "error": ""}, ensure_ascii=False), flush=True)
        except Exception as error:
            print(json.dumps({"ok": False, "result": None, "error": str(error)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in {"serve", "--serve"}:
        serve()
    else:
        try:
            payload = json.loads(sys.stdin.read().lstrip("\ufeff"))
            print(json.dumps({"ok": True, "result": main(payload), "error": ""}, ensure_ascii=False))
        except Exception as error:
            print(json.dumps({"ok": False, "result": None, "error": str(error)}, ensure_ascii=False))
            sys.exit(1)
