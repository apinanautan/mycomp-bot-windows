"""Single-flight queues scoped to an authenticated user and a canonical MCP tool.

A duplicate request is skipped immediately with no prior result attached.
Never return a stale tool response as though it answered the new request.
Underlying timeouts are unchanged and every completion/cancellation releases
the running slot.
"""
from __future__ import annotations

import asyncio
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

    def is_running(self, user: str, tool: str) -> bool:
        key = (user, normalize_tool_name(tool))
        with self._lock:
            return key in self._running

    async def execute(
        self,
        user: str,
        tool: str,
        runner: Callable[[], Awaitable[Any]],
        *,
        request_id: str | None = None,
    ) -> Any:
        key = (str(user) or "owner", normalize_tool_name(tool))
        with self._lock:
            if key in self._running:
                return {
                    "status": "skipped", "request_id": request_id,
                    "changed": False, "results": [],
                    "warnings": [
                        "This request was not executed: another call to this tool "
                        "is still running for this user. No prior result was returned."
                    ],
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
            with self._lock:
                self._running.discard(key)

        task.add_done_callback(completed)
        return await asyncio.shield(task)
