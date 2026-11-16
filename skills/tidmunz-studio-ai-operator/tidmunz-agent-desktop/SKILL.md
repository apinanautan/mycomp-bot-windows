---
name: tidmunz-agent-desktop
description: Use only when Tidmunz Studio work genuinely requires Windows desktop UI interactions beyond direct Web/API/local operator commands, and an installed Agent Desktop capability may be available under any user-chosen plugin name.
---

# Agent Desktop — optional GUI capability, not a hardcoded plugin name

## Routing priority

1. **First choice: direct Web/API.** Read status, diagnose, and perform supported authenticated Tidmunz Studio commands over the current machine's native local interface or connected web access. This is usually faster and less fragile than image/screenshot clicking.
2. **Second choice: Agent Desktop capability.** Discover the installed, connected tools or skills that expose **Agent Desktop** functionality. "Agent Desktop" is a capability / generic tool type, **not** a fixed plugin name, installation title, connector ID, URL, service name, executable path, or machine identity. Different users may rename the plugin arbitrarily. Use whatever authorized connector actually provides the capability (including one that relays Agent Desktop through another transport). Check capabilities and available actions before invocation. Do not assume a plugin is missing only because its displayed name differs.
3. If GUI control is unavailable, explain the specific limitation. Never invent an Agent Desktop tool, a plugin alias, a device ID or a click result; do not silently switch to another computer.

## When to use the optional UI route

- Native file picker, GUI-only selection (e.g. choosing script/audio/reference folder), unsupported model or aspect-ratio control, modal approval, and reading a GUI-only failure, **when there is no supported API**.
- Prefer accessibility/semantic element inspection for a single necessary screen. Obtain a fresh snapshot or targeted element query, act on an unambiguous control, and verify the result. Use screenshots only when visual inspection is materially required. Do **not** continuously take screenshots as a heartbeat, poll by full-screen image, or re-open unchanged views repeatedly.
- Verify intended device and specific Tidmunz instance via `tidmunz-device-routing` before every state-changing UI action, especially on shared logins and duplicate machine names. Never use a display name, email or a previously observed hostname alone as identity.
- Preserve source files and completed paid assets. File selection or opening a dialog must not inadvertently start a new project or paid video job. Follow approved credit and receipt checks before any job launch/retry.
- Treat UI action result as tentative until status and filesystem/project state corroborate it. For ambiguous delivery, observe instead of repeating a click or paid submission.

## Naming rule — important

In all reusable skills and instructions, refer to this optional integration **only as "Agent Desktop"**. Do not pin user-specific plugin titles (even if they include those words), tool prefix names, user display names, hostnames, device IDs, URL endpoints or Windows paths as the plugin identifier. Runtime discovery resolves the actual available tool; the selected machine identity comes separately from authenticated device selection.

## Scope

These are workflow instructions. They do not install Agent Desktop, guarantee permission, bypass account/device selection, or turn the ChatGPT plugin into a persistent background agent. The primary Web/API workflow remains unchanged.


## Remote Desktop Commander — second-choice fallback
- Preferred: verified per-device Tidmunz Studio Web/API control. **Second choice: Remote Desktop Commander** when Web/API is unavailable, misrouted, or cannot perform the needed operation. Agent Desktop is an optional GUI-specific fallback after that or when the task specifically requires accessible desktop interaction.
- Discover the installed Remote Desktop Commander connector dynamically by capability, not a fixed plugin slug. Call `list_devices`, identify the intended target device using live, stable identity and app/process evidence; never reuse a device ID from another session or hardcode names, URLs, device IDs, tokens, paths, or credentials into this skill.
- Use Remote Desktop Commander `start_process`/file tools for programmatic inspection and safe app control on the verified device. Prefer short, idempotent read-only checks first. Confirm target, exact script/audio paths, project, pipeline state and receipts before a paid or non-idempotent operation.
- If a tool returns an unexpected or stale command result, stop writes on that channel and switch to the verified Remote Desktop Commander channel rather than repeatedly retrying. If a command is running, query its call/session result rather than submitting duplicates.
- Continue autonomously through the established task until a verifiable artifact is produced, without asking redundant questions. Report blockers precisely; never claim completed video before confirming the output file.
