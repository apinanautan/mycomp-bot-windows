---
name: tool-routing
description: Choose the fastest currently healthy authorized tool for each coding, file, or desktop task, using observed latency and capability rather than a fixed rank.
---

# Task-aware, measured tool routing

Use across the three MyComp Bot channels: Tailscale MCP, OpenAI Secure MCP Tunnel, and Remote Desktop Commander. Desktop Commander may be a separate plugin. These routes are not interchangeable without checking capabilities and authorization.

1. **Discover first.** Check which tools are actually connected and authenticated in this session. Inspect read-only capabilities. No known URL, running process or copied skill proves ChatGPT can call a tool.
2. **Choose by operation.** Prefer an authorized shell/filesystem path for coding, git, tests and text edits. Prefer accessibility-aware Remote Desktop Commander or agent-desktop for graphical apps. A fast tool that cannot perform the task correctly is ineligible.
3. **Measure, do not guess.** For each eligible path and task type, record elapsed time and successful outcome from real low-risk calls. Use median of up to 5 recent successful comparable calls, note failures/timeouts separately, and invalidate stale values after reconnection. Do not benchmark with mutations or secret reads. One sample is provisional, not a universal ranking.
4. **Route.** Among working authorized tools with equivalent capabilities and comparable evidence, choose the lowest observed successful latency. When evidence is weak, prefer the currently verified stable path and gather read-only samples opportunistically. Reassess if errors, network conditions or capabilities change.
5. **Fail over safely.** For read-only/idempotent queries, retry only if error disposition permits and then choose the next healthy eligible path. For changes, commands, clicks, publishing or spending, FIRST inspect post-state; never replay a possibly completed write merely to try a faster channel. If outcome cannot be determined, stop and report blocked.
6. **Don't fan out UI actions.** Never call multiple tools concurrently to click/type into the same window. Avoid parallel writes to one worktree. Preserve authentication, exact device identity, and consent.
7. **Report evidence.** If asked which is fastest, show task type, sample count, observed latency, success rate, and any untested path. Never declare a global winner based on guesses.

Transport latency is not model inference or code quality. Skill documents advise tool selection; they cannot intercept tool calls or grant permissions. Use development-loop and ponytail alongside this skill.
