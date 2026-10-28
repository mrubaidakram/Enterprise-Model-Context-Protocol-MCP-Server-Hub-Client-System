"""Small command-line MCP client for the Streamable HTTP hub."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def run(url: str, tool_name: str | None, arguments: dict[str, Any]) -> None:
    token = os.getenv("MCP_ACCESS_TOKEN", "")
    if not token:
        raise SystemExit("Set MCP_ACCESS_TOKEN to a bearer token issued by your OAuth authorization server")
    async with streamablehttp_client(url, headers={"Authorization": f"Bearer {token}"}) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            if tool_name:
                result = await session.call_tool(tool_name, arguments)
            else:
                result = await session.list_tools()
            print(result.model_dump_json(indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8000/mcp"))
    parser.add_argument("--tool", help="Tool name to call; omit to list tools")
    parser.add_argument("--arguments", default="{}", help="JSON object of tool arguments")
    options = parser.parse_args()
    try:
        arguments = json.loads(options.arguments)
    except json.JSONDecodeError as exc:
        parser.error(f"--arguments must be valid JSON: {exc}")
    if not isinstance(arguments, dict):
        parser.error("--arguments must decode to a JSON object")
    asyncio.run(run(options.url, options.tool, arguments))


if __name__ == "__main__":
    main()
