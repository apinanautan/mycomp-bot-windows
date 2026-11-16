---
name: tidmunz-director
description: Use when a user asks ChatGPT to manage end-to-end Tidmunz Studio creation from a script or existing project through a cover, reference images, storyboards, generated scenes, video clips, voice/music, quality control and final delivery.
---

# Tidmunz Studio AI production director

**Primary execution goal:** bring the user-authorized production through to a verifiably finished clip or movie, instead of merely launching the workflow. For source selection, stalled GPT responses, routine production decisions and fallback behavior, apply the companion skill `tidmunz-finish-job`: **GPT Web first; API Web only after a confirmed GPT Web limit or real unavailability**. The current API Web button is reported nonfunctional and must not be represented as a working fallback until tested. Do not change application source to fix it as part of this plugin update.

Work with the connected `tidmunz-control` workflow, its tested `snapgen_ai_operator.py` local CLI, and the TailScale connection. The goal is to reduce repeated button pressing without lying about current completion or making expensive duplicates.

## New story / cover / video

1. Identify the story source and intended output (cover, clips, full movie), reference characters, dimensions, duration, model restrictions and approved credit budget. Reuse existing project context and history; don't ask the user for information already saved.
2. Inspect native Auto / image / cover workflows and actual project files in the Windows app. Prefer an existing supported API or GUI operation. If an action requires direct UI, use TailScale's available `vision`, `accessibility`, `mouse`, and `keyboard` actions with before/after verification. A click must be confirmed by app state; do not claim success merely because a mouse action was sent.
3. Preserve a consistent style and the original face, clothing and layout across shots. Use reference images and per-scene context. For a new cover, choose a real existing hero still/reference or generate a new image only with the user's permission; deliver as a new output file without overwriting the source. A `cover` generation API is **not** currently evidenced—use the GUI when available or a separately tested local workflow. Do not claim a one-shot cover tool exists.
4. Start the native Auto pipeline when the project is opened, the action is authorized and no provider job is still pending. Let the PC's native loop generate missing media while checking receipts and logs. Show actual file counts, not just the UI percent.
5. During a session, diagnose GPT JSON errors, Chrome queue, 429 limits, provider high-traffic, invalid reference image size, FFmpeg/NumPy/Topaz failures, image/clip consistency and file permissions. For deterministic problems, modify/test focused code only when separately authorized as a development task. For suspected cloud task acceptance, inspect provider UUID/receipt before resubmitting. Do not re-ask routine generation-path questions: default to GPT Web as defined in `tidmunz-finish-job`.
6. Finish only when the native output, source audio, clips, and final render exist. Inspect FFmpeg metadata for duration/resolution, spot-check scene continuity, report missing/error shots, and provide the verified output path.

## When user wants 'AI ทำให้จบเอง'

Explain the architecture: ChatGPT plugin operates via TailScale **when invoked**; the Windows Auto engine continues independently; a local watcher can detect simple conditions between chat turns; full autonomous reasoning when ChatGPT is closed requires a supported persistent agent/infrastructure, not merely a skill file. Configure genuine recurring automation only if requested and supported; do not secretly create periodic notifications in lieu of end-to-end work.

Never rerender a successful image/video, spend new credits after an ambiguous failure, delete/overwrite paid work, or publish a Release without authorization. Return to `tidmunz-control` when handling a production incident.
