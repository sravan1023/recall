"""Custom MongoDB tools the Recall agent can call.

Each function is exposed to the agent as a tool; its docstring and type hints
become the tool's schema, so keep them accurate and agent-readable.
"""

from __future__ import annotations

from .db import VECTOR_INDEX, embed_query, get_collection

_SUMMARY_FIELDS = {
    "_id": 0,
    "mr_id": 1,
    "title": 1,
    "outcome": 1,
    "outcome_evidence": 1,
    "files_touched": 1,
    "author": 1,
    "merged_at": 1,
}


def vector_search_similar_mrs(query: str, limit: int = 5) -> dict:
    """Find past merge requests whose code diffs are semantically similar to the query.

    Use this to surface prior art / analogous historical changes for a symptom,
    description, or diff snippet.

    Args:
        query: Free-text description, symptom, or diff snippet to search for.
        limit: Maximum number of similar merge requests to return (default 5).

    Returns:
        A dict with 'count' and 'results' (each: mr_id, title, outcome, files_touched,
        author, merged_at, and a similarity 'score' in [0, 1]).
    """
    query_vector = embed_query(query)
    pipeline = [
        {
            "$vectorSearch": {
                "index": VECTOR_INDEX,
                "path": "embedding",
                "queryVector": query_vector,
                "numCandidates": max(100, limit * 20),
                "limit": limit,
            }
        },
        {"$project": {**_SUMMARY_FIELDS, "score": {"$meta": "vectorSearchScore"}}},
    ]
    results = list(get_collection().aggregate(pipeline))
    return {"count": len(results), "results": results}


def get_mr_record(mr_id: int) -> dict:
    """Fetch the stored record for one merge request by its numeric id (iid).

    Args:
        mr_id: The merge request iid, e.g. 3302.

    Returns:
        The MR record (title, description, files_touched, author, merged_at, outcome,
        outcome_evidence, reverted_by_mr, linked_incident), or an 'error' if not found.
    """
    doc = get_collection().find_one(
        {"mr_id": mr_id}, {"_id": 0, "embedding": 0, "diff_text": 0}
    )
    return doc or {"error": f"no merge request with mr_id {mr_id} in the corpus"}


def filter_by_outcome(outcome: str, limit: int = 20) -> dict:
    """List merge requests that have a given stored outcome label.

    Args:
        outcome: One of 'shipped_clean', 'reverted', or 'linked_to_incident'.
        limit: Maximum number of merge requests to return (default 20).

    Returns:
        A dict with 'outcome', 'count', and 'results' (summary fields per MR).
    """
    cursor = get_collection().find({"outcome": outcome}, _SUMMARY_FIELDS).limit(limit)
    results = list(cursor)
    return {"outcome": outcome, "count": len(results), "results": results}
