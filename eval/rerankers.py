"""Compare reranker models offline, on your laptop, against the same hybrid candidates.

    uv run python -m eval.rerankers        # needs the API up; downloads each model once (~0.1 to 1 GB)

Fetches the top 30 hybrid candidates per question from /search (rerank off), then reranks them locally
with each model and scores like eval/retrieval.py. Swapping the reranker is then one setting:
RAG_RERANK_MODEL (and the RERANK_MODEL build arg in the Dockerfile).
"""
import statistics
import time

from fastembed.rerank.cross_encoder import TextCrossEncoder

from eval.common import RESULTS, client, doc_ranking, load_golden, mrr_at, ndcg_at, recall_at
from rag.settings import get_settings

MODELS = ["Xenova/ms-marco-MiniLM-L-6-v2", "Xenova/ms-marco-MiniLM-L-12-v2", "jinaai/jina-reranker-v1-turbo-en",
          "BAAI/bge-reranker-base", "jinaai/jina-reranker-v2-base-multilingual"]


def score(golden, ranked_per_q) -> dict:
    m = {"recall@5": [], "hit@1": [], "mrr@10": [], "ndcg@10": []}
    for q, hits in zip(golden, ranked_per_q):
        ranked, rel = doc_ranking(hits), set(q["relevant"])
        m["recall@5"].append(recall_at(ranked, rel, 5))
        m["hit@1"].append(1.0 if ranked and ranked[0] in rel else 0.0)
        m["mrr@10"].append(mrr_at(ranked, rel, 10))
        m["ndcg@10"].append(ndcg_at(ranked, rel, 10))
    return {k: round(statistics.mean(v), 3) for k, v in m.items()}


def main() -> None:
    golden = [q for q in load_golden() if q["relevant"]]
    with client() as http:
        cands = [http.post("/search", json={"query": q["question"], "mode": "hybrid", "rerank": False, "k": 20}
                           ).json()["hits"] for q in golden]
    rows = [{"model": "(no reranker: hybrid RRF order)", **score(golden, cands), "ms_per_query": 0}]
    for name in MODELS:
        model = TextCrossEncoder(name, cache_dir=str(get_settings().models_dir))
        t = time.perf_counter()
        reranked = []
        for q, hits in zip(golden, cands):
            s = list(model.rerank(q["question"], [f"{h['header']}\n{h['content']}" for h in hits]))
            reranked.append([h for _, h in sorted(zip(s, hits), key=lambda x: x[0], reverse=True)])
        ms = (time.perf_counter() - t) * 1000 / len(golden)
        rows.append({"model": name, **score(golden, reranked), "ms_per_query": round(ms)})
        print(rows[-1])
    cols = ["model", "recall@5", "hit@1", "mrr@10", "ndcg@10", "ms_per_query"]
    lines = ["# Reranker comparison (hybrid top 20 candidates, reranked on the host CPU)", "",
             "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols),
             *["| " + " | ".join(str(r[c]) for c in cols) + " |" for r in rows]]
    (RESULTS / "rerankers.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
