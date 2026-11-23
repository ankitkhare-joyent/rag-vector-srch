# Lab 06 · Retrieval evals: measuring search instead of eyeballing it

One sitting, about 30 minutes. Background: [docs/04](../docs/04-evaluating-retrieval.md). Code:
[eval/golden.jsonl](../eval/golden.jsonl), [eval/retrieval.py](../eval/retrieval.py),
[eval/common.py](../eval/common.py) (the metrics, each a few lines).

Lab 05 showed single queries. Single queries can't tell you whether a change helped: the reranker fixed P5 and broke
P6. This lab measures all of retrieval over a labelled set, for free (no LLM). After it you can explain:

- what's in a golden set and why it has categories
- recall@5, hit@1, MRR and nDCG, and which one matches what the user experiences
- why the reranker is worth 4 seconds here, and hybrid without it isn't worth anything
- how a labelling mistake makes a system look better than it is

## Before you start

```bash
source lab/env.sh
head -3 eval/golden.jsonl | jq -c '{id, category, question, relevant}'
jq -r .category eval/golden.jsonl | sort | uniq -c
```

## 1. Run the full eval

Five configurations over 32 answerable questions: dense, lexical, hybrid, dense + rerank, hybrid + rerank. The
reranked ones take about 2 minutes each (Lab 05, P6).

**Predict (P1):** rank the five configurations by hit@1 before you run. Where do lexical and plain hybrid land?

```bash
mise run eval:retrieval 2>&1 | grep config
sed -n '/Top-1 misses/,$p' eval/results/retrieval.md | sed -n '/hybrid + rerank/,$p'
```

`eval/results/retrieval.md` has the table and every top-1 miss per configuration.

## 2. Read the metrics

Pick one question and compute its metrics by hand from its document ranking, then compare with the code in
[eval/common.py](../eval/common.py).

**Predict (P2):** q29 ("Scaling out CI fails with launch errors. Is it a quota or an AWS capacity problem…") is
labelled with three relevant documents: RB-013, RB-004 and RB-020. Suppose the top 5 documents come back as
`RB-004, RB-020, RB-003, RB-013, RB-021`. What are recall@5, hit@1 and MRR@10?

```bash
uv run python -c "
from eval.common import recall_at, mrr_at, ndcg_at
ranked = ['RB-004', 'RB-020', 'RB-003', 'RB-013', 'RB-021']; rel = {'RB-013', 'RB-004', 'RB-020'}
print('recall@5', round(recall_at(ranked, rel, 5), 3), 'hit@1', ranked[0] in rel,
      'mrr@10', mrr_at(ranked, rel, 10), 'ndcg@10', round(ndcg_at(ranked, rel, 10), 3))"
```

## Break it, then fix it

**Break: a wrong label, and a new question.** Golden sets are written by people. Change q20's label ("We deleted data
by accident on a volume, how do we get it back?") from the snapshot-restore runbook RB-025 to RB-002 (volume full),
and add a new question q37 about the GPU quota code.

**Predict (P3):** hybrid (no rerank) currently has hit@1 0.844 and misses q20 at the top (it returns RB-002 first).
After your edit, does hit@1 go up, down, or stay the same?

```bash
cp eval/golden.jsonl /tmp/golden.bak
sed -i.tmp 's/get it back?", "relevant": \["RB-025"\]/get it back?", "relevant": ["RB-002"]/' eval/golden.jsonl && rm eval/golden.jsonl.tmp
echo '{"id": "q37", "category": "lexical", "question": "What is the GPU instance quota code for G and VT instances?", "relevant": ["RB-020"], "facts": ["L-DB2E81BA"]}' >> eval/golden.jsonl
grep -E '"q20"|"q37"' eval/golden.jsonl | jq -c '{id, relevant}'
mise run eval:retrieval -- --only hybrid 2>&1 | grep config
```

**Fix:** restore the golden set and the results file.

```bash
cp /tmp/golden.bak eval/golden.jsonl
git checkout eval/results/retrieval.md
```

## Check your predictions

**P1.** On a fresh stack (deterministic, so yours should match exactly):

```
config            recall@5  hit@1  mrr@10  ndcg@10  lexical  semantic  multi  p50_ms
dense             0.958     0.875  0.927   0.934    1.0      0.944     0.917     22
lexical           0.88      0.719  0.807   0.814    1.0      0.833     0.792      3
hybrid            0.958     0.844  0.906   0.913    1.0      0.944     0.917     35
dense + rerank    0.958     0.938  0.958   0.952    1.0      0.944     0.917   4130
hybrid + rerank   0.969     0.938  0.958   0.956    1.0      0.944     1.0     3993
```

Lexical is last, and weakest on the semantic category, as Lab 05 suggested. Plain hybrid is *worse* than dense on
hit@1: RRF gives Postgres's weak `ts_rank` an equal vote, so where lexical is wrong it drags good dense results down.
The reranker is what moves hit@1 from 0.84 to 0.94, and hybrid + rerank is the only configuration that finds every
document for the multi-document questions. Two misses remain at the top: q14 (rightsizing guide) and q19 (incident
severity guide), both of which RB-004 outranks. The lexical category is 1.0 everywhere: on this small, clean corpus,
contextual headers make dense search good at identifiers too.

**P2.** `recall@5 1.0` (all three relevant documents are in the top 5), `hit@1 True` (RB-004 is relevant),
`mrr@10 1.0` (the first relevant document is at rank 1), `ndcg@10 0.967` (the third relevant document sits at rank 4
instead of 3). hit@1 and MRR only care about the first relevant document; recall@5 is closest to what the
model sees in pipeline mode (it gets the top 6 chunks); nDCG rewards putting *all* of them high.

**P3.** It goes **up**: `"hit@1": 0.879` (from 0.844), with recall@5 `0.96`. The new q37 is a hit, and the
mislabelled q20 turned from a miss into a "hit", because the label now agrees with the system's mistake. A wrong label
can make a worse system score better, and nobody notices unless they read the misses. Golden sets need the same
review as code: two people per label, and every top-1 miss read by a human, not just counted.

## What to remember

- Measure retrieval on its own, over a labelled set with categories. It's free, deterministic and fast.
- hit@1 and MRR say "is the first result right"; recall@k says "will the model see the answer".
- Hybrid search is not automatically better than dense. The reranker is what earned its keep here.
- Labels are code. A wrong one hides a real failure.

Next: [Lab 07 · Claude answers with citations](07-generation-and-citations.md).
