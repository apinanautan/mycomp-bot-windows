## Version 1.1.42 — Direct read-only UIA without GUI queue stalls

- Read-only Accessibility inspection (observe, observe_summary, observe_changes, inspect_elements, find_element, wait_until) uses the installed pywinauto UI Automation bridge directly when a window handle is explicitly selected or a Win32 title lookup is unique. This avoids blocking on the MyComp Bot GUI's Tk event loop and skips desktop-wide scans for known handles.
- Ambiguous window names and UIA-only selector attributes still use the original owner-supervised route. Every mutating action (click, focus, set_value, window state, input) remains on the original route and retains the exact permission policy; the owner's stop switch also prevents direct read-only inspection.
- Regression tests cover unique matching, ambiguous-name fallback, and owner stop behavior. The full Windows suite passed 190 total (173 pass, 17 POSIX-only skips, zero failures/errors).
- A local, isolated handle-specific UIA observe completed in 40.9 ms; source read-only capability with a uniquely matched window completed in 372.8 ms including import time. These are not ChatGPT round-trip timings; post-install live verification is required.

## Version 1.1.41 — Fast, owner-safe Windows window discovery

- Windows list_windows now uses a live Win32 top-level window enumeration when only names, handles, PIDs and bounds are needed. It does not block on the desktop application's Tk event loop or a slow UI Automation desktop scan.
- UIA-specific filters (automation_id, control_type) and detail=True still use the existing owner-supervised Windows UI Automation bridge. All clicks and changes retain the existing permission checks. The owner's stop flag remains effective for the native read path.
- status returns a lightweight Win32 capability status without relying on the desktop UI polling loop.
- Added 4 regression tests for native snapshot accuracy, handle selection, owner stop and unchanged UIA/GUI action routing.
- Included the bounded one-call project diagnostic scripts/fast-check.ps1, with its separate smoke test and measured latency notes. This does not change the configured Tunnel ID, OAuth state, secrets or filesystem allowances.

**Measured** before optimization on the loaded Windows host: a one-shot pywinauto/UIA list_windows took 28.5 seconds; an isolated native Win32 enumeration took 4.5 ms. These measurements omit the cost of the ChatGPT tool round trip. The native code path must still be measured end-to-end after deployment. Chrome dom_cdp.steps independently passed a 3-read batch through the existing Dino Tunnel. A separately named batch_execute tool may still need connector-tool schema refresh to appear in ChatGPT; local source code cannot force the App-backed tool catalog to update.

## 2026-11-13 performance experiment — one-call read-only preflight (unreleased)

**Measured on DESKTOP-F1PJT4S through ChatGPT → Dino Tunnel, identical 16 safe file-existence checks:**

| Method | Wall clock | Successful checks | Workload speedup |
| --- | ---: | ---: | ---: |
| 16 separate Shell tool calls | 38.506 s | 16/16 | baseline |
| One compound Shell call, median of 3 | 2.480 s | 16/16 | **15.5x** |
| New scripts/fast-check.ps1, median of 3 | 3.590 s | 16/16 | **10.7x** |

These are *observed tool wall-clock times*, not total model thinking time or guarantees for every task. The new read-only PowerShell script performs 16 source integrity checks and returns source version, missing count and Git cleanliness as compact JSON. Use -WithRuntime to include active MyComp versions and loopback Engine health. It never reads OAuth, API keys or other secret values.

**Use the platform's supported batching before adding dependencies.** On the MCP side prefer batch_read (20 individually allowed-root checks), batch_execute (12 independently permission-checked actions) and existing DOM/UIA multi-step calls *where those tools are actually exposed*. If using the existing authorized Shell interface to group trusted read-only checks, the Shell's policy applies to the invocation; it is not a substitute for per-step permission checks for writes. Keep GUI mutations ordered, and verify post-state after errors.

GitHub research: the [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) recommends stateless Streamable HTTP with JSON responses, which MyComp Bot already uses. [Microsoft UI Automation caching](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-cachingforclients) explains why bulk property access helps; [pywinauto](https://github.com/pywinauto/pywinauto) already powers the current bridge. [Playwright CDP attach](https://playwright.dev/python/docs/api/class-browsertype) could be evaluated separately, but it has fidelity trade-offs and is **not** installed by this experiment. The [uv project](https://github.com/astral-sh/uv) speeds up installing Python dependencies, not ChatGPT tool round trips; do not add it for runtime latency.

## Version 1.1.40 — Correct and observable Batch execution

- `batch_execute` treats Accessibility `wait_until` as a read-only operation, matching the standalone tool permission. Every other batch step retains its independent permission check.
- An Accessibility bridge result with `ok: false` now fails the corresponding `batch_execute` step instead of reporting a false success.
- Accessibility multi-step calls report `partial` or `failed` when nested bridge actions fail; warnings preserve the failed step count.
- Potentially mutating Accessibility or Chrome/CDP batch steps conservatively mark `changed=true` even if an action fails after dispatch, preventing unsafe blind retries.
- Regression tests cover these boundaries. Existing OAuth, Tunnel ID, permitted roots, executable policy and versioned install directories remain unchanged.

## Version 1.1.39 — Cold scan moved off the first call, observe cached

Diagnosis first: the "first window scan is slow" cost was **not** enumeration of properties (12 ms) and **not** this repo's code. In a fresh process, `Desktop(backend="uia").windows()` costs **1737 ms** once while the UIA COM layer and pywinauto's tree cache initialise; every later call is ~2 ms. That one-time cost landed on whichever tool call happened to be first, so it read as a per-call regression and scaled with machine load (1.7 s idle, 6.6 s loaded).

- `UIAutomationBridge.warm()` primes the UIA layer on a background thread, and the desktop app calls it from `WindowsAutomation.preload()` during startup (`MycompBot.__init__`). The 1.7 s is now paid while the app boots instead of by the first MCP call.
- `observe` / `inspect_elements` results are reused for 1 s (keyed by selector, limit and depth). Walking a heavy window such as the taskbar is the dominant cost inside a batch; the second observe of the same window is now free. `detail=True` always reads live values, and `reset_cache()` clears it.
- New `tests/test_uia_bridge_cache.py` covers warm-up, list_windows cache identity plus `refresh` bypass, observe cache plus `detail` bypass, and per-step batch results.

Interleaved A/B against v1.1.38 (same machine, alternating order, 5 trials each):

| metric | 1.1.38 | 1.1.39 | change |
|---|---|---|---|
| first `list_windows` | 2393 ms | 115 ms | **−95%** |
| batch of 4 steps | 499 ms | 287 ms | **−42%** |
| repeating `observe` inside batch | 265 ms | **0 ms** | cached |

Full suite: 180 tests OK, 17 skipped.

## Version 1.1.38 — wait_until and batch now actually reachable end-to-end

v1.1.36 added `wait_until` to the UIA bridge, the MCP tool enum, the `windows_ui` capability and the manifest — but not to the desktop app's action router. `MyCompBot._execute_ui` only forwards a hard-coded set of actions to the bridge, so every `wait_until` and `batch` call that arrived over MCP fell through to `unsupported Windows desktop action`. The feature was documented and tested in isolation but unreachable from ChatGPT.

- `windows/MyCompBot.py`: `wait_until` and `batch` are now in the `uia_actions` routing set, so the desktop app forwards them to the pywinauto bridge like the other UIA actions.
- `windows/UIAutomationBridge.py`: `list_windows` reuses element records for 1 s. Previously every call re-read name, bounds, automation id, control type and process id across the UIA boundary for every window, which both dominated the cost and made timings swing between ~13 ms and ~55 ms. `refresh=True` still forces a full re-enumeration (and a `detail=True` call still reads live values).
- Added `test_bridge_actions_are_routed_to_uia_automation` so any future action implemented in the bridge but missing from the router fails the suite instead of silently breaking at runtime.

Measured on this machine (15 windows open): `list_windows` cached call 0.04 ms, after the 1 s TTL 14.8 ms, forced `refresh=True` 1.6 s. `_execute_ui` → bridge: `wait_until` match 2 ms, timeout raises `TimeoutError`, 3-step `batch` 90 ms.

Note: the earlier UIA "16.6 ms → 50.5 ms slower" reading was measurement noise — both versions ran byte-identical bridge code and single samples vary 13–55 ms. The real defect was the per-window property re-read, now cached.

## Version 1.1.37 — Green test suite on Windows

The full suite now passes on Windows: **175 tests OK, 17 intentional POSIX-only skips** (previously 20 failures + 31 errors). No behaviour change beyond one schema fix.

- **Schema fix**: `accessibility.action` had become `Optional`, which dropped the action `enum` from the published MCP tool schema. It is now `AccessibilityAction = "status"`, so the enum (including `wait_until`) is advertised again.
- **POSIX-only tests are now skipped on Windows** instead of failing: `ShellLifecycleTests` relies on `os.fork()`, `SIGTERM`/`SIGKILL`, `killpg` and `/bin/*` fixtures that do not exist on Windows. Windows process-tree cleanup is covered by `test_windows_fast_shell_cleanup`.
- **Liveness probe accepts Windows errors**: the capability-timeout test now treats any `OSError` (including `WinError 87`) as "process is gone", matching `taskkill /T /F` semantics.
- **Tests updated for the async `@threaded` tool wrapper**: three engine tests called tool functions positionally and synchronously; they now pass keyword arguments and `asyncio.run(...)`.
- **Stale tunnel-prompt tests rewritten**: `plugin_prompt` was intentionally redesigned in v1.1.23 to never inline the saved tunnel ID or key (the recipient GPT may be on another Platform account), but the tests still asserted the old behaviour. They now assert the current contract: no tunnel ID or secret in the prompt, the local MCP upstream is used rather than the caller's Tailscale base, and name/computer-name validation only.

Note for contributors: the venv's `site-packages` copy of `mycomp_bot_engine` can lag the working tree (it is not installed editable). Run the suite with `PYTHONPATH=src` so tests import the source under change.

## Version 1.1.36 — wait_until and a before/after benchmark

- `accessibility` gains a `wait_until` action: poll a selector (handle, name, name_contains, automation_id or control_type) until the window/element appears, optionally waiting for a descendant `text`, all inside ONE call. It reuses the warm window-map cache (existing matches resolve in ~1 ms) and re-scans the desktop once per second so genuinely new windows are noticed. A `TimeoutError` is raised on expiry so the caller knows nothing appeared. This collapses what used to be several `list_windows` round trips into one call.
- `scripts/benchmark.py` measures the exact levers v1.1.35/1.1.36 change (shell spawn, browser_cdp import/warm/batch/screenshot bytes, UIA one-shot/cached/observe/batch) and appends to `scripts/benchmark-results.json` so a before/after pair can be diffed. Run it with the version's own Python (`<root>/.venv/Scripts/python.exe scripts/benchmark.py --root <root>`); `--with-browser` adds evaluate/screenshot numbers.

## Version 1.1.35 — Warm capability workers, one-call batches, compact screenshots

Speed changes that keep the eight-tool surface and the deny-by-default policy:

- Capability workers: each maintained capability (browser_cdp, windows_ui) now runs in one warm, isolated subprocess that survives between calls instead of spawning a fresh interpreter per call. Import, OCR model load and the DevTools WebSocket handshake are paid once. Workers idle out after 15 minutes, cap at four, and a dead worker falls back to the old one-shot path automatically. Disable with `MYCOMP_CAPABILITY_WORKERS=0`.
- Handle-first UI Automation: passing a `handle` skips the whole virtual-desktop scan; the window map and resolved elements are cached briefly. Measured on this machine: cached `list_windows` 16 ms vs 1.66 s cold, a 3-step `batch` costs one scan total instead of three.
- One-call batches: `accessibility` and `dom_cdp` accept `steps` (up to 40 / 100 actions) executed inside one warm round trip, and `batch_execute` now accepts `accessibility`, `dom_cdp` and `vision` step kinds in addition to shell/filesystem. Each step still checks its own permission level.
- Compact screenshots: `vision` captures default to JPEG quality 80 with optional `scale`, and `dom_cdp` screenshots follow the same defaults; OCR captures stay PNG internally. Smaller payloads leave more room in the model context. OCR accepts a `window` selector so it scans one window instead of the full display.
- Shell auto-wait default dropped from 5 s to 1.5 s (`MYCOMP_SHELL_AUTO_WAIT_SECONDS` still overrides).
- The Windows app runs the UIA bridge in-process (pywinauto) when available and keeps the PowerShell helper as fallback (`MYCOMP_UIA_BACKEND=powershell` to force it).
- Ready-made macros in `scripts/win` (windows, click, read, wait_window, type, ocr, shot, cdp) let one Shell call do what used to take several tool round trips.

## Version 1.1.33 — Faster Windows Shell cleanup

Avoids taskkill for successfully completed short Shell commands. Preserves cleanup for timeouts and pipe-holding descendants. Includes Batch Execution from v1.1.32.

## Version 1.1.32 — Permission-checked Batch Execution

Adds batch_execute for 1–12 sequential Shell or filesystem steps per MCP call. Each step independently checks the existing permission policy, executable restrictions and allowed filesystem roots. Per-step results and optional stop-on-error are supported. This reduces ChatGPT tool round trips without changing OAuth, Tunnel IDs or existing tools.

## Version 1.1.31 — Automatic Tailscale MCP URL and quick-copy setup controls

MyComp Bot now discovers the current Windows host's MagicDNS URL from the
Tailscale CLI when the app opens, checks the existing Funnel mappings, and
shows the actual MCP URL directly in the GUI. If root HTTPS belongs to a
different application, MyComp uses its own /mycomp route when available.
The app never overwrites a different service's existing Funnel route.
A generated URL stays *unverified* until the public health check succeeds.
New installs configure /mycomp automatically and copy the MCP endpoint.

The main window now remembers a user-supplied plugin base name across launches
and offers one-click copy for "<name> Tailscale", "<name> Tunnel", the
saved Tunnel ID, and main Channel name. Channel ID is distinct from Tunnel ID
and Channel name "main"; the Channel ID button reports that it is not
available when the client has not provided one, instead of inventing an ID.
These buttons work without opening the AI setup prompt.

The full setup prompt remains available for AI-assisted Skills checks,
remaining plugin tasks and system validation, and it starts with the stored
name. API keys and OAuth secrets are never copied by these controls.
Desktop shortcut repair and safe Save and connect behavior from v1.1.30
are preserved.

## Version 1.1.30 — Desktop shortcut and Tunnel connect workflow

MyComp Bot's Windows installer now creates an actual "MyComp Bot.lnk"
Desktop shortcut using the installed pythonw.exe, the application script,
and its bundled MyComp icon. The app also repairs missing shortcuts on
startup, including redirected OneDrive Desktop paths. It is idempotent
and will not overwrite an unrelated shortcut with the same name.

The "Save and connect" Tunnel button now truly enables and starts the
saved local Tunnel client even when the reconnect checkbox was initially
unchecked. "Save named ID/key" remains the separate save-without-activation
option. The GUI explains that creating/installing the plugin in ChatGPT
is a separate account/workspace action and that successful local Tunnel
readiness does not itself install a ChatGPT plugin.

Existing Tunnel ID, encrypted API key, OAuth channel and user settings
remain intact across in-app updates. No new Tunnel or Key is generated
automatically. The updater uses the Windows DesktopDirectory known
folder to support redirected Desktop paths.

## Version 1.1.29 — automatic OAuth discovery over OpenAI Secure MCP Tunnel

MyComp Bot now automatically configures OpenAI tunnel-client's independent
OAuth discovery trusted-origin and OAuth forwarding-origin allowlists on
startup from the application's existing configured HTTPS public URL.
It also enables loopback HTTP Harpoon discovery only when the MCP backend
is explicitly bound to loopback. No manual PowerShell patch, advanced OAuth
URL entry, new Tunnel ID, channel, or API key is needed for this configuration.

The selected tunnel-client must support these settings (v0.0.20 or later
for OAuth forwarding to a distinct HTTPS origin). The existing ChatGPT
workspace must still authorize the Tunnel plugin and OAuth consent. Windows
client readiness is not proof of ChatGPT authenticated tools/list success.

Install by using the existing in-app Update MyComp Bot button and
confirming the update. The updater preserves per-user MyComp Bot settings.
The app will restart with the new launch configuration; OAuth should be
retested through the same previously selected Tunnel ID.

## Version 1.1.28 — Windows Capability Winsock hotfix

Fixed the sanitized Python subprocess environment used by MyComp Bot
capabilities. Windows needs SystemRoot and selected Windows OS paths to
initialize socket providers; previously these were absent and Chrome CDP
could fail with WinError 10106 even when Chrome and Tailscale were healthy.

The fix preserves the minimal environment allowlist and does not forward
API keys or OAuth tokens to capability subprocesses. Tests cover real
socket initialization inside that sandbox-like runner and secret exclusion.

This code fix does not change ChatGPT workspace Custom MCP entitlements.
A private Plugin Creator package update is distinct from installing or
enabling that plugin in ChatGPT's active workspace.

## Operator clarity and channel verification

The operator-clarity skill is bundled with MyComp Bot. It requires exact machine
identity, prevents modifications to unrelated Studio/Orchestrator plugins, and
continues independent setup tasks even when the ChatGPT account/workspace
denies custom MCP attachment. Existing Tunnel ID, DPAPI API key and main
channel are retained when available. Health checks are not proof of
authenticated ChatGPT tools/list. A working Tailscale fallback is not
misreported as a working Tunnel plugin. No skill can unlock account
entitlements; verify availability from the specific workspace and error.

## Version 1.1.26 — Tunnel-first setup and visible browser workspace

The MyComp Bot setup prompt first checks the existing saved Secure MCP Tunnel ID,
DPAPI-encrypted key, profiles, and main channel. It reuses working configuration,
repairs only failed portions, and never regenerates credentials simply because they
already exist. It verifies actual authenticated ChatGPT MCP access before proceeding.

The setup prompt uses the name entered in MyComp Bot consistently for
<name> Tailscale and <name> Tunnel, and forbids edits to unrelated
Orchestrator, Studio, or other apps. An existing Tailscale plugin is renamed
only if the owner has the rights and the platform supports editing its name.

Chrome CDP opens a visible, separate-profile worker window in the right half
of the primary screen, preserves the existing ChatGPT window on the left,
and reuses the worker tab for sequential tasks. The prompt no longer opens
another ChatGPT tab when copied.

# MyComp Bot for Windows

MyComp Bot คือ MCP server ที่รันบนเครื่อง Windows ของเรา เพื่อให้ ChatGPT เรียกใช้เครื่องนั้นผ่าน connector ได้ โดยตัวโปรแกรมรันในเครื่องและเก็บค่าไว้ในบัญชี Windows ปัจจุบัน การเชื่อมต่อใช้ HTTPS ของ Tailscale Funnel

คู่มือนี้ตั้งใจให้เปิดแล้วทำงานต่อได้ แม้เป็นเครื่องใหม่หรือเปิดแชต Codex/ChatGPT หน้าต่างใหม่

### ตรวจและซ่อมการเชื่อมต่ออัตโนมัติ

AutoFix ตรวจ Funnel ทุก 60 วินาทีผ่าน IP สาธารณะจริง หน้าต่างจะแสดงสถานะ **Public connection** แยกจาก Local service และมีปุ่ม **Repair Tailscale now** หากซ่อม route แล้วยังเชื่อมต่อไม่ได้ โปรแกรมจะลองรีเฟรช transport ด้วย `tailscale debug rebind` ไม่เกินหนึ่งครั้งต่อ 5 นาที โดยไม่ reset mapping ของแอพอื่น คำสั่ง debug นี้อาจเปลี่ยนใน Tailscale รุ่นถัดไป; ถ้าคำสั่งไม่รองรับหรือยังล้ม โปรแกรมจะแสดง FAILED และเก็บรายละเอียดที่ `%LOCALAPPDATA%\MyComp Bot\tailscale-autofix.log` แทนการรายงานว่าซ่อมสำเร็จ

> อย่าใส่ token, OAuth callback, owner consent code, log ทั้งก้อน หรือชื่อเครื่องจริงลงใน GitHub Issue สาธารณะ

## ลิงก์สำคัญ

- [ดาวน์โหลดตัวติดตั้งล่าสุด](https://github.com/apinanautan/mycomp-bot-windows/releases/latest/download/Install-MyComp-Bot.bat)
- [หน้า Releases](https://github.com/apinanautan/mycomp-bot-windows/releases)
- [Source code](https://github.com/apinanautan/mycomp-bot-windows)
- [แจ้งปัญหา](https://github.com/apinanautan/mycomp-bot-windows/issues)

ไม่จำเป็นต้องติดตั้ง Git บนเครื่องที่จะใช้งาน ตัวติดตั้ง `.bat` จะดาวน์โหลด source ที่ต้องใช้เองจาก GitHub

## ใช้งานแบบเร็วบนเครื่อง Windows ใหม่

สิ่งที่ต้องมี:

1. Windows ที่เข้าอินเทอร์เน็ตได้
2. [Tailscale](https://tailscale.com/download/windows) ติดตั้งและ Sign in แล้ว
3. tailnet ที่อนุญาตให้ใช้ **Tailscale Funnel** บน HTTPS port 443
4. สิทธิ์เปิดไฟล์ `.bat` ในบัญชี Windows ปัจจุบัน

ขั้นตอน:

1. ดาวน์โหลด `Install-MyComp-Bot.bat` จากหน้า **Releases** ไม่ใช่หน้าดู source code ของ GitHub
2. ดับเบิลคลิกไฟล์ `.bat` และรอจนติดตั้งเสร็จ
3. ถ้า Windows ถามเรื่อง Python ตัวติดตั้งจะพยายามติดตั้ง Python 3.11 ผ่าน `winget` ให้เอง
4. เมื่อสำเร็จ ตัวติดตั้งจะแสดงและคัดลอก MCP URL ลักษณะนี้:

   ```text
   https://ชื่อเครื่อง.tailnet.ts.net/mcp
   ```

5. หน้าต่าง MyComp Bot จะเปิดขึ้น ให้ตรวจว่า Local service เป็น `Running` และ Funnel ทำงานอยู่
6. ทำ OAuth ใน ChatGPT ตามหัวข้อถัดไป

ไฟล์ที่ลงไว้ในเครื่องอยู่ที่:

```text
%LOCALAPPDATA%\MyComp Bot Source
%LOCALAPPDATA%\MyComp Bot
```

## เชื่อมกับ ChatGPT ผ่าน OAuth

ใน ChatGPT ให้สร้างหรือเปิด connector ของ MyComp Bot แล้วใส่ MCP endpoint ที่คัดลอกมา ซึ่งต้องจบด้วย `/mcp`

ตัวอย่าง:

```text
https://ชื่อเครื่อง.tailnet.ts.net/mcp
```

จากหน้าตั้งค่า OAuth ของ connector ให้กด **Copy Callback URL** แล้วกลับมาที่ MyComp Bot:

1. ลบข้อความเดิมในช่อง **Your ChatGPT callback URI** ทั้งหมด
2. วาง callback ที่คัดลอกมา **เพียง 1 URL**
3. ห้ามมี comma (`,`) ช่องว่าง URL เก่า หรือ callback สองอันต่อกัน
4. กด **Save & Restart**
5. กลับไปที่ ChatGPT แล้วเชื่อมต่อ/Approve ใหม่

หน้าตั้งค่า connector ควรใช้ OAuth endpoint ที่ MyComp Bot ประกาศจาก MCP server ไม่ต้องนำ token หรือ client secret ของตัวเองไปใส่ เว้นแต่หน้าของ ChatGPT ระบุให้ทำเช่นนั้นโดยชัดเจน

## การใช้งานประจำวัน

หลังติดตั้งครั้งแรก ให้เปิด MyComp Bot จาก Start menu หรือไฟล์นี้:

```text
%LOCALAPPDATA%\MyComp Bot Source\Start MyComp Bot (Tray).bat
```

เมื่อปิดหน้าต่างหลัก โปรแกรมจะซ่อนอยู่ที่ system tray ด้านขวาล่างของ Windows:

- คลิกไอคอนเพื่อเปิดหน้าต่างอีกครั้ง
- คลิกขวาแล้วเลือก **Open MyComp Bot**, **Report Error on GitHub** หรือ **Exit**
- ติ๊ก **Start MyComp Bot automatically when I sign in to Windows** ถ้าต้องการให้เปิดเองทุกครั้งที่ sign in
- ติ๊ก **Start Remote Desktop Commander automatically with MyComp Bot** เพื่อให้ MyComp เรียก `npx -y @wonderwhy-er/desktop-commander@latest remote` เมื่อเปิดขึ้นมา และใช้ **Start Remote Desktop Commander now** เพื่อเริ่มทันที

MyComp Bot ใช้ Windows single-instance lock หากโปรแกรมเปิดอยู่แล้ว การกดเปิดซ้ำจะไม่สร้าง process/tray icon ชุดใหม่ แต่ส่งสัญญาณให้หน้าต่างเดิมแสดงขึ้นมาแทน หลังอัปเดตจากรุ่นเก่าที่เปิดซ้ำอยู่ ให้ Exit ไอคอนเก่าทั้งหมดหนึ่งครั้งแล้วเปิดรุ่นใหม่

การติ๊ก autostart จะสร้างค่า startup เฉพาะผู้ใช้ Windows ปัจจุบัน ไม่ได้ตั้งเป็น Windows service และไม่ต้องใช้สิทธิ์ Administrator
Remote Desktop Commander ใช้ค่า autostart แยกต่างหาก โดย MyComp จะตรวจ process เดิมก่อนเริ่มเพื่อป้องกันการเปิดซ้ำ และเขียน output ไว้ที่ `%LOCALAPPDATA%\MyComp Bot\remote-desktop-commander.log`.

### อัปเดตจากในโปรแกรม

ตั้งแต่ v1.1.43 โปรแกรมแบบ managed จะเช็ก GitHub Release ล่าสุดทุกครั้งที่เปิดโปรแกรม และเมื่อมีรุ่น Stable ใหม่จะดาวน์โหลด ติดตั้งแยกโฟลเดอร์ และรีสตาร์ตเฉพาะ MyComp Bot อัตโนมัติโดยไม่ถามซ้ำ ถ้าเช็กไม่สำเร็จจะใช้รุ่นเดิมต่อโดยไม่หยุดงาน ไม่เขียนทับโค้ด Git นักพัฒนา ผู้ใช้รุ่นเก่าต้องกด Update หนึ่งครั้งเพื่อรับระบบใหม่

กด **Update MyComp Bot** ในหน้าต่างหรือเมนู tray โปรแกรมจะตรวจ GitHub Release ล่าสุด ถ้ามีรุ่นใหม่ให้ยืนยันเพื่อติดตั้ง จากนั้นโปรแกรมจะปิดและเปิดกลับเอง ไม่ต้องดาวน์โหลดตัวติดตั้งใหม่ทุกครั้ง ค่า OAuth, Allowed folders, permission profile และ Tailscale ที่เก็บไว้ในเครื่องยังใช้ต่อได้

การอัปเดตต้องใช้อินเทอร์เน็ตเพื่อดาวน์โหลดซอร์สโค้ดและติดตั้ง dependencies หากเกิดข้อผิดพลาดจะบันทึกไว้ที่ `%LOCALAPPDATA%\MyComp Bot\update.log` การอัปเดตจากโฟลเดอร์ Git (แม้มีไฟล์แก้ไขค้างอยู่) จะติดตั้งสำเนาแอปแยกรุ่นไว้ใน `%LOCALAPPDATA%` โดยไม่เขียนทับไฟล์พัฒนา หากเวอร์ชันในโฟลเดอร์ Git ตรงกับ Release ล่าสุดก็สามารถกด Update เพื่อเปลี่ยนไปใช้สำเนาแอปได้

รุ่นก่อน 1.1.4 ยังไม่มีปุ่มนี้ ต้องติดตั้งรุ่น 1.1.4 ครั้งเดียวก่อน แล้วรุ่นถัดไปกดอัปเดตจากโปรแกรมได้

### สิทธิ์ที่ควรรู้

MyComp Bot จำกัดการทำงานด้วย Allowed folders, permission profile และ executable allowlist อย่าเพิ่มโฟลเดอร์หรือโปรแกรมโดยไม่จำเป็น หากต้องอนุญาต shell ค่าเริ่มต้นรองรับ `cmd.exe` และ `powershell.exe`; ถ้าเรียก shell ไม่ได้ ให้ตรวจค่าพวกนี้ในหน้าต่างโปรแกรมก่อน

## เลือกวิธีเชื่อมต่อ

เลือกใช้เพียงหนึ่งวิธีในแต่ละครั้ง:

| วิธี | ใช้เมื่อ | URL คงที่ไหม | หมายเหตุ |
| --- | --- | --- | --- |
| **Tailscale Funnel** | ติดตั้งผ่าน release `.bat` และใช้งานจริง | คงที่ตราบเท่าที่ชื่อ MagicDNS เดิม | วิธีมาตรฐานของโปรเจกต์นี้ |
| **Cloudflare Quick Tunnel** | ทดสอบชั่วคราวจากปุ่ม Start Free Temporary Tunnel | ไม่คงที่ | ต้องติดตั้ง `cloudflared` เอง และ URL เปลี่ยนเมื่อเริ่มใหม่ |

หากติดตั้งผ่าน release แล้ว ไม่ต้องกด Start Free Temporary Tunnel เพื่อให้ Tailscale ทำงานอยู่แล้ว การเปลี่ยนไป Quick Tunnel ทำให้ต้องแก้ endpoint และ OAuth callback ใหม่ตาม URL ชั่วคราวนั้น

## อาการเสียที่พบบ่อย

| อาการ | สาเหตุที่เป็นไปได้ | วิธีตรวจ/แก้ |
| --- | --- | --- |
| `503: OAuth token request failed, try again later` | callback ผิด, ซ้ำ, หรือ OAuth endpoint ติดต่อไม่ได้ | คัดลอก callback ใหม่จาก ChatGPT แล้ววางเพียง URL เดียว จากนั้น Save & Restart และ Connect ใหม่ |
| `Cannot connect to host ...:443 ssl:default` | เครื่อง offline, Tailscale ไม่ได้ Sign in, Funnel ไม่ทำงาน หรือ DNS/เครือข่ายไปไม่ถึง | เปิด Tailscale ให้สถานะ Connected, ตรวจ Local service และ Funnel ใน MyComp Bot แล้วลองเชื่อมใหม่ |
| กด Approve แล้วไม่กลับ ChatGPT | callback URI ไม่ตรงกับ connector หรือ flow เก่าหมดอายุ | ปิดหน้า authorize เก่า เริ่ม Connect ใหม่จาก ChatGPT และใช้ callback URL ปัจจุบันเพียงหนึ่งค่า |
| `You cannot call a method on a null-valued expression` ใน installer | installer รุ่นเก่ามีปัญหากับไฟล์ `.env` ว่างใน Windows PowerShell 5 | ดาวน์โหลด installer รุ่นล่าสุดจาก Releases แล้วรันใหม่ |
| บอกว่า `pystray` หรือ `Pillow` ไม่มี | dependency ติดตั้งไม่ครบหรือใช้ release เก่า | ใช้ installer ล่าสุด; ถ้ายังเกิด ให้ดู `host-error.log` และ `host-output.log` |
| `local health check did not become ready` | เป็นข้อความสรุป ไม่ใช่สาเหตุสุดท้าย | เปิด log ของ host ด้านล่างเพื่ออ่าน Python traceback จริง แล้วใช้ข้อความนั้นในการแก้ |
| BAT บอก error กว้าง ๆ | การดาวน์โหลดหรือ PowerShell installer ล้มเหลว | อ่าน error ที่หน้าต่าง, Notepad ที่เปิดขึ้น, และ `install-error.log`; BAT รุ่นล่าสุดจะไม่ซ่อน error จริง |
| เครื่องอื่นไม่มี Git | ไม่ใช่ปัญหา | ใช้ `.bat` จาก Releases ได้เลย Git ไม่ใช่ dependency |
| มี tray icon MyComp Bot สองอัน | โปรแกรมรุ่นเก่าถูกเปิดมากกว่าหนึ่งครั้ง | Exit ทั้งสองอันแล้วเปิดรุ่นล่าสุดหนึ่งครั้ง; รุ่นใหม่มี single-instance lock |
| กด Exit แล้วไอคอน/process ไม่หาย | โปรแกรมรุ่นเก่าไม่ได้หยุด `pystray` loop | ใช้รุ่นล่าสุด; Exit จะหยุด tray icon, tunnels, engine และ Tk main loop ครบ |

## Log และการรายงานปัญหา

เมื่อ install หรือเริ่มโปรแกรมไม่สำเร็จ ให้ดูไฟล์เหล่านี้ก่อน:

```text
%LOCALAPPDATA%\MyComp Bot\install-error.log
%LOCALAPPDATA%\MyComp Bot\host-error.log
%LOCALAPPDATA%\MyComp Bot\host-output.log
```

ตัวติดตั้งจะแสดง error จริงในหน้าต่าง, คัดลอกข้อความไว้ใน clipboard และเปิด log ด้วย Notepad เมื่อทำได้ นอกจากนี้อาจเปิดหน้า GitHub Issue แบบร่างให้ แต่ **จะไม่ส่ง log ขึ้น GitHub อัตโนมัติ**: ผู้ใช้ต้องตรวจข้อมูลลับแล้วกด Submit เอง

ก่อนส่ง issue ให้ลบข้อมูลเหล่านี้ออก:

- OAuth callback URL, authorization code, token, secret, owner consent code
- ชื่อเครื่อง, URL ส่วนตัว, ที่อยู่ไฟล์ที่เปิดเผยข้อมูลส่วนบุคคล
- เนื้อหาจาก screenshot/log ที่ไม่เกี่ยวกับ error

## กู้คืนหลังลง Windows ใหม่หรือเผลอลบโปรแกรม

1. ติดตั้งและ Sign in Tailscale บนเครื่องนั้นก่อน
2. ดาวน์โหลด `.bat` ล่าสุดจาก [Releases](https://github.com/apinanautan/mycomp-bot-windows/releases)
3. รัน installer แล้วรอ MCP URL ใหม่/ปัจจุบัน
4. เปิด MyComp Bot แล้ววาง **callback URL ปัจจุบัน** จาก connector ของ ChatGPT
5. Save & Restart แล้ว Connect/Approve ใหม่ใน ChatGPT
6. ติ๊ก autostart หากต้องการ

ชื่อ MagicDNS เดิมอาจเปลี่ยนเมื่อเปลี่ยนเครื่องหรือเอาเครื่องออกจาก tailnet หาก MCP URL เปลี่ยน ต้องแก้ URL ใน connector และทำ OAuth ใหม่ การมี GitHub repository และ release ช่วยให้ติดตั้งซ้ำได้ แต่ไม่ควรนำ OAuth secret หรือไฟล์ตั้งค่าส่วนตัวไป commit

## เริ่มงานต่อใน Codex/ChatGPT หน้าต่างใหม่

คัดลอกข้อความนี้ไปเปิดแชตใหม่ได้:

```text
โปรเจกต์คือ apinanautan/mycomp-bot-windows บน Windows
โปรดอ่าน README.md ก่อนทำงาน
เป้าหมาย: ตรวจ MyComp Bot แบบไม่ทำลายค่า OAuth/Allowed folders
ตรวจตามลำดับ: Tailscale Connected → Funnel/HTTPS → Local service 127.0.0.1:8645 → MCP URL /mcp → callback URL มีเพียงหนึ่งค่า → log ใน %LOCALAPPDATA%\MyComp Bot
ห้าม commit token, OAuth callback, owner consent code, log หรือ .env
ถ้าจะแก้โค้ด ให้ตรวจ git status ก่อนและรายงาน error จริงจาก host-error.log/host-output.log
```

สำหรับ source checkout ให้เริ่มจาก:

```powershell
git status --short --branch
Get-Content -Raw README.md
Get-Content -Raw AGENTS.md
```

การแก้โค้ดที่กระทบ host ควรทดสอบบน Windows จริง และรันชุดทดสอบตาม `AGENTS.md` เมื่อเกี่ยวข้อง

## สำหรับผู้พัฒนา

หาก clone source แล้ว ต้องมี Python 3.11 จากนั้นรัน:

```powershell
PowerShell -ExecutionPolicy Bypass -File '.\windows\Run MyComp Bot.ps1'
```

launcher จะสร้าง `.venv` ใน repository และติดตั้ง dependency จาก `requirements.lock` อย่า commit `.venv`, `.env`, token, logs หรือ build output

---

คู่มือ Windows ฉบับย่ออยู่ที่ [windows/README.md](windows/README.md) แต่ให้ยึด README หน้านี้เป็นข้อมูลการติดตั้งและแก้ปัญหาหลัก

## Release v1.1.23: Windows MCP tools and UI automation
Adds filesystem, batch_read, diagnostics, and full-control-only windows_automation to the MCP engine. The existing Windows UI bridge is retained, with selected-window capture and window frame resizing implemented. Existing OAuth, configured roots, tunnel settings, and credential storage remain unchanged. Restart MyComp Bot after updating so the Engine registers the new tools.
