# MyComp Bot portable skills

The single source of truth for all MyComp Bot plugin copies is this GitHub repository. Add the same three skills to every owned/editable MyComp transport plugin: Tailscale, Tunnel, and Remote Desktop Commander.

- mycomp-operator: exact machine, plugin names, scope and channel; diagnose and recover Tailscale, Tunnel and Remote Desktop Commander; record verified repairs in PLAYBOOK.md.
- fast-batch: plan first and do more per tool call, because each ChatGPT round trip is far slower than the PC.
- development-loop: inspect, edit minimally, test, review, and record outcome.

Copy the support file mycomp-operator/PLAYBOOK.md. Remove the retired skills operator-clarity, tool-routing, connection-recovery, ponytail and agent-desktop-portable from plugins. Do not blindly run any third-party installer or lifecycle hook.

These are instructions, not access credentials. An unavailable or unowned plugin cannot be repaired or updated merely by copying skills. Never invent a Tunnel or Desktop plugin. Preserve app bindings and auth; do not replicate runtime secrets in a plugin archive.
