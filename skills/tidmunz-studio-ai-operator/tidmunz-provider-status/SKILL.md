---
name: tidmunz-provider-status
description: Use BEFORE diagnosing or retrying a failed or stuck Tidmunz Studio video generation request on SnapGen, especially Grok Lite, Grok Lower, Veo, provider maintenance, API errors, low success rates or credit-risk decisions.
---

# Tidmunz Studio — check SnapGen model status before troubleshooting or retrying

## First response to an error

1. Identify the exact model ID and provider in the user's selected project/slot and receipt. For Grok Lite, `grok-1.5-lite` belongs to **SnapGen.ai**, accessed through `api.snapgen.ai`, not the direct xAI API. Do not infer the SnapGen model's health from the xAI/Grok status page.
2. Open the **actual live SnapGen status UI** at `https://snapgen.ai/status/` (or its canonical redirect), not merely the homepage and not only a generic third-party website-up check. If the page is client-rendered, use a browser and inspect rendered model rows. Refresh it at check time; note the timestamp, model label, operational/degraded/outage state and displayed success rate.
3. Match the status row to the exact model. A generic row such as `Grok Video` is not necessarily equivalent to `grok-1.5-lite`/Grok Lite. Report that distinction explicitly; never invent a model-specific success rate or claim the model is healthy/down when it is not separately listed. A 200 response for the website proves only that the page responds, not that video generation is healthy.
4. Compare the status observation with the **actual API response**, configured SnapGen endpoint and credentials, request parameters, locally stored receipt/history/UUID, and recent tasks. `MODEL_UNDER_MAINTENANCE` is an observed API error, not proof of a permanent site-wide outage or a local-code defect.
5. **Do not repeat a paid generation while the result/receipt is ambiguous**; if a specific model reports a partial outage or low success rate, show that fact before suggesting another attempt. Never silently switch from the user-selected model to another model. Check history and credits before submitting a single authorized retry.
6. If the status page is unavailable or ambiguous, state that clearly and diagnose app/auth/endpoint/parameter/network errors independently. Do not assert a successful generation until the task UUID and resulting media can be verified.

## Evidence from observed SnapGen UI (2026-11-09)

The live `/status/` interface displayed `Grok Video` with `Partial Outage` and `Success rate: 10%`, while other rows such as `Veo 3.1 Lite` showed `Operational`/90%. The visible status page did **not** explicitly identify `Grok Lite` as an independent status row in this check; do not transfer the generic Grok Video figure to Grok Lite as an exact measurement. These values are time-varying and must be rechecked, never reused as current data on a later day.

This is a **read-only diagnostic workflow**, not permission to change application source, authenticate new accounts, switch models or consume credits.
