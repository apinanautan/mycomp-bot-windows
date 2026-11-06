---
name: development-loop
description: Use for code fixes, implementation, repository changes, or debugging that must be verified and resumable. Inspect first, preserve changes, make a minimal fix, test it, and record a truthful outcome.
---

# Development Loop

A repeatable engineering workflow, not a shell/UI tool. Combine with ponytail for the smallest correct change. Repository AGENTS.md, platform permissions, and explicit user constraints take precedence.

## Start
1. Read repository instructions (AGENTS.md) and git status. Identify the target repo and existing state file. Never wipe, reset, stash, or overwrite unrelated work to simplify the task.
2. Define the observable outcome and one to three acceptance checks. Confirm what is and is not authorized (especially publish, merge, secrets, spending, external communication, or destructive changes).
3. Trace the path before editing: caller, owner/source of truth, write/read path, defaults, restart and failure behavior. For multi-step work, keep a short plan with one active step.
4. Prefer a clean isolated worktree when another task is already changing the same checkout; never discard user edits.

## Execute
1. Fix the root cause in the existing owner, not a parallel settings mechanism. Reuse existing libraries and APIs. Change the fewest coherent lines and files; do not remove input validation, authorization, accessibility, or data-loss protection.
2. Add one useful regression check for logic with branches, loops, parsing, persistence or security. Avoid redundant test scaffolding.
3. Run the narrowest check first, then broader tests appropriate to risk. An unrelated failing test must be identified as such; do not call the full suite green.
4. Review the final diff for scope drift, accidentally included secrets, private paths, binaries, temporary files, and generated outputs.

## Durable state
If work spans sessions, use the existing project state file or create STATE.md (one owner, no duplicated config). Keep: current objective; confirmed facts; changes; verification evidence; remaining risk or next action. Never store credentials, tokens, cookies, or verbose logs.

## Decide and report
Choose exactly one:
- complete: acceptance checks passed and no required work remains.
- iterate: specific evidence identifies an unaddressed defect; start another bounded diagnostic or fix.
- blocked: dependency or approval prevents safe progress; state exactly what is missing.

Never call a plausible edit verified. Stop a repeated failing loop without new evidence. For unattended or scheduled checks, default to report-only. Require explicit permission before publishing, merging, deleting material data, spending money, or sending messages to third parties. A skill cannot bypass or grant missing tool access.

Report concisely: outcome, files changed, tests actually run, and anything unverified.