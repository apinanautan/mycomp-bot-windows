---
name: tidmunz-device-routing
description: Mandatory device selection and verification for any Tidmunz Studio operation through the connected user-named Tailscale/MyComp Bot plugin, including when PCs share hostnames or a ChatGPT/MyComp account. Use before status checks, remote reads, GUI interactions, file edits, or paid video production.
---

# Tidmunz Studio — select the correct computer every time

## Which tool to call

- The user named their connected **MyComp Bot** ChatGPT plugin **`Tailscale`**. When authorized to operate Tidmunz Studio, use the connected **`@Tailscale` plugin/tool** (`mcp__TailScale__...` where available), not a guessed Windows program with that name. MyComp Bot is the access mechanism; Tailscale networking and its MagicDNS names are separate concepts.
- Available plugin actions may be HTTP/API, shell, browser, vision, or desktop control; inspect which actions are actually exposed before using them. Prefer verified app APIs for commands. If the Tailscale plugin cannot operate the target Windows computer, a separately authorized Remote Desktop Commander connection can be used — but verify its target identity independently. **Do not silently jump to a different machine or plugin** just because the preferred path is unavailable.

## Mandatory target selection: never use a name or email as identity

- **A machine hostname, user-visible alias, MagicDNS address, Tailscale IP, Windows username, ChatGPT login email, MyComp login email, or a shared account is NOT sufficient to uniquely identify the intended target.** Two users may name machines identically, and the same account may expose multiple machines.
- Discover accessible devices using actual supported MyComp Bot/Tailscale connector device-selection or listing commands, if available. If the current connector exposes only one implicit backend and provides no authenticated device inventory, do not pretend that you can enumerate other computers. Ask the user to identify/select the intended computer in the connector or supply a confirmed endpoint.
- Prefer a stable, opaque **MyComp Bot agent/device ID** reported by that agent. If available, independently cross-check the target's Tailscale **node ID** and a device-local pairing/registration ID. These identifiers must be read from the **authenticated target itself**; never make them up, scrape them from an arbitrary email, or substitute an IP/hostname for an ID. Device IDs can change after reinstall/re-enrollment; if so, re-pair and re-confirm.
- If several computers are reachable, or if two have the same hostname, explicitly identify the target by **its unique device ID and a human-friendly label**. Ask for selection when not already confidently pinned to this task. Bind that device ID to this active operation. Merely being logged into the same email does not give authority to choose a machine at random.
- In the current project, prior examples of `<VERIFIED_DEVICE_ID_OR_LABEL>`, a specific `C:\Users\...` path, a `100.x` address, a `.ts.net` hostname, or an old query-token URL describe **one previously used PC only**. They are **not defaults for all users or all machines**. Never select them just because they appear in another Tidmunz skill.

## Verify before every action that changes state

1. Resolve the **intended target device ID** from the user's current selection / a previously confirmed binding for this specific operation.
2. Connect to that exact device and obtain a fresh authenticated identity response from the remote agent or device-local identity endpoint. Match the returned unique ID with the intended device ID; cross-check secondary identifiers if available. Confirm the Tidmunz Studio instance and intended story/project from the **same target** before performing any mutation. If identity cannot be independently confirmed, limit to no action and ask the user to select or re-pair; don't write, click, start, stop, upload, or spend credits.
3. Discover Tidmunz installation, local API port, and credential path **on that confirmed PC**. Read its Mobile Web access token locally; never embed, publish, echo, copy across machines, or assume a credential from a different machine is valid. An accessible URL alone does not prove machine ownership.
4. For multi-step tasks, re-check the ID after reconnection, device switching, connector changes or loss of session. Before every new state-changing command re-confirm that the active session still targets the bound device. Never follow a stale saved Tailscale hostname if current identity disagrees.
5. For paid production, additionally follow the existing Tidmunz receipt/idempotency checks and project authorization rules in `tidmunz-control` and `tidmunz-finish-job`.

## Failure / ambiguity policy

- Missing device inventory, duplicate names, identical email addresses, expired credentials, changing node ID, conflicting device fingerprints or unexpected device change: **fail closed**. Say exactly what can and cannot be verified and request a single explicit target selection or re-pairing. Don't guess and do not act on another device.
- Do not claim this skill alone enforces access control. Actual protection requires the connector/agent to enforce per-device IDs, authentication and permissions. A plugin instruction cannot technically prevent someone with unrestricted remote shell permissions from accessing other computers.
- Do not patch Tidmunz Studio, create a new identity agent or change connector permissions just because this skill is invoked. Such changes are separate authorized development tasks.
- Keep the device/connector IDs in the skill only as **abstract field names**, not the user's real access URL, token or a reusable target identifier. A temporary operation binding belongs in the authenticated session, never in a public shared skill.

## Operator checklist

**Connected tool:** `@Tailscale` (user-named MyComp Bot plugin), if enabled. **Selected device:** verified unique ID, not the display name. **App:** verified Tidmunz Studio on the same device. **Project:** verified currently selected story. **Action:** within user authorization; receipt-aware for paid work. If any item is unknown, do not claim safe remote control succeeded.
