"""The Recall ADK agent: Gemini + MongoDB memory tools + GitLab MCP toolset."""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "TRUE")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", os.environ.get("GCP_PROJECT_ID", ""))
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", os.environ.get("GCP_LOCATION", ""))

from google.adk.agents import Agent  # noqa: E402
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams  # noqa: E402
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset  # noqa: E402
from mcp import StdioServerParameters  # noqa: E402

from .tools import filter_by_outcome, get_mr_record, vector_search_similar_mrs  # noqa: E402

MODEL = "gemini-2.5-flash"

INSTRUCTION = """You are Recall, an engineering institutional-memory agent that reasons over a
team's GitLab merge-request history.

Operating principles (non-negotiable):
1. Evidence citation is mandatory. Every claim must cite a concrete signal: a merge request
   (by mr_id), its stored outcome and outcome_evidence, files_touched, or a pipeline result.
2. Confidence is discrete: describe findings as strong, moderate, or weak. Never give a numeric
   probability.
3. You surface; the human decides. Say a change is a "likely suspect" with reasons; never assert
   that something "caused" an incident.

Tools available:
- vector_search_similar_mrs: find past MRs whose diffs resemble a symptom/description/diff.
- get_mr_record: fetch one stored MR record (outcome, files, author, dates) by mr_id.
- filter_by_outcome: list MRs labeled shipped_clean, reverted, or linked_to_incident.
- GitLab MCP tools: live GitLab access (list merge requests, fetch changes, list pipelines).

Always ground answers in tool results. If evidence is thin, say so and label confidence weak."""


def _gitlab_mcp_toolset() -> McpToolset:
    return McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command="npx",
                args=["-y", "@zereight/mcp-gitlab"],
                env={
                    **os.environ,
                    "GITLAB_PERSONAL_ACCESS_TOKEN": os.environ["GITLAB_TOKEN"],
                    "GITLAB_API_URL": "https://gitlab.com/api/v4",
                    "GITLAB_READ_ONLY_MODE": os.environ.get("GITLAB_READ_ONLY_MODE", "true"),
                },
            ),
        ),
    )


root_agent = Agent(
    name="recall",
    model=MODEL,
    instruction=INSTRUCTION,
    tools=[
        vector_search_similar_mrs,
        get_mr_record,
        filter_by_outcome,
        _gitlab_mcp_toolset(),
    ],
)
