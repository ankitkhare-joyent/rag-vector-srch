# 00. Where RAG fits in 2026

## The problem RAG solves

A language model knows what was in its training data and nothing else. It has never seen your runbooks,
your tagging policy or last month's postmortem. You have three ways to give it that knowledge:

| Approach | How | Good for | Weak at |
|---|---|---|---|
| **Put everything in the prompt** | Paste all documents into every request | Small corpora (under a few hundred thousand tokens). Claude's 1M-token context makes this viable for more than you'd think | Cost and latency on every request; does not scale to millions of documents; no access control per document |
| **Fine-tune** | Train the model on your documents | Style, format, domain vocabulary | Facts that change weekly; citing sources; deleting a fact once learned |
| **Retrieval-augmented generation (RAG)** | Search your documents at question time, put only the relevant parts in the prompt | Large, changing corpora; answers that must cite sources; per-user permissions | Only as good as the search: if retrieval misses the right passage, the answer is wrong or empty |

RAG won as the default because knowledge changes faster than you can retrain, and because "show me
the source" is a hard requirement for anything operational. Think of it like a Trino query engine
over a data lake: the model is the compute, retrieval decides which data it reads.

## The two halves

```
          INGEST (offline, like an ETL job)                    QUERY (online, per question)

 runbooks ─► parse ─► chunk ─► embed ─► Postgres/pgvector       question ─► retrieve ─► rerank ─► Claude ─► cited answer
                                          (vectors + text)                     ▲
                                                 └─────────────────────────────┘
```

* **Ingest** turns documents into searchable chunks. It is a batch pipeline with the usual data-platform
  concerns: idempotency, incremental loads, schema (the embedding dimension), backfills when the model changes.
* **Query** finds the best chunks for a question and has the model answer from them, citing each one.

Almost every quality problem in RAG is a retrieval problem. That is why most of this course is about
search, and why lesson 04 measures retrieval separately from the answers.

## RAG vs agentic retrieval vs "just use tools"

The 2024 picture was a fixed pipeline: retrieve once, then generate. In 2026 three patterns coexist,
and this repo implements all three so you can compare them:

1. **Pipeline RAG** (`POST /ask` with `mode=pipeline`). Code retrieves, the model answers. One model call,
   predictable cost and latency, easy to evaluate. Still the right default for support bots, Q&A over
   docs and anything high-volume.
2. **Agentic retrieval** (`mode=agentic`). Retrieval is a *tool*; the model decides what to search for,
   searches again with better terms, reads whole documents and stops when it has enough. Better on vague
   or multi-part questions ("Is this a quota or a capacity problem, and what do I do for each?"), at 3 to
   10 times the tokens and latency.
3. **Retrieval as one tool among many** (the MCP server in `mcp_server/`). An agent that can also query
   live systems (your EC2 inventory MCP server in learn-ai-agent) uses runbook search when it needs
   *procedure* and the inventory tools when it needs *facts about now*. This is how coding agents and
   on-call assistants are built today.

Long context did not kill RAG; it changed the trade-off. With 1M tokens you can afford to retrieve more
generously (whole documents rather than tiny chunks), and for a corpus this size you could even skip
retrieval. You would still want search for cost (every token in the prompt is paid for on every call),
latency, citations and per-user permissions, and the corpus you care about at work is rarely this small.

## What you will build, in order

| Lesson | Topic | Code |
|---|---|---|
| 01 | Embeddings, distance, ANN indexes (HNSW), pgvector | [`rag/models.py`](../rag/models.py), [`sql/001_schema.sql`](../sql/001_schema.sql), [`scripts/ann_bench.py`](../scripts/ann_bench.py) |
| 02 | Chunking and idempotent ingestion | [`rag/corpus.py`](../rag/corpus.py), [`rag/ingest.py`](../rag/ingest.py) |
| 03 | Hybrid search (vectors + full text), RRF, reranking | [`rag/search.py`](../rag/search.py) |
| 04 | Evaluating retrieval | [`eval/retrieval.py`](../eval/retrieval.py), [`eval/golden.jsonl`](../eval/golden.jsonl) |
| 05 | Grounded generation with citations | [`rag/generate.py`](../rag/generate.py), [`eval/answers.py`](../eval/answers.py) |
| 06 | Agentic retrieval and MCP | [`rag/generate.py`](../rag/generate.py) (`answer_agentic`), [`mcp_server/server.py`](../mcp_server/server.py) |
| 07 | Secrets with OpenBao | `openbao/`, [`rag/bao.py`](../rag/bao.py), [`rag/bao_bootstrap.py`](../rag/bao_bootstrap.py) |
| 08 | Production checklist | everything |
| 09 | Architecture diagram | [`docs/09-architecture.md`](../docs/09-architecture.md) |

---

[Index](../README.md) · [01-embeddings-and-vector-search](01-embeddings-and-vector-search.md) →
