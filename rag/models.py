"""Embedding and reranking models, run locally on CPU with ONNX Runtime via fastembed.

Two different kinds of model, and the difference is the heart of modern retrieval:

* A **bi-encoder** (the embedder) turns a query and a passage into vectors *independently*. Passages
  can be embedded once at ingest time and indexed, so search over millions is fast. But the query and
  passage never "see" each other, so fine distinctions get lost.
* A **cross-encoder** (the reranker) reads the query and one passage *together* and outputs a relevance
  score. Much more accurate, but it must run once per (query, passage) pair at query time, so you only
  use it on the top few dozen candidates the fast retrievers found.
"""
from functools import lru_cache

import numpy as np
from fastembed import TextEmbedding
from fastembed.rerank.cross_encoder import TextCrossEncoder

from rag.settings import get_settings


@lru_cache
def embedder() -> TextEmbedding:
    s = get_settings()
    return TextEmbedding(s.embed_model, cache_dir=str(s.models_dir))


@lru_cache
def reranker() -> TextCrossEncoder:
    s = get_settings()
    return TextCrossEncoder(s.rerank_model, cache_dir=str(s.models_dir))


def embed_passages(texts: list[str]) -> list[np.ndarray]:
    # passage_embed vs query_embed: some models (BGE, E5, Nomic) expect different prefixes for the
    # query side and the document side. Mixing them up silently costs recall.
    return list(embedder().passage_embed(texts, batch_size=32))


def embed_query(text: str) -> np.ndarray:
    return next(iter(embedder().query_embed(text)))


def rerank(query: str, passages: list[str]) -> list[float]:
    return list(reranker().rerank(query, passages, batch_size=32))


def warm_up() -> None:
    """Load both models at startup so the first request doesn't pay the load time."""
    embed_query("warm up")
    rerank("warm up", ["warm up"])
