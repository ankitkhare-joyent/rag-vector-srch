# 08. Production checklist

What this repo does, what it leaves out on purpose, and what you would add at work. Use it as a review
checklist for any RAG system.

## Retrieval quality

- [x] Structure-aware chunking with contextual headers, code and tables kept whole (02)
- [x] Hybrid search (vectors + full text) fused with RRF (03)
- [x] Cross-encoder reranking of the fused candidates (03)
- [x] Metadata filters, with pgvector iterative scans so filtered HNSW still returns k rows (03)
- [x] Golden set and retrieval metrics, separate from answer metrics (04)
- [ ] True BM25 (ParadeDB `pg_search`, VectorChord-BM25) or learned sparse vectors instead of `ts_rank`
- [ ] Contextual retrieval: an LLM-written context sentence per chunk at ingest
- [ ] Eval in CI as a regression gate; golden set grown from real failures

## Generation

- [x] Native citations via `search_result` blocks; citations returned to the client (05)
- [x] Grounding and abstention rules; refusal handling and server-side fallback (05)
- [x] Agentic mode with step limit, strict schemas, read-only tools, errors as tool results (06)
- [ ] Streaming responses; prompt caching for the system prompt and tools
- [ ] Router: pipeline by default, agentic when retrieval confidence is low or the question is multi-part
- [ ] LLM-as-judge faithfulness eval, calibrated on human labels

## Data and ingestion

- [x] Idempotent, incremental, atomic per document; tracks the embedding model per chunk (02)
- [x] Models baked into the image; no downloads at runtime
- [ ] Document-level permissions stored with chunks and enforced as a filter on every query
- [ ] Change-driven ingestion (S3 events, CDC) instead of a manual job; PII scrubbing before embedding
- [ ] Blue/green re-embedding when the model changes (new column or table, switch reads, drop old)

## Security and secrets

- [x] No static database passwords: dynamic Postgres users per service from OpenBao, 15 min to 1 h (07)
- [x] Least privilege: API gets read-only users and the LLM key; ingest gets writer users and no key (07)
- [x] OpenBao's own DB admin password rotated so no human knows it; audit log of every secret access (07)
- [x] Auto-unseal, Raft storage, declarative audit device (07)
- [x] All ports bound to 127.0.0.1; containers run as non-root
- [ ] TLS everywhere (OpenBao, Postgres, API); OpenBao HA with 3 nodes and KMS auto-unseal
- [ ] Platform identity (Kubernetes or AWS IAM auth) instead of AppRole secret_id files
- [ ] End-user auth on the API (OIDC at a gateway or in-app JWT validation) and OAuth on the MCP server
- [ ] Prompt-injection review of ingested sources; output filtering if answers are shown to customers

## Operations

- [x] Health and readiness endpoints; per-stage timings returned by `/search`
- [ ] Tracing per request (query, chunk IDs, scores, tokens, latency) with OpenTelemetry/Langfuse
- [ ] Dashboards: p95 latency per stage, tokens and cost per answer, "not covered" rate, feedback rate
- [ ] Postgres backups and HNSW rebuild plan (`REINDEX CONCURRENTLY`); `maintenance_work_mem` sized for builds
- [ ] Rate limits and per-user cost budgets on `/ask`

---

← [07-secrets-with-openbao](07-secrets-with-openbao.md) · [Index](../README.md) · [09-architecture](09-architecture.md) →
