# 03. Hybrid search and reranking

Lesson 01 showed what vectors are good at: meaning. They are bad at exact tokens. Ask a dense retriever
for `L-1216C47A` and it sees a meaningless string, so it returns whatever is vaguely about "quotas" or
nothing useful. Keyword search has the opposite profile. Production retrieval uses both and then lets a
more expensive model sort the result. This is the single biggest quality lever after chunking.

```
                       ┌─► dense:   embed query ─► HNSW cosine top 30 ─────┐
question ─► /search ───┤                                                   ├─► RRF fusion ─► cross-encoder rerank ─► top k
                       └─► lexical: tsquery     ─► GIN full-text top 30 ───┘      (top 30)       (reads query + chunk together)
```

All of it is one SQL statement plus one model call, in [`rag/search.py`](../rag/search.py).

## Lexical search in Postgres

`chunks.tsv` is a generated `tsvector` with three layers:

| Weight | Config | Source | Why |
|---|---|---|---|
| A | `english` | header (doc ID, title, section) | Matches in the title matter most |
| B | `english` | content | Stemmed, so "volumes" matches "volume" |
| C | `rag.ident` | header + content | Not stemmed, stopwords removed: `VcpuLimitExceeded`, `L-1216C47A`, `i4i` stay intact |

The query side ORs the terms (`plainto_tsquery` would AND them, and a natural-language question rarely
contains every word of the right chunk) and ranks with `ts_rank_cd`.

**Honest caveat:** Postgres's built-in ranking is not BM25. BM25, the standard keyword ranking in
Elasticsearch, OpenSearch and Lucene, weighs rare terms more (IDF) and saturates repeated terms; `ts_rank`
does neither. For production keyword quality in Postgres, use a BM25 extension: ParadeDB `pg_search`
(Tantivy), VectorChord-BM25, or Timescale's `pg_textsearch`. Qdrant (sparse vectors with IDF), Weaviate,
OpenSearch and Elasticsearch have BM25 built in. We stay with core Postgres to keep the stack small, and
the eval in lesson 04 shows what that costs and how the reranker compensates.

Another option is **learned sparse retrieval** (SPLADE, BGE-M3 sparse): a model outputs a sparse vector
of weighted vocabulary terms, including expansions the text never used. It combines the precision of
keywords with some semantic matching.

## Fusion: Reciprocal Rank Fusion (RRF)

Dense scores (cosine, 0 to 1) and lexical scores (ts_rank, unbounded) are on different scales, so you
cannot just add them. RRF ignores scores and uses ranks:

```
RRF(chunk) = Σ over retrievers  1 / (k + rank_in_that_retriever)      k = 60
```

A chunk ranked 1st by one retriever and 3rd by the other (1/61 + 1/63 = 0.0323) beats one ranked 1st
by only one of them (1/61 = 0.0164). Agreement wins; a chunk found by only one side still survives.
`k` dampens the advantage of the very top ranks; 60 is the value from the original paper and rarely
worth tuning. The SQL is a `FULL OUTER JOIN` of the two ranked CTEs (`_HYBRID` in [`rag/search.py`](../rag/search.py));
`rag.search.rrf()` is the same formula in Python and [`tests/test_rrf.py`](../tests/test_rrf.py) checks it.

Alternatives: weighted score fusion after min-max normalisation (Weaviate's `relativeScoreFusion`), or
let the reranker do all the work on the union of both candidate lists.

## Reranking with a cross-encoder

The embedder is a **bi-encoder**: query and chunk are embedded separately, so the model never compares
them directly. A **cross-encoder** reads `[query] [SEP] [chunk]` together and outputs one relevance score.
It understands "Is it safe to *reboot* a Kafka machine" vs a chunk saying "never stop and start a broker"
much better than vector similarity. It is also ~100x more expensive per pair, which is why it only
sees the ~30 fused candidates.

We use `jinaai/jina-reranker-v1-turbo-en` (ONNX, 150 MB, CPU), picked by comparing five models with [`eval/rerankers.py`](../eval/rerankers.py) (lesson 04). Production choices: `bge-reranker-v2-m3`,
`mxbai-rerank`, Jina reranker v2 (open, GPU recommended), or Cohere Rerank and Voyage rerank (API).
Rerank scores are logits: above 0 usually relevant, well below 0 usually not. That makes them useful
for a "nothing relevant found" threshold, which pure vector similarity is bad at (the nearest
neighbour of nonsense is still *some* chunk).

## Filters

Every retriever applies the same metadata filters (`doc_type`, `team`, `service`). With HNSW, a
selective filter is tricky: the index finds the `ef_search` nearest vectors first, then the filter may
throw most away and you get fewer than `k` rows. pgvector 0.8 added **iterative index scans**
(`SET hnsw.iterative_scan = relaxed_order`), which keep walking the graph until enough rows pass the
filter. We set it on every query. For very selective filters (one tenant out of thousands), partial
indexes per tenant or partitioning work better.

## Try it

```bash
# compare the three retrievers and the effect of reranking on one question
for mode in dense lexical hybrid; do
  curl -s localhost:47100/search -H 'content-type: application/json' \
    -d "{\"query\": \"what is quota code L-1216C47A\", \"mode\": \"$mode\", \"rerank\": false, \"k\": 3}" \
    | jq -r --arg m "$mode" '"\($m): " + ([.hits[].chunk_id] | join(", "))'
done

curl -s localhost:47100/search -H 'content-type: application/json' \
  -d '{"query": "is it safe to reboot a kafka machine to move it to new hardware?", "k": 3}' | jq '.hits[] | {chunk_id, dense_rank, lexical_rank, rerank_score}'
```

Lesson 04 turns this into numbers over 32 labelled questions.

---

← [02-chunking-and-ingestion](02-chunking-and-ingestion.md) · [Index](../README.md) · [04-evaluating-retrieval](04-evaluating-retrieval.md) →
