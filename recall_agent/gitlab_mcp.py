"""Thin synchronous wrapper to call a single GitLab MCP tool (community server).

Used for the showcase write action (posting an MR note) so it goes through the GitLab MCP
surface rather than raw REST. Spawns the stdio server per call; fine for low-frequency actions.
"""

from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv()

GITLAB_API_URL = "https://gitlab.com/api/v4"


async def _call(name: str, args: dict, read_only: bool) -> str:
    params = StdioServerParameters(
        command="npx",
        args=["-y", "@zereight/mcp-gitlab"],
        env={
            **os.environ,
            "GITLAB_PERSONAL_ACCESS_TOKEN": os.environ["GITLAB_TOKEN"],
            "GITLAB_API_URL": GITLAB_API_URL,
            "GITLAB_READ_ONLY_MODE": "true" if read_only else "false",
        },
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(name, args)
            return "".join(getattr(b, "text", "") or "" for b in result.content)


def call_tool(name: str, args: dict, read_only: bool = True) -> str:
    return asyncio.run(_call(name, args, read_only))
