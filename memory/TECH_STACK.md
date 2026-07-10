# Recall — Tech Stack

> The full technology stack for Recall, what each piece is for, and how it's wired.
> For the build plan see `IMPLEMENTATION_PLAN.md`; for live status see `STATE.md` / `HANDOFF.md`.

---

## At a glance

| Layer | Technology | Role |
|---|---|---|
| LLM | Google **Gemini 3 Flash** (`gemini-2.5-flash` verified) | Reasoning + narration |
| Embeddings | Google **text-embedding-005** (768-d, cosine) | Diff → vector for similarity search |
| Agent framework | **ADK** (Agent Development Kit, Python) | Agent runtime, tool-calling |
| Scaffolding | **Agent Starter Pack** | Generates Cloud-Run-ready ADK project |
| Memory / DB | **MongoDB Atlas M0** + **Vector Search** | Corpus store + semantic retrieval |
| DB driver | **pymongo[srv]** | Python ↔ Atlas |
| Action surface | **GitLab Duo MCP server** (beta) | Agent-time GitLab actions |
| Ingestion | **GitLab REST API v4** | One-time bulk history pull |
| Web framework | **FastAPI** | HTTP app + webhook receiver |
| Interactivity | **HTMX** | Server-driven UI without heavy JS |
| Streaming | **Server-Sent Events (SSE)** | Stream agent reasoning to the browser |
| Styling | **Tailwind CSS** | UI styling |
| Runtime/host | **Google Cloud Run** | Hosts web app + webhook |
| Build/registry | **Cloud Build** + **Artifact Registry** | Container build + image storage |
| Secrets | **Secret Manager** | Prod credentials |
| Observability | **Cloud Logging** | Logs/traces |
| Config (local) | **python-dotenv** + `.env` | Local env vars |
| Language | **Python 3.11+** (venv at `.venv`) | All backend code |
| Source control | **Git** + public **GitHub** repo `recall` (MIT) | Code + submission artifact |

---

## Google Cloud

- **Project:** `recall-hackathon` · **Region:** `us-central1` (matches Atlas region for latency).
- **APIs enabled:** Agent Platform (Vertex AI), Cloud Run, Cloud Build, Artifact Registry,
  Secret Manager, Cloud Logging.
- **Auth:** gcloud CLI authenticated; Application Default Credentials (ADC) for local SDK calls.
- **Credits:** $100 hackathon credits — form submitted, approval pending (non-blocking).

### Gemini 3 Flash
- Verified reachable (`gemini-2.5-flash`) from local via `google-genai`.
- Used for: Change Triage narration, Prior-Art comment composition, (optional) diff summaries.

### text-embedding-005
- 768-dim output, cosine similarity. Google-provided → satisfies MongoDB's "model must be
  MongoDB- or Google-provided" requirement.
- Used at build-time (embed each MR diff) and runtime (embed a new MR diff for Prior-Art).

---

## MongoDB Atlas

- **Cluster:** `recall-cluster` (M0 free tier), GCP `us-central1`.
- **DB / collection:** `recall` / `merge_requests`.
- **User:** `recall-app` (readWriteAnyDatabase). **Network:** laptop IP + `0.0.0.0/0` (for Cloud Run).
- **Connection:** `MONGODB_URI` in `.env`.
- **Vector index:** `mr_diff_embedding_index` (ACTIVE) — 768-d cosine on `embedding`,
  plus structured filters on `outcome` and `project_id`.
- **Access pattern:** `pymongo[srv]` for ingestion + agent tools. (MongoDB MCP server exists but
  is NOT used — we call Mongo directly.)

---

## GitLab

- **Account:** `saisravan1023`. **Token:** PAT `recall-agent` (api scope) in `.env` as `GITLAB_TOKEN`.
- **Source repo:** `gitlab-org/cli` — project ID `34675721` (corpus source, 3,222 MRs).
- **Demo repo (fork):** `saisravan1023/cli-recall` — project ID `82111266` (live demo MRs).

### REST API v4 — ingestion only
- Bulk historical pull (Day 2). No Duo credit cost. Already verified against `/user` and MRs.

### Duo MCP server (beta) — agent-time only
- **Prerequisite:** external tools calling GitLab via MCP must set a **default Duo namespace**.
- **Credit budget:** Duo Agent Platform trial = **24 credits/user** → use MCP sparingly in dev.
- **Tools needed:** `list_merge_requests`, `get_merge_request_changes`, `list_pipelines`,
  `create_merge_request_note`.
- **Fallback:** community `@zereight/mcp-gitlab` server if the official beta fails.

---

## Agent layer (ADK)

- Scaffolded via `agent-starter-pack create recall-agent -a adk -d cloud_run --prototype` (Day 5).
- **Custom Mongo tools:** `vector_search_similar_mrs`, `get_mr_record`, `filter_by_outcome`.
- **MCP toolset:** GitLab Duo MCP (4 tools above).
- Gemini 3 Flash as the model; deterministic scorer (plain Python) sits alongside the agent for
  Change Triage ranking — Gemini narrates, scorer decides order.

---

## Web / frontend

- **FastAPI** app on Cloud Run: two pages (Change Triage chat, MR list view) + `POST /webhook`.
- **HTMX** for partial updates; **SSE** to stream agent reasoning token-by-token.
- **Tailwind** for styling.

---

## Python dependencies (installed Day 1; pin versions at install time)
- `google-genai` — Gemini + embeddings.
- `pymongo[srv]` — Atlas access.
- `python-dotenv` — local `.env` loading.
- _To add later:_ `fastapi`, `uvicorn`, ADK / `agent-starter-pack`, GitLab REST client (or `requests`/`httpx`).

> Maintain a `requirements.txt` once Phase 1 code lands; pin exact versions for reproducible Cloud Run builds.

---

## Environment variables (`.env`, gitignored)
| Var | Purpose |
|---|---|
| `GCP_PROJECT_ID` | `recall-hackathon` |
| `GCP_LOCATION` | `us-central1` |
| `MONGODB_URI` | Atlas connection string |
| `GITLAB_TOKEN` | PAT (api scope) |
| `GITLAB_PROJECT_ID_SOURCE` | `34675721` (corpus source) |
| `GITLAB_PROJECT_ID_DEMO` | `82111266` (demo fork) |

`.env.example` mirrors these with secrets blanked.
