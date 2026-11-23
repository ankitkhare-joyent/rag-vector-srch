# 04. Evaluating retrieval (and answers)

"It looks good on the three questions I tried" is how most RAG systems ship, and why most of them
disappoint. You would never change a Spark job's join logic without comparing row counts; treat
retrieval the same way. Evaluation is what turns every lesson so far from opinion into measurement.

## Evaluate the two halves separately

```
question ─► retrieval ─► chunks ─► generation ─► answer
             └ eval/retrieval.py        └ eval/answers.py
             free, fast, deterministic   costs tokens, slower
```

If an answer is wrong, the first question is always: *was the right chunk retrieved?* If not, no prompt
change will fix it. Retrieval evals need no LLM, so you can run them on every change to chunking,
models, weights or SQL.

## The golden set ([`eval/golden.jsonl`](../eval/golden.jsonl))

36 questions, each labelled with the documents that answer it and a few key facts the answer must
contain. They are deliberately mixed:

| Category | Count | Example | Tests |
|---|---|---|---|
| lexical | 10 | "Which quota code covers running on-demand standard instances?" | Exact identifiers, error codes |
| semantic | 18 | "Developers are complaining their builds wait a long time before starting" | Paraphrase, no shared words |
| multi | 4 | "Is it a quota or a capacity problem, and what do I do for each?" | Answers spanning 2 to 3 documents |
| unanswerable | 4 | "How do I rotate the TLS certificate on the internal load balancer?" | Saying "not covered" instead of inventing |

In a real project you build this set from real questions (search logs, Slack, tickets), label it with
the people who own the documents, and keep adding every failure you find. 50 to 200 questions catches
most regressions. An LLM can draft questions from documents, but have humans check the labels.

## Retrieval metrics

Relevance is judged per document: chunk hits are collapsed to documents in rank order.

| Metric | Question it answers |
|---|---|
| **recall@5** | Of the documents needed, what share is in the top 5? (What the model will see.) |
| **hit@1** | Is the top result relevant? |
| **MRR@10** | How high is the *first* relevant document? 1.0 = always first, 0.5 = usually second |
| **nDCG@10** | Are *all* relevant documents near the top, weighted by position? |

## Results

Run with the stack up: `uv run python -m eval.retrieval`.

Retrieval, 32 answerable questions, reranker `jina-reranker-v1-turbo-en` (full output, with every
top-1 miss listed, in [`eval/results/retrieval.md`](../eval/results/retrieval.md)):

| config | recall@5 | hit@1 | mrr@10 | ndcg@10 | cat:lexical | cat:semantic | cat:multi | p50_ms | p95_ms |
|---|---|---|---|---|---|---|---|---|---|
| dense | 0.958 | 0.875 | 0.927 | 0.934 | 1.0 | 0.944 | 0.917 | 24 | 45 |
| lexical | 0.88 | 0.719 | 0.807 | 0.814 | 1.0 | 0.833 | 0.792 | 8 | 13 |
| hybrid | 0.958 | 0.844 | 0.906 | 0.913 | 1.0 | 0.944 | 0.917 | 38 | 72 |
| dense + rerank | 0.958 | 0.938 | 0.958 | 0.952 | 1.0 | 0.944 | 0.917 | 4766 | 6780 |
| hybrid + rerank | 0.969 | 0.938 | 0.958 | 0.956 | 1.0 | 0.944 | 1.0 | 4157 | 5070 |

What the numbers say:

* **Lexical alone is clearly worst** on paraphrased questions (semantic recall 0.83) but perfect on exact
  identifiers. Dense is strong everywhere here, because every chunk carries its contextual header and
  the corpus is small and clean; on a real corpus with thousands of near-duplicate pages the gap
  between dense and hybrid is usually much larger.
* **Hybrid without reranking was not better than dense** on this set: RRF gives equal votes to a weak
  lexical ranking (Postgres `ts_rank` is not BM25, lesson 03). That is a real finding, and exactly the
  kind of thing you only learn by measuring.
* **The reranker is what moves hit@1**, from 0.84 to 0.94, and hybrid + rerank is the only setup that
  finds every document for the multi-document questions (multi recall 1.0).
* **Latency**: retrieval takes 20 to 70 ms; the cross-encoder adds about 4 seconds for 30 candidates on
  the shared CPU Docker VM. In production you run it on a GPU, use a reranking API, or rerank fewer
  candidates. Measure cost per quality point, not quality alone.

### Choosing the reranker with data ([`eval/rerankers.py`](../eval/rerankers.py))

Same hybrid top-20 candidates, reranked on the laptop CPU by each model (latency was measured while
other evals were running, so compare it relatively):

| model | recall@5 | hit@1 | mrr@10 | ndcg@10 | ms_per_query |
|---|---|---|---|---|---|
| (no reranker: hybrid RRF order) | 0.958 | 0.844 | 0.909 | 0.927 | 0 |
| Xenova/ms-marco-MiniLM-L-6-v2 | 0.958 | 0.875 | 0.921 | 0.934 | 1239 |
| Xenova/ms-marco-MiniLM-L-12-v2 | 0.958 | 0.875 | 0.92 | 0.927 | 2526 |
| jinaai/jina-reranker-v1-turbo-en | 0.99 | 0.938 | 0.959 | 0.957 | 1517 |
| BAAI/bge-reranker-base | 0.99 | 0.906 | 0.953 | 0.957 | 9810 |
| jinaai/jina-reranker-v2-base-multilingual | 0.979 | 0.938 | 0.969 | 0.97 | 15148 |

`jina-reranker-v1-turbo-en` gives most of the quality of the 1 GB models at a fraction of the latency,
so it became the default (`RAG_RERANK_MODEL`, and the `RERANK_MODEL` build arg). The original choice,
MiniLM-L12, barely helped. Model choice deserves its own eval, every time.


## Answer metrics ([`eval/answers.py`](../eval/answers.py))

Deterministic checks, so results are reproducible and free of judge bias:

* **citation hit**: the answer cites at least one labelled relevant document.
* **fact coverage**: share of the key facts (exact strings like `L-1216C47A` or `modify-volume`) present.
* **abstention**: on unanswerable questions, the answer says the runbooks don't cover it.

Results, 36 questions, Claude Opus 5.5 at medium effort (these runs used the earlier MiniLM-L12 reranker):

| metric | pipeline | agentic |
|---|---|---|
| citation hit (32 answerable) | 0.969 | 1.0 |
| fact coverage | 0.875 | 0.984 |
| abstention (4 unanswerable) | 1.0 | 1.0 |
| p50 / p95 latency | 20.5 s / 33.2 s | 25.9 s / 42.3 s |
| avg input tokens per question | 2,615 | 5,822 |
| avg tool calls | 0 | 1.6 |

Three lessons hide in those rows (read them in `eval/results/answers-*.md`):

* **q14** ("How do I tell if a server is too big for what it does?"): retrieval missed the rightsizing guide,
  so pipeline mode correctly said the excerpts don't cover it and pointed at GUIDE-010 by name. Agentic
  mode searched again and answered it. That is the case for agentic retrieval in one example.
* **Right document, incomplete answer.** For q15 (CI builds waiting) and q27 (PgBouncer failing) the
  pipeline answer cited the right runbook but left out a key step ("raise `MaxSize`", "do not terminate
  a proxy"), because that section was not among the 6 chunks sent. Agentic mode, which can read the
  whole runbook, included both. Fact checks catch this; citation checks alone would have passed it.
* **The first abstention score was 0.75 and 0.5**, and all eight answers had in fact declined. The regex
  missed "don't list" and "couldn't find". The checker was fixed and re-scored. Evaluate your evaluator.

Agentic mode costs about 2.2x the input tokens and 25% more latency for better coverage. A router that
uses pipeline mode by default and agentic mode when the reranker's top score is low gets most of both.

Read the full answers in `eval/results/answers-*.md` too. Numbers tell you *where* to look; reading
tells you *why*.

## Going further

* **LLM-as-judge** for faithfulness ("is every sentence supported by a cited chunk?") and answer
  relevance. Tools: Ragas, DeepEval, promptfoo, or a few lines with Claude and a rubric. Calibrate the
  judge against human labels before trusting it.
* **Online signals**: thumbs up/down, "copied the command", follow-up questions, escalations. Log query,
  retrieved chunk IDs, scores and answer for every request (the agent-evals-observ thread covers tracing
  with Langfuse and OpenTelemetry).
* **Regression gate in CI**: run `eval.retrieval` on every pull request that touches chunking, models,
  SQL or the corpus, and fail if recall@5 drops.

---

← [03-hybrid-search-and-reranking](03-hybrid-search-and-reranking.md) · [Index](../README.md) · [05-generation-and-citations](05-generation-and-citations.md) →
