# 02. Chunking and ingestion

Ingestion is an ETL job: extract documents, transform them into chunks with embeddings, load them into
Postgres. Everything you know about pipelines applies (idempotency, incremental loads, backfills), plus
one RAG-specific decision that matters more than the choice of vector database: **how you cut documents
into chunks**.

## Why chunk at all

* Embedding models have an input limit (512 tokens for BGE) and squash a whole input into one vector.
  A 3,000-word runbook squashed into one vector is a blur of every topic in it.
* Retrieval returns units. If the unit is a whole document, the model gets lots of irrelevant text; if it
  is a sentence, it lacks context.
* Citations point at the unit. Smaller units give more precise citations.

There is no universally right size. Typical production values are 200 to 800 tokens. With a 1M-token
model you can afford to retrieve generously, so err towards slightly bigger, self-contained chunks.

## Our strategy ([`rag/corpus.py`](../rag/corpus.py))

1. **Structure first.** Split on `##` headings. Runbooks are written in sections ("Triage", "Fix",
   "Do not"), and a section is the natural unit an engineer looks for.
2. **Size second.** A section over `chunk_max_tokens` (300) is split on paragraph boundaries, carrying
   the last paragraph or two (up to 40 tokens) into the next piece as **overlap**, so a step that refers
   to the previous paragraph keeps its context.
3. **Never split a code block or a table.** Half a command is worse than none.
4. **Contextual header.** Every chunk is stored and embedded with a header such as
   `RB-002 EBS data volume running out of space > Immediate mitigation`. A section called "Fix" means
   nothing alone; with the header it is findable both by meaning and by the document ID. This is a cheap
   version of Anthropic's *contextual retrieval* technique, where an LLM writes a sentence of context
   for each chunk at ingest time; that costs one LLM call per chunk and typically cuts retrieval
   failures further. Try adding it as an exercise (use prompt caching on the document so it stays cheap).

Our 26 documents produce about 120 chunks of roughly 70 tokens on average, because our runbooks have
short sections. Run the chunker yourself:

```bash
uv run python -c "
from pathlib import Path; from rag.corpus import load_corpus, chunk_document
for d in load_corpus(Path('corpus/runbooks'))[:2]:
    for c in chunk_document(d): print(c.chunk_id, c.token_estimate, '|', c.header)
"
```

### Other strategies you will meet

| Strategy | Idea | When |
|---|---|---|
| Fixed-size windows | Every N tokens with overlap | Unstructured text, logs, transcripts |
| Recursive character splitting (LangChain's default) | Try paragraph, then sentence, then word boundaries | Mixed content without reliable headings |
| Semantic chunking | Split where consecutive sentence embeddings change a lot | Long prose without structure; costs embeddings at ingest |
| Parent-child ("small to big") | Search small chunks, return their bigger parent section to the model | When small chunks retrieve well but answers need more context |
| Late chunking / multi-vector (ColBERT) | Embed tokens with full-document context, pool per chunk | Higher quality, more storage; Qdrant and Vespa support it natively |

Our `read_runbook` tool (lesson 06) is a form of small-to-big: search chunks, then read the whole document.

## Ingestion pipeline ([`rag/ingest.py`](../rag/ingest.py))

```
load_corpus ─► sha256 per file ─► changed? ─► chunk ─► embed (batch 32) ─► one transaction per document:
                                                                          DELETE doc (cascades to chunks)
                                                                          INSERT doc, INSERT chunks
```

Properties worth copying into any RAG pipeline:

* **Idempotent and incremental.** Each document's content hash is stored; re-running ingests only changed
  files, and documents removed from the corpus are deleted. `--full` forces a re-embed.
* **Atomic per document.** Readers never see a document with half its chunks.
* **Model-aware.** Every chunk stores `embedding_model`; if you change `RAG_EMBED_MODEL`, the next run
  re-embeds everything whose model differs. (A dimension change also needs a schema change; see lesson 01.)
* **Least privilege.** The ingest job gets a `rag-writer` Postgres user from OpenBao that lives 15
  minutes; the API only ever gets read-only users (lesson 07).
* **Full text alongside vectors.** The `tsv` column is *generated* from the header and content, so the
  keyword index can never drift from the text.

At larger scale the same design becomes: documents land in object storage, a change feed (S3 events,
CDC, or an Iceberg table's snapshots) drives an Airflow or Spark job, embedding runs in batches on GPUs
or through a provider's batch API, and you load with `COPY` and build the HNSW index after bulk loads.

## The schema ([`sql/001_schema.sql`](../sql/001_schema.sql))

```
documents(doc_id PK, title, doc_type, team, services[], updated, body, content_sha256)
chunks(chunk_id PK, doc_id FK, ordinal, section, header, content,
       embedding vector(384), embedding_model, tsv tsvector GENERATED)
  index: HNSW on embedding (cosine), GIN on tsv, GIN on documents.services
```

Metadata columns (`doc_type`, `team`, `services`) are what make **filtered search** possible: "only
policies", "only kafka-broker docs". In a real system the most important filter is *permissions*: store
which groups may read each document and always filter by the caller's groups, so retrieval can never
leak a document into an answer that the user couldn't open themselves.

---

← [01-embeddings-and-vector-search](01-embeddings-and-vector-search.md) · [Index](../README.md) · [03-hybrid-search-and-reranking](03-hybrid-search-and-reranking.md) →
