# Recall — Handoff

> Living handoff doc. Read this first when picking the project back up. Update it at the end of
> every working session: what changed, what's next, anything that would surprise the next person
> (or the next AI session). Keep it short and current.

**Last updated:** Jul 9, 2026 (housekeeping: requirements fix, .gitignore, real README)

---

## TL;DR — where we are right now
- **Phase 0–3: DONE.** Corpus (158 MRs), ADK agent, both workflows verified live.
- **Phase 4 (Surface): built + tested LOCALLY.** FastAPI app (`server.py`): Change Triage page with
  SSE-streamed reasoning, MR-list/prior-art page, `POST /webhook`, `/health`. Webhook verified
  end-to-end (new MR → auto prior-art comment in ~18s). **Remaining: actual Cloud Run deploy.**
- **Code:** `ingest.py` · `label.py` · `enrich_reverts.py` · `demo_mr.py` · `mcp_smoke.py` ·
  `server.py` · `recall_agent/` (agent, tools, db, scorer, workflows, gitlab_mcp) ·
  `Dockerfile` · `.dockerignore` · `requirements.txt`.
- **Official Duo MCP:** still 404 (GitLab-side); everything uses the community PAT server. Not blocking.
- `memory/` holds: `IMPLEMENTATION_PLAN.md`, `STATE.md`, `TECH_STACK.md`, this file.

## Phase 4 — what works (verified D1, locally)
- `server.py` (FastAPI + HTMX + Tailwind CDN). Pages: `/` Change Triage (EventSource → SSE), `/mrs`
  prior-art list (shows demo MRs + posted Recall comments), `POST /webhook`, `GET /health`.
- SSE endpoint `/api/triage/stream` streams: status events → suspects payload → narration tokens →
  done. Verified streaming with reverted !2190 ranked #1.
- Webhook: verifies `X-Gitlab-Token` against `WEBHOOK_SECRET`; on merge_request open/reopen/update,
  runs `prior_art_review(..., post=True)` as a BackgroundTask. Verified: MR !2 got an auto comment.
- New env var: `WEBHOOK_SECRET` (in `.env`; blank in `.env.example`).
- Run locally: `uvicorn server:app --port 8080` then open http://127.0.0.1:8080
- `Dockerfile` installs **Node 20** (needed so the container can spawn the GitLab MCP server via npx).

## Cloud Run deploy (NOT yet run — needs gcloud + build; GCP credits pending)
```
gcloud run deploy recall --source . --region us-central1 --project recall-hackathon \
  --allow-unauthenticated --port 8080 \
  --set-env-vars GCP_PROJECT_ID=recall-hackathon,GCP_LOCATION=us-central1,GITLAB_PROJECT_ID_SOURCE=34675721,GITLAB_PROJECT_ID_DEMO=82111266 \
  --set-secrets MONGODB_URI=...,GITLAB_TOKEN=...,WEBHOOK_SECRET=...   # via Secret Manager
```
- Service account needs **Vertex AI User** (for ADC embeddings/Gemini) + read access to the secrets.
- After deploy: set the GitLab webhook on the fork → `<run-url>/webhook` with the secret token.

## Phase 3 — what works (verified D1)
- **Change Triage** (`workflows.change_triage(symptom, window_days)`): enumerate corpus by merged_at
  window → deterministic `scorer.rank_suspects` (similarity + outcome-risk + file overlap) → Gemini
  narration. Verified: reverted MR !2190 ranked #1 for an `.fdignore`/markdown symptom, cited + banded.
- **Prior-Art Review** (`workflows.prior_art_review(project_id, mr_iid, post=)`): fetch diff (REST)
  → vector search top-4 → outcomes → Gemini comment → optional MCP post. Verified: opened demo MR !1
  (re-adds `.fdignore`), surfaced !2190 as **reverted / strong**, and POSTED the comment via MCP
  `create_merge_request_note` (read_only=false). Live: cli-recall MR !1.
- **Corpus labels (real signal only):** 156 shipped_clean, 1 reverted (!2190 ←!2771), 1 incident.
  Sparse by nature (healthy repo); `label.py` auto-detects reverts + title incident keywords;
  `enrich_reverts.py` pulled real revert pairs. Human thread-reading (D5) can enrich further.

## Gotchas
- Windows console can't print the 🧠 emoji in comments (cp1252). Use `$env:PYTHONUTF8=1` when
  printing to console; irrelevant for API/MCP/web (all UTF-8).
- `prior_art_review` imports `ingest.GitLabClient` — run from repo root so `import ingest` resolves.

## Agent layer (recall_agent/)
- `db.py` — Mongo collection + Vertex genai client + `embed_query` (RETRIEVAL_QUERY, 768-d).
- `tools.py` — `vector_search_similar_mrs`, `get_mr_record`, `filter_by_outcome` (plain functions;
  docstrings ARE the tool schemas). All tested in isolation.
- `agent.py` — `root_agent` (ADK `Agent`, model `gemini-2.5-flash` via Vertex) + GitLab MCP toolset
  (community `@zereight/mcp-gitlab`, stdio/npx, `GITLAB_READ_ONLY_MODE=true` for now).
- Verified: agent calls `vector_search_similar_mrs` (cited + banded output) AND MCP
  `list_merge_requests`. Run via ADK: `adk run recall_agent` or `adk web`.
- **Phase 3 TODO:** set `GITLAB_READ_ONLY_MODE=false` to expose `create_merge_request_note` for posting.

## Corpus snapshot (recall.merge_requests)
- 150 docs from `gitlab-org/cli` (project 34675721). 0 failures.
- Every doc: 768-d `embedding` (text-embedding-005, RETRIEVAL_DOCUMENT), `files_touched` populated.
- diff_text: median ~3.7k chars, capped at 20k stored / 6k embedded. 31 distinct authors.
- `outcome` = None on all (filled in D3 labeling). Vector search index `mr_diff_embedding_index` works.

## P0 results (this session)
- **`ingest.py`** — `Config.from_env`, `GitLabClient`, `fetch_one_mr`, `to_record`, smoke-test
  `__main__`. Verified against `gitlab-org/cli`: returned MR 3302 (real title/author/6 files/16.5K diff).
  Day-2 stubs raise `NotImplementedError`: `embed_diff`, `upsert_record`, `run_ingest`.
- **`mcp_smoke.py`** — reusable GitLab MCP client. `--server community` ✅ (58 tools, called
  `list_merge_requests`). `--server official` ⏳ returns "Session terminated" (Duo namespace not set).
- **Bug fixed:** UTF-8 BOM on `.env`/`.env.example` first line made `GCP_PROJECT_ID` invisible — stripped.
- **`requirements.txt`** pinned (google-genai 2.0.1, pymongo[srv] 4.17.0, python-dotenv 1.2.2,
  requests 2.34.0, mcp 1.27.2).

## ⚠️ MCP auth — corrected understanding (important)
- Official GitLab MCP server = `https://gitlab.com/api/v4/mcp`, authenticated via **OAuth 2.0
  Dynamic Client Registration** (opens a browser to approve), **NOT** a PAT header. That's why our
  PAT-bearer attempt returned "Session terminated". `mcp_smoke.py --server official` now uses
  `npx mcp-remote` (the OAuth path).
- Official MCP requires **Premium/Ultimate** + **GitLab Duo enabled on a top-level GROUP**
  (personal namespace does NOT expose Duo settings). Account is currently **free tier**.
- DECISION (2026-05-29): pursue the **official** Duo MCP (strongest GitLab-partner story).

## Official Duo MCP — all prereqs DONE, but endpoint still 404s (GitLab-side)
Verified namespaces (they differ by ONE char — easy to confuse):
- `saisravan1023`  = **personal user namespace** (kind=user) — NOT Agent-Platform capable.
- `saisravan10231` = **group** (id 126849241), `plan=ultimate_trial`, trial ends 2026-06-29. ← the real one.
- `recall` project lives in the **group**. Default Duo namespace = the group (only dropdown option).

Completed prereqs: Ultimate trial on group ✓ · Duo Core ✓ · beta/experimental features ✓ ·
default Duo namespace ✓ · OAuth DCR flow completes ✓.

**Symptom:** `POST https://gitlab.com/api/v4/mcp` → `404 Not Found`, even with a direct PAT
(no client/OAuth involved). So it's GitLab's feature gate, not our code.
**Likely cause:** trial/feature propagation lag (settings ~15 min old) OR known beta bug
(gitlab-org/gitlab#579602: /api/v4/mcp 404s despite correct config).

**Re-check later (browser-free, run periodically):**
```
.\.venv\Scripts\python.exe -c "import os,requests;from dotenv import load_dotenv;load_dotenv();r=requests.post('https://gitlab.com/api/v4/mcp',headers={'Authorization':'Bearer '+os.environ['GITLAB_TOKEN'],'Content-Type':'application/json'},json={'jsonrpc':'2.0','id':1,'method':'tools/list'});print(r.status_code,r.text[:200])"
```
When it returns 200 (not 404), run `python mcp_smoke.py --server official` to finish validation.

- **Headless concern (Phase 2):** official MCP OAuth browser flow doesn't fit a Cloud Run agent
  anyway. Plan: reuse `mcp-remote` cached token OR register a GitLab OAuth app + Secret Manager.
- **DECISION:** community PAT MCP server is the working runtime surface NOW; official is for the
  partner-integration story once GitLab's gate opens. Neither blocks Phase 1 (Corpus).

## What changed (Jul 9, 2026 — housekeeping session)
- **Fixed a Cloud Run blocker:** `requirements.txt` was missing `fastapi`/`uvicorn`, so the Docker
  image would build but crash at `CMD uvicorn server:app`. Pinned `fastapi==0.136.3`,
  `uvicorn==0.48.0` (versions from the working `.venv`).
- Rewrote `.gitignore` (env variants with `!.env.example`, caches, editor dirs, logs).
- Replaced the 2-line `README.md` stub with a real one (overview, architecture, layout, setup,
  run, deploy pointer) — partial credit toward the P5 README task.
- Deleted stray `__pycache__/` dirs. No source files moved: the flat layout is load-bearing
  (`enrich_reverts.py` imports `ingest`/`label`; `workflows` imports `ingest` from repo root).
- **Note:** almost all source is still untracked in git (only LICENSE/README/.gitignore committed).

## What changed this session
- Read partner resource pages; cross-checked against plan.
- Discovered + resolved a timeline conflict (21-day plan → recompressed to 14 days; deadline Jun 11).
- Cut product Phase 2 & 3 (no time).
- Designed both Phase-1 workflows (see decisions below).
- Wrote planning docs; restructured the build into 5 engineering phases (P0–P5).

## Key design decisions (locked)
- **Change Triage ranking:** deterministic scorer decides order; Gemini narrates with citations.
- **Deploy unit:** pipelines (`list_pipelines`, mapped to MRs by merge SHA); merges as fallback.
- **Prior-Art:** top-3 analogues; post a "no strong prior art" comment when below threshold (never silent).
- **Confidence bands:** strong/moderate/weak rubric (plan §5.7), never numeric.
- **Embedding model:** `text-embedding-005` (768-d). Raw-diff vs summary decided on Day 4.
- Full log in `STATE.md` → Decisions log.

## Next actions (in order)
1. **Deploy to Cloud Run** (command above) → get the public URL; set the GitLab webhook on the fork.
2. **Phase 5 (Ship):** record 3-min demo video, finalize README + project description, submit on Devpost.
3. **Quality polish (optional):** richer outcome labels via human thread-reading; D4 vector validation;
   tune scorer weights in `scorer.py`.
4. **(Background) re-check official MCP** with the one-liner above when convenient.
5. See `IMPLEMENTATION_PLAN.md` §7 for the rest.

## Open / blocked
- GitLab Duo default namespace not set → official Duo MCP blocked. **Not blocking** (community fallback works).
- $100 GCP credits: approval pending (non-blocking).

## How to run
- Python: use `.venv` (Python 3.12.4). On Windows call `.\.venv\Scripts\python.exe <script>`.
- Install deps: `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`.
- Env: `.env` (gitignored) holds all 6 vars. Never commit it. Keep it BOM-free.
- Ingestion smoke (one MR): `.\.venv\Scripts\python.exe ingest.py smoke`
- Ingestion full: `.\.venv\Scripts\python.exe ingest.py run --limit 150` (resumable; `--force` to re-embed).
- MCP smoke-test: `.\.venv\Scripts\python.exe mcp_smoke.py --server community` (or `--server official`).
- Run the agent: `.\.venv\Scripts\python.exe -m google.adk.cli run recall_agent` (or `... adk.cli web`).
- Re-label corpus: `.\.venv\Scripts\python.exe label.py` · enrich reverts: `... enrich_reverts.py`
- Open a demo MR: `.\.venv\Scripts\python.exe demo_mr.py`
- Workflows are Python: `from recall_agent.workflows import change_triage, prior_art_review`.
- Web app: `$env:PYTHONUTF8="1"; .\.venv\Scripts\python.exe -m uvicorn server:app --port 8080` → http://127.0.0.1:8080
- Build image: `docker build -t recall .` (or deploy via `gcloud run deploy ... --source .`).

---

## Working conventions (honor these in all code)
- **No unnecessary comments.** Do not narrate what the code does. Comments only for non-obvious
  intent, trade-offs, or constraints the code can't express. No "// import X", "// loop over Y".
- **Always maintain this `HANDOFF.md`.** Update it at the end of every session.
- **Secrets stay in `.env`** (gitignored); use Secret Manager for Cloud Run. Never hardcode.
- **REST for ingestion, MCP only at agent-time** (24 Duo-credit budget).
- **Pin dependency versions** in `requirements.txt` once code exists (reproducible Cloud Run builds).
- **Evidence-cited, discrete-confidence, surfaces-not-decides** — the three product principles are
  non-negotiable in any agent output.
