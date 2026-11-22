"""Owner-local Blender MCP client. No external listeners or arbitrary stdio commands.

Connects to the locally installed mcp-for-blender stdio server and its GUI addon
on 127.0.0.1:9876. Never launches Blender or changes a project implicitly.
"""
from __future__ import annotations

import asyncio
import os
import socket
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

READ_TOOLS = frozenset({"get_scene_info", "get_addon_status"})
KNOWN_TOOLS = frozenset({
    "get_scene_info", "get_addon_status", "disable_telemetry",
    "execute_blender_code", "record_trajectory_feedback", "look",
    "generate_3d", "generate_gaussian_world", "search_assets", "import_asset",
})
HOST = "127.0.0.1"
PORT = 9876


def is_addon_listening() -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=0.7):
            return True
    except OSError:
        return False


def local_stdio_parameters() -> StdioServerParameters:
    uvx = Path.home() / ".local" / "bin" / ("uvx.exe" if os.name == "nt" else "uvx")
    if not uvx.is_file():
        raise FileNotFoundError("Blender MCP requires uvx in ~/.local/bin")
    env = dict(os.environ)
    env.update(BLENDER_HOST=HOST, BLENDER_PORT=str(PORT),
               DISABLE_TELEMETRY="true", UV_PYTHON_PREFERENCE="only-managed")
    return StdioServerParameters(command=str(uvx),
                                 args=["--offline", "--python", "3.11", "mcp-for-blender"],
                                 env=env)


async def _invoke(operation: str, tool: str | None, arguments: dict[str, Any]) -> dict[str, Any]:
    async with asyncio.timeout(30):
        async with stdio_client(local_stdio_parameters()) as (reader, writer):
            async with ClientSession(reader, writer) as client:
                await client.initialize()
                available = await client.list_tools()
                found = {item.name: item for item in available.tools}
                if operation == "list_tools":
                    return {"tools": sorted(found), "addon_listening": is_addon_listening()}
                if tool not in found or tool not in KNOWN_TOOLS:
                    raise ValueError("Unrecognized Blender MCP tool")
                response = await client.call_tool(tool, arguments)
                return {"tool": tool, "isError": bool(response.isError),
                        "data": response.model_dump(mode="json", exclude_none=True)}


def run_blender_mcp(operation: str, tool: str | None = None,
                    arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Called only after outer MyComp permission gate checks the requested operation."""
    if operation == "status":
        return {"addon_listening": is_addon_listening(), "host": HOST, "port": PORT}
    if operation not in {"list_tools", "call_tool"}:
        raise ValueError("Unknown Blender MCP operation")
    if operation == "call_tool" and not is_addon_listening():
        raise ConnectionError("Blender GUI addon is not listening on 127.0.0.1:9876")
    if operation == "call_tool" and (tool is None or tool not in KNOWN_TOOLS):
        raise ValueError("Unrecognized Blender MCP tool")
    if not isinstance(arguments, dict) and arguments is not None:
        raise ValueError("Blender MCP tool arguments must be a JSON object")
    return asyncio.run(_invoke(operation, tool, arguments or {}))
