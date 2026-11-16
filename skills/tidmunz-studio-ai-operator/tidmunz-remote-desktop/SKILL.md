# Remote Desktop Commander fallback


## Remote Desktop Commander — second-choice fallback
- Preferred: verified per-device Tidmunz Studio Web/API control. **Second choice: Remote Desktop Commander** when Web/API is unavailable, misrouted, or cannot perform the needed operation. Agent Desktop is an optional GUI-specific fallback after that or when the task specifically requires accessible desktop interaction.
- Discover the installed Remote Desktop Commander connector dynamically by capability, not a fixed plugin slug. Call `list_devices`, identify the intended target device using live, stable identity and app/process evidence; never reuse a device ID from another session or hardcode names, URLs, device IDs, tokens, paths, or credentials into this skill.
- Use Remote Desktop Commander `start_process`/file tools for programmatic inspection and safe app control on the verified device. Prefer short, idempotent read-only checks first. Confirm target, exact script/audio paths, project, pipeline state and receipts before a paid or non-idempotent operation.
- If a tool returns an unexpected or stale command result, stop writes on that channel and switch to the verified Remote Desktop Commander channel rather than repeatedly retrying. If a command is running, query its call/session result rather than submitting duplicates.
- Continue autonomously through the established task until a verifiable artifact is produced, without asking redundant questions. Report blockers precisely; never claim completed video before confirming the output file.
