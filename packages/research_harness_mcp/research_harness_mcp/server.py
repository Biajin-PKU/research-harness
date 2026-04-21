"""MCP server entry point — exposes research_harness primitives via stdio transport."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .tools import execute_tool, list_tool_definitions

logger = logging.getLogger(__name__)

app = Server("research-harness")


@app.list_tools()
async def handle_list_tools() -> list[Tool]:
    return list_tool_definitions()


@app.call_tool()
async def handle_call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
    arguments = arguments or {}
    result = execute_tool(name, arguments)
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, default=str))]


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
