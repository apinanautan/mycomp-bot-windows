---
name: agent-desktop-portable
description: Use vercel-labs agent-desktop on an authorized machine for safe verified graphical interaction without assuming one computer, wrapper, or preinstalled plugin.
---

# Portable agent-desktop

Source: https://github.com/vercel-labs/agent-desktop (Apache-2.0). This is MyComp Bot integration guidance, not a vendored executable.

1. Discover whether agent-desktop exists on the target machine and an authorized connected tool can invoke it. Never hardcode a specific machine, user profile, domain, plugin ID or filesystem path.
2. If absent, ask permission before installing official packages. The upstream install command is npm install -g agent-desktop when Node/npm and platform support are confirmed. Do not download or run unverified scripts.
3. Before interacting, run agent-desktop status, agent-desktop skills get desktop, and agent-desktop skills get platform. Follow binary-version-specific permission and headed/headless guidance. Inspect JSON response fields ok, data, error and retry disposition.
4. Prefer find and an accessible ref for narrow headless interaction. Otherwise inspect list-windows and snapshot. Observe -> act -> verify; do not infer success from a click response. Refresh refs after UI changes.
5. Retry a failed write only if the tool reports it safe or post-state proves it did not happen. Physical input requires user authorization; logins and consent dialogs require required human approval.
6. agent-desktop mcp is local stdio, NOT a remote public URL. Check a real authenticated MyComp transport (Tailscale, Tunnel or approved desktop connector) before claiming ChatGPT can reach it.
7. Avoid screenshots or clipboard when accessibility suffices. Keep private UI contents, screenshots, clipboard and secrets out of skills and logs.

Use tool-routing for task-specific measured latency and connection-recovery for failed paths. A new Windows installation has no assumed existing desktop plugin.
