# MyComp Bot for Windows

MyComp Bot is a local Windows desktop host and loopback-only Python MCP engine.
It has no hosted service and no preconfigured public endpoint: each person runs
it on their own computer, chooses their own public HTTPS address, and enters
the callback URI issued by their own ChatGPT connector.

## One-click developer start

Install Python 3.11 or later, clone the repository, then right-click
**`windows\Run MyComp Bot.ps1`** and select **Run with PowerShell**. If script
policy blocks it, run this from the repository root instead:

```powershell
PowerShell -ExecutionPolicy Bypass -File '.\windows\Run MyComp Bot.ps1'
```

The launcher creates a local `.venv`, installs the hash-locked dependencies,
and opens the app. It does not need administrator rights and it does not change
system-wide settings.

## Connect your own ChatGPT connector

1. In the app, provide your own public HTTPS domain, or install `cloudflared`
   yourself and select **Start Free Temporary Tunnel**. The app will not copy
   an endpoint until a public HTTPS URL is available.
2. In ChatGPT, turn on **Settings → Security and login → Developer mode**.
   Open **Settings → Plugins**, select **+**, and paste the copied `/mcp` URL.
3. Copy the callback URI supplied by your ChatGPT connector into the app, save,
   and restart the engine. Use **Copy Owner Consent Code** only when the
   MyComp Bot authorization page asks for it.

The engine binds only to `127.0.0.1:8645`. A public domain or Cloudflare tunnel
must route to that local service; the app never opens a public listener itself.

Cloudflare Quick Tunnels are temporary testing URLs that change on each start.
Use your own named tunnel and domain for a persistent connection.

## Windows control scope

The desktop host executes explicit mouse move/click/double-click/right-click,
drag, scroll, text input, key/hotkey input, visible-window listing, and
virtual-desktop or region screen capture through an owner-supervised local
bridge. Accessibility uses the Windows UI Automation API for element discovery,
focus, invoke-click, value entry, and window close/minimize operations—never a
coordinate mouse fallback. Screen capture is implemented with the native Win32
GDI API and is returned as a PNG resource. Mouse and keyboard actions require
the **Elevated** profile. OCR, virtual displays, window-only capture, and
AppleScript deliberately return an explicit error rather than using a shell
fallback.

For Windows UI Automation actions, provide a selector such as `process_id`,
`name`, `name_contains`, `automation_id`, `control_type`, or a native window
`handle`. This makes an Accessibility action target an actual Windows UIA
element rather than inferred screen coordinates.

The public MCP surface remains the same fixed eight semantic tools. Files and
shell remain deny-by-default, and allowed folders/executables are configured by
the local owner. OAuth is the secure default; tokens, consent codes, logs,
SQLite state, `.env`, virtual environments, and build artifacts are ignored by
Git.

## Validation

On a Windows machine, run the PowerShell launcher and then verify the app can
start the loopback engine, start/stop a Quick Tunnel, and perform only the
explicit UI actions above. This repository publishes source, not an untested
cross-compiled `.exe`; sign and test a Windows release before distributing one.
