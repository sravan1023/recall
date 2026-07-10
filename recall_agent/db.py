"""Shared MongoDB + embedding helpers for the Recall agent tools."""

from __future__ import annotations

import os

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pymongo import MongoClient
from pymongo.collection import Collection

load_dotenv()

DB_NAME = "recall"
COLLECTION_NAME = "merge_requests"
VECTOR_INDEX = "mr_diff_embedding_index"
EMBED_MODEL = "text-embedding-005"
EMBED_DIMS = 768

_collection: Collection | None = None
_genai_client: genai.Client | None = None


def get_collection() -> Collection:
    global _collection
    if _collection is None:
        _collection = MongoClient(os.environ["MONGODB_URI"])[DB_NAME][COLLECTION_NAME]
    return _collection


def get_genai_client() -> genai.Client:
    global _genai_client
    if _genai_client is None:
        _genai_client = genai.Client(
            vertexai=True,
            project=os.environ["GCP_PROJECT_ID"],
            location=os.environ["GCP_LOCATION"],
        )
    return _genai_client


def embed_query(text: str) -> list[float]:
    result = get_genai_client().models.embed_content(
        model=EMBED_MODEL,
        contents=(text or "").strip()[:6000],
        config=types.EmbedContentConfig(
            task_type="RETRIEVAL_QUERY", output_dimensionality=EMBED_DIMS
        ),
    )
    return list(result.embeddings[0].values)
