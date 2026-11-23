# 01. Embeddings and vector search

## Embeddings: meaning as coordinates

An **embedding model** maps text to a fixed-length list of numbers (a vector) such that texts with similar
meaning land close together. Our model, `BAAI/bge-small-en-v1.5`, outputs 384 numbers per text:

```
"EBS data volume running out of space"   -> [ 0.021, -0.087,  0.044, ... ]  (384 floats)
"the search cluster's disks are full"    -> [ 0.019, -0.079,  0.051, ... ]  close: same meaning
"Spot interruption two-minute notice"    -> [-0.064,  0.012, -0.033, ... ]  far: different topic
```

Nobody designs what each dimension means; the model learns the space from hundreds of millions of
(question, relevant passage) pairs. What you get is: "disk full" and "volume out of space" are neighbours
even though they share no words. That is the thing keyword search cannot do.

Try it (host Python, no stack needed):

```bash
uv run python -c "
from rag.models import embed_query, embed_passages
import numpy as np
q = embed_query('the search cluster disks are almost full')
docs = ['EBS data volume running out of space', 'Spot interruptions on spark-batch', 'IMDSv2 is mandatory']
for d, v in zip(docs, embed_passages(docs)): print(f'{float(np.dot(q, v)):.3f}  {d}')
"
```

### Distance metrics

| Operator (pgvector) | Metric | Use when |
|---|---|---|
| `<=>` | cosine distance (1 - cosine similarity) | The default for text embeddings |
| `<#>` | negative inner product | Vectors are normalised (then it ranks the same as cosine, slightly faster) |
| `<->` | Euclidean (L2) | Image and some older models; check the model card |
| `<~>` | Hamming (on `bit`) | Binary-quantised vectors |

Use what the model was trained with. BGE vectors are normalised, so cosine and inner product agree.

### Query and passage are embedded differently

Many models (BGE, E5, Nomic, most commercial ones) expect a prefix or a separate mode for queries versus
documents ("Represent this sentence for searching relevant passages: ..."). [`rag/models.py`](../rag/models.py) uses
fastembed's `query_embed` and `passage_embed` for that. Getting this wrong costs recall without any error.

### Choosing an embedding model (2026)

| Option | Dim | Where it runs | Notes |
|---|---|---|---|
| `BAAI/bge-small-en-v1.5` (this repo) | 384 | CPU, local | 67 MB, fast, decent. Good for learning and small corpora |
| `bge-base` / `snowflake-arctic-embed-m` / `nomic-embed-text-v1.5` | 768 | CPU or GPU | Better quality, ~3x slower |
| Qwen3-Embedding, `bge-m3`, Jina v3 | 1024+ | GPU | Strong open models, multilingual, long inputs |
| Voyage (Anthropic's recommended provider), OpenAI `text-embedding-3`, Cohere Embed | 256 to 3072 | API | Top quality, no infra, data leaves your network |

Choose with your own eval set (lesson 04), not leaderboards: MTEB scores often don't transfer to ops
runbooks full of error codes. Many newer models support **Matryoshka** truncation: you can keep only the
first 256 of 1024 dimensions and lose little quality, which cuts storage 4x.

**The dimension is part of your schema** (`vector(384)` in [`sql/001_schema.sql`](../sql/001_schema.sql)). Changing models means
re-embedding everything into a new column or table and switching reads over, exactly like a backfill
into a new Iceberg table version. We store `embedding_model` on every chunk so a mismatch is detectable,
and [`rag/ingest.py`](../rag/ingest.py) re-embeds documents whose model differs.

## Vector search: exact vs approximate

Finding the nearest vectors to a query exactly means comparing against every row: O(n). For our ~120
chunks that is under a millisecond and Postgres does exactly that. At 10 million chunks it is far too
slow, so production systems use **approximate nearest neighbour (ANN)** indexes, which trade a little
recall for orders of magnitude of speed.

### HNSW (what we use)

**Hierarchical Navigable Small World** builds a multi-layer graph: each vector links to its `m` nearest
neighbours; the top layers are sparse "highways", the bottom layer has every vector. A search enters at
the top, greedily walks towards the query, drops a layer, repeats, and at the bottom explores the
`ef_search` best candidates it has seen.

```
layer 2:   A ─────────────────── F                 few nodes, long jumps
layer 1:   A ──── C ──── F ──── H
layer 0:   A ─ B ─ C ─ D ─ E ─ F ─ G ─ H ─ I       every node, short links
```

Knobs (pgvector names):

| Knob | When | Effect |
|---|---|---|
| `m` (default 16) | build | Links per node. Higher: better recall, bigger index, slower build |
| `ef_construction` (default 64) | build | Search breadth while building. Higher: better graph, slower build |
| `hnsw.ef_search` (default 40) | query, `SET` per session or transaction | Candidates explored. **The main recall vs latency dial**. We use 100 |
| `hnsw.iterative_scan` (0.8+) | query | Keeps searching when a `WHERE` filter removes most neighbours. We set `relaxed_order` |

### IVFFlat (the other pgvector index)

Clusters vectors into `lists` with k-means at build time and searches the `probes` nearest clusters.
Faster to build and smaller than HNSW, but worse recall at the same speed and it must be built *after*
loading data (the clusters come from the data). HNSW is the usual choice now.

### Quantisation: making vectors smaller

A 384-dim `vector` is 1.5 KB. At 100 million chunks that is 150 GB before the index. Options in pgvector:

* `halfvec`: 16-bit floats, half the size, almost no recall loss.
* `binary_quantize(v)`: 1 bit per dimension, 32x smaller. Recall drops a lot on its own, so you search the
  binary index for a shortlist (say 100) and re-score the shortlist with full vectors. This is the same
  "cheap first pass, expensive second pass" idea as reranking in lesson 03.

[`scripts/ann_bench.py`](../scripts/ann_bench.py) shows all of this on 20,000 synthetic vectors: exact search vs HNSW at several
`ef_search` values, halfvec and binary quantisation, with recall and latency. Run it with the stack up.

Results on the local Docker VM (20,000 x 384, 50 queries):

```
loaded 20,000 x 384-dim vectors in 1.0s, table 33 MB

method                                       recall@10   p50 ms  index MB
exact (sequential scan)                          1.000     20.6         -
HNSW m=16, ef_search=10                          0.970      1.5        41
HNSW m=16, ef_search=20                          0.978      1.8        41
HNSW m=16, ef_search=40                          0.978      1.8        41
HNSW m=16, ef_search=100                         1.000      2.1        41
HNSW m=16, ef_search=200                         1.000      2.2        41
   (HNSW build took 14.5s)
HNSW on halfvec (16-bit), ef_search=40           0.998      2.6        23
binary quantised HNSW + exact re-rank of 100     0.994      2.1         7
```

What to take from it:

* HNSW answers in about 2 ms instead of 21 ms for a full scan, and the gap grows linearly with table size:
  at 10 million rows the scan takes seconds, HNSW still milliseconds.
* `ef_search` is the recall dial. Here 100 gives perfect recall; on harder data you will see the curve
  more clearly. We use 100 in the API.
* `halfvec` halves the index (41 MB to 23 MB) with no visible recall loss, a free win at scale.
* Binary quantisation plus re-ranking the shortlist with full vectors keeps 99% recall with an index
  6x smaller than full precision.
* The first version of this benchmark used uniform random 384-dim noise and HNSW recall at ef_search=40
  was 0.47. Real embeddings are clumped by topic and have low intrinsic dimension, which is what makes
  graph search work. Always benchmark ANN settings on your own vectors, not on random data.


## pgvector vs a dedicated vector database

| | pgvector (this repo) | Qdrant / Weaviate / Milvus | Managed (Pinecone, Turbopuffer, OpenSearch, Aurora) |
|---|---|---|---|
| Strength | One database: SQL joins, transactions, filters, backups and permissions you already run | Built for vectors: faster at very large scale, native hybrid and multi-vector (ColBERT) search, quantisation built in | No operations |
| Sweet spot | Up to tens of millions of vectors, when you already run Postgres | Hundreds of millions, heavy filtering, high QPS | Teams without platform capacity |
| Cost of choosing it | Tuning `maintenance_work_mem` and index builds at scale; no BM25 built in | Another stateful system to run and keep in sync | Vendor lock-in, data leaves your network |

The common 2026 advice: start with pgvector unless you already know you'll exceed what one Postgres
cluster can do. For a data platform engineer the mental model is familiar: a vector index is just
another secondary index, with a recall knob.

---

← [00-where-rag-fits](00-where-rag-fits.md) · [Index](../README.md) · [02-chunking-and-ingestion](02-chunking-and-ingestion.md) →
