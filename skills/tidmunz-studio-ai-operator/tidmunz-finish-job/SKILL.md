---
name: tidmunz-finish-job
description: Use when the user tells Tidmunz Studio to "ทำให้เสร็จ", finish a video/clip, complete an Auto production, continue a stalled GPT Web task, or choose GPT Web versus API Web without repeated routine questions.
---

# Tidmunz Studio — Finish the authorized job

## Primary operational goal: produce a verifiably finished result

When the user gives Tidmunz Studio an authorized production task, **prioritize completing that same task to its verified deliverable**. Do not consider a queued request, a waiting GPT response, a progress percentage, or a successful button click to be the deliverable. Keep track of the actual job, project, current scene, missing assets, receipts, and next recovery step. Do not abandon the job or repeatedly ask which ordinary production step to take when the user's established instructions already resolve that choice.

This is an operational priority within the user's scope and existing tool permissions; it does not override higher-priority instructions, required authorization, safety checks, or provider restrictions. A skill file does not itself make ChatGPT run continuously in the background. The Windows Auto engine can continue independently, while a configured local watcher can perform deterministic checks. Be truthful about both.

## Default generation path — GPT Web first

1. **GPT Web is the primary choice** for routine image/video production and related GPT prompts in Tidmunz Studio. When the app asks “GPT Web or API Web?”, select **GPT Web** without re-asking the user for every scene, unless the user explicitly overrides that preference for the current task.
2. If GPT Web is taking time, inspect **real** app status, browser response progress, provider errors and current scene. A timer or a "no reply after 3 minutes" banner alone does not prove that the provider has hit a limit. Distinguish actively streaming, page stalled, provider queued, browser disconnected, malformed response, and a confirmed GPT Web usage limit. Avoid unnecessary refreshes, duplicate submits or destructive resets.
3. If a reversible, non-paid recovery is available (for example a bounded structured-response correction for malformed JSON, reconnecting after a verified disconnect, or continuing the next ready stage), perform it as allowed and verify the effect. Preserve existing clips, generated prompts, project state and receipts. Do not loop infinitely: record each recovery attempt, compare new evidence, then escalate if the same failure repeats without progress.
4. **Only when GPT Web has a confirmed limit or is actually unavailable for this job**, prefer **API Web as the fallback**. This is a documented fallback *policy*, not a claim that the current API Web button or API integration works. The owner has reported that the API Web button currently does not actually function. Verify a real supported endpoint, action result or produced output before considering the fallback successful; don't repeatedly click an inert button.
5. If API Web is not operational, report the concrete blocker, keep the job state and existing completed scenes intact, and continue independent authorized steps if any remain. Do not invent a working API, secretly switch providers, bypass a restriction, or edit the application to make API Web work: repairing API Web is a **separate future development request**.

## Autonomous routine decisions, without unnecessary prompts

- For dialogs asking whether to continue the **already authorized production**, use the established project settings and choose the safe continuation. Default to GPT Web when a source choice is requested. Avoid asking the user to approve the same routine choice for every scene.
- If the project is still running, monitor and diagnose rather than issuing another start/resume. Use the current job's identifiers/receipts to determine whether a cloud job may already have been submitted.
- If safely idle and authorized to generate still-missing paid media for **this specific project**, use the existing supported resume path only after checking the pending job/receipt state. Do not interpret “finish” as unlimited credit authorization or permission to re-render successful scenes. Where spending, provider identity, account settings, or other material consequences are unresolved, obtain required approval rather than guessing.
- Where an action requires approval from the app/platform, stop at that genuine approval step and resume only after it is granted. Don't interpret an instruction in this skill as overriding such approval.
- If the user explicitly stops/pauses/cancels, honor it; the completion goal never overrides their new instruction.

## Completion criteria and concise reporting

- For a **clip**, verify the file exists, is nonempty, is playable, and belongs to the intended scene. For a **whole video**, check every required shot/clip, actual final rendered movie, media duration/resolution and audio integrity when available, not just a status label.
- Report verified completed deliverables; otherwise state precisely where the job is blocked (scene/shot, GPT Web or API Web, reason, receipt confidence), the safe next action, and whether Windows Auto continues independently. Never say “done” when an unverified API click, queued generation or missing final render remains.
- If ChatGPT's current interactive task ends before the desktop production ends, do not claim ongoing AI monitoring. Preserve state through the supported native workflow and resume diagnosis on the next invocation.

Use the established tools and safety procedures in `tidmunz-control`, `tidmunz-run-live`, and `tidmunz-director` for actual operation. This skill changes **instructions only**. It does not patch Tidmunz Studio, fix the API Web button, alter GitHub or grant new permissions.
