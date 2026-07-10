# Recall

AI agent for engineering-team institutional memory. Recall ingests a project's merge-request
history into a searchable corpus and answers two questions no one else on the team remembers:

- **Change Triage** — "Something broke; which recent change is the likely cause?" Ranks suspect
  MRs in a time window with a deterministic scorer (similarity + outcome risk + file overlap),
  then narrates the reasoning with Gemini.
- **Prior-Art Review** — "Has anyone tried this before?" On a new MR (via webhook), finds the
  closest historical MRs by diff similarity, checks how they turned out (shipped clean, reverted,
  incident), and posts an evidence-cited comment back to GitLab.

Built on Google Vertex AI (Gemini + `text-embedding-005`), MongoDB Atlas Vector Search, and the
GitLab MCP server. Every output is evidence-cited, uses discrete confidence bands
(strong/moderate/weak, never numeric), and surfaces — it never decides.

## Architecture

```
GitLab REST ──► ingest.py ──► MongoDB Atlas (768-d embeddings, vector index)
                                   │
webhook / UI ──► server.py ──► recall_agent/workflows.py
                                   ├─ scorer.py     deterministic ranking + bands
                                   ├─ tools.py      vector search / outcome lookup
                                   └─ gitlab_mcp.py post comment via GitLab MCP
```

## Repository layout

| Path | Purpose |
|---|---|
| `server.py` | FastAPI app: Change Triage UI (SSE-streamed), MR list, `POST /webhook`, `/health` |
| `recall_agent/` | Agent package: ADK agent, Mongo tools, scorer, workflows, MCP client |
| `ingest.py` | MR ingestion pipeline (GitLab REST → embed → MongoDB) |
| `label.py` | Auto-label corpus outcomes (revert detection, incident keywords) |
| `enrich_reverts.py` | Pull revert pairs to enrich outcome labels |
| `demo_mr.py` | Open a demo MR in the fork to exercise the webhook |
| `mcp_smoke.py` | GitLab MCP connectivity smoke test (`--server community\|official`) |
| `memory/` | Living project docs — `HANDOFF.md` is the authoritative briefing |

## Setup

1. Python 3.12 virtualenv: `python -m venv .venv`, then
   `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`
2. Node 20+ on PATH (the GitLab MCP server is spawned via `npx`).
3. Copy `.env.example` → `.env` and fill in: `MONGODB_URI`, `GITLAB_TOKEN`, `WEBHOOK_SECRET`
   (GCP project/location and GitLab project IDs are prefilled).
4. GCP: Application Default Credentials with Vertex AI access
   (`gcloud auth application-default login`).

## Run

```powershell
# Web app → http://127.0.0.1:8080
$env:PYTHONUTF8="1"; .\.venv\Scripts\python.exe -m uvicorn server:app --port 8080

# Ingest corpus (resumable; --force re-embeds)
.\.venv\Scripts\python.exe ingest.py run --limit 150

# Label outcomes / enrich revert pairs
.\.venv\Scripts\python.exe label.py
.\.venv\Scripts\python.exe enrich_reverts.py

# Interactive agent (ADK)
.\.venv\Scripts\python.exe -m google.adk.cli run recall_agent
```

Deploy: `docker build -t recall .` or `gcloud run deploy recall --source .` (full command and
required secrets in `memory/HANDOFF.md`).

## License

MIT — see `LICENSE`.
