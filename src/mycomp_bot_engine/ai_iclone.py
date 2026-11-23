"""Ai-iclone bridge: run ONE fixed Ai-iclone.exe command (iClone 8 story-video pipeline).

Ai-iclone (github.com/apinanautan/iclone-story-pipeline) decides the steps itself; this bridge only
passes a whitelisted command and returns its text. No free arguments, no shell, stdin closed.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

READ_COMMANDS = frozenset({"manual", "status", "steps", "rules", "version"})
WRITE_COMMANDS = frozenset({"do", "use", "new-story", "range", "approve", "clean", "update"})
COMMANDS = READ_COMMANDS | WRITE_COMMANDS
EXIT_MEANING = {0: "OK: call do again", 1: "FAIL: fix what it says, one retry",
                2: "STOP: tell the user and wait", 3: "AI WORK: do what the card says, then do"}
MAX_TEXT = 60_000


def find_exe() -> Path | None:
    """AI_ICLONE_EXE, then Downloads, the self-installed copy, Desktop, the project checkout."""
    home = Path.home()
    local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
    candidates = [os.environ.get("AI_ICLONE_EXE", ""),
                  home / "Downloads" / "Ai-iclone.exe",
                  local / "Ai-iclone" / "Ai-iclone.exe",
                  home / "Desktop" / "Ai-iclone.exe",
                  home / "Documents" / "iClone Story Pipeline" / "Ai-iclone.exe"]
    for c in candidates:
        if c and Path(c).is_file():
            return Path(c)
    return None


def _need(value: Any, what: str) -> str:
    text = str(value or "").strip()
    if not text or "\x00" in text or len(text) > 500:
        raise ValueError(f"{what} is required for this Ai-iclone command")
    return text


def build_args(command: str, story: str | None = None, part: str | int | None = None,
               step: str | None = None, time_range: str | None = None, user_said: str | None = None,
               dry: bool = False, retry: bool = False) -> list[str]:
    if command not in COMMANDS:
        raise ValueError(f"unknown Ai-iclone command {command!r}; use one of {', '.join(sorted(COMMANDS))}")
    if command == "manual":
        return []
    if command == "do":
        return ["do", *(["--dry"] if dry else []), *(["--force"] if retry else [])]
    if command == "rules":
        return ["rules", _need(step, "step")]
    if command == "use":
        return ["use", _need(story, "story"), *([str(part).strip()] if str(part or "").strip() else [])]
    if command == "new-story":
        return ["new-story", _need(story, "story")]
    if command == "range":
        return ["range", _need(time_range, "time_range")]
    if command == "approve":
        return ["approve", "--said", _need(user_said, "user_said (the user's own words)")]
    return [command]


def run_ai_iclone(args: list[str], timeout: float = 600) -> dict[str, Any]:
    exe = find_exe()
    if exe is None:
        return {"isError": True, "exit": None,
                "text": "Ai-iclone.exe not found. Download it from "
                        "https://github.com/apinanautan/iclone-story-pipeline/releases/latest into Downloads."}
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        cp = subprocess.run([str(exe), *args], capture_output=True, stdin=subprocess.DEVNULL, env=env,
                            text=True, encoding="utf-8", errors="replace",
                            timeout=max(5.0, min(float(timeout), 3600.0)),
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return {"isError": True, "exit": None, "exe": str(exe),
                "text": f"Ai-iclone {' '.join(args)} took over {timeout:.0f} s and was stopped. "
                        "Run command=status to see where it is; do not start the same step twice."}
    text = (cp.stdout + ("\n" + cp.stderr if cp.stderr.strip() else "")).strip()
    if len(text) > MAX_TEXT:
        text = "...(start cut)...\n" + text[-MAX_TEXT:]
    return {"isError": cp.returncode == 1, "exit": cp.returncode, "exe": str(exe),
            "meaning": EXIT_MEANING.get(cp.returncode, "FAIL"), "text": text}
