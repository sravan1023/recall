"""Recall ingestion pipeline."""

from __future__ import annotations

import argparse
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any

import requests
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pymongo import MongoClient
from pymongo.collection import Collection

load_dotenv()

GITLAB_API_BASE = "https://gitlab.com/api/v4"
DIFF_TEXT_BUDGET = 20_000  # cap stored diff size
EMBED_INPUT_BUDGET = 6_000  # cap embed input (~1.5k tokens; under the 2048 model limit)

EMBED_MODEL = "text-embedding-005"
EMBED_DIMS = 768
DB_NAME = "recall"
COLLECTION_NAME = "merge_requests"


@dataclass
class Config:
    gitlab_token: str
    project_id_source: str
    project_id_demo: str
    mongodb_uri: str
    gcp_project_id: str
    gcp_location: str

    @classmethod
    def from_env(cls) -> "Config":
        missing = [
            name
            for name in (
                "GITLAB_TOKEN",
                "GITLAB_PROJECT_ID_SOURCE",
                "GITLAB_PROJECT_ID_DEMO",
                "MONGODB_URI",
                "GCP_PROJECT_ID",
                "GCP_LOCATION",
            )
            if not os.getenv(name)
        ]
        if missing:
            raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")
        return cls(
            gitlab_token=os.environ["GITLAB_TOKEN"],
            project_id_source=os.environ["GITLAB_PROJECT_ID_SOURCE"],
            project_id_demo=os.environ["GITLAB_PROJECT_ID_DEMO"],
            mongodb_uri=os.environ["MONGODB_URI"],
            gcp_project_id=os.environ["GCP_PROJECT_ID"],
            gcp_location=os.environ["GCP_LOCATION"],
        )


@dataclass
class MRRecord:
    mr_id: int
    project_id: int
    title: str
    description: str
    diff_text: str
    files_touched: list[str]
    author: str
    merged_at: str | None
    diff_summary: str | None = None
    embedding: list[float] = field(default_factory=list)
    outcome: str | None = None
    outcome_evidence: str | None = None
    reverted_by_mr: int | None = None
    linked_incident: str | None = None


class GitLabClient:
    def __init__(self, token: str, base_url: str = GITLAB_API_BASE) -> None:
        self._session = requests.Session()
        self._session.headers.update({"PRIVATE-TOKEN": token})
        self._base_url = base_url.rstrip("/")

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        resp = self._session.get(f"{self._base_url}{path}", params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def list_merged_mrs(self, project_id: str, per_page: int = 20, page: int = 1) -> list[dict]:
        return self._get(
            f"/projects/{project_id}/merge_requests",
            params={
                "state": "merged",
                "order_by": "updated_at",
                "sort": "desc",
                "per_page": per_page,
                "page": page,
            },
        )

    def fetch_one_mr(self, project_id: str, mr_iid: int) -> dict:
        return self._get(f"/projects/{project_id}/merge_requests/{mr_iid}")

    def fetch_mr_changes(self, project_id: str, mr_iid: int) -> dict:
        return self._get(f"/projects/{project_id}/merge_requests/{mr_iid}/changes")


def _build_diff_text(changes: list[dict]) -> str:
    parts = [c.get("diff", "") for c in changes]
    text = "\n".join(parts)
    return text[:DIFF_TEXT_BUDGET]


def _files_touched(changes: list[dict]) -> list[str]:
    return [c.get("new_path") or c.get("old_path") for c in changes if c.get("new_path") or c.get("old_path")]


def to_record(mr: dict, changes_payload: dict) -> MRRecord:
    changes = changes_payload.get("changes", [])
    return MRRecord(
        mr_id=mr["iid"],
        project_id=mr["project_id"],
        title=mr.get("title", ""),
        description=mr.get("description") or "",
        diff_text=_build_diff_text(changes),
        files_touched=_files_touched(changes),
        author=(mr.get("author") or {}).get("username", ""),
        merged_at=mr.get("merged_at"),
    )


_genai_client: genai.Client | None = None
_collection: Collection | None = None


def get_genai_client(config: Config) -> genai.Client:
    global _genai_client
    if _genai_client is None:
        _genai_client = genai.Client(
            vertexai=True, project=config.gcp_project_id, location=config.gcp_location
        )
    return _genai_client


def get_collection(config: Config) -> Collection:
    global _collection
    if _collection is None:
        client = MongoClient(config.mongodb_uri)
        coll = client[DB_NAME][COLLECTION_NAME]
        coll.create_index([("mr_id", 1), ("project_id", 1)], unique=True)
        _collection = coll
    return _collection


def embed_diff(config: Config, text: str) -> list[float]:
    payload = (text or "").strip()[:EMBED_INPUT_BUDGET]
    if not payload:
        return []
    client = get_genai_client(config)
    result = client.models.embed_content(
        model=EMBED_MODEL,
        contents=payload,
        config=types.EmbedContentConfig(
            task_type="RETRIEVAL_DOCUMENT", output_dimensionality=EMBED_DIMS
        ),
    )
    return list(result.embeddings[0].values)


def upsert_record(config: Config, record: MRRecord) -> None:
    coll = get_collection(config)
    doc = asdict(record)
    coll.update_one(
        {"mr_id": record.mr_id, "project_id": record.project_id},
        {"$set": doc},
        upsert=True,
    )


def already_ingested(config: Config, mr_id: int, project_id: int) -> bool:
    coll = get_collection(config)
    return coll.count_documents({"mr_id": mr_id, "project_id": project_id}, limit=1) > 0


def run_ingest(limit: int = 150, force: bool = False) -> None:
    config = Config.from_env()
    client = GitLabClient(config.gitlab_token)
    project_id = config.project_id_source

    ingested = skipped = failed = 0
    page = 1
    per_page = 100

    while ingested + skipped < limit:
        batch = client.list_merged_mrs(project_id, per_page=per_page, page=page)
        if not batch:
            break
        for mr_summary in batch:
            if ingested + skipped >= limit:
                break
            iid = mr_summary["iid"]
            try:
                if not force and already_ingested(config, iid, int(project_id)):
                    skipped += 1
                    continue
                mr = client.fetch_one_mr(project_id, iid)
                changes = client.fetch_mr_changes(project_id, iid)
                record = to_record(mr, changes)
                record.embedding = embed_diff(config, record.diff_text or record.title)
                if len(record.embedding) != EMBED_DIMS:
                    raise ValueError(f"bad embedding length {len(record.embedding)}")
                upsert_record(config, record)
                ingested += 1
                print(f"  [{ingested:>3}] MR !{iid} {record.title[:60]}")
                time.sleep(0.2)
            except Exception as exc:  # keep going; one bad MR shouldn't abort the run
                failed += 1
                print(f"  [!!] MR !{iid} failed: {exc}")
        page += 1

    print(f"\ndone. ingested={ingested} skipped={skipped} failed={failed}")


def _smoke_test() -> None:
    config = Config.from_env()
    client = GitLabClient(config.gitlab_token)

    mrs = client.list_merged_mrs(config.project_id_source, per_page=1)
    if not mrs:
        raise SystemExit("No merged MRs returned for source project.")

    iid = mrs[0]["iid"]
    mr = client.fetch_one_mr(config.project_id_source, iid)
    changes_payload = client.fetch_mr_changes(config.project_id_source, iid)
    record = to_record(mr, changes_payload)

    print(f"source project_id : {config.project_id_source}")
    print(f"mr_id (iid)        : {record.mr_id}")
    print(f"title              : {record.title}")
    print(f"author             : {record.author}")
    print(f"merged_at          : {record.merged_at}")
    print(f"files_touched      : {len(record.files_touched)} -> {record.files_touched[:5]}")
    print(f"diff_text chars    : {len(record.diff_text)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Recall ingestion")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("smoke", help="fetch + print one source MR")
    run_p = sub.add_parser("run", help="ingest merged MRs into MongoDB")
    run_p.add_argument("--limit", type=int, default=150)
    run_p.add_argument("--force", action="store_true", help="re-ingest even if already present")
    args = parser.parse_args()

    if args.cmd == "run":
        run_ingest(limit=args.limit, force=args.force)
    else:
        _smoke_test()


if __name__ == "__main__":
    main()
