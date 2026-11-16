---
name: tidmunz-auto-workflow
description: Use when controlling Tidmunz Studio's สร้างวิดีโอออโต้ / Auto page, choosing a story and voice-over, verifying native script/audio alignment, Prompt-Ref Context and reference folder, or taking an authorized Auto video job to a verified rendered output. Follow the installed native flow rather than externally cutting a script.
---

# Tidmunz Studio Auto video — verified native workflow

Source inspected on 2026-11-06: installed `snapgen_modules/snapgen_page_narrate.py` (`install_video_auto`, `build_narrate_page`, `VIDEO_STAGES`, `stage_transcribe`, `start_pipeline`). This documents existing behavior; **it is not authorization to change application source**. Use this together with `tidmunz-control`, `tidmunz-device-routing`, `tidmunz-finish-job`, and `tidmunz-agent-desktop`.

## Select the correct PC and application

- The ChatGPT connector named **Tailscale** is the owner's MyComp Bot integration; call this tool first when available. The connector name does not mean a hardcoded machine or a fixed hostname.
- Enumerate/verify the intended device using stable device identity, not a matching device name or shared login/email alone. Confirm Tidmunz Studio is running on that device. If ambiguous, ask which device before making writes. Resolve the connected PC's own local URL/token only on that PC; never copy a different PC's credential or publish a token.
- **Prefer direct Web/API and native local status/commands** via the authenticated connection for normal work. Use **Agent Desktop** only when an authorized step requires desktop-only UI or direct APIs cannot perform it; resolve whatever installed plugin/tool exposes the Agent Desktop capability at runtime, regardless of its user-chosen plugin name. Do not hardcode a connector/plugin ID, alias, machine name, hostname or endpoint. Avoid screenshot polling when API status or accessibility observations suffice.
- Prefer real local status/API and safely inspected native UI via the connector. Where supported, `auto_open`, `auto_start`, `auto_stop` work only for existing project operations; don't invent API endpoints for picking files, creating Prompt-Ref Context, references or modifying model controls. Use the actual UI on the authenticated PC when needed. A command is successful only after readback from GUI/project status.

## Preflight — avoid duplicate work

1. Confirm the selected story, selected audio, true length, project folder, running/idle state and existing `project.json` outputs. Reopen an existing project if present. New ChatGPT session does **not** mean a new project or a reason to reset GPT history.
2. Source selection in Auto is `📄 บท` (DOCX/TXT/MD) followed by `🎙 เสียง` (WAV/MP3/M4A/AAC/FLAC/OGG). Use the user's source files on their PC without overwriting them; only create copies when a test/trim was requested. In a short-voice test, the **full story script is usually the correct source**; let Auto derive the spoken excerpt. Do not independently shorten the script because a shorter audio file was selected.
3. Auto **requires validated same-story Context from Prompt-Ref**. `stage_context` reuses Prompt-Ref's Context and does not run a second full analysis. `sync_auto_context` checks the script hash and looks beside the script/selected reference folder; refuses another story's Context. If missing, complete Prompt-Ref on the same story first. Do not fabricate or cross-wire Context.
4. Auto uses the **Image AI page's currently selected reference folder** for characters/locations; this must be set before Start and verified to belong to this story. `attachments_for` selects appropriate images by character/location; separate character-reference creation happens in the Prompt-Ref/Ref workflow, not as a standard Auto `characters` stage. Review look-alike character references where the user requests, and re-create only affected refs if authorized.
5. Check chosen **aspect ratio** `16:9` versus `9:16` with the user if not established. Check actual **video model**, clip length, resolution and any economic Slow 2× option in this live project. Auto may default a new story to Grok Lite 720p with 10-second clips; do not assume user-requested Grok 1080p is already selected. Verify supported UI choices rather than inventing a model ID. Source choice defaults to GPT Web when its use was established; the API Web control was previously reported not functional and is NOT a proven fallback.
6. Check style, subtitles, storyboard provider, and whether `หยุดให้ตรวจแผนก่อนสร้างรูป` is enabled. Ask only truly missing creative choices or actual required approval, not repeated routine continuation prompts. Read actual media credit/receipt state before resuming to avoid duplicates.

## Auto's built-in script and narration processing — do not duplicate

- `stage_transcribe()` invokes its own Whisper pipeline, checks for reusable `transcript.json` from the same audio/stamp, and records word timestamps for dialogue-cut timing when necessary. Do not launch a separate Whisper task merely to pre-cut the script.
- `cut_part_from_full(full_script, heard_text)` attempts to locate **the excerpt of the full story corresponding to the selected narration** and saves it to the project folder as `บท_ท่อนนี้.txt`. `story_script()` prioritizes `project.part_text` afterward. This matching is conditional: it may return no excerpt if content cannot be matched; verify output instead of presuming success.
- `correct_with_script`, `repair_transcript`, `recover_missing_speech`, and dialogue word timestamps reconcile transcription, repetitions and gaps with the script. `check_script_matches_audio` raises an error below 0.6 alignment score before generating expensive visuals. On a mismatch, stop and inspect exact story/audio/Context rather than forcing unrelated files.
- If the narration is deliberately trimmed or replaced later, Auto notices an audio stamp change and invalidates timing-based stages (`transcribe`, `plan`, `storyboard`, `images`, `motion`, `clips`, `video`) while retaining files on disk. Do not replace audio mid-production without explaining the necessary replan.
- For a user-requested 1-minute trial: prefer **copy and trim the audio only** in a Desktop TEST folder; then select the original full-story script plus the new short audio, provided the Prompt-Ref Context is still the same story. Let Auto produce the matching excerpt in its output folder. Do not choose an unverified separately cut DOCX or submit the original ~25-minute voice for a 1-minute test. Check final excerpt and timeline once Auto transcribes.

## Exact native Auto stage order (`VIDEO_STAGES`)

1. `context` — **วิเคราะห์บท (4%)**: verifies and binds same-story Prompt-Ref Context.
2. `transcribe` — **ฟังเสียง (6%)**: built-in Whisper, reusable transcript and audio-script matching.
3. `plan` — **วางแผนฉาก (5%)**: GPT plans shots with narration/word timing; if `หยุดให้ตรวจแผนก่อนสร้างรูป` is enabled, Auto intentionally pauses for review.
4. `storyboard` — **สตอรี่ชีต (5%)**: generate storyboard groups, attach correct character/location references, retain previously completed sheets.
5. `images` — **สร้างรูปฉาก (20%)**: generate remaining story stills, verify identity/style; allow selective ref, image or prompt repair without re-generating all shots.
6. `motion` — **พรอมต์วิดีโอ (5%)**: video prompts / motion planning. In full Auto, the native worker can dispatch clip generation as part of this stage; don't send a second independent job.
7. `clips` — **สร้างคลิปวิดีโอ (45%)**: create missing clips with configured model/Slots; verify provider IDs, per-shot receipts and files. Parallel Slots are possible; count saved clips rather than relying on percent alone.
8. `video` — **ตัดต่อ (10%)**: join existing clips with narration/subtitles and complete required local postprocessing.

In the source, stage names have weights totaling 100%; they are UI progress weights, not proof that a stage's cloud job was actually accepted/completed. The standard Auto pipeline has **no separate character-reference stage**; do that beforehand in Prompt-Ref/Ref and Image AI.

## Controls and recovery

- Auto button `▶ เริ่ม` becomes `▶ ทำต่อ` after a pause; `⏸ หยุด` requests a graceful stop. `เปิดโปรเจกต์` reopens persisted projects. `เครื่องมือ ▾` includes opening the output folder and **เริ่มประวัติ GPT ใหม่…** (only use the latter when old history is truly lost). `↺ ทำใหม่ตั้งแต่ขั้น` is explicit recalculation, not a safe default for a minor stall.
- Changing aspect, style or clip length after generating scenes can invalidate planned scenes/images/clips even though old media remains on disk. Never select 'redo all' casually, especially on paid outputs.
- A running job should be observed, not restarted. For GPT response wait, inspect actual browser reply progress read-only as in `tidmunz-control/references/chrome-page-readonly.md`. 429 or an unchanging UI counter alone is not a conclusive provider result.
- Per-shot controls include `สร้างใหม่`, `แก้รูปเดิม`, `แก้ให้ตรงเรฟ`, `พรอมต์ภาพ`, `GPT ช่วยแก้`, `นำเข้ารูป`, `สร้างคลิป`, `แจ้งปัญหาคลิป`, `แก้พรอมต์วิดีโอ`, `ทำสโลว์`, `รวมวิดีโอ`, `เปิดวิดีโอ`; choose only the targeted action requested. A source image/clip can be edited without recreating the rest of a story.
- GPT Web first as the user preference; API Web only after a confirmed limit/unavailability, never assume the reported nonworking button is functional. Never blindly resubmit a paid cloud request when a receipt/UUID outcome is unknown.
- An idle project with no `done.video` is not a completed video. Verify actual saved scene images, nonempty clips, finished render path and audio/video duration/resolution before reporting success. Existing completed shots and source files are preserved.

## Current read-only findings from 2026-11-06

- The active Auto project was `บท - เลือกนักมักได้แร่` with `auto_busy=false`, no scenes/images/clips, progress 0%, and an existing full-story `project.json` pointing to the original script and original ~1498-second audio.
- A separate Desktop folder `Tidmunz_TEST_1min_20261106` contains backed-up originals and attempted test files (`test_audio_1min.wav` near 59.7 seconds and `test_script_1min.docx`). Those test assets were **not confirmed selected in Auto**; the trimmed DOCX was produced before inspecting the native excerpt-matching flow and must not be chosen by default. Prefer the original story script plus the short voice sample if the user continues the 1-minute experiment.
- Merely inspecting the Auto flow is **not permission to press Start**, change provider, alter repository, reset, or spend credits. Resume only with the user's current explicit authorization and verified target machine.


## Continuous skill improvement
When a repeatable, verified new operating method is discovered, follow `tidmunz-skill-learning`: update the relevant skill automatically where supported, while preserving the working flow and not changing the application source.


## Remote Desktop Commander — second-choice fallback
- Preferred: verified per-device Tidmunz Studio Web/API control. **Second choice: Remote Desktop Commander** when Web/API is unavailable, misrouted, or cannot perform the needed operation. Agent Desktop is an optional GUI-specific fallback after that or when the task specifically requires accessible desktop interaction.
- Discover the installed Remote Desktop Commander connector dynamically by capability, not a fixed plugin slug. Call `list_devices`, identify the intended target device using live, stable identity and app/process evidence; never reuse a device ID from another session or hardcode names, URLs, device IDs, tokens, paths, or credentials into this skill.
- Use Remote Desktop Commander `start_process`/file tools for programmatic inspection and safe app control on the verified device. Prefer short, idempotent read-only checks first. Confirm target, exact script/audio paths, project, pipeline state and receipts before a paid or non-idempotent operation.
- If a tool returns an unexpected or stale command result, stop writes on that channel and switch to the verified Remote Desktop Commander channel rather than repeatedly retrying. If a command is running, query its call/session result rather than submitting duplicates.
- Continue autonomously through the established task until a verifiable artifact is produced, without asking redundant questions. Report blockers precisely; never claim completed video before confirming the output file.
