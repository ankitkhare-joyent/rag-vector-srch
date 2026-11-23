# Lab 04 · Vectors in Postgres: what's stored, how it's searched, what HNSW buys

One sitting, about 35 minutes. Background: [docs/01](../docs/01-embeddings-and-vector-search.md). Code:
[sql/001_schema.sql](../sql/001_schema.sql), [rag/models.py](../rag/models.py),
[scripts/ann_bench.py](../scripts/ann_bench.py).

A vector index is just another Postgres index, with one difference you've never had to think about: it can be
*wrong*, on purpose, to be fast. After this lab you can explain:

- what an embedding looks like on disk, and what cosine distance measures
- why Postgres ignores the HNSW index on our table, and when it would use it
- why a filter can make an approximate search return too few rows, and the setting that fixes it
- the recall vs latency vs size trade-off of HNSW, halfvec and binary quantisation

## Before you start

```bash
source lab/env.sh
psql_su "\d rag.chunks"
```

## 1. What a vector is

**Predict (P1):** what are the dimensions and the length (L2 norm) of every stored embedding?

```bash
psql_su "select chunk_id, vector_dims(embedding) dims, round(vector_norm(embedding)::numeric, 4) norm,
         (embedding::real[])[1:4] first4, embedding_model
         from rag.chunks where chunk_id in ('RB-002#1', 'PM-2026-05#0')"
```

**Predict (P2):** rank these four chunks by similarity to `RB-002#1` (EBS volume full, immediate mitigation):
`RB-002#2` (same runbook, root cause), `RB-025#2` (restore a volume from snapshot), `PM-2026-05#2` (OpenSearch disks
filled, timeline), `POL-SEC-004#0` (IMDSv2 policy).

```bash
psql_su "select b.chunk_id, round((1 - (a.embedding <=> b.embedding))::numeric, 3) cosine_similarity
         from rag.chunks a, rag.chunks b
         where a.chunk_id = 'RB-002#1' and b.chunk_id in ('RB-002#2', 'RB-025#2', 'PM-2026-05#2', 'POL-SEC-004#0')
         order by 2 desc"
```

`<=>` is cosine *distance* (1 - similarity). Smaller distance, more similar.

## 2. Does Postgres use the HNSW index?

**Predict (P3):** the table has an HNSW index on `embedding`. Will this nearest-neighbour query use it?

```bash
psql_su "explain (costs off) select chunk_id from rag.chunks
         order by embedding <=> (select embedding from rag.chunks where chunk_id = 'RB-002#1') limit 5"
psql_su "select pg_size_pretty(pg_relation_size('rag.chunks')) heap,
         pg_size_pretty(pg_relation_size('rag.chunks_embedding_hnsw')) hnsw,
         pg_size_pretty(pg_relation_size('rag.chunks_tsv_gin')) gin"
```

Now take sequential scans away and look again:

```bash
docker compose exec -T postgres psql -U postgres -d rag -P pager=off <<'EOF'
set enable_seqscan = off;
explain (costs off) select chunk_id from rag.chunks
order by embedding <=> (select embedding from rag.chunks where chunk_id = 'RB-002#1') limit 5;
EOF
```

## 3. The trade-off, at a size where it matters

Our 118 chunks are too few for an index to matter. The benchmark builds a scratch table of 20,000 clustered
384-dimension vectors (the same shape as ours) and measures exact search against HNSW at several `ef_search` values,
plus two ways of making the index smaller.

**Predict (P4):** at `ef_search = 10` (the planner explores only 10 candidates), what recall@10 do you expect: 0.3,
0.7 or 0.99? And how much faster than the exact scan?

```bash
uv run python scripts/ann_bench.py          # about 1 minute; the scratch schema is dropped at the end
```

## Break it, then fix it

**Break: a selective filter on an approximate search.** HNSW finds the `ef_search` nearest vectors first, and only
then applies your `WHERE`. Our API filters by document type and service.

**Predict (P5):** there are 11 postmortem chunks. You ask the HNSW index for the 5 postmortem chunks nearest to
`RB-002#1`, with `ef_search = 10`. How many rows come back?

```bash
docker compose exec -T postgres psql -U postgres -d rag -P pager=off <<'EOF'
set enable_seqscan = off; set hnsw.ef_search = 10;
select count(*) postmortem_chunks from rag.chunks where doc_id like 'PM-%';
select count(*) returned_plain from (
  select chunk_id from rag.chunks where doc_id like 'PM-%'
  order by embedding <=> (select embedding from rag.chunks where chunk_id = 'RB-002#1') limit 5) t;
EOF
```

**Fix:** pgvector 0.8's iterative index scan keeps walking the graph until the `LIMIT` is satisfied. The API sets
it on every query (`SET LOCAL hnsw.iterative_scan` in [rag/search.py](../rag/search.py)).

```bash
docker compose exec -T postgres psql -U postgres -d rag -P pager=off <<'EOF'
set enable_seqscan = off; set hnsw.ef_search = 10; set hnsw.iterative_scan = relaxed_order;
select count(*) returned_iterative from (
  select chunk_id from rag.chunks where doc_id like 'PM-%'
  order by embedding <=> (select embedding from rag.chunks where chunk_id = 'RB-002#1') limit 5) t;
EOF
```

## Check your predictions

**P1.** Every row: `dims 384`, `norm 1.0000`, `embedding_model BAAI/bge-small-en-v1.5`; the first four numbers are
small values around ±0.05 (for example `{-0.052481875,-0.031237299,0.018498588,0.000132067}` for `RB-002#1`). The
model outputs unit-length vectors, so cosine similarity and inner product rank identically, and the numbers mean
nothing individually: only distances between vectors do.

**P2.**

```
 RB-002#2      | 0.816
 RB-025#2      | 0.785
 PM-2026-05#2  | 0.777
 POL-SEC-004#0 | 0.592
```

Same runbook first, then the two other "disk/volume" chunks, then the unrelated policy. Note how compressed the
scale is: unrelated text still scores 0.59. Cosine similarity is only meaningful relative to other candidates, which
is why the API ranks by it but never thresholds on it.

**P3.** No. The plan is `Sort` over a `Seq Scan on chunks`: with 118 rows (a 152 kB table), reading everything and
sorting is cheaper than walking a graph, and it's exact. The HNSW index is 248 kB, the GIN index 344 kB, both bigger
than the table. With `enable_seqscan = off` the plan becomes `Index Scan using chunks_embedding_hnsw on chunks` with
`Order By: (embedding <=> …)`. You'd see that plan on its own above a few thousand rows.

**P4.** Much better than you'd guess:

```
method                                       recall@10   p50 ms  index MB
exact (sequential scan)                          1.000      9.2         -
HNSW m=16, ef_search=10                          0.992      0.8        41
HNSW m=16, ef_search=20                          0.998      0.8        41
HNSW m=16, ef_search=40                          0.998      1.0        41
HNSW m=16, ef_search=100                         1.000      1.2        41
HNSW m=16, ef_search=200                         1.000      1.3        41
   (HNSW build took 7.5s)
HNSW on halfvec (16-bit), ef_search=40           0.998      1.1        23
binary quantised HNSW + exact re-rank of 100     0.996      1.3         7
```

Recall 0.99 at about 10x the speed, and the scan's cost grows linearly with rows while HNSW's barely moves. halfvec
halves the index for no visible loss; binary quantisation plus an exact re-score of a 100-row shortlist keeps 99.6%
recall with an index 6x smaller. Timings vary run to run; recall doesn't (the data is seeded). One caveat that bit
this repo: the first version of the benchmark used uniform random vectors and got recall 0.47 at `ef_search = 40`.
Real embeddings are clustered and HNSW thrives on that. Benchmark on your own vectors.

**P5.** `postmortem_chunks = 11`, `returned_plain = 1`. HNSW found its 10 nearest candidates for "EBS volume full",
almost none of them were postmortems, and the filter threw them away: you asked for 5 rows and got 1, silently.
With `iterative_scan = relaxed_order`, `returned_iterative = 5`. `relaxed_order` may return rows slightly out of
distance order (the API re-sorts anyway); `strict_order` keeps exact order at some extra cost.

## What to remember

- Embeddings are unit vectors; only relative distances mean anything.
- An HNSW index is only used when it's cheaper than a scan, which for vectors means thousands of rows.
- `ef_search` is the recall dial; halfvec and binary quantisation trade a little recall for a lot of space.
- Filtered ANN search can silently return too few rows. Use iterative scans (pgvector 0.8+).

Next: [Lab 05 · Hybrid search and reranking](05-hybrid-search-and-reranking.md).
