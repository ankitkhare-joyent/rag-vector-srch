# Lab 05 · Hybrid search and reranking

One sitting, about 35 minutes. Background: [docs/03](../docs/03-hybrid-search-and-reranking.md). Code:
[rag/search.py](../rag/search.py) (the whole retrieval path is one SQL statement plus one model call).

`POST /search` runs two retrievers, fuses them, and has a cross-encoder reorder the result. This lab pulls them
apart so you can see what each contributes. After it you can explain:

- which questions vectors win, which keyword search wins, and why
- what Postgres actually searches for when you type a question
- how reciprocal rank fusion combines two rankings, by hand
- what a reranker score means, and why "nothing relevant" is hard to detect

The `search` helper prints one line per hit: chunk, its rank in the dense list, its rank in the lexical list, the
reranker score (`-` when reranking is off), and the section.

## Before you start

```bash
source lab/env.sh
search "kafka broker replacement" hybrid true 3
```

## 1. An identifier

**Predict (P1):** "Which quota code is L-1216C47A?" Will dense (vector) search find RB-020, the vCPU quota runbook?
Will lexical search? Which does better?

```bash
for m in dense lexical hybrid; do echo "== $m"; search "Which quota code is L-1216C47A?" $m false 3; done
```

**Predict (P2):** what does Postgres actually search for? The lexical side builds a `tsquery` from your text with two
configurations: `english` (stemmed) and `rag.ident` (exact tokens, stopwords removed).

```bash
psql_su "select replace(plainto_tsquery('english', 'Which quota code is L-1216C47A?')::text, '&', '|') english,
                replace(plainto_tsquery('rag.ident', 'Which quota code is L-1216C47A?')::text, '&', '|') ident"
```

## 2. A paraphrase

**Predict (P3):** "developers say their builds sit waiting a long time before they start". The right runbook is
RB-013, "CI runner queue backlog", which never uses the words *developers*, *builds* or *waiting*. Which retriever
finds it?

```bash
for m in dense lexical; do echo "== $m"; search "developers say their builds sit waiting a long time before they start" $m false 3; done
```

## 3. Fusion by hand

The hybrid result for the identifier question in step 1 was:

```
RB-020#1     dense=1   lex=1
RB-020#3     dense=3   lex=2
GUIDE-019#1  dense=2   lex=4
```

**Predict (P4):** compute each chunk's RRF score, `1/(60 + dense_rank) + 1/(60 + lexical_rank)`. Does the order
match? Why is `GUIDE-019#1` (dense rank 2) below `RB-020#3` (dense rank 3)?

```bash
python3 -c "
for c, d, l in [('RB-020#1', 1, 1), ('RB-020#3', 3, 2), ('GUIDE-019#1', 2, 4)]:
    print(c, round(1/(60+d) + 1/(60+l), 5))"
```

## 4. The reranker

**Predict (P5):** "is it safe to reboot a kafka machine to move it to new hardware?" The answer is in RB-012 ("never
stop and start a broker to move it to new hardware"). What will its reranker score be compared with the next hit?

```bash
curl -s $API/search -H 'content-type: application/json' \
  -d '{"query":"is it safe to reboot a kafka machine to move it to new hardware?","k":3}' \
  | jq -c '.hits[] | {chunk_id, dense_rank, lexical_rank, rerank_score: (.rerank_score * 1000 | round / 1000)}'
```

**Predict (P6):** now the paraphrase from step 2 with the full pipeline. Does the reranker keep RB-013 first? Look at
the scores, and at `timings_ms`.

```bash
search "developers say their builds sit waiting a long time before they start" hybrid true 3
```

## Break it, then fix it

**Break: questions the corpus can't answer.** Retrieval always returns *something*: a typo'd identifier, and a
question that has nothing to do with EC2.

**Predict (P7):** for `L-1216C47B` (one character off), does lexical search find nothing? For "banana bread", what
comes back, and with what reranker scores?

```bash
echo "== typo"; search "Which quota code is L-1216C47B?" lexical false 3
echo "== off-topic"; search "what is a good recipe for banana bread" hybrid true 3
```

**Fix (design, not a command):** the API never refuses on retrieval scores; it passes the best chunks to Claude and
relies on the grounding prompt to say "the runbooks don't cover this" (Lab 07). A score threshold looks tempting.
Compare the off-topic scores with P6 before deciding where you'd put it.

## Check your predictions

**P1.** Both find it here:

```
== dense
RB-020#1     dense=1  lex=-  Relevant quota codes
GUIDE-019#1  dense=2  lex=-  Four weeks before
RB-020#3     dense=3  lex=-  Request an increase
== lexical
RB-020#1     dense=-  lex=1  Relevant quota codes
RB-020#3     dense=-  lex=2  Request an increase
RB-020#2     dense=-  lex=3  Check current usage
== hybrid
RB-020#1     dense=1  lex=1
RB-020#3     dense=3  lex=2
GUIDE-019#1  dense=2  lex=4
```

Dense works because every chunk's contextual header says "vCPU quota" and the question says "quota code"; the
identifier itself means nothing to the embedder. Lexical works because `l-1216c47a` is an exact token match, and its
top 3 are all RB-020. GUIDE-019 (new region launch) also mentions the quota code, so dense ranks it second. On a
large corpus, exact identifiers are where lexical search earns its place.

**P2.** Both columns: `'quota' | 'code' | 'l-1216c47a' | 'l' | '1216c47a'`. "Which" and "is" are stopwords and gone.
The hyphenated code is indexed whole *and* in parts, and the terms are ORed (`|`), not ANDed, so a chunk doesn't
need every word to match; `ts_rank_cd` then scores how many matched, how close together, and with what weight
(header words weigh more).

**P3.** Only dense:

```
== dense
RB-013#1      dense=1  Symptoms
PM-2026-03#3  dense=2  What went well
PM-2026-03#2  dense=3  Timeline
== lexical
RB-008#2      lex=1    Start a session
RB-017#4      lex=2    Rolling out a new AMI
RB-017#2      lex=3    Promotion pipeline
```

The embedder knows "builds waiting" is close to "jobs queued". Lexical search matched "start" and "time" in
unrelated chunks. This is the retrieval eval's "semantic" category (Lab 06), where lexical recall drops to 0.83.

**P4.** `RB-020#1 0.03279`, `RB-020#3 0.03200`, `GUIDE-019#1 0.03175`: same order as the API. RRF rewards agreement:
RB-020#3 is 3rd and 2nd (two good ranks), GUIDE-019#1 is 2nd and 4th. The scores are close because `k = 60` dampens
the difference between top ranks on purpose, so neither retriever can dominate.

**P5.** `RB-012#1` scores `0.644` (dense 1, lexical 3); the next ones are `RB-001#1 -1.148` and `PM-2026-05#4
-1.288`. A clear gap: the cross-encoder read the question and the passage together and recognised "never stop and
start a broker" as the answer. Scores are logits: above 0 usually relevant, well below 0 usually not.

**P6.** No. The reranker moved GUIDE-019 (new region launch) above RB-013, and every score is negative:

```
GUIDE-019#1  dense=20  lex=10  rerank=-3.015  Four weeks before
RB-013#1     dense=1   lex=14  rerank=-3.030  Symptoms
RB-021#1     dense=-   lex=9   rerank=-3.400  Event types
timings_ms: {"embed":14.8,"sql":46.8,"rerank":4140.2,"total":4201.8}
```

A reranker that improves hit@1 from 0.84 to 0.94 on average (Lab 06) still gets individual questions wrong; this is
eval question q15's miss. And it costs about 4 seconds: 30 (query, passage) pairs through a transformer on a shared
CPU VM, against 15 ms for embedding and 50 ms for SQL. In production you'd run it on a GPU, use a reranking API, or
rerank fewer candidates.

**P7.** The typo'd query still returns RB-020 lexically, ranked 1-3: the identifier didn't match, but "quota" and
"code" did, because the terms are ORed. The banana bread query returns three chunks anyway:

```
GUIDE-026#1   dense=2   lex=-  rerank=-4.223  Families we use
PM-2026-05#4  dense=19  lex=-  rerank=-4.361  Action items
GUIDE-026#3   dense=17  lex=-  rerank=-4.372  Sizes
```

The nearest neighbour of nonsense is still some chunk. Its reranker scores (-4.2) are lower than the real paraphrase
in P6 (-3.0), but not by much: a threshold at -3.5 would work for these two queries and fail on others. That's why
the abstention decision is left to the model that reads the text, and measured in Lab 07.

## What to remember

- Dense search wins on meaning, lexical on exact tokens; hybrid keeps both, RRF fuses ranks without score tuning.
- The reranker is the expensive, accurate step. It helps on average and still misses individual questions.
- Retrieval never returns "nothing". Detecting "not covered" belongs downstream, and needs its own measurement.

Next: [Lab 06 · Retrieval evals](06-retrieval-evals.md).
