"""MyComp Bot speed benchmark — run the SAME script against two versions to diff.

Run with the version's OWN Python so third-party imports (pywinauto) resolve:

    <root>\\.venv\\Scripts\\python.exe scripts\\benchmark.py
    <root>\\.venv\\Scripts\\python.exe scripts\\benchmark.py --root C:\\path\\to\\other\\version
    <root>\\.venv\\Scripts\\python.exe scripts\\benchmark.py --with-browser

What it measures (the exact things v1.1.35 changed):

  shell        python interpreter spawn cost (unchanged baseline)
  browser_cdp  cold = fresh-interpreter import+status (old engine paid this
               EVERY call); warm = same-process status/evaluate/batch (the new
               warm capability worker pays the import once)
  uia          cold list_windows vs cached list_windows vs observe-by-handle vs
               a 3-step batch (handle-first + window-map cache)
  screenshot   (--with-browser only) JPEG vs PNG encoded byte size

Results are appended to ``scripts/benchmark-results.json`` so a before/after
pair can be diffed directly. Nothing is written outside the source tree.
"""

from __future__ import annotations

import importlib.util
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

RESULTS = Path(__file__).resolve().with_name("benchmark-results.json")
N_SPAWN = 5


def resolve_root() -> Path:
    args = sys.argv[1:]
    if "--root" in args:
        return Path(args[args.index("--root") + 1]).resolve()
    return Path(__file__).resolve().parents[1]


def read_version(root: Path) -> str:
    version_file = root / "VERSION"
    if version_file.is_file():
        return version_file.read_text(encoding="utf-8", errors="replace").strip() or "?"
    return "?"


def load_module(root: Path, relative: str, name: str):
    candidate = root / relative
    if not candidate.is_file():
        raise FileNotFoundError(str(candidate))
    spec = importlib.util.spec_from_file_location(name, candidate)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {candidate}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def median_ms(samples: list[float]) -> float:
    return round(statistics.median(samples) * 1000, 1)


def bench_shell() -> dict:
    samples = []
    for _ in range(N_SPAWN):
        start = time.perf_counter()
        subprocess.run([sys.executable, "-c", "pass"], capture_output=True)
        samples.append(time.perf_counter() - start)
    return {"shell_spawn_ms": median_ms(samples), "shell_spawn_n": N_SPAWN}


def bench_browser_cdp(root: Path, with_browser: bool) -> dict:
    # Import cost is what the warm worker amortises: the old engine paid a fresh
    # interpreter import on every call; the worker pays it once.
    import_inline = (
        "import importlib.util,sys,time\n"
        "p=sys.argv[1]\n"
        "t=time.perf_counter()\n"
        "spec=importlib.util.spec_from_file_location('bcdp',p+'/capability_sources/browser_cdp.py')\n"
        "m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        "print((time.perf_counter()-t)*1000)\n"
    )
    import_ms = 0.0
    for _ in range(3):
        import_ms += float(subprocess.run(
            [sys.executable, "-c", import_inline, str(root)],
            capture_output=True, check=True).stdout)
    out: dict = {"browser_cdp_import_ms": round(import_ms / 3, 1)}

    module = load_module(root, "capability_sources/browser_cdp.py", "bench_bcdp")

    if with_browser:
        module.execute({"action": "launch", "url": "https://example.com"})
        time.sleep(1.5)
        start = time.perf_counter()
        module.execute({"action": "status"})
        out["browser_cdp_warm_status_ms"] = round((time.perf_counter() - start) * 1000, 1)

        start = time.perf_counter()
        module.execute({"action": "evaluate", "expression": "document.title"})
        out["browser_cdp_warm_evaluate_ms"] = round((time.perf_counter() - start) * 1000, 1)

        start = time.perf_counter()
        module.execute({"action": "batch", "steps": [
            {"action": "status"}, {"action": "evaluate", "expression": "location.href"},
        ]})
        out["browser_cdp_warm_batch2_ms"] = round((time.perf_counter() - start) * 1000, 1)

        import tempfile
        for fmt in ("jpeg", "png"):
            target = Path(tempfile.gettempdir()) / f"bench-{fmt}.{fmt if fmt == 'png' else 'jpg'}"
            result = module.execute({"action": "screenshot", "format": fmt, "path": str(target)})
            out[f"screenshot_{fmt}_bytes"] = int(result.get("bytes", 0))
    return out


def bench_uia(root: Path) -> dict:
    bridge = root / "windows" / "UIAutomationBridge.py"
    out: dict = {}
    if not bridge.is_file():
        out["uia_error"] = f"missing {bridge}"
        return out

    # One-shot subprocess (JSON on stdin) is how UIA ran in BOTH old and new
    # code paths; it is the apples-to-apples per-call cost.
    request = json.dumps({"action": "list_windows", "limit": 40})
    samples = []
    for _ in range(2):
        start = time.perf_counter()
        subprocess.run([sys.executable, str(bridge)], input=request, text=True,
                       capture_output=True, check=True, timeout=120)
        samples.append(time.perf_counter() - start)
    out["uia_one_shot_list_windows_ms"] = round(statistics.median(samples) * 1000, 1)

    # In-process warm measurements only exist where the bridge is importable
    # (v1.1.35). The old bridge self-executed on import and could not stay warm.
    try:
        module = load_module(root, "windows/UIAutomationBridge.py", "bench_uia")
    except (SystemExit, Exception) as error:  # noqa: BLE001
        out["uia_warm"] = "n/a (bridge not importable in-process; one-shot only)"
        return out

    start = time.perf_counter()
    first = module.main({"action": "list_windows", "limit": 40})
    out["uia_first_list_windows_ms"] = round((time.perf_counter() - start) * 1000, 1)

    start = time.perf_counter()
    module.main({"action": "list_windows", "limit": 40})
    out["uia_cached_list_windows_ms"] = round((time.perf_counter() - start) * 1000, 1)

    windows = first.get("windows") or []
    if windows:
        handle = windows[0]["handle"]
        start = time.perf_counter()
        module.main({"action": "observe", "selector": {"handle": handle}, "limit": 100})
        out["uia_observe_by_handle_ms"] = round((time.perf_counter() - start) * 1000, 1)

        start = time.perf_counter()
        module.main({"action": "batch", "selector": {"handle": handle}, "steps": [
            {"action": "observe", "limit": 20},
            {"action": "find_element"},
            {"action": "list_windows", "limit": 20},
        ]})
        out["uia_batch3_cached_ms"] = round((time.perf_counter() - start) * 1000, 1)
    return out


def main() -> int:
    root = resolve_root()
    with_browser = "--with-browser" in sys.argv
    version = read_version(root)
    print(f"=== MyComp Bot benchmark  v{version}  @ {root} ===")
    if "--with-browser" in sys.argv:
        print("(browser mode: will launch the dedicated Chrome worker)")

    results: dict = {"version": version, "root": str(root), "python": sys.executable,
                     "with_browser": with_browser, "measured_at": time.time()}
    results.update(bench_shell())
    results.update(bench_browser_cdp(root, with_browser))
    results.update(bench_uia(root))

    labels = [
        ("shell_spawn_ms", "shell spawn (python -c pass)", "ms"),
        ("browser_cdp_import_ms", "browser_cdp import (fresh interpreter)", "ms"),
        ("browser_cdp_warm_status_ms", "browser_cdp warm status", "ms"),
        ("browser_cdp_warm_evaluate_ms", "browser_cdp warm evaluate", "ms"),
        ("browser_cdp_warm_batch2_ms", "browser_cdp warm batch x2", "ms"),
        ("screenshot_jpeg_bytes", "screenshot JPEG bytes", "B"),
        ("screenshot_png_bytes", "screenshot PNG bytes", "B"),
        ("uia_one_shot_list_windows_ms", "uia one-shot list_windows (per call)", "ms"),
        ("uia_warm", "uia warm mode", ""),
        ("uia_first_list_windows_ms", "uia first list_windows (in-process)", "ms"),
        ("uia_cached_list_windows_ms", "uia cached list_windows", "ms"),
        ("uia_observe_by_handle_ms", "uia observe by handle", "ms"),
        ("uia_batch3_cached_ms", "uia batch x3 (cached)", "ms"),
    ]
    for key, label, unit in labels:
        value = results.get(key)
        if value is not None:
            print(f"  {label:<42s} {value:>9} {unit}")
    if results.get("uia_error"):
        print(f"  uia_error: {results['uia_error']}")

    history = []
    if RESULTS.is_file():
        try:
            history = json.loads(RESULTS.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            history = []
    if not isinstance(history, list):
        history = []
    history.append(results)
    RESULTS.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved to {RESULTS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
