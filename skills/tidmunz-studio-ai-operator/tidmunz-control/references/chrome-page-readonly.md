# Read the actual ChatGPT page in Tidmunz Studio without interfering

Use this procedure when the user specifically asks to inspect the ChatGPT **browser chat actually used by the Windows app**, rather than app logs or a progress percentage.

## First: select the authorized device and scope

1. Discover the connected computer with Remote Desktop Commander `list_devices` (or authorized TailScale shell); never reuse a stale ID. Do not run commands on another machine or assume a saved session is connected.
2. For Narrate/เล่าภาพ read the local app's **loopback** `/api/status` on port 8765 and its `narrate` object. Read the secret from the authorized Windows app's local `snapgen_data/mobile_web_token.txt`, use it only for localhost requests, and never print it. Verify `narrate.title`, `busy`, `stage`, `detail`, `percent`, `last_error`, and relevant sanitized log entries. This API is **not** the ChatGPT web page.
3. Inspect Windows Chrome root processes and top-level windows to identify the browser owned by Tidmunz; a typical dedicated instance uses a profile path ending in `TidMunStudio\SnapGenChromeProfile` and a tab called `อ่านบทและบริบท`. Do not assume fixed PID/HWND, username, profile path, or title. Other unrelated ChatGPT windows may exist.

## Noninteractive UI Automation inspection

On a Windows machine with `pywinauto` available, the following **read-only** example inspects a selected Chrome top-level window by its current handle. Discover the handle first, e.g. via `EnumWindows` and `GetWindowThreadProcessId` matched to the dedicated Chrome process. Never paste a stale handle without verifying its title/process.

```python
import time
from pywinauto import Desktop

handle = VERIFIED_TIDMUNZ_CHROME_HWND  # must be discovered live
win = Desktop(backend="uia").window(handle=handle)
for i in range(2):
    nodes = win.descendants()
    texts = [node.window_text() for node in nodes
             if node.element_info.control_type == "Text" and node.window_text()]
    replies = [value for value in texts
               if value.lstrip().startswith("{") and '"characters"' in value]
    lengths = [len(text) for text in replies]
    print({"sample": i + 1, "title": win.window_text(),
           "reply_lengths": lengths[-2:]})
    if i == 0:
        time.sleep(4)
```

For a different GPT stage, identify the *most recent assistant response Text control* from its neighboring `ChatGPT พูดว่า:` label rather than assuming JSON or `characters`. The example is specifically the validated Narrate stylist JSON stage. Inspect only relevant conversation metadata, lengths, and brief safe extracts; do not print entire private stories, cookies, secrets, or unrelated tabs.

- **Verified behavior (2026-11-06):** UIA `Desktop(backend="uia").window(handle=...)` read an **offscreen** dedicated Chrome window titled `อ่านบทและบริบท - Google Chrome`. Across samples 4 seconds apart, the latest response text grew from 6,782 to 7,261 characters while Narrate advanced from 3% to 4%. This confirms that a Chrome page can often be read without making it foreground.
- Growing response content across samples is direct evidence that GPT is still rendering a reply. Unchanged content does **not** prove a hang: GPT may be thinking, throttled, disconnected, the app may be waiting for the final marker, or UIA may return a truncated/virtualized snapshot. Inspect stop/streaming indicators, last reply and elapsed time in context; compare app error/log; report uncertainty honestly.
- Do not click, bring window to foreground, change tabs, refresh, submit a prompt, copy via UI button, stop, restart, clear chat, enable debugging, or attach an invasive Chrome automation session while the app is using its GPT page. This check must not affect the running generation.
- No access to hidden reasoning or internal server state is implied; this only reads what the web UI exposes. If UIA is not available, say that page-level observation is unverified and continue with app status.
