---
name: tidmunz-run-live
description: Use when the user asks the Tidmunz Studio AI Operator to watch a live production job, identify why Auto is waiting, safely continue a paused story, or verify a finished movie.
---

# Tidmunz Studio: live work and safe recovery

Use the **connected TailScale app** for the user's Windows machine. Never assume the app is running just because a percentage is shown. Prefer the real local operator adapter rather than simulated clicks.

## Verified machine and command

The user's connected workstation is `<VERIFIED_DEVICE_ID_OR_LABEL>` and the source checkout is `<TIDMUNZ_SOURCE_DIR>`.

Use TailScale `shell` (`powershell.exe -NoProfile -Command`) to run the local operator in that checkout:

```powershell
$python = '<TIDMUNZ_INSTALL_DIR>\.venv312\Scripts\python.exe'
$operator = '<TIDMUNZ_SOURCE_DIR>\snapgen_modules\snapgen_ai_operator.py'
& $python -B $operator status
& $python -B $operator diagnose
& $python -B $operator projects
```

These three commands were executed against the live machine and return sanitized JSON. Do not print or reveal the local Mobile Web token, authentication URL, session keys, or full image prompts.

## Human-directed workflow

1. Identify the exact existing story from `status` or `projects`. If the user asks to produce a complete story from scratch, inspect the actual GUI before using it to create a new project; the operator CLI has **no invented `cover` or `create_story` endpoint**.
2. Read `diagnose`, the recent app log, actual file paths and the first missing clip. Treat a green "running" display as live work only if the native `auto_busy` flag and application process corroborate it.
3. If `auto_busy` is true, observe or diagnose. Do **not** submit a duplicate `resume`, even when a user asks you to "make it finish".
4. If `auto_busy` is false and `provider_capacity`, `ambiguous_cloud_result` or `provider_task_may_be_pending` is reported, investigate provider receipts and cooldown. Never bypass a refusal with raw UI clicks; the cloud may already have accepted a paid task.
5. Only when authorized to generate missing media **and** no task/credit ambiguity exists, use `resume --authorize-paid`. This authorization is an explicit user direction for the current story and potential paid missing work, not perpetual permission for new expensive rerenders or provider changes.
6. For a user-authorized pause, use `stop` (graceful request) and verify by reading `status`. Do not forcibly kill the desktop GUI or provider jobs.
7. Verify complete delivery only after all recorded scenes have existing nonempty clips, `done.video` is set, and the final rendered movie exists. Inspect duration, resolution, audio and file integrity separately when possible.

## What the plugin can and cannot do

**In a ChatGPT session:** read status, classify faults, control authorized existing operations through TailScale, inspect the GUI, and write/test repairs on the connected machine when user requests. A cover, scene or video can be launched using the real desktop GUI if its controls are inspected, not by making up an API method.

**After a ChatGPT session ends:** the desktop Auto process may keep rendering. The local `watch` or `naka_auto_supervisor` is deterministic status checking, not a live GPT model. A private plugin alone does not provide independent 24/7 AI reasoning, computer control or repair of unexpected bugs. Do not claim otherwise. When the user returns, resume diagnosis from the saved status and journal rather than restarting media requests.

## Safety checklist

- Never leak Mobile Web URL/query, GPT cookies, payment tokens or API keys.
- Read `AGENTS.md` and `STATE.md` before repository edits. Do not overwrite project files, images or prior clips.
- Preserve the same HTTP command id if a receipt is uncertain; never send a fresh id just to check if the first job succeeded.
- Do not auto-run `image_generate`, `video_generate`, `auto_start` or issue new paid requests without user authorization and receipt review.
- Distinguish malformed JSON (safe bounded reply correction) from provider timeout (may have consumed credit).
- Return a concise report: story, `busy`, images/clips, first missing shot, provider error class, action taken, and blockers. Never promise delivery while missing clips remain.
