# 06. Agentic retrieval and MCP

## From pipeline to agent

Pipeline RAG retrieves once with the user's words. That fails in predictable ways:

* The question has **two parts** ("is it quota or capacity, and what do I do for each?"); one search
  returns chunks for the more prominent part.
* The user's words are **vague** ("builds wait a long time") and the right chunk uses different ones
  ("queue backlog", "MaxSize").
* The answer needs **a document the first chunk points to** ("follow RB-012" inside the retirement runbook).

Agentic retrieval gives the model the search as a tool and lets it work like an engineer would: search,
read, refine, search again, then answer. `answer_agentic()` in [`rag/generate.py`](../rag/generate.py):

```
messages = [user question]
loop (max 6 model calls):
    response = Claude(messages, tools=[search_runbooks, read_runbook])
    append the full response (thinking blocks included) to messages
    if no tool calls: done
    run every tool call (Claude may ask for several at once), return ALL results in ONE user message
```

Details that matter in production agents, all in that function:

* **Tools return `search_result` blocks**, so citations work across the whole conversation (the citation
  index counts every search result in every tool result, in order; we keep a parallel `sources` list).
* **A hard step limit** (`RAG_AGENT_MAX_STEPS`). Agents loop; budgets stop them.
* **Strict tool schemas** (`strict: true`, enums for `doc_type`) so arguments are always valid.
* **Errors as tool results** (`is_error: true`, "No document with id X. Search first to find valid IDs")
  so the model can correct itself instead of the request failing.
* **Parallel calls answered in one message**; splitting them teaches the model to stop calling in parallel.
* **Tools are read-only.** An agent that can only read can be wrong but cannot do damage.

The cost is real: compare `avg_input_tokens`, `avg_tool_calls` and latency between
[`eval/results/answers-pipeline.md`](../eval/results/answers-pipeline.md) and `answers-agentic.md`. A common production design is a **router**:
pipeline RAG by default, agentic mode for questions classified as multi-part, or when the reranker's best
score is low (retrieval was unsure).

## Patterns you will hear about

| Pattern | What it is | Here |
|---|---|---|
| Query rewriting / HyDE | LLM rewrites the question, or writes a hypothetical answer and embeds that | Implicitly: the agent writes its own queries |
| Multi-query / decomposition | Split into sub-questions, retrieve for each, merge | The agent does this when it issues several searches |
| Corrective / self-RAG | Grade retrieved chunks, re-retrieve if poor | Exercise: add a reranker-score threshold that triggers agentic mode |
| GraphRAG | Build an entity graph from documents; retrieve by traversal and community summaries | Useful for "what connects X and Y" questions over large corpora; overkill here |
| Deep research | Long-running agent with many searches and a written report | Same loop, bigger budget, plus web search |

## MCP: retrieval as a shared tool

The **Model Context Protocol** is the standard way to expose tools to any agent: Claude Code, Claude
Desktop, the Claude API's MCP connector, LangGraph, Strands, and your learn-ai-agent agents. Instead of
copying the search code into every agent, [`mcp_server/server.py`](../mcp_server/server.py) exposes two tools over Streamable HTTP:

* `search_runbooks(query, doc_type?, service?, limit)` -> sections with doc IDs and reranker scores
* `read_runbook(doc_id)` -> the full document

It is a thin adapter over the RAG API: no database credentials, no models, no secrets. Outputs are typed
(pydantic models become the tool's output schema), bounded and compact, because every byte lands in the
model's context. It follows the same rules as the EC2 inventory MCP server in learn-ai-agent (read-only
annotations, actionable errors). The difference worth noticing: that server is an OAuth 2.1 resource
server; this one runs without auth on 127.0.0.1 only. Production would add the same OAuth layer.

### Plug it into the EC2 inventory agent

With both stacks up, an agent can now combine **live facts** (inventory MCP: "which kafka brokers have a
retirement event?") with **procedure** (runbook MCP: "how do I replace one?"). In learn-ai-agent, add a
second server to the agent's MCP client config, for example with `langchain-mcp-adapters`:

```python
client = MultiServerMCPClient({
    "ec2-inventory": {"transport": "streamable_http", "url": "http://localhost:8001/mcp", "headers": {...}},
    "ec2-runbooks":  {"transport": "streamable_http", "url": "http://localhost:47101/mcp"},
})
tools = await client.get_tools()
```

Or try it from Claude Code on your laptop:

```bash
claude mcp add --transport http ec2-runbooks http://localhost:47101/mcp
# then ask: "using the ec2-runbooks tools, what do I do when an i4i Kafka broker gets a retirement notice?"
```

That is the shape of most real agentic systems in 2026: several narrow MCP servers (data, procedures,
actions with approval gates) and one model deciding which to call.

---

← [05-generation-and-citations](05-generation-and-citations.md) · [Index](../README.md) · [07-secrets-with-openbao](07-secrets-with-openbao.md) →
