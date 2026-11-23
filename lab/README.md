# Hands-on lab: the RAG stack, one component per sitting

The lessons in [docs/](../docs) explain the design. This track has you poke each running piece until you could debug
it yourself. It follows the data: secrets first (nothing starts without them), then the database credentials they
turn into, the documents and how they become chunks, the vectors and their index, search, the evals that measure
search, and finally Claude answering, on its own and as an agent with tools.

## Fresh start (do this once, before Lab 01)

```bash
cd ~/workstuff/argocd-terraform-opentofu/rag-vector-srch && git pull
docker ps --format '{{.Names}}' | grep -v ec2-lakehouse   # should print nothing: one lab stack at a time
cp -n .env.example .env       # then put ANTHROPIC_API_KEY in .env (Labs 07 and 08 need it)
mise install                  # Python, uv and the `bao` CLI, pinned in mise.toml
mise run setup                # Python deps for the host-side scripts
mise run reset                # DELETES this stack's volumes: Postgres, OpenBao (data, seal key, root token). .env stays
mise run up                   # build, OpenBao init + config, Postgres, ingest, API, MCP. ~35 s (first build ~5 min)
source lab/env.sh             # once per terminal
curl -s $API/readyz | jq -c . # {"status":"ready","db_user":"v-approle-rag-read-…","chunks":118}
```

When you finish a sitting, `mise run down` stops the stack and keeps its data. OpenBao unseals itself on the next
`mise run up` (auto-unseal; Lab 01 shows how).

Every lab has the same shape:

1. **Look**: real commands against your running stack.
2. **Predict** before you run: each step asks a question (P1, P2, …). Write your guess down first. The answers, with
   the output I got running every command on a freshly reset stack, are at the bottom of each file.
3. **Break it, then fix it**: at least one failure on purpose, so you've seen it before it happens for real.

A tmux split works well: the lab on one side, a shell on the other, a third pane for `docker compose logs -f api`.

| Lab | Component | You'll be able to explain | Changes anything? |
|---|---|---|---|
| [01](01-openbao.md) | OpenBao | auto-unseal vs Shamir, what a token may do, policies applied at request time, the audit log | rewrites one policy, then restores it |
| [02](02-dynamic-db-credentials.md) | Dynamic Postgres users | a user that exists for an hour, `VALID UNTIL`, revocation, a rotated root, OpenBao on the critical path | creates, revokes and drops users; stops OpenBao for a minute |
| [03](03-corpus-and-ingest.md) | Corpus, chunking, ingest | front matter, sections as chunks, contextual headers, incremental and atomic loads | edits a runbook, adds a broken one, restores both |
| [04](04-vectors-in-postgres.md) | pgvector | what a stored vector is, cosine distance in SQL, when HNSW is used, filtered ANN, recall vs speed | no (the benchmark uses a scratch schema) |
| [05](05-hybrid-search-and-reranking.md) | Hybrid search and reranking | why each retriever wins where it does, RRF by hand, what a reranker score means | no |
| [06](06-retrieval-evals.md) | Retrieval evals | recall, hit@1, MRR, nDCG on a golden set; how a wrong label lies to you | edits the golden set, restores it |
| [07](07-generation-and-citations.md) | Claude answers with citations | `search_result` blocks, citations, abstaining, a poisoned document | adds a malicious runbook, removes it; calls Claude (about 5 cents) |
| [08](08-agentic-and-mcp.md) | Agentic retrieval and MCP | when the agent searches again, what an MCP client sees, transport security | calls Claude (about 5 cents) |

Each lab is one sitting of 30-45 minutes. Do them in order: later labs reuse things you saw earlier. Searches with
the reranker take about 4 seconds each on the Docker VM; that's expected (Lab 05 explains why).

## Helpers

| | What | Where |
|---|---|---|
| `source lab/env.sh` | `$BAO_ADDR`, `$BAO_TOKEN` (the root token, local only), `$API`, `$MCP_URL`, and the functions below | [env.sh](env.sh) |
| `bao …` | the OpenBao CLI (mise installs it for this folder; otherwise `mise exec -- bao …`) | |
| `vol_cat PATH` | read a file from the bootstrap volumes (`init/init.json`, `approle/rag-api/role_id`) | |
| `role_token NAME` | an AppRole login token for `rag-api` or `rag-ingest`, for `$( … )` | |
| `bao_keys PATH`, `bao_field PATH FIELD` | a KV secret's field names and version; one value, for `$( … )` only | |
| `search "q" [dense\|lexical\|hybrid] [true\|false] [k]` | `/search`, one line per hit with its dense rank, lexical rank and rerank score | |
| `ask "q" [pipeline\|agentic]` | `/ask`: the answer, its citations, tool calls, tokens and latency | |
| `psql_su "SQL"` | psql as the Postgres superuser (break-glass; the services never use it) | |
| `pg_as USER PASS "SQL"` | psql over the container network, so the password is really checked | |
| `mise run ingest`, `mise run bootstrap` | re-run the ingest job; re-run the idempotent OpenBao bootstrap | [mise.toml](../mise.toml) |
| `mise run eval:retrieval [-- --only hybrid]` | the retrieval eval (free) | [eval/retrieval.py](../eval/retrieval.py) |
| `mise run -q lab:mcp [-- "query"]` | talk to the MCP server like an MCP client would | [mcp_call.py](mcp_call.py) |

None of the labs print a secret value. The ones that need a password read it into a shell variable.

## If something is off

- `lab/env.sh: no root token yet`: run `mise run up` first, from the repo root.
- `bao: command not found`: `mise install`, or prefix with `mise exec --`.
- `/readyz` is 500 or hangs 30 s: OpenBao is stopped or unreachable and the API needed a new database connection
  (Lab 02 does this on purpose). `docker compose start openbao`.
- `bao-bootstrap didn't complete successfully`: `docker compose logs bao-bootstrap`. After `mise run reset` it starts
  from scratch; if you deleted only some volumes, reset fully.
- `/ask` returns 503 "No Anthropic API key": put the key in `.env`, then `mise run bootstrap`.
- Your numbers differ: chunk counts, ranks, retrieval metrics and the benchmark's recall are deterministic and should
  match. IDs, timings, token counts and anything Claude wrote will differ; the shape and the reasoning should match.

## The stack, with the lab that covers each part

```
   you: curl / lab helpers / Claude Code
        │                                   ┌─────────────────────────────────────────┐
        ▼                                   │ 08  MCP server :47101  search_runbooks, │
   ┌────────────────────────────────────┐   │     read_runbook  (thin adapter)        │
   │ RAG API :47100                     │◄──┴─────────────────────────────────────────┘
   │ 05  /search  embed → HNSW + FTS    │
   │              → RRF → rerank        │──► 07/08  Claude API (search_result citations)
   │ 07  /ask pipeline   08 /ask agentic│
   │ 06  measured by eval/retrieval.py  │
   └──────────────┬─────────────────────┘
                  │ SQL as a 1-hour Postgres user (02)
                  ▼
   ┌────────────────────────────────────┐        ┌──────────────────────────────────┐
   │ 04  Postgres 18 + pgvector 0.8     │◄───────│ 03  ingest: front matter → chunk │
   │     chunks: vector(384) HNSW,      │ writer │     → embed → upsert per doc     │
   │     tsv GIN · documents            │ user   │     corpus/runbooks/*.md (26)    │
   └────────────────────────────────────┘        └──────────────────────────────────┘
                  ▲ CREATE / DROP ROLE (02)
   ┌────────────────────────────────────────────────────────────────────────────────┐
   │ 01  OpenBao :47200  raft · static auto-unseal · AppRole · policies · KV · audit │
   │ 02  database engine: rag-reader (1h), rag-writer (15m)                          │
   │     feeds every box above; no service holds a long-lived password               │
   └────────────────────────────────────────────────────────────────────────────────┘
```

The full architecture diagram, with every flow numbered, is in [docs/09](../docs/09-architecture.md).
