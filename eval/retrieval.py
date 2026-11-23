"""Retrieval eval: which retrieval setup finds the right runbooks? No LLM involved, so it is free and fast.

    uv run python -m eval.retrieval          # needs the stack up (API on localhost:47100)

For every answerable question in golden.jsonl and every configuration below, ask /search for the top 10
chunks, collapse them to documents, and score against the labelled relevant documents.
Writes eval/results/retrieval.md.
"""
import argparse
import json
import statistics
from collections import defaultdict

from eval.common import RESULTS, client, doc_ranking, load_golden, mrr_at, ndcg_at, pct, recall_at

CONFIGS = [
    ("dense", False), ("lexical", False), ("hybrid", False), ("dense", True), ("hybrid", True),
]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--only", choices=["dense", "lexical", "hybrid", "dense+rerank", "hybrid+rerank"],
                   help="run one configuration (a few seconds without rerank, about 2 minutes with)")
    args = p.parse_args()
    configs = [c for c in CONFIGS if not args.only or args.only == c[0] + ("+rerank" if c[1] else "")]
    golden = [q for q in load_golden() if q["relevant"]]
    rows, per_cat, misses = [], defaultdict(dict), defaultdict(list)
    with client() as http:
        for mode, rerank in configs:
            name = f"{mode}{' + rerank' if rerank else ''}"
            m = defaultdict(list)
            for q in golden:
                r = http.post("/search", json={"query": q["question"], "mode": mode, "rerank": rerank, "k": 10})
                r.raise_for_status()
                body = r.json()
                ranked, rel = doc_ranking(body["hits"]), set(q["relevant"])
                m["recall@5"].append(recall_at(ranked, rel, 5))
                m["hit@1"].append(1.0 if ranked[:1] and ranked[0] in rel else 0.0)
                m["mrr@10"].append(mrr_at(ranked, rel, 10))
                m["ndcg@10"].append(ndcg_at(ranked, rel, 10))
                m["ms"].append(body["timings_ms"]["total"])
                m[f"cat:{q['category']}"].append(recall_at(ranked, rel, 5))
                if not ranked[:1] or ranked[0] not in rel:
                    misses[name].append(f"{q['id']} top1={ranked[:1]} want={q['relevant']}")
            row = {"config": name, **{k: round(statistics.mean(v), 3) for k, v in m.items() if k != "ms"},
                   "p50_ms": round(pct(m["ms"], 0.5)), "p95_ms": round(pct(m["ms"], 0.95))}
            rows.append(row)
            print(json.dumps(row))

    cols = ["config", "recall@5", "hit@1", "mrr@10", "ndcg@10", "cat:lexical", "cat:semantic", "cat:multi",
            "p50_ms", "p95_ms"]
    lines = [f"# Retrieval eval ({len(golden)} answerable questions, document-level relevance)", "",
             "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(str(r.get(c, "")) for c in cols) + " |" for r in rows]
    lines += ["", "`cat:*` columns are recall@5 per question category. Latency is server-side, including "
              "embedding and reranking, on the local Docker VM.", "", "## Top-1 misses per config", ""]
    for name, ms in misses.items():
        lines += [f"**{name}** ({len(ms)})", "", *[f"- {x}" for x in ms], ""]
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "retrieval.md").write_text("\n".join(lines))
    print(f"wrote {RESULTS / 'retrieval.md'}")


if __name__ == "__main__":
    main()
