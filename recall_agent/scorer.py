"""Deterministic suspect scoring + discrete confidence bands.

The ranking is intentionally NOT done by the LLM: a stable, explainable score decides the
order (so demo runs are reproducible), and Gemini only narrates the result downstream.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

# outcome -> risk weight (how suspicious this outcome makes an MR)
OUTCOME_RISK = {
    "reverted": 1.0,
    "linked_to_incident": 1.0,
    "shipped_clean": 0.15,
    None: 0.5,
}

W_SIMILARITY = 0.50
W_OUTCOME = 0.35
W_FILE_OVERLAP = 0.15

# Bands are outcome-driven: a known-bad outcome that's clearly relevant is the only "strong"
# signal. Similarity alone (embedding closeness) never earns more than "moderate".
STRONG_BAD_SIM = 0.60   # bad outcome + this similarity -> strong
HIGH_SIM = 0.78         # very high similarity alone -> at most moderate
MODERATE_BAD_SIM = 0.0  # any bad outcome is at least moderate


@dataclass
class Suspect:
    mr_id: int
    title: str
    outcome: str | None
    outcome_evidence: str | None
    files_touched: list[str]
    author: str
    merged_at: str | None
    similarity: float
    score: float
    band: str
    reasons: list[str] = field(default_factory=list)


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _symptom_tokens(symptom: str) -> set[str]:
    return {t for t in re.split(r"[^a-zA-Z0-9_]+", symptom.lower()) if len(t) >= 4}


def file_overlap(symptom: str, files_touched: list[str]) -> float:
    tokens = _symptom_tokens(symptom)
    if not tokens or not files_touched:
        return 0.0
    blob = " ".join(files_touched).lower()
    hits = sum(1 for t in tokens if t in blob)
    return min(1.0, hits / max(1, len(tokens)))


def _band(outcome: str | None, similarity: float, overlap: float) -> tuple[str, list[str]]:
    bad_outcome = outcome in ("reverted", "linked_to_incident")
    reasons: list[str] = []
    if outcome:
        reasons.append(f"outcome={outcome}")
    if overlap > 0:
        reasons.append("touches related files")

    # strong: a known-bad change that is clearly relevant to the symptom
    if bad_outcome and similarity >= STRONG_BAD_SIM:
        reasons.insert(0, "known-bad outcome on a closely related change")
        return "strong", reasons
    # moderate: a known-bad change (weaker match) OR an unusually close match with no outcome signal
    if bad_outcome:
        reasons.insert(0, "known-bad outcome, weaker match")
        return "moderate", reasons
    if similarity >= HIGH_SIM:
        reasons.insert(0, "very close match (no known-bad outcome)")
        return "moderate", reasons
    # weak: circumstantial — clean/unlabeled change with ordinary similarity
    reasons.insert(0, "circumstantial similarity only")
    return "weak", reasons


def score_candidate(symptom: str, symptom_vec: list[float], doc: dict) -> Suspect:
    similarity = cosine(symptom_vec, doc.get("embedding") or [])
    overlap = file_overlap(symptom, doc.get("files_touched") or [])
    outcome = doc.get("outcome")
    risk = OUTCOME_RISK.get(outcome, 0.5)
    score = W_SIMILARITY * similarity + W_OUTCOME * risk + W_FILE_OVERLAP * overlap
    band, reasons = _band(outcome, similarity, overlap)
    return Suspect(
        mr_id=doc["mr_id"],
        title=doc.get("title", ""),
        outcome=outcome,
        outcome_evidence=doc.get("outcome_evidence"),
        files_touched=doc.get("files_touched") or [],
        author=doc.get("author", ""),
        merged_at=doc.get("merged_at"),
        similarity=round(similarity, 4),
        score=round(score, 4),
        band=band,
        reasons=reasons,
    )


def rank_suspects(symptom: str, symptom_vec: list[float], docs: list[dict], top_k: int = 5) -> list[Suspect]:
    scored = [score_candidate(symptom, symptom_vec, d) for d in docs]
    scored.sort(key=lambda s: s.score, reverse=True)
    return scored[:top_k]
