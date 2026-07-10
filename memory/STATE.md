# Recall — Current State

> Snapshot of where the project actually is. Update at the end of each working day.
> For *how* we build, see `IMPLEMENTATION_PLAN.md`.

**Last updated:** May 29, 2026 (D1)
**Current day:** D1 of 14 (deadline Jun 11, 2026 @ 2:00pm PDT) — far ahead (P0–P4 built on D1)
**Current eng. phase:** Phase 4 — Surface (deploy left), then Phase 5 — Ship

---

## Engineering phases (see plan §7)
- [x] **P0 Foundations** (D1) — setup ✅; MCP smoke-test ✅ (community); `ingest.py` scaffold ✅
- [x] **P1 Corpus** (D2–D4) — ingest ✅ (158 docs, 768-d, vector search ✅); labeling ✅ (real signal, sparse); D4 validation optional
- [x] **P2 Agent core** (D5–D6) — lean ADK agent ✅; 3 Mongo tools ✅; GitLab MCP toolset ✅ (live calls verified)
- [x] **P3 Workflows** (D7–D9) — Change Triage ✅ + Prior-Art ✅ (posted to demo MRs !1/!2 via MCP)
- [~] **P4 Surface** (D10–D12) — FastAPI UI + SSE ✅; webhook ✅ (verified end-to-end); **Cloud Run deploy left**
- [ ] **P5 Ship** (D13–D14) — demo video + README + Devpost submit
- [ ] **P5 Ship** (D13–D14) — polish + video + submit

---

## Status by day
- **D1 (May 29) — IN PROGRESS**
  - [x] GCP project `recall-hackathon` + 6 APIs enabled
  - [x] gcloud auth + ADC configured
  - [x] Gemini hello-world verified (`gemini-2.5-flash`)
  - [x] MongoDB Atlas M0 `recall-cluster` up; user `recall-app`; network access set
  - [x] DB `recall` / coll `merge_requests`; vector index `mr_diff_embedding_index` ACTIVE
  - [x] Mongo ping + vector search + write/delete verified
  - [x] GitLab token verified; source `34675721` + demo `82111266` confirmed
  - [x] Local venv + 3 packages (`google-genai`, `pymongo[srv]`, `python-dotenv`)
  - [x] `.env` filled (6 vars); `.gitignore` excludes `.env`/`.venv`
  - [x] Public GitHub repo `recall` (MIT) pushed
  - [x] Partner resource pages read & cross-checked
  - [x] GitLab MCP smoke-test ✅ via **community** `@zereight/mcp-gitlab` (58 tools, called `list_merge_requests`)
  - [x] Scaffold `ingest.py` — `fetch_one_mr()` returns real data (MR 3302 verified)
  - [x] Fixed UTF-8 BOM in `.env` / `.env.example` (was breaking `GCP_PROJECT_ID`)
  - [x] `requirements.txt` pinned (google-genai, pymongo[srv], python-dotenv, requests, mcp)
  - [~] **Official Duo MCP:** all prereqs done (group `saisravan10231` on ultimate_trial, Duo+beta on,
    default namespace set, OAuth works) BUT `/api/v4/mcp` still 404s — GitLab-side propagation/beta bug.
    Re-check command + diagnosis in HANDOFF. Community MCP works now; does NOT block Phase 1.
- **D2 (ingestion) — DONE early (on D1):** `ingest.py` full pipeline; 150 MRs from gitlab-org/cli
  → MongoDB `recall.merge_requests`, all 768-d embeddings, vector search verified. ingested=147 skipped=3 failed=0.
- **D5–D6 (agent core) — DONE early (on D1):** `recall_agent/` (db, tools, agent). ADK `Agent` on
  `gemini-2.5-flash` (Vertex). 3 Mongo tools tested in isolation; agent verified calling
  `vector_search_similar_mrs` (cited+banded) and MCP `list_merge_requests` (community server).
- **D7–D9 (workflows) — DONE early (on D1):** `recall_agent/scorer.py` (deterministic ranking + bands),
  `recall_agent/workflows.py` (change_triage, prior_art_review), `recall_agent/gitlab_mcp.py` (MCP write).
  Change Triage surfaced reverted !2190 #1; Prior-Art posted to demo MR !1 via MCP.
- **D3 labeling — DONE** (`label.py` + `enrich_reverts.py`): real signal only, sparse (1 reverted, 1 incident).
- **D10–D12 (surface) — built early (on D1):** `server.py` (FastAPI + HTMX + SSE + Tailwind);
  pages `/` (Change Triage streamed), `/mrs` (prior-art list), `POST /webhook`, `/health`. Webhook
  verified end-to-end (MR !2 auto-commented in ~18s). `Dockerfile` (+Node 20) + `.dockerignore` ready.
- **Cloud Run deploy NOT yet run** (needs gcloud build; GCP credits pending) — command in HANDOFF.
- D4 validation optional; D13–D14 (Ship): see roadmap in `IMPLEMENTATION_PLAN.md` §7.

---

## Decisions log
- 2026-05-29: Roadmap recompressed 21d → 14d to fit Jun 11 deadline.
- 2026-05-29: Phase 2 (Incident Recall) & Phase 3 (router) CUT — no room.
- 2026-05-29: Embedding model `text-embedding-005` confirmed compliant (Google-provided).
- 2026-05-29: Confirmed split — REST for ingestion, MCP only for agent-time (24-credit budget).
- 2026-05-29: Change Triage ranking = **deterministic scorer + Gemini narration** (stable order, visible reasoning).
- 2026-05-29: Deploy unit = **pipelines** (`list_pipelines`, mapped to MRs by merge SHA); **merges as fallback** if sparse.
- 2026-05-29: Confidence bands rubric fixed (strong/moderate/weak — see plan §5.7).
- 2026-05-29: Prior-Art = top-3 analogues; **post "no strong prior art" comment** when below threshold (never silent).
- 2026-05-29: Time window accepts relative + absolute (default relative).
- 2026-05-29: MCP path = **official GitLab Duo MCP** (partner story); community PAT server = dev/runtime fallback.
- 2026-05-29: Learned official MCP uses OAuth DCR (browser), requires Premium/Ultimate + Duo on a top-level group.
- 2026-05-29: Embeddings via Vertex AI (`genai.Client(vertexai=True)`) + ADC — text-embedding-005 needs Vertex, not the Gemini Developer API.
- 2026-05-29: Embed input capped at 6k chars (under the 2048-token model limit); stored diff capped at 20k. Revisit raw-vs-summary on D4.
- 2026-05-29: P2 built lean ADK agent in-repo (`recall_agent/`) instead of Agent Starter Pack — coherence + control; add starter-pack deploy scaffolding in P4 if needed.
- 2026-05-29: google-adk 2.1.0 pins google-genai to 1.75.0 (downgraded from 2.0.1); embeddings still work. requirements.txt updated.
- 2026-05-29: Agent uses community GitLab MCP (read-only) for now; flip GITLAB_READ_ONLY_MODE=false in P3 for create_merge_request_note.
- 2026-05-29: P3 workflows are deterministic Python pipelines (scorer decides order; Gemini narrates) — stable/demoable, not LLM-driven ranking.
- 2026-05-29: Change Triage enumerates from corpus by merged_at window (the documented merges fallback) — reliable; MCP list_pipelines can layer in later.
- 2026-05-29: Prior-Art fetches diff via REST, posts via MCP (the showcase write). Created demo_mr.py to open test MRs in the fork.
- 2026-05-29: Corpus outcome signal is genuinely sparse (healthy repo) — kept labels honest rather than fabricating; can enrich via human review (D5).
- 2026-05-29: P4 web app is a single `server.py` (FastAPI) with inline HTML (Tailwind+HTMX via CDN); SSE via EventSource. Simpler than a templates dir for a hackathon.
- 2026-05-29: Change Triage streams over SSE (status → suspects → narration tokens via generate_content_stream).
- 2026-05-29: Dockerfile installs Node 20 because the container must spawn the GitLab MCP server (npx) for prior-art posting.
- 2026-05-29: Added WEBHOOK_SECRET env var (verified via X-Gitlab-Token header).
- 2026-05-29: UI/UX refinements (review feedback): bands are now OUTCOME-driven (strong = bad outcome
  + sim≥0.60; moderate = bad outcome weak match OR sim≥0.78; else weak) so they actually spread;
  removed numeric similarity from UI (bands only); triage narration reduced to a 1-2 sentence read
  (cards are primary); narration rendered as markdown (marked.js); window options are time-based
  (6h/24h/7d/30d/90d/1y, default 7d). Verified: !2190 strong, !3321 moderate, rest weak.
- 2026-05-29: UI redesigned to a "dossier" aesthetic — warm espresso-dark canvas, aged manila/paper
  panels, Spectral serif + IBM Plex Mono labels, confidence bands as rubber-stamp marks
  (oxblood/amber/faded). Case-file framing ("Open the file", "Suspects on file", "Prior-art filed").

## Open questions / blockers
- **Official Duo MCP 404 (GitLab-side):** every documented prereq satisfied; `/api/v4/mcp` still
  404s via direct PAT. Propagation lag or known bug gitlab-org/gitlab#579602. Re-check later (HANDOFF
  has the one-liner). Community MCP works; does NOT block Phase 1.
- Headless OAuth for Cloud Run agent (Phase 2): solve via cached `mcp-remote` token or OAuth app + Secret Manager.
- $100 GCP credits: approval pending (non-blocking).

## Pending embedding-strategy decision (D4)
- Raw `diff_text` (default) vs LLM `diff_summary`. Decide via 5-pair top-3 validation.
