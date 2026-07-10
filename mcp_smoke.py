"""GitLab MCP smoke-test: initialize a session, list tools, call one read-only tool.

Two backends:
  --server official    GitLab Duo MCP at /api/v4/mcp via `mcp-remote` (OAuth, opens a browser
                        on first run). Requires Premium/Ultimate + Duo enabled on a top-level group.
  --server community    stdio via npx @zereight/mcp-gitlab (PAT-based; works on free tier; fallback)

Usage:
  python mcp_smoke.py --server community
  python mcp_smoke.py --server official
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os

from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv()

TOKEN = os.environ["GITLAB_TOKEN"]
SOURCE = os.environ["GITLAB_PROJECT_ID_SOURCE"]
GITLAB_API_URL = "https://gitlab.com/api/v4"
OFFICIAL_MCP_URL = f"{GITLAB_API_URL}/mcp"

# values we can supply when a tool's schema requires them
ARG_HINTS = {
    "project_id": SOURCE,
    "projectId": SOURCE,
    "id": SOURCE,
    "namespace": SOURCE,
    "per_page": 1,
    "perPage": 1,
}

READ_TOOL_PREFERENCE = (
    "get_mcp_server_version",
    "list_merge_requests",
    "get_project",
    "list_projects",
)


def _required(schema: dict) -> list[str]:
    return list((schema or {}).get("required", []))


def _can_satisfy(schema: dict) -> dict | None:
    args = {}
    for key in _required(schema):
        if key in ARG_HINTS:
            args[key] = ARG_HINTS[key]
        else:
            return None
    return args


def _choose_tool(tools: list) -> tuple[str, dict] | None:
    by_name = {t.name: t for t in tools}
    for preferred in READ_TOOL_PREFERENCE:
        tool = by_name.get(preferred)
        if tool is not None:
            args = _can_satisfy(tool.inputSchema)
            if args is not None:
                return tool.name, args
    for tool in tools:
        name = tool.name.lower()
        if name.startswith(("get_", "list_", "search")):
            args = _can_satisfy(tool.inputSchema)
            if args is not None:
                return tool.name, args
    return None


async def _drive(read, write) -> None:
    async with ClientSession(read, write) as session:
        await session.initialize()

        listed = await session.list_tools()
        tools = listed.tools
        print(f"[ok] connected. {len(tools)} tools exposed:")
        for tool in tools:
            print(f"  - {tool.name}")

        choice = _choose_tool(tools)
        if choice is None:
            print("[warn] no zero-config read tool found to call; listing alone succeeded.")
            return

        name, args = choice
        print(f"\n[call] {name}({args})")
        result = await session.call_tool(name, args)
        preview = ""
        for block in result.content:
            preview += getattr(block, "text", "") or ""
        preview = preview.strip().replace("\n", " ")
        print(f"[ok] tool returned {len(preview)} chars: {preview[:300]}")


async def _run_official() -> None:
    params = StdioServerParameters(
        command="npx",
        args=["-y", "mcp-remote", OFFICIAL_MCP_URL],
        env={**os.environ},
    )
    async with stdio_client(params) as (read, write):
        await _drive(read, write)


async def _run_community() -> None:
    params = StdioServerParameters(
        command="npx",
        args=["-y", "@zereight/mcp-gitlab"],
        env={
            **os.environ,
            "GITLAB_PERSONAL_ACCESS_TOKEN": TOKEN,
            "GITLAB_API_URL": GITLAB_API_URL,
            "GITLAB_READ_ONLY_MODE": "true",
        },
    )
    async with stdio_client(params) as (read, write):
        await _drive(read, write)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", choices=("official", "community"), default="community")
    args = parser.parse_args()
    runner = _run_official if args.server == "official" else _run_community
    print(f"=== GitLab MCP smoke-test :: {args.server} ===")
    asyncio.run(runner())


if __name__ == "__main__":
    main()
