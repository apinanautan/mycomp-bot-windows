# MyComp Bot for Windows

This is the Windows source edition of MyComp Bot. It runs the MCP engine only
on `127.0.0.1`, keeps settings under `%LOCALAPPDATA%\MyComp Bot`, and never
ships another person's endpoint, callback URI, token, or consent code.

## Start

Install Python 3.11 or later, clone this repository, then right-click
**`windows\Run MyComp Bot.ps1`** and choose **Run with PowerShell**. If Windows
blocks local scripts, run this one command in PowerShell from the repository:

```powershell
PowerShell -ExecutionPolicy Bypass -File '.\windows\Run MyComp Bot.ps1'
```

The launcher creates a repository-local virtual environment, installs the
hash-locked dependencies, and opens the desktop host. It does not require an
administrator account.

## Connect your own machine

1. Open the app and set your own public HTTPS domain, or start a free temporary
   Cloudflare Quick Tunnel after installing `cloudflared` yourself.
2. In ChatGPT, turn on **Settings → Security and login → Developer mode**, then
   open **Settings → Plugins**, select **+**, and paste the derived `/mcp` URL.
3. Copy the callback URI from your ChatGPT connector into the app and save,
   then approve access using **Copy Owner Consent Code** when the authorization
   page asks for it.

The temporary tunnel URL changes every time it starts. It is for local testing;
use a named tunnel and your own domain for ongoing use.

## Current Windows controls

The Windows host handles explicit mouse movement/click/drag/scroll, text and
key input, and window listing through a local owner-supervised bridge. Those
actions require the **Elevated** permission profile. Screen capture/OCR,
UIAutomation element inspection, and macOS-only AppleScript are deliberately
reported as unsupported rather than silently using a shell fallback.

Before distributing an `.exe`, test the source app on a real Windows machine
and sign the release; this repository does not claim a cross-compiled macOS
binary is a Windows release.
