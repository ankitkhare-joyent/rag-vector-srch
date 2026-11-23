"""Retrieval: dense (vector), lexical (full-text), hybrid (both, fused with RRF), and reranking.

    query --+--> embed --> HNSW nearest neighbours (top 30) --+
            |                                                  +--> RRF fusion --> cross-encoder --> top k
            +--> tsquery --> GIN full-text match  (top 30) ----+

Each retriever is good at different questions: vectors match meaning ("my disk is almost full"),
full-text matches exact tokens ("L-1216C47A", "HttpTokens"). Fusion keeps both; the reranker then
reads every surviving candidate together with the query and puts the best ones first.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Literal

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from rag import models
from rag.settings import Settings

Mode = Literal["dense", "lexical", "hybrid"]


@dataclass
class Filters:
    doc_type: str | None = None      # runbook | policy | guide | postmortem
    team: str | None = None
    service: str | None = None       # matches documents listing this service, or "all"


@dataclass
class Hit:
    chunk_id: str
    doc_id: str
    title: str
    section: str
    header: str
    content: str
    doc_type: str
    score: float                      # fused / retriever score (higher is better)
    dense_rank: int | None = None
    lexical_rank: int | None = None
    rerank_score: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SearchResult:
    hits: list[Hit]
    timings_ms: dict[str, float] = field(default_factory=dict)


# Natural-language questions rarely contain *every* term of the right chunk, so the lexical side
# ORs the terms (plainto_tsquery ANDs them) and lets ranking sort it out. Both configs are queried:
# 'english' for stemmed words, rag.ident for exact identifiers.
_TSQUERY = """(
    replace(plainto_tsquery('english', %(text)s)::text, '&', '|')::tsquery ||
    replace(plainto_tsquery('rag.ident', %(text)s)::text, '&', '|')::tsquery
)"""

_FILTER = """
      AND (%(doc_type)s::text IS NULL OR d.doc_type = %(doc_type)s)
      AND (%(team)s::text IS NULL OR d.team = %(team)s)
      AND (%(service)s::text IS NULL OR d.services && ARRAY[%(service)s::text, 'all'])"""

_DENSE = f"""
    SELECT c.chunk_id, row_number() OVER (ORDER BY c.embedding <=> %(qvec)s) AS rnk,
           1 - (c.embedding <=> %(qvec)s) AS score
    FROM chunks c JOIN documents d USING (doc_id)
    WHERE TRUE {_FILTER}
    ORDER BY c.embedding <=> %(qvec)s
    LIMIT %(n)s"""

_LEXICAL = f"""
    SELECT c.chunk_id, row_number() OVER (ORDER BY ts_rank_cd(c.tsv, q, 1) DESC) AS rnk,
           ts_rank_cd(c.tsv, q, 1) AS score
    FROM chunks c JOIN documents d USING (doc_id) CROSS JOIN (SELECT {_TSQUERY} AS q) tsq
    WHERE c.tsv @@ q {_FILTER}
    ORDER BY ts_rank_cd(c.tsv, q, 1) DESC
    LIMIT %(n)s"""

# Reciprocal Rank Fusion: score = sum over retrievers of 1 / (k + rank). Uses only ranks, so it
# needs no score normalisation between cosine similarity and ts_rank (which are on different scales).
_HYBRID = f"""
WITH dense AS ({_DENSE}),
     lexical AS ({_LEXICAL})
SELECT chunk_id,
       coalesce(1.0 / (%(rrf_k)s + dense.rnk), 0) + coalesce(1.0 / (%(rrf_k)s + lexical.rnk), 0) AS score,
       dense.rnk AS dense_rank, lexical.rnk AS lexical_rank
FROM dense FULL OUTER JOIN lexical USING (chunk_id)
ORDER BY score DESC
LIMIT %(n)s"""

_FETCH = """
SELECT c.chunk_id, c.doc_id, d.title, c.section, c.header, c.content, d.doc_type
FROM chunks c JOIN documents d USING (doc_id)
WHERE c.chunk_id = ANY(%(ids)s)"""


def search(pool: ConnectionPool, settings: Settings, query: str, *, mode: Mode = "hybrid", rerank: bool = True,
           k: int = 5, filters: Filters | None = None) -> SearchResult:
    f = filters or Filters()
    timings: dict[str, float] = {}
    t0 = time.perf_counter()
    params = {"text": query, "n": settings.candidates, "rrf_k": settings.rrf_k,
              "doc_type": f.doc_type, "team": f.team, "service": f.service}
    if mode in ("dense", "hybrid"):
        params["qvec"] = models.embed_query(query)
        timings["embed"] = (time.perf_counter() - t0) * 1000

    sql = {"dense": _DENSE, "lexical": _LEXICAL, "hybrid": _HYBRID}[mode]
    t1 = time.perf_counter()
    with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        # SET LOCAL lasts for this transaction only, so pooled connections stay clean.
        cur.execute(f"SET LOCAL hnsw.ef_search = {int(settings.hnsw_ef_search)}")
        # With a filter, plain HNSW can return fewer than LIMIT rows (it finds 100 neighbours, then the
        # filter drops most). Iterative scans (pgvector 0.8+) keep searching the graph until LIMIT is met.
        cur.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
        cur.execute(sql, params)
        ranked = cur.fetchall()
        cur.execute(_FETCH, {"ids": [r["chunk_id"] for r in ranked]})
        rows = {r["chunk_id"]: r for r in cur.fetchall()}
    timings["sql"] = (time.perf_counter() - t1) * 1000

    hits = []
    for r in ranked:
        row = rows[r["chunk_id"]]
        hits.append(Hit(**row, score=float(r["score"]),
                        dense_rank=r.get("dense_rank", r["rnk"] if mode == "dense" else None),
                        lexical_rank=r.get("lexical_rank", r["rnk"] if mode == "lexical" else None)))

    if rerank and hits:
        t2 = time.perf_counter()
        scores = models.rerank(query, [f"{h.header}\n{h.content}" for h in hits])
        for h, s in zip(hits, scores):
            h.rerank_score = float(s)
        hits.sort(key=lambda h: h.rerank_score, reverse=True)
        timings["rerank"] = (time.perf_counter() - t2) * 1000

    timings["total"] = (time.perf_counter() - t0) * 1000
    return SearchResult(hits=hits[:k], timings_ms={k_: round(v, 1) for k_, v in timings.items()})


def rrf(rankings: list[list[str]], k: int = 60) -> list[tuple[str, float]]:
    """Pure-Python RRF, identical to the SQL above; used by tests and to explain the formula."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
