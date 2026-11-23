"""Shared helpers for the evals: load the golden set, call the API, compute ranking metrics."""
import json
import math
import os
from pathlib import Path

import httpx

API = os.environ.get("RAG_API_URL", "http://localhost:47100")
GOLDEN = Path(__file__).parent / "golden.jsonl"
RESULTS = Path(__file__).parent / "results"


def load_golden() -> list[dict]:
    return [json.loads(line) for line in GOLDEN.read_text().splitlines() if line.strip()]


def client() -> httpx.Client:
    return httpx.Client(base_url=API, timeout=300)


def doc_ranking(hits: list[dict]) -> list[str]:
    """Chunk hits -> document IDs in first-seen order. We judge relevance per document, not per chunk."""
    return list(dict.fromkeys(h["doc_id"] for h in hits))


def recall_at(ranked: list[str], relevant: set[str], k: int) -> float:
    """Share of the relevant documents that appear in the top k."""
    return len(set(ranked[:k]) & relevant) / len(relevant)


def mrr_at(ranked: list[str], relevant: set[str], k: int) -> float:
    """1 / rank of the first relevant document (0 if none in the top k). Rewards putting one right answer first."""
    for i, d in enumerate(ranked[:k], start=1):
        if d in relevant:
            return 1 / i
    return 0.0


def ndcg_at(ranked: list[str], relevant: set[str], k: int) -> float:
    """Discounted cumulative gain, normalised by the best possible ordering. Rewards all relevant docs high up."""
    dcg = sum(1 / math.log2(i + 1) for i, d in enumerate(ranked[:k], start=1) if d in relevant)
    ideal = sum(1 / math.log2(i + 1) for i in range(1, min(len(relevant), k) + 1))
    return dcg / ideal


def pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p * (len(xs) - 1))))]
