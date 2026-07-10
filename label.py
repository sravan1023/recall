"""Outcome labeling for the Recall corpus.

Auto-detects the easy, defensible signals and writes `outcome` + `outcome_evidence`:
  - reverted          : an MR that a later "Revert" MR points back to.
  - linked_to_incident: title/description references an incident / outage / hotfix.
  - shipped_clean     : everything else (the default).

This captures the mechanical signals; human refinement (reading threads) can layer on top.
Run: python label.py
"""

from __future__ import annotations

import os
import re

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

DB_NAME = "recall"
COLLECTION_NAME = "merge_requests"

REVERT_REF = re.compile(r"reverts?\s+(?:merge request\s+)?!(\d+)", re.IGNORECASE)
MR_REF = re.compile(r"!(\d+)")
INCIDENT_RE = re.compile(r"\b(incident|outage|rollback|sev-?[12]|production down)\b", re.IGNORECASE)


def _is_revert(title: str, description: str) -> bool:
    return title.lower().startswith("revert") or "this reverts" in description.lower()


def _revert_target(title: str, description: str) -> int | None:
    match = REVERT_REF.search(description) or REVERT_REF.search(title)
    if not match:
        match = MR_REF.search(title)  # fall back to any !iid in a "Revert ..." title
    return int(match.group(1)) if match else None


def run_labeling() -> None:
    coll = MongoClient(os.environ["MONGODB_URI"])[DB_NAME][COLLECTION_NAME]
    docs = list(coll.find({}, {"_id": 0, "mr_id": 1, "title": 1, "description": 1}))
    present_ids = {d["mr_id"] for d in docs}

    labels: dict[int, tuple[str, str]] = {}

    # pass 1: reverts. the revert MR is itself a clean fix; its target is `reverted`.
    for d in docs:
        title, desc = d.get("title", ""), d.get("description", "")
        if _is_revert(title, desc):
            labels[d["mr_id"]] = ("shipped_clean", "revert MR (a corrective change)")
            target = _revert_target(title, desc)
            if target and target in present_ids:
                labels[target] = ("reverted", f"reverted by MR !{d['mr_id']}")

    # pass 2: incident links — TITLE ONLY (descriptions in this repo discuss incidents as
    # documentation content, which produced false positives). Don't override a confirmed revert.
    for d in docs:
        if d["mr_id"] in labels and labels[d["mr_id"]][0] == "reverted":
            continue
        m = INCIDENT_RE.search(d.get("title", ""))
        if m:
            labels[d["mr_id"]] = ("linked_to_incident", f"title mentions '{m.group(0).lower()}'")

    # pass 3: default everything else to shipped_clean
    for d in docs:
        labels.setdefault(d["mr_id"], ("shipped_clean", "no revert or incident signal found"))

    counts: dict[str, int] = {}
    for mr_id, (outcome, evidence) in labels.items():
        extra = {}
        if outcome == "reverted":
            ref = re.search(r"!(\d+)", evidence)
            if ref:
                extra["reverted_by_mr"] = int(ref.group(1))
        coll.update_one(
            {"mr_id": mr_id},
            {"$set": {"outcome": outcome, "outcome_evidence": evidence, **extra}},
        )
        counts[outcome] = counts.get(outcome, 0) + 1

    print("labeled", len(labels), "MRs:")
    for outcome, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {outcome:>20}: {n}")


if __name__ == "__main__":
    run_labeling()
