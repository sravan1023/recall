# Recall — Implementation Plan

> Living implementation plan for the Recall project. This file is the source of truth
> for *how* we build. Update it as decisions are made. See `STATE.md` for current status.

---

## 1. What we're building

**Recall** is an AI agent that gives small engineering teams the institutional memory of a
much bigger one — answering *"What changed that broke this?"* and *"Has anyone tried this
kind of change before?"* by reasoning over their GitLab history.

**Hackathon:** Google Cloud Rapid Agent Hackathon. **Submission deadline: Jun 11, 2026 @ 2:00pm PDT.**

**Track:** GitLab (primary) + MongoDB (memory substrate).

### Phase 1 workflows (committed)
1. **Change Triage** — engineer gives a *symptom* + *time window*; agent enumerates MRs/deploys
   in that window, looks up each one's stored outcome and similar past diffs, returns a
   **ranked suspect list** with cited evidence and **confidence bands (strong / moderate / weak)**.
2. **Prior-Art Review** — a new MR opens in the demo repo → GitLab webhook fires → agent fetches
   the diff, vector-searches similar past MRs, looks up their outcomes, and posts a
   "DiffSense-style" comment back to the MR thread.

### Non-negotiable design principles (encode into agent + UI)
1. **Evidence citation is mandatory** — every claim cites a concrete signal.
2. **Confidence is discrete** (strong/moderate/weak), never numeric.
3. **The agent surfaces; the human decides.** Never says "this caused the incident."

### Scope decision (locked given 13-day timeline)
- **Phase 2 (Incident Recall) and Phase 3 (router agent) are CUT.** They were gate-conditional
  and there is no room. Phase 1 alone is a strong submission.

---

## 2. Architecture

```
                         ┌─────────────────────────────────────────┐
                         │            Cloud Run (web app)           │
                         │  FastAPI + HTMX + SSE  (Tailwind UI)      │
                         │   • Change Triage chat (streamed)        │
                         │   • MR list view + prior-art comments    │
                         │   • /webhook  (GitLab MR events)         │
                         └───────────────┬─────────────────────────┘
                                         │
                                ┌────────▼─────────┐
                                │   ADK Agent      │  Gemini 3 Flash
                                │ (Agent Dev Kit)  │
                                └───┬───────────┬──┘
                  custom tools      │           │   MCP toolset
            ┌─────────────────────▼─┐       ┌──▼───────────────────────┐
            │  MongoDB Atlas (M0)    │       │  GitLab Duo MCP (beta)   │
            │  recall.merge_requests │       │  list_merge_requests     │
            │  Vector Search index   │       │  get_merge_request_changes│
            │  (768-d cosine)        │       │  list_pipelines          │
            │  filters: outcome,     │       │  create_merge_request_note│
            │  project_id            │       └──────────────────────────┘
            └────────────────────────┘
                  ▲
                  │ batch ingest (REST API, one-time, Day 2)
            ┌─────┴──────────────────┐
            │  ingest.py (standalone)│  GitLab REST + Gemini embeddings
            └────────────────────────┘
```

**Key split:** GitLab **REST API** is used for one-time bulk ingestion (no Duo credit cost).
GitLab **MCP server** is used only for *agent-time* actions (consumes the 24 Duo credits — stay frugal).

---

## 3. Tech stack & accounts (all verified Day 1)

| Layer | Choice | Notes |
|---|---|---|
| LLM | Gemini 3 Flash (`gemini-2.5-flash` verified) | via `google-genai` |
| Embeddings | `text-embedding-005` (768-d, cosine) | Google-provided → MongoDB-compliant |
| Agent framework | ADK (Python), scaffolded via Agent Starter Pack | installed Day 5 (was D8) |
| Memory | MongoDB Atlas M0 `recall-cluster` (GCP us-central1) | DB `recall`, coll `merge_requests` |
| Vector index | `mr_diff_embedding_index` (ACTIVE) | 768-d cosine + filters `outcome`, `project_id` |
| Action surface | GitLab Duo MCP server (beta) | **requires default Duo namespace** (see §7) |
| Frontend | FastAPI + HTMX + SSE + Tailwind | streamed reasoning |
| Deploy | Cloud Run + Cloud Build + Artifact Registry | Secret Manager for prod creds |
| Observability | Cloud Logging | |
| Repo | Public GitHub `recall`, MIT | secrets gitignored |

**Source repo:** `gitlab-org/cli` (project ID `34675721`, 3,222 MRs of real history).
**Demo repo (fork):** `saisravan1023/cli-recall` (project ID `82111266`), live demo MRs in Week 3.

---

## 4. Data model

MongoDB `recall.merge_requests` — one document per ingested MR:

```jsonc
{
  "mr_id": 12345,                    // GitLab MR iid
  "project_id": 34675721,            // source or demo project id
  "title": "Bump go-gitlab to v0.x",
  "description": "…",                // MR description (markdown)
  "diff_text": "…",                  // raw unified diff (truncated to a budget)
  "diff_summary": "…",               // LLM-summarized diff (embedding candidate; decide D4)
  "embedding": [/* 768 floats */],   // text-embedding-005 over diff_text OR diff_summary
  "files_touched": ["pkg/foo.go"],
  "author": "username",
  "merged_at": "2026-05-01T12:00:00Z",

  // outcome fields — filled during Day 3 labeling
  "outcome": "shipped_clean",        // shipped_clean | reverted | linked_to_incident
  "outcome_evidence": "…",           // why we labeled it that way (cited signal)
  "reverted_by_mr": null,            // mr_id of the revert, if any
  "linked_incident": null            // issue ref, if any
}
```

**Embedding strategy is a DECISION POINT (Day 4):** embed raw `diff_text` vs `diff_summary`.
Default to raw diff; switch to LLM summary only if hand-validation (5 pairs in top-3) fails.

---

## 5. Components to build

### 5.1 `ingest.py` (Phase 1 · Day 2)
Standalone script. Steps:
1. Load `.env` (`GITLAB_TOKEN`, `GITLAB_PROJECT_ID_SOURCE`, `MONGODB_URI`, `GCP_*`).
2. `fetch_one_mr(mr_iid)` → fetch MR metadata + changes via REST.
3. Pull last **100–150 merged** MRs from `gitlab-org/cli` (`state=merged`, paginate).
4. For each: fetch diff, build `diff_text` (+ optional `diff_summary`), `files_touched`.
5. Generate `text-embedding-005` embedding (768-d).
6. Upsert into `recall.merge_requests` (idempotent on `mr_id`+`project_id`).
7. Verify count + a sample embedding length == 768.

Guardrails: rate-limit awareness, diff size budget (truncate huge diffs), resumable (skip
already-ingested mr_ids).

### 5.2 Outcome labeling (Phase 1 · Day 3)
Manual / semi-automated pass over the corpus:
- **Easy:** "Revert" in title → `reverted` (link back to original mr → set `reverted_by_mr`).
  Issues tagged "incident" → `linked_to_incident`.
- **Hard:** read discussion threads; judgment call. Default `shipped_clean`.
- Optionally a helper script that surfaces revert/incident candidates to speed this up.
- Fill `outcome`, `outcome_evidence`, `reverted_by_mr`, `linked_incident`.

### 5.3 Agent tools (Phase 2 · Day 5–6)

**MongoDB custom tools (Day 5):**
- `vector_search_similar_mrs(query_embedding | mr_id, k, filters)` → top-k similar MRs.
- `get_mr_record(mr_id)` → full stored record incl. outcome.
- `filter_by_outcome(outcome, project_id, time_window?)` → MRs matching structured filters.

**GitLab MCP tools (Day 6):**
- `list_merge_requests`, `get_merge_request_changes`, `list_pipelines`, `create_merge_request_note`.

### 5.4 Workflow prompts (Phase 3 · Day 7–8)

**Change Triage (Day 7):** inputs `symptom`, `time_window` (relative *or* absolute; default relative).

Ranking model = **deterministic scorer + Gemini narration** (decided 2026-05-29):
1. **Enumerate deploys in window** via `list_pipelines` (MCP); map each pipeline → the MR that
   produced it by merge-commit SHA. **Fallback: merged MRs** if pipeline data is sparse.
2. **Deterministic scorer** ranks the candidate MRs by a stable, defensible score:
   `outcome weight` (reverted / linked_to_incident float to top) + `MR-to-MR similarity`
   (vector search vs known-bad analogues) + `file/area overlap` with the symptom. This keeps the
   ranking stable across demo takes (no live reshuffle) and leans on the labeled corpus.
3. **Gemini narration pass** explains each suspect in cited prose as it streams (the visible
   "reasoning" the SSE UI shows). Gemini explains; the scorer decides the order.
4. Output: ranked suspect list, each with **cited evidence** + **strong/moderate/weak** band.
   System prompt enforces citation discipline + "surfaces, never concludes."

> Why not pure-LLM ranking: non-deterministic order + latency spikes are risky in a 3-min demo.
> Why not pure-deterministic: streamed reasoning would look mechanical. Hybrid gets both.

**Prior-Art Review (Day 8):** input `mr_id`. Pipeline: `get_merge_request_changes` (MCP) →
embed diff → `vector_search_similar_mrs` (**top-3** analogues) → `get_mr_record` on analogues →
compose comment → `create_merge_request_note` (MCP) to post.
- **Comment shape:** one-line framing → per analogue: MR link + title + **outcome** + similarity
  reason (files/approach) + confidence band → "surfaces, doesn't decide" footer.
- **No-match path:** if nothing clears the similarity threshold, **post an explicit
  "no strong prior art found" comment** (honest, shows the agent ran). Never stay silent.

### 5.5 Web UI (Phase 4 · Day 10–11)
- FastAPI app, two pages:
  - **Change Triage chat** — form (symptom + time window) → streamed agent reasoning via SSE.
  - **MR list view** — shows demo-repo MRs and their prior-art comments.
- HTMX for interactivity, Tailwind for styling, SSE for streamed reasoning (judges must *see* it think).
- Deploy to Cloud Run → public URL. Secrets via Secret Manager.

### 5.6 Webhook (Phase 4 · Day 12)
- GitLab webhook on the fork → `POST /webhook` on Cloud Run.
- On MR open/update event → run Prior-Art Review → MCP posts comment. Target **< 30s** latency.
- Verify webhook secret token.

### 5.7 Cross-cutting rules (apply to BOTH workflows)

**Confidence band rubric** (the spine of credibility — discrete, never numeric):
- **Strong** — hard signal: an analogue MR was `reverted` or `linked_to_incident` **and** high
  diff similarity **and** file overlap with the change/symptom.
- **Moderate** — partial signal: high similarity but the analogue shipped clean, **or** a
  bad-outcome analogue with weaker similarity / partial overlap.
- **Weak** — circumstantial only: same files touched, low similarity, no outcome signal.

**Evidence citation (mandatory):** every claim points to a concrete artifact — an MR link, an
`outcome` label + its `outcome_evidence`, `files_touched`, or a pipeline result. No uncited
assertions ever. The UI renders each cited signal as a clickable reference.

**Surfaces, never decides:** outputs say "this MR is a likely suspect because…", never
"this caused the incident."

---

## 6. Dataflow / workflows

### 6.1 Build-time (one-time, Day 2–4)
```
GitLab REST (gitlab-org/cli)
   └─ list last 100–150 merged MRs
        └─ per MR: fetch diff + metadata
             └─ text-embedding-005 → 768-d vector
                  └─ upsert → MongoDB recall.merge_requests
                       └─ Day 3: human labels `outcome` (+ evidence)
                            └─ Day 4: vector-validation gate (5 pairs in top-3)
```

### 6.2 Change Triage (runtime, request → response)
```
User: symptom + time_window
   │
   ▼
[1] Enumerate deploys in window
    GitLab MCP: list_pipelines  ──(map pipeline → MR by merge SHA)──►  candidate MRs
                                   └─ fallback: list_merge_requests (merged) if sparse
   │
   ▼
[2] Enrich each candidate
    Mongo tool: get_mr_record(mr_id)            → stored outcome + evidence
    Mongo tool: vector_search_similar_mrs(mr)   → nearest known-bad analogues
    derive: file/area overlap with symptom
   │
   ▼
[3] Deterministic scorer  → stable ranked suspect list  (+ assign confidence band)
   │
   ▼
[4] Gemini narration pass → cited prose per suspect, streamed over SSE to the UI
   │
   ▼
Ranked suspect list: MR + evidence citations + strong/moderate/weak  (human decides)
```

### 6.3 Prior-Art Review (event → comment)
```
New MR opened in fork (saisravan1023/cli-recall)
   │
   ▼  GitLab webhook  →  POST /webhook (Cloud Run)  [verify secret token]
   │
   ▼
[1] GitLab MCP: get_merge_request_changes(mr_id)   → new diff
[2] text-embedding-005 → embed new diff
[3] Mongo: vector_search_similar_mrs (top-3, filter project_id)
[4] Mongo: get_mr_record on each analogue          → outcomes + evidence
[5] Compose comment (analogues + outcomes + bands)  | or "no strong prior art" if below threshold
   │
   ▼  GitLab MCP: create_merge_request_note(mr_id, comment)   [target < 30s]
   │
   ▼
Comment appears in the MR thread
```

---

## 7. Implementation phases (5 phases over 14 days)

> The build is organized into **5 engineering phases**. This is a different lens on the same
> 14-day timeline — no dates or decisions change. Each phase has an **exit gate**; do not start
> the next phase until the current gate is green. (Distinct from the *product* Phase 1/2/3 in §1,
> which are scope gates — Phase 2/3 are cut.)

### Phase 0 — Foundations  ·  D1 (May 29, today)  ·  mostly ✅
Setup verified Day 1 (GCP, Mongo, GitLab, repo — see `STATE.md`). **Remaining tonight:**
set GitLab Duo default namespace → MCP smoke-test (list + call 1 tool) → scaffold `ingest.py`.
**Exit gate:** MCP lists+calls one tool; `fetch_one_mr()` returns real data.

### Phase 1 — Corpus  ·  D2–D4 (May 30 – Jun 1)
Build the memory substrate. Components: `ingest.py` (§5.1), outcome labeling (§5.2), build-time
dataflow (§6.1).
- **D2** — finish `ingest.py`; ingest 100–150 merged MRs + 768-d embeddings → MongoDB.
- **D3** — manual outcome labeling (`shipped_clean` / `reverted` / `linked_to_incident` + evidence).
- **D4** — vector-validation gate (5 known-similar pairs in top-3); finalize embedding strategy
  (raw diff vs summary); spillover buffer.
- **Exit gate:** 100–150 docs in Mongo, every doc has a valid 768-d embedding **and** an `outcome`;
  5/5 validation pairs retrieve each other in top-3.

### Phase 2 — Agent core  ·  D5–D6 (Jun 2 – Jun 3)
Stand up the agent and its hands. Components: Mongo custom tools (§5.3), GitLab MCP tools (§5.3).
- **D5** — Agent Starter Pack scaffold (ADK + Cloud Run); run hello-world; wire 3 Mongo tools
  (`vector_search_similar_mrs`, `get_mr_record`, `filter_by_outcome`); test in isolation.
- **D6** — wire GitLab MCP toolset; confirm Gemini calls all 4 MCP tools and parses results.
- **Exit gate:** agent runs locally; all 3 Mongo tools + all 4 MCP tools callable and parsed.

### Phase 3 — Workflows  ·  D7–D9 (Jun 4 – Jun 6)
The two committed product workflows. Components: Change Triage (§5.4), Prior-Art (§5.4),
cross-cutting rules (§5.7), runtime dataflows (§6.2–6.3).
- **D7** — Change Triage: enumerate (pipelines→MRs) → deterministic scorer → Gemini narration →
  ranked suspects + citations + bands.
- **D8** — Prior-Art Review: diff → vector search (top-3) → outcomes → cited comment (or no-match).
- **D9** — **product Phase 1 gate / buffer:** both flows end-to-end vs the demo repo; record a
  rough video cut if clean.
- **Exit gate:** both workflows run end-to-end against the demo repo with cited, banded output.

### Phase 4 — Surface  ·  D10–D12 (Jun 7 – Jun 9)
Make it visible and live. Components: Web UI (§5.5), Webhook (§5.6).
- **D10** — FastAPI + HTMX + SSE UI: Change Triage chat (streamed) + MR list view.
- **D11** — finish UI; deploy to Cloud Run (Secret Manager for creds); public URL.
- **D12** — GitLab webhook on fork → `/webhook` → Prior-Art → MCP posts comment (< 30s).
- **Exit gate:** public Cloud Run URL live; new MR in fork triggers a posted comment in < 30s.

### Phase 5 — Ship  ·  D13–D14 (Jun 10 – Jun 11 ≤ 2pm PDT)
Polish and submit. See Definition of Done (§10).
- **D13** — polish (styling, error states, prompt tuning); **record 3-min demo video**; README +
  written description.
- **D14** — upload video (English subtitles); verify URL/repo/license/links; **submit on Devpost**.
  Morning = hard buffer.
- **Exit gate:** submitted on Devpost before Jun 11, 2:00pm PDT.

### Dated quick-reference
| Date | Day | Eng. phase | Focus |
|---|---|---|---|
| May 29 Fri | D1 | P0 Foundations | Setup ✅ + tonight: Duo namespace, MCP smoke-test, scaffold `ingest.py` |
| May 30 Sat | D2 | P1 Corpus | `ingest.py`: 100–150 MRs + embeddings → Mongo |
| May 31 Sun | D3 | P1 Corpus | Manual outcome labeling |
| Jun 1 Mon | D4 | P1 Corpus | Vector validation (5 pairs top-3); embedding strategy; buffer |
| Jun 2 Tue | D5 | P2 Agent core | ADK scaffold + 3 Mongo tools |
| Jun 3 Wed | D6 | P2 Agent core | GitLab MCP toolset wired |
| Jun 4 Thu | D7 | P3 Workflows | Change Triage flow |
| Jun 5 Fri | D8 | P3 Workflows | Prior-Art Review flow |
| Jun 6 Sat | D9 | P3 Workflows | Product Phase-1 gate / buffer (both flows vs demo) |
| Jun 7 Sun | D10 | P4 Surface | FastAPI + HTMX + SSE UI |
| Jun 8 Mon | D11 | P4 Surface | Finish UI + deploy to Cloud Run |
| Jun 9 Tue | D12 | P4 Surface | Webhook integration (< 30s) |
| Jun 10 Wed | D13 | P5 Ship | Polish + record demo video + README |
| Jun 11 Thu (≤2pm) | D14 | P5 Ship | Upload video, verify links, **submit** |

---

## 8. Open setup items / prerequisites
- **GitLab Duo default namespace** — required for *external tools* calling GitLab via MCP.
  Must be set before the Day 1 MCP smoke-test works. (Backup: community `@zereight/mcp-gitlab`.)
- **$100 GCP credits** — form submitted, approval pending (doesn't block).
- **Secret Manager** — wire prod creds when deploying to Cloud Run (Day 11), not before.

---

## 9. Risks & mitigations
| Risk | Mitigation |
|---|---|
| GitLab MCP beta fails / namespace issues | Day 1 smoke-test retires it early; fallback `@zereight/mcp-gitlab` |
| Only 24 Duo credits | REST for all ingestion; MCP only at agent-time; minimize dev calls |
| Vector results poor | D4 validation gate; switch raw-diff → LLM-summary embedding |
| Labeling is the secret sauce but time-consuming | Protect D3; semi-automate revert/incident detection |
| Last 1.5 days carry video+submit (underestimated) | Record rough cut on D9 if flows demo cleanly |
| Thin buffer (only D9) | If slip, sacrifice polish — never the two core workflows |

---

## 10. Definition of done (submission)
- [ ] Both Phase 1 workflows work end-to-end against the demo repo with streamed reasoning.
- [ ] Public Cloud Run URL live.
- [ ] Public GitHub repo, MIT license, no secrets committed.
- [ ] 3-min demo video uploaded (English subtitles), under 2:55.
- [ ] README + written project description complete.
- [ ] Submitted on Devpost before Jun 11, 2:00pm PDT.

---

## 11. Locked vs flexible
**Locked:** name (Recall); track (GitLab + MongoDB); 2 Phase-1 workflows; cut Phase 2/3;
stack (ADK, Gemini 3 Flash, Cloud Run, GitLab MCP, MongoDB Vector Search); repos; corpus 50–150 MRs.
**Flexible:** exact MCP tool names (depends on server); UI styling/copy; Agent Runtime vs direct
Cloud Run (bias: Cloud Run, final call D11); embedding strategy raw-vs-summary (decide D4).
