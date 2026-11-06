# MyComp Bot portable skills

The single source of truth for all MyComp Bot plugin copies is this GitHub repository. Add the same five skill files to every owned/editable MyComp transport plugin: Tailscale, Tunnel, and Remote Desktop Commander.

- development-loop: inspect, edit minimally, test, review, and record outcome.
- ponytail: prefer the simplest correct complete implementation.
- agent-desktop-portable: safely operate desktop UI via an actually connected CLI.
- connection-recovery: verify a failing route, repair safely, record reusable evidence in PLAYBOOK.md.
- tool-routing: choose the fastest eligible and healthy tool for each type of work, based on observed successful calls, not a permanent rank.

Copy support files: ponytail/LICENSE and connection-recovery/PLAYBOOK.md. Do not blindly run any third-party installer or lifecycle hook.

Ponytail is copied verbatim from https://github.com/DietrichGebert/ponytail at commit 96608e078b2d5ea607c5c3b8b5a54d1c1fba6846 and retains its MIT license. The portable agent-desktop guidance references https://github.com/vercel-labs/agent-desktop (Apache-2.0) without copying its executable or repo contents.

These are instructions, not access credentials. An unavailable or unowned plugin cannot be magically repaired or updated merely by copying skills. Never invent a Tunnel or Desktop plugin. Preserve app bindings and auth; do not replicate runtime secrets in a plugin archive.

To improve a skill, first verify a real diagnostic/repair and test; record a short anonymized case, update this canonical source, then propagate only to owned editable plugin releases with explicit authority. Do not create separate self-learning mechanisms in the three plugins.
