---
name: fast-batch
description: Make MyComp Bot tasks fast by doing more per tool call. Every call costs a slow ChatGPT think-and-round-trip (often 15-40 s) while the PC itself answers in under 1 s, so plan first and batch.
---

# Fast batch

The machine is fast; the round trip is slow. Fewer calls = faster task.

## Rules
1. **Plan before the first call.** List every read/check the task needs, then do them together.
2. **Batch by tool.**
   - Several files: `batch_read` (up to 20 files) instead of many `filesystem` reads.
   - Several independent steps: `batch_execute` (up to 12 steps, each permission-checked).
   - Browser: `dom_cdp` with `steps` (up to 100 actions on one warm socket). `evaluate` JavaScript beats clicking.
   - Windows UI: `accessibility` with `steps`, addressing windows by handle.
3. **Pick the fastest correct path:** shell/filesystem > `dom_cdp` > `accessibility` > `keyboard`/`mouse` > `vision`. Use screenshots/OCR only when nothing else can see the state.
4. **One shell call for many read-only checks.** Combine independent, trusted, read-only PowerShell checks into one call. Never hide writes, admin commands or secret reads inside it.
5. **Do not re-check.** No repeated `status`/`diagnostics` calls, no screenshot just to confirm a step that already returned success.
6. **Keep output small.** Ask for counts, matches and errors, not whole files or full listings.
7. **Mutations stay safe.** Batched UI or file changes must stop on error. If a write may have completed, inspect post-state before retrying; never replay blindly.
