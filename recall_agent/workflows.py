"""Recall workflows: Change Triage and Prior-Art Review.

These are deterministic Python pipelines. The LLM is used only to narrate ranked results
or compose the comment — never to decide the ranking or invent evidence.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

from .db import embed_query, get_collection, get_genai_client
from .scorer import Suspect, rank_suspects
from .tools import vector_search_similar_mrs

load_dotenv()

NARRATION_MODEL = "gemini-2.5-flash"
DIFF_BUDGET = 6000
PRIOR_ART_THRESHOLD = 0.60

_SYSTEM_RULES = (
    "Rules: (1) cite every claim with a concrete signal (mr_id, outcome, files_touched); "
    "(2) use only the discrete confidence bands strong/moderate/weak, never a number; "
    "(3) you surface likely suspects with reasons, you never assert something 'caused' an incident."
)


def _gemini(prompt: str) -> str:
    resp = get_genai_client().models.generate_content(model=NARRATION_MODEL, contents=prompt)
    return (resp.text or "").strip()


# --------------------------------------------------------------------------- Change Triage


def _enumerate_and_rank(symptom: str, window_days: int, top_k: int) -> tuple[int, list[Suspect]]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )
    candidates = list(
        get_collection().find(
            {"merged_at": {"$gte": cutoff}},
            {
                "_id": 0,
                "mr_id": 1,
                "title": 1,
                "outcome": 1,
                "outcome_evidence": 1,
                "files_touched": 1,
                "author": 1,
                "merged_at": 1,
                "embedding": 1,
            },
        )
    )
    symptom_vec = embed_query(symptom)
    suspects = rank_suspects(symptom, symptom_vec, candidates, top_k=top_k)
    return len(candidates), suspects


def _triage_prompt(symptom: str, window_days: int, n_candidates: int, suspects: list[Suspect]) -> str:
    rows = [
        {
            "mr_id": s.mr_id,
            "title": s.title,
            "outcome": s.outcome,
            "outcome_evidence": s.outcome_evidence,
            "confidence_band": s.band,
            "similarity": s.similarity,
            "files_touched": s.files_touched[:6],
        }
        for s in suspects
    ]
    return (
        f"You are Recall, triaging a reported symptom over the last {window_days} days.\n"
        f"Symptom: {symptom!r}\n"
        f"A deterministic scorer ranked {n_candidates} merged MRs; the UI already shows the suspect "
        f"cards (mr_id, outcome, files, band). The selected suspects are:\n"
        f"{json.dumps(rows, indent=2)}\n\n"
        f"Write ONLY a 1-2 sentence top-level read (max ~40 words): what kinds of changes the "
        f"suspects involve and the overall confidence picture. If exactly one suspect stands out "
        f"(e.g. a strong band), name it by !mr_id. Do NOT list each suspect — the cards do that. "
        f"Do not output any numbers.\n{_SYSTEM_RULES}"
    )


def change_triage(symptom: str, window_days: int = 60, top_k: int = 5) -> dict:
    n_candidates, suspects = _enumerate_and_rank(symptom, window_days, top_k)
    narration = _gemini(_triage_prompt(symptom, window_days, n_candidates, suspects))
    return {
        "symptom": symptom,
        "window_days": window_days,
        "candidates_considered": n_candidates,
        "suspects": [s.__dict__ for s in suspects],
        "narration": narration,
    }


def change_triage_stream(symptom: str, window_days: int = 60, top_k: int = 5):
    """Generator yielding triage progress events for SSE: status, suspects, token, done."""
    yield {"type": "status", "message": f"Enumerating merged MRs from the last {window_days} days..."}
    n_candidates, suspects = _enumerate_and_rank(symptom, window_days, top_k)
    yield {"type": "status", "message": f"Scored {n_candidates} merge requests; selected top {len(suspects)} suspects."}
    yield {"type": "suspects", "reviewed": n_candidates, "data": [s.__dict__ for s in suspects]}
    yield {"type": "status", "message": "Writing the triage summary with cited evidence..."}
    prompt = _triage_prompt(symptom, window_days, n_candidates, suspects)
    for chunk in get_genai_client().models.generate_content_stream(model=NARRATION_MODEL, contents=prompt):
        if chunk.text:
            yield {"type": "token", "text": chunk.text}
    yield {"type": "done"}


# --------------------------------------------------------------------------- Prior-Art Review


def _fetch_mr(project_id: str, mr_iid: int) -> dict:
    from ingest import GitLabClient

    client = GitLabClient(os.environ["GITLAB_TOKEN"])
    mr = client.fetch_one_mr(project_id, mr_iid)
    changes = client.fetch_mr_changes(project_id, mr_iid)
    diff_text = "\n".join(c.get("diff", "") for c in changes.get("changes", []))[:DIFF_BUDGET]
    return {"title": mr.get("title", ""), "description": mr.get("description") or "", "diff_text": diff_text}


def prior_art_review(project_id: str, mr_iid: int, post: bool = False) -> dict:
    mr = _fetch_mr(project_id, mr_iid)
    query_text = mr["diff_text"] or f"{mr['title']} {mr['description']}"
    found = vector_search_similar_mrs(query_text, limit=4)
    analogues = [a for a in found["results"] if a["mr_id"] != mr_iid]
    top_score = analogues[0]["score"] if analogues else 0.0

    if not analogues or top_score < PRIOR_ART_THRESHOLD:
        comment = _no_prior_art_comment(mr["title"])
    else:
        comment = _compose_prior_art(mr["title"], analogues)

    posted = False
    post_result = None
    if post:
        from .gitlab_mcp import call_tool

        post_result = call_tool(
            "create_merge_request_note",
            {"project_id": str(project_id), "merge_request_iid": int(mr_iid), "body": comment},
            read_only=False,
        )
        posted = True

    return {
        "mr_iid": mr_iid,
        "title": mr["title"],
        "analogues": analogues,
        "top_score": top_score,
        "comment": comment,
        "posted": posted,
        "post_result": post_result,
    }


def _band_for(score: float, outcome: str | None) -> str:
    bad = outcome in ("reverted", "linked_to_incident")
    if bad and score >= 0.75:
        return "strong"
    if bad or score >= 0.75:
        return "moderate"
    return "weak"


def _compose_prior_art(title: str, analogues: list[dict]) -> str:
    rows = [
        {
            "mr_id": a["mr_id"],
            "title": a["title"],
            "outcome": a.get("outcome"),
            "outcome_evidence": a.get("outcome_evidence"),
            "similarity": round(a["score"], 3),
            "confidence_band": _band_for(a["score"], a.get("outcome")),
            "files_touched": (a.get("files_touched") or [])[:6],
        }
        for a in analogues
    ]
    prompt = (
        f"You are Recall, posting a prior-art note on a newly opened merge request titled "
        f"{title!r}. Below are the most similar past merge requests (similarity + stored outcome). "
        f"Write a short GitLab Markdown comment:\n"
        f"- one-line framing ('Found N similar past changes'),\n"
        f"- a bulleted list, one per analogue: link as !mr_id, its outcome, confidence band, and a "
        f"half-sentence on why it's similar (files/approach),\n"
        f"- a closing line reminding readers this surfaces prior art and the author decides.\n"
        f"Analogues:\n{json.dumps(rows, indent=2)}\n\n{_SYSTEM_RULES}\n"
        f"Start the comment with '**🧠 Recall — prior art**'."
    )
    return _gemini(prompt)


def _no_prior_art_comment(title: str) -> str:
    return (
        "**🧠 Recall — prior art**\n\n"
        "I searched the team's merge-request history and found **no strongly similar prior change** "
        f"for this MR ({title!r}). That doesn't mean it's risky or safe — just that there's no close "
        "precedent on record. Confidence: weak."
    )
