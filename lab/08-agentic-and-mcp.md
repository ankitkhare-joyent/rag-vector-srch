# Lab 08 · Agentic retrieval and the MCP server

One sitting, about 35 minutes. Calls Claude a few times (about 5 cents). Background:
[docs/06](../docs/06-agentic-retrieval-and-mcp.md). Code: [rag/generate.py](../rag/generate.py) (`answer_agentic`,
`_run_tool`), [mcp_server/server.py](../mcp_server/server.py), [lab/mcp_call.py](mcp_call.py).

Pipeline RAG searches once, with the user's words. In agentic mode Claude gets `search_runbooks` and `read_runbook`
as tools and decides what to search for and when to stop. The MCP server exposes the same two tools to any agent.
After this lab you can explain:

- the question shapes where an agent beats one search, and what it costs
- what the agent actually searched for, and why it can cite documents pipeline mode never saw
- what an MCP client sees: tools, schemas, structured output, two kinds of errors
- why an MCP server on localhost still checks the `Host` header

## Before you start

```bash
source lab/env.sh
```

## 1. When one search isn't enough

Lab 06 found that hybrid + rerank misses q14 at the top: "How do I tell if a server is too big for what it does?"
(the answer is GUIDE-010, rightsizing).

**Predict (P1):** in pipeline mode, does Claude answer it? In agentic mode, what will the agent search for?

```bash
ask "How do I tell if a server is too big for what it does?" pipeline | head -5
ask "How do I tell if a server is too big for what it does?" agentic | tail -6
```

**Predict (P2):** a two-part, procedural question: "An i4i Kafka broker got an AWS retirement notice. What exactly do
I do?" The procedure spans RB-021 (scheduled events) and RB-012 (replacing a broker). Which documents does each
mode cite, and what does agentic mode cost in tokens?

```bash
ask "An i4i Kafka broker got an AWS retirement notice. What exactly do I do?" pipeline | grep -E '^\[|usage'
ask "An i4i Kafka broker got an AWS retirement notice. What exactly do I do?" agentic | grep -E '^\[|tool calls|usage'
```

The full loop is about 40 lines in `answer_agentic`: call Claude, run every tool call it made, send all results
back in one message, repeat until it stops calling tools or hits `RAG_AGENT_MAX_STEPS` (6).

## 2. The same tools over MCP

The MCP server is a thin adapter over the RAG API: no models, no database, no secrets. `lab/mcp_call.py` talks to it
the way Claude Code or an agent framework would.

**Predict (P3):** what will the client see for each tool: input parameters, an output schema, a read-only flag? And
how will these two bad calls differ: `read_runbook("RB-999")` and `read_runbook("../etc/passwd")`?

```bash
mise run -q lab:mcp
mise run -q lab:mcp -- "spot instances keep getting interrupted"
```

To use it from Claude Code on your laptop, with the stack up:

```bash
claude mcp add --transport http ec2-runbooks http://localhost:47101/mcp
# then ask: "using the ec2-runbooks tools, what do I do when an i4i Kafka broker gets a retirement notice?"
```

## Break it, then fix it

**Break: a web page talks to your local MCP server.** A malicious site can make your browser send requests to
`localhost` (DNS rebinding: its domain resolves to 127.0.0.1). The request then carries the attacker's domain in the
`Host` header.

**Predict (P4):** the server has no authentication (it's on 127.0.0.1 only). Does a request with
`Host: evil.example:47101` get the tool list?

```bash
H=(-H 'content-type: application/json' -H 'accept: application/json, text/event-stream' -H 'mcp-protocol-version: 2025-11-25')
curl -s -o /dev/null -w "Host: evil.example -> %{http_code}\n" $MCP_URL "${H[@]}" -H 'Host: evil.example:47101' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
curl -s -o /dev/null -w "Host: localhost    -> %{http_code}\n" $MCP_URL "${H[@]}" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

**Fix (already in place):** `TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=…)` in
[mcp_server/server.py](../mcp_server/server.py). Comment out that argument, rebuild (`docker compose build mcp &&
docker compose up -d mcp`) and run the check again to see the difference, then put it back. The production fix goes
further: an OAuth 2.1 resource server, as in learn-ai-agent's MCP server.

## Check your predictions

**P1.** Pipeline mode answers honestly but not helpfully, because GUIDE-010 isn't in its top 6 chunks:

```
**The excerpts I have don't explain how to tell whether an instance is oversized.** None of them give utilization
thresholds, metrics to check or a rightsizing procedure, so I can't give you criteria without making them up.
**Closest fit: GUIDE-010.** GUIDE-026 points to it for downsizing. Pull that guide for the actual rightsizing criteria…
```

It noticed GUIDE-010 is mentioned inside GUIDE-026 and pointed you there. Agentic mode rewrote the question in the
corpus's words and found it in one search:

```
[2] GUIDE-010: - **AWS Compute Optimizer** gives per-instance recommendations with a performance risk sco…
[3] GUIDE-010: - Instances in Auto Scaling groups: tune the scaling policy instead. - `kafka-broker` and …
tool calls: ["search_runbooks {\"query\":\"rightsizing oversized instance underutilized CPU memory\"}"]
usage: {"input_tokens":4000,"output_tokens":934}  latency_ms: 17934
```

The user's words ("too big for what it does") were the problem; the agent's words ("rightsizing", "underutilized")
match the document. That's query rewriting, done by the model when it needs it.

**P2.** Pipeline mode cites RB-021 four times and RB-017 (AMI age for instance-store fleets) once, but not RB-012, so
the actual broker replacement steps are missing. Agentic mode made two searches and cited both runbooks:

```
[1] RB-021: For `kafka-broker` (`i4i`) and `opensearch-data` on `i4g`, an `instance-retirement` means …
[2] RB-012: - The instance failed a system status check or has a scheduled retirement event (RB-021). …
[3] RB-012: 1. Confirm the cluster is healthy: no under-replicated partitions (`kafka-topics.sh --desc…
…
tool calls: ["search_runbooks {\"query\":\"instance retirement notice i4i Kafka broker\"}",
             "search_runbooks {\"query\":\"scheduled retirement event instance store\"}"]
usage: {"input_tokens":5322,"output_tokens":974}  latency_ms: 17580
```

Against pipeline's `input_tokens 2312, latency 12 s`: about 2.3x the input tokens and 1.5x the latency, for a
complete procedure. Over the whole eval set the numbers were 2.2x tokens, fact coverage 0.875 → 0.984
([docs/04](../docs/04-evaluating-retrieval.md)). A router that uses the agent only when the pipeline is unsure gets
most of both.

**P3.**

```
server: ec2-runbooks 1.0.0 | protocol: 2025-11-25
tool search_runbooks: input ['doc_type', 'limit', 'query', 'service'], output schema: yes, read-only: True
tool read_runbook: input ['doc_id'], output schema: yes, read-only: True
   1.061  RB-021      Instance-store instances
   0.068  RB-012      When to replace
  -0.511  RB-012      Overview
read_runbook: RB-021 - 1655 chars
bad call: isError = True | Error executing tool read_runbook: no document RB-999; use search_runbooks to find valid IDs
invalid input: isError = True | "Error executing tool read_runbook: 1 validation error for read_runbookArguments\ndoc_id\n  String should matc…
```

The output schema comes from the pydantic return types, so a client gets typed, structured results, not just text.
The two errors differ: `RB-999` passed validation and failed in the tool, with a message written for a model ("use
search_runbooks to find valid IDs"); `../etc/passwd` never reached the tool, because the `doc_id` parameter has a
regex pattern and the SDK rejected it. Both come back as tool results with `isError = True`, so the model can read
them and correct itself, instead of the whole request failing.

**P4.** `Host: evil.example -> 421` (Misdirected Request) and `Host: localhost -> 200`. Binding to 127.0.0.1 is not
enough on its own: the attacker's page runs in *your* browser, on *your* machine. Checking `Host` against an
allowlist is what stops it, and the MCP spec asks local servers to do exactly this.

## What to remember

- Agents beat one search on vague and multi-part questions, at roughly twice the tokens. Measure both and route.
- The agent's own search queries are often the most useful thing in its trace: they show the corpus's vocabulary.
- MCP gives any agent the same tools with typed inputs and outputs; validation errors and tool errors both go back
  to the model as `isError` results.
- A localhost server still needs `Host` checks (DNS rebinding), and a real one needs OAuth.

That's the last lab. The architecture diagram that ties all eight together is in
[docs/09](../docs/09-architecture.md). When you're done: `mise run down`.
