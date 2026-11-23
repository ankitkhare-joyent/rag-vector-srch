"""Answer eval: are Claude's answers grounded, correct and honest? Costs API tokens (about 36 calls).

    uv run python -m eval.answers                  # pipeline RAG
    uv run python -m eval.answers --mode agentic   # agentic retrieval (more calls)

Cheap, deterministic checks rather than an LLM judge, so results are reproducible:
  * citation hit    the answer cites at least one labelled relevant document
  * fact coverage   share of the question's key facts (exact strings) present in the answer
  * abstention      for unanswerable questions: says the runbooks don't cover it and cites nothing
Writes eval/results/answers-<mode>.md with every answer, so you can read them yourself (do!).
"""
import argparse
import re
import statistics

from eval.common import RESULTS, client, load_golden, pct

ABSTAIN = re.compile(r"(do not|don't|doesn't|does not|do n't) (cover|mention|contain|include|describe|address|list|explain)"
                     r"|not covered|isn't covered|aren't covered|couldn't find|could not find|isn't in (the|these)"
                     r"|(there's|there is) no (runbook|document|procedure)|no (runbook|document|procedure) (for|covers)", re.IGNORECASE)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["pipeline", "agentic"], default="pipeline")
    p.add_argument("--limit", type=int, default=0, help="only the first N questions")
    args = p.parse_args()
    golden = load_golden()[: args.limit or None]
    rows, out = [], []
    with client() as http:
        for q in golden:
            r = http.post("/ask", json={"question": q["question"], "mode": args.mode})
            r.raise_for_status()
            a = r.json()
            cited = {c["doc_id"] for c in a["citations"]}
            text = a["answer"]
            row = {"id": q["id"], "category": q["category"], "ms": a["latency_ms"],
                   "in": a["usage"].get("input_tokens", 0), "out": a["usage"].get("output_tokens", 0),
                   "tools": len(a["tool_calls"])}
            if q["relevant"]:
                row["citation_hit"] = float(bool(cited & set(q["relevant"])))
                row["fact_coverage"] = (sum(f.lower() in text.lower() for f in q["facts"]) / len(q["facts"])
                                        if q["facts"] else 1.0)
            else:
                row["abstained"] = float(bool(ABSTAIN.search(text)))
            rows.append(row)
            print(row)
            out += [f"## {q['id']} ({q['category']}): {q['question']}", "",
                    f"relevant: {q['relevant'] or 'none'}; cited: {sorted(cited) or 'none'}; "
                    f"tool calls: {[c['tool'] + ' ' + str(c['input']) for c in a['tool_calls']] or 'none'}", "",
                    text, ""]

    ans = [r for r in rows if "citation_hit" in r]
    una = [r for r in rows if "abstained" in r]
    summary = {
        "citation_hit": round(statistics.mean(r["citation_hit"] for r in ans), 3) if ans else None,
        "fact_coverage": round(statistics.mean(r["fact_coverage"] for r in ans), 3) if ans else None,
        "abstention": round(statistics.mean(r["abstained"] for r in una), 3) if una else None,
        "p50_latency_ms": round(pct([r["ms"] for r in rows], 0.5)),
        "p95_latency_ms": round(pct([r["ms"] for r in rows], 0.95)),
        "avg_input_tokens": round(statistics.mean(r["in"] for r in rows)),
        "avg_output_tokens": round(statistics.mean(r["out"] for r in rows)),
        "avg_tool_calls": round(statistics.mean(r["tools"] for r in rows), 2),
    }
    print(summary)
    head = [f"# Answer eval, mode={args.mode} ({len(rows)} questions)", "",
            "| metric | value |", "|---|---|", *[f"| {k} | {v} |" for k, v in summary.items()], "",
            "Input tokens for the agentic mode are summed over all its model calls.", ""]
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"answers-{args.mode}.md").write_text("\n".join(head + out))
    print(f"wrote {RESULTS / f'answers-{args.mode}.md'}")


if __name__ == "__main__":
    main()
