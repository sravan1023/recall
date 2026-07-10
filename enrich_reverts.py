"""Enrich the corpus with REAL revert signal.

Searches the source repo's full history for merged MRs whose title contains "Revert",
ingests each one plus the MR it reverted, so the corpus carries genuine `reverted` outcomes
(applied by re-running label.py afterwards).

Run: python enrich_reverts.py
"""

from __future__ import annotations

import requests

from ingest import (
    Config,
    GitLabClient,
    GITLAB_API_BASE,
    already_ingested,
    embed_diff,
    to_record,
    upsert_record,
)
from label import _revert_target

MAX_REVERTS = 30


def _ingest_one(config: Config, client: GitLabClient, iid: int) -> str:
    if already_ingested(config, iid, int(config.project_id_source)):
        return "skip"
    mr = client.fetch_one_mr(config.project_id_source, iid)
    changes = client.fetch_mr_changes(config.project_id_source, iid)
    record = to_record(mr, changes)
    record.embedding = embed_diff(config, record.diff_text or record.title)
    if len(record.embedding) != 768:
        return "fail"
    upsert_record(config, record)
    return "ok"


def main() -> None:
    config = Config.from_env()
    client = GitLabClient(config.gitlab_token)

    resp = requests.get(
        f"{GITLAB_API_BASE}/projects/{config.project_id_source}/merge_requests",
        headers={"PRIVATE-TOKEN": config.gitlab_token},
        params={
            "search": "Revert",
            "in": "title",
            "state": "merged",
            "order_by": "created_at",
            "sort": "desc",
            "per_page": MAX_REVERTS,
        },
        timeout=30,
    )
    resp.raise_for_status()
    reverts = resp.json()
    print(f"found {len(reverts)} revert MRs in source history")

    pairs = 0
    for r in reverts:
        riid = r["iid"]
        target = _revert_target(r.get("title", ""), r.get("description") or "")
        rs = _ingest_one(config, client, riid)
        ts = "no-target"
        if target:
            ts = _ingest_one(config, client, target)
            if ts in ("ok", "skip"):
                pairs += 1
        print(f"  revert !{riid} ({rs}) -> target !{target} ({ts})")

    print(f"\ndone. revert/target pairs ingested: {pairs}")


if __name__ == "__main__":
    main()
