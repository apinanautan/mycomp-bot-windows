---
name: codex-luna
description: Hand multi-step or parallelizable work to the local Codex CLI running gpt-6-luna, using Codex quota the user already pays for. Use for medium tasks (edit code to a clear spec, search many files, summarize long logs) or to split a big job into independent parts run at the same time. Do single-call jobs yourself.
---

# Codex CLI + Luna helper

The Windows PC has the Codex CLI (`codex`) with model `gpt-6-luna`. Measured on this PC: a short job takes ~8 s, and three parallel jobs take ~10 s in total.

## 1. Login check (run once at install/test and before the first use in a chat)

```powershell
codex login status
```

- If it prints `Logged in`, carry on and do NOT open a login window.
- If it is not logged in (non-zero exit or no `Logged in` line), open the login window for the user and wait:
  `Start-Process codex -ArgumentList 'login'`
  Tell the user in one line: "Sign in to ChatGPT in the browser window that just opened". Then poll `codex login status` every ~10 s for up to 3 minutes. Never type a password or code yourself.

## 1b. Account match check (Codex must use the same email as this ChatGPT)

Read only the email Codex is signed in with. The command never prints tokens:
```powershell
python -c "import json,base64,os;t=json.load(open(os.path.expanduser('~/.codex/auth.json')))['tokens']['id_token'].split('.')[1];print(json.loads(base64.urlsafe_b64decode(t+'='*(-len(t)%4))).get('email',''))"
```
- Expected email = the email of the ChatGPT account the user is chatting from. You cannot see it reliably yourself, so ask the user once ("Which email is this ChatGPT account?"), save it to memory, and reuse it later.
- **Same email:** carry on.
- **Different email:** stop. Do not send any work to Luna. Tell the user which email Codex is using, then run `codex logout` and `Start-Process codex -ArgumentList 'login'` so they can sign in with the right account, and check again.
- Never print or copy `auth.json` tokens; show the email only.

## 2. When to use Luna

- **Do it yourself:** one command or one batch_execute (read a file, move a file, check status).
- **Send to Luna:** work with several steps that Luna can finish on its own, such as editing code to a clear spec, searching many files, or summarizing long logs.
- **Split across Luna jobs:** a big job that breaks into independent parts. Run at most 3 at once, each on its own files or folder. Parts that depend on each other run one after another.
- **Keep for yourself (do or review):** hard or high-stakes work, paid production jobs, anything touching secrets.

## 3. How to run

Read-only analysis:
```powershell
codex exec -m gpt-6-luna --skip-git-repo-check -s read-only -C "<folder>" "<clear task + expected output>"
```

Edits limited to one folder:
```powershell
codex exec -m gpt-6-luna --skip-git-repo-check -s workspace-write -C "<folder>" "<task>"
```

For parallel or long jobs, run each one in the background with its output in its own file, then read all the files:
```powershell
Start-Process codex -ArgumentList 'exec','-m','gpt-6-luna','--skip-git-repo-check','-s','read-only','-C','<folder>','<task>' -RedirectStandardOutput "$env:TEMP\luna-1.txt" -NoNewWindow
```

## Rules

- Never use `--dangerously-bypass-approvals-and-sandbox`.
- Never pass tokens, keys or passwords in the task text.
- Write each task so it stands on its own: the files, the goal, and what "done" means.
- Luna's output is a report, not proof. Check the changed files or the result yourself before telling the user it is done.
- If Codex is missing or out of quota, say so in one line and do the work yourself.
