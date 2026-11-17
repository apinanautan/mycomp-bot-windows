---
name: chat-handoff
description: Never lose work when a ChatGPT chat gets long or full. Keep a running work log on the PC, watch for signs the chat is nearly full, write a handoff summary and tell the user to continue in a new chat; at the start of every chat, read the latest handoff and continue. Use on every multi-step task.
---

# Chat handoff: don't lose work when the chat fills up

ChatGPT cannot see exactly how full a chat is and cannot open a new chat by itself. So: **save progress to the PC all the time**, and **hand off early**.

Handoff folder (inside the default allowed Documents root):
`%USERPROFILE%\Documents\MyComp Bot Handoff\`
- `HANDOFF.md`: the latest state, overwritten each time.
- `history\YYYY-MM-DD_HHMM.md`: copies of older handoffs, kept.

## 1. Start of every chat

Read `HANDOFF.md`. If it exists, has `Status: open`, and the user's message continues that work (or says "ต่องาน" / "continue"):
- Say in one line what you are continuing.
- Carry on from **Next step**. Do not ask again for what is already written there.

If the user starts different work, leave the handoff alone. When that work finishes, ask once whether the old handoff is still needed.

## 2. During work: keep the log current (cheap, always)

After each milestone (every ~5 tool calls, after any important result, or after the user gives a new instruction), update `HANDOFF.md` in **one** filesystem write:

```markdown
# Handoff — <task title>
Status: open
Updated: <date time>
Machine: <computer name>

## Goal (user's words)
<what the user asked, quoted briefly, including every extra instruction added later>

## Done
- <finished step + evidence: file/path/result>

## Current state
<what is running, half-done, or waiting; job/project IDs; paths>

## Next step
1. <exact next action>
2. ...

## Rules/decisions from the user
- <preferences, things not to touch, approvals given>
```

Never write tokens, passwords, keys, cookies or private chat IDs into it.

## 3. Signs the chat is nearly full: hand off NOW

Hand off when **any** of these holds:
- About 40 or more tool calls in this chat, or many very long outputs (big files, logs, screenshots).
- You notice you are forgetting earlier details or repeating yourself.
- Replies or tool calls get noticeably slow, cut off, or error for no reason.
- The task will clearly need many more steps than the chat can hold.

Hand off like this:
1. Update `HANDOFF.md` fully (section 2). Copy the previous version into `history\` first.
2. Tell the user in their language, short:
   "แชตนี้ใกล้เต็มแล้ว บันทึกงานไว้ที่ Documents\MyComp Bot Handoff\HANDOFF.md แล้ว — เปิดแชตใหม่แล้วพิมพ์ว่า **ต่องาน** ได้เลย"
3. Stop starting new long steps in this chat. Do not start paid or irreversible actions right before a handoff.

## 4. When the work is finished

Set `Status: done`, add a final summary of the results, and copy the file into `history\`. The next chat will see `done` and won't resume it.
