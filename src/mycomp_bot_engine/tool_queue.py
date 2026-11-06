"""Single-flight queues scoped to an authenticated user and a canonical MCP tool.

A duplicate request is skipped immediately; no runner is left waiting.  The most
recent completed result for the queue is returned when one exists.  Underlying
tool timeouts are unchanged and every completion/failure/cancellation releases
the running slot.
"""
from __future__ import annotations

import asyncio
import copy
import threading
from collections.abc import Awaitable, Callable
from typing import Any

from .schema import TOOL_NAMES


def normalize_tool_name(name: str) -> str:
    """Resolve short, dotted and fully-qualified MCP tool names without aliases."""
    value = str(name).strip()
    if "__" in value:
        value = value.rsplit("__", 1)[-1]
    value = value.rsplit("/", 1)[-1].rsplit(".", 1)[-1]
    if value not in TOOL_NAMES:
        raise ValueError(f"Unknown MyComp tool: {name}")
    return value


class ToolQueue:
    """At most one running call per (user, tool); separate users/tools can run."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running: set[tuple[str, str]] = set()
        self._latest: dict[tuple[str, str], Any] = {}

    def is_running(self, user: str, tool: str) -> bool:
        key = (user, normalize_tool_name(tool))
        with self._lock:
            return key in self._running

    async def execute(
        self,
        user: str,
        tool: str,
        runner: Callable[[], Awaitable[Any]],
    ) -> Any:
        key = (str(user) or "owner", normalize_tool_name(tool))
        with self._lock:
            if key in self._running:
                recent = copy.deepcopy(self._latest.get(key))
                if isinstance(recent, dict):
                    return {
                        **recent,
                        "status": "skipped",
                        "changed": False,
                        "warnings": [*(recent.get("warnings") or []), "A call to this tool is already running for this user; latest completed result returned."],
                    }
                return {
                    "status": "skipped", "changed": False, "results": [],
                    "warnings": ["A call to this tool is already running for this user; no previous result is available."],
                }
            self._running.add(key)
        # Shield the underlying tool: a client disconnect/cancellation must not
        # free the slot while an uncancellable worker thread is still running.
        try:
            task = asyncio.create_task(runner())
        except BaseException:
            with self._lock:
                self._running.discard(key)
            raise

        def completed(done: asyncio.Task[Any]) -> None:
            try:
                value = done.result()
            except BaseException:
                value = None
            with self._lock:
                if value is not None:
                    self._latest[key] = copy.deepcopy(value)
                self._running.discard(key)

        task.add_done_callback(completed)
        return await asyncio.shield(task)
