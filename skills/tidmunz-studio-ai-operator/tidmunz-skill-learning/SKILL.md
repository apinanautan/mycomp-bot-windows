---
name: tidmunz-skill-learning
description: Automatically capture and update reusable Tidmunz Studio operating skills when a new method or reliable workflow improvement is actually discovered and verified during authorized work.
---

# Automatically improve operating skills from verified discoveries

- **Standing user authorization:** When a useful *new method* is found while operating Tidmunz Studio, proactively update the relevant Tidmunz **skill instructions** without asking again solely for permission to document the method. Keep working on the user's main task; do not replace execution with documentation.
- Record discoveries that are repeatable and directly useful: reliable API endpoints and documented parameters, exact UI controls, recovery steps, correct provider behavior, verified state checks, safe file workflows, and known failure conditions. Prefer editing the existing relevant skill over creating many redundant skills.
- **Evidence before promotion:** Verify against actual application behavior, source inspection or a successful controlled test. Separate confirmed steps from hypotheses and environment-specific observations. Include prerequisites, expected result, verification method, safe fallback, and date/version if relevant. If unverified, log as a candidate only, not as a mandatory procedure.
- **Preserve prior knowledge:** Read the current installed skill and plugin version before edits; make small, additive changes; avoid deleting or contradicting established instructions. Check for conflicting guidance. If the plugin update mechanism is available, publish the updated skill and read back its version/content. If it is unavailable, keep a local draft or report the pending change; never claim it was uploaded.
- **Safety and scope:** Automatic skill updates do **not** authorize modifying Tidmunz application code, repositories, dependencies, plugins' tool permissions, authentication, machine settings, or performing production/paid jobs. Those remain separate actions requiring their own authorization. Never change security policies or device-routing rules merely to simplify operations.
- **Portable by design:** Do not embed personal machine names, specific device IDs, fixed Tailscale URLs, credentials, tokens, emails, or user-chosen plugin names. Refer generically to **Agent Desktop** when describing optional GUI capabilities; discover the actual connected tool at runtime. Prefer direct Web/API first and GUI only when needed.
- Do not auto-publish secrets or private diagnostic data. Do not propagate an untested fix to all users. Avoid repeated version bumps for the same insight; consolidate related findings into one coherent update.
- After a successful skill update, briefly report what changed and the verified plugin version, then resume the original task. A skill is instructional guidance, not a self-running updater: it only changes when an authorized agent with an available skill-editing mechanism performs the update.
