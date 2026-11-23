# 05. Generation with citations

Retrieval found the right chunks. Now the model has to answer **only from them**, say so when they don't
contain the answer, and show where each claim came from. [`rag/generate.py`](../rag/generate.py) does this with Claude.

## The request

```python
client.beta.messages.create(
    model="claude-opus-5-5",
    system=SYSTEM_PROMPT,                       # role, grounding rules, answer format
    messages=[{"role": "user", "content": [
        {"type": "search_result", "source": "RB-002#1",
         "title": "RB-002: EBS data volume running out of space > Immediate mitigation",
         "content": [{"type": "text", "text": "<chunk text>"}], "citations": {"enabled": True}},
        ...                                      # one block per retrieved chunk, best first
        {"type": "text", "text": "The search cluster's data disks are almost full, what do I do?"},
    ]}],
    output_config={"effort": "medium"},
    betas=["server-side-fallback-2026-07-01"], fallbacks="default",
)
```

Three choices in there:

1. **`search_result` content blocks.** Instead of pasting chunks into the prompt as text, each chunk is
   a structured search result with a source and title. Claude then returns **native citations**: the
   answer comes back as several text blocks, and each block that relies on a chunk carries a
   `search_result_location` citation with the result's index, source, title and the exact `cited_text`.
   The UI can link every claim to its source, and you can verify a claim was actually in the source
   rather than trusting the model to write "[1]" correctly. `_to_answer()` turns those into `[n]` markers
   and a citation list.
2. **The system prompt sets the grounding contract**: use only the excerpts, copy commands and IDs
   exactly, say plainly when the runbooks don't cover something, prefer the most specific and recent
   document when they conflict. Short, specific rules beat long lists of "never" statements.
3. **Model and effort.** Claude Opus 5.5 at `effort: medium`. For a high-volume support bot you would
   test `low` effort or a smaller model against the eval in lesson 04 before deciding; cost per correct
   answer is the number that matters. `fallbacks: "default"` retries on a fallback model server-side if
   a safety classifier declines, and `stop_reason == "refusal"` is handled before reading content.

## Failure modes and what handles them

| Failure | Cause | Mitigation here |
|---|---|---|
| Wrong answer, confidently | Retrieval missed the right chunk | Hybrid + rerank (03), measured in 04; agentic mode can search again (06) |
| Hallucinated command or threshold | Model fills gaps from training data | Grounding rule in the system prompt; citations make unsupported sentences visible; answer eval checks key facts |
| Answers an unanswerable question | Nearest chunks are always *something* | Prompt rule to say it isn't covered; abstention check in the answer eval |
| Mixes up two similar runbooks | Near-duplicate chunks (status checks vs scheduled events) | Contextual headers, reranking, citations show which doc was used |
| Outdated procedure | Old and new docs both retrieved | `updated` date in metadata; prompt prefers the most recent; in production, retire old docs |
| Prompt injection inside a document | Retrieved text says "ignore previous instructions" | Documents arrive as data blocks, not instructions; keep tools read-only; only ingest trusted sources |

## Streaming and caching (not implemented, worth knowing)

* **Streaming** (`client.messages.stream`) shows the answer as it is generated; citations arrive as
  `citations_delta` events. Use it in any chat UI.
* **Prompt caching**: the system prompt and tool definitions are identical on every call; put a
  `cache_control` breakpoint after them and repeat calls read them at a tenth of the price. It pays off
  most in the agentic loop, where every step resends the growing conversation.

## Try it

```bash
curl -s localhost:47100/ask -H 'content-type: application/json' \
  -d '{"question": "The search cluster data disks are almost full, what do I do right now?"}' | jq -r '.answer, "", (.citations[] | "[\(.number)] \(.doc_id): \(.cited_text[:80])...")'

uv run python -m eval.answers            # all 36 questions, writes eval/results/answers-pipeline.md
```

---

← [04-evaluating-retrieval](04-evaluating-retrieval.md) · [Index](../README.md) · [06-agentic-retrieval-and-mcp](06-agentic-retrieval-and-mcp.md) →
