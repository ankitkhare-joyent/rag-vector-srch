"""Generation: turn retrieved chunks into a grounded, cited answer with Claude.

Two ways to wire retrieval to the model (docs/05 and docs/06 compare them):

* `answer_pipeline`  classic RAG. Our code retrieves once, then asks Claude to answer from those
                     results. One model call, predictable latency and cost, easy to evaluate.
* `answer_agentic`   agentic retrieval. Claude gets a `search_runbooks` tool (and `read_runbook`) and
                     decides what to search for, how often, and when it has enough. Better for vague or
                     multi-part questions, at the cost of more calls and less predictability.

Both pass chunks to Claude as `search_result` content blocks. That gives *native citations*: every
sentence that relies on a chunk comes back with a `search_result_location` saying which chunk and the
exact cited text, so the UI can link to the source instead of trusting the model to cite correctly.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

import anthropic

from rag.search import Filters, Hit
from rag.settings import Settings

log = logging.getLogger("rag.generate")

# Server-side refusal fallback: if a safety classifier declines, the API retries on a fallback model
# inside the same call instead of returning an empty answer.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

SYSTEM_PROMPT = """You are the on-call assistant for a cloud platform team. You answer questions about \
operating the company's EC2 fleet using the internal runbooks, policies, guides and postmortems.

Ground every statement in the runbook excerpts you are given. Use the excerpts' exact commands, \
thresholds, quota codes and document IDs; never invent them. If the excerpts do not contain the answer, \
say plainly that the runbooks do not cover it and name the team or document that is the closest fit. \
When excerpts disagree, prefer the most specific and most recently updated one and mention the conflict.

Answer for an engineer in the middle of an incident: lead with the action, use a short numbered list \
for steps, put commands in code blocks, and keep it under 250 words unless the question needs more."""

AGENT_PROMPT = SYSTEM_PROMPT + """

You have tools to search and read the runbooks. Search before answering anything factual. Prefer \
several focused searches over one broad one (for example one per error code or service), read the full \
runbook when a step references another section, and stop searching once you can answer."""


@dataclass
class Citation:
    number: int
    doc_id: str
    title: str
    cited_text: str


@dataclass
class Answer:
    text: str                                   # answer with [n] markers after cited sentences
    citations: list[Citation]
    sources: list[dict]                         # every search result shown to the model, in order
    model: str
    stop_reason: str | None
    usage: dict = field(default_factory=dict)
    tool_calls: list[dict] = field(default_factory=list)


def _search_result_block(source: str, title: str, text: str) -> dict:
    return {"type": "search_result", "source": source, "title": title,
            "content": [{"type": "text", "text": text}], "citations": {"enabled": True}}


def hit_to_block(h: Hit) -> dict:
    return _search_result_block(source=h.chunk_id, title=f"{h.doc_id}: {h.title} > {h.section}", text=h.content)


class Generator:
    def __init__(self, settings: Settings, api_key: str):
        self.s = settings
        # Retries 408/409/429/5xx with backoff; the key comes from OpenBao, never from the environment.
        self.client = anthropic.Anthropic(api_key=api_key, max_retries=3, timeout=120.0)

    def _create(self, *, system: str, messages: list, tools: list | None = None):
        kwargs = dict(model=self.s.llm_model, max_tokens=8000, system=system, messages=messages,
                      output_config={"effort": self.s.llm_effort}, betas=[FALLBACK_BETA], fallbacks="default")
        if tools:
            kwargs["tools"] = tools
        return self.client.beta.messages.create(**kwargs)

    # ------------------------------------------------------------------ classic RAG
    def answer_pipeline(self, question: str, hits: list[Hit]) -> Answer:
        sources = [{"source": h.chunk_id, "doc_id": h.doc_id, "title": f"{h.doc_id}: {h.title} > {h.section}"}
                   for h in hits]
        content = [hit_to_block(h) for h in hits] + [{"type": "text", "text": question}]
        resp = self._create(system=SYSTEM_PROMPT, messages=[{"role": "user", "content": content}])
        return self._to_answer(resp, sources)

    # ------------------------------------------------------------------ agentic retrieval
    def answer_agentic(self, question: str, search_fn: Callable[[str, Filters, int], list[Hit]],
                       read_fn: Callable[[str], dict | None]) -> Answer:
        tools = [
            {"name": "search_runbooks", "strict": True,
             "description": "Hybrid search (keywords + meaning, reranked) over the EC2 operations runbooks, "
                            "policies, guides and postmortems. Returns the most relevant sections. Use specific "
                            "terms: error codes, service names, policy IDs.",
             "input_schema": {"type": "object", "additionalProperties": False, "required": ["query"],
                              "properties": {
                                  "query": {"type": "string", "description": "What to look for"},
                                  "doc_type": {"type": "string",
                                               "enum": ["runbook", "policy", "guide", "postmortem"],
                                               "description": "Optional: restrict to one kind of document"},
                                  "service": {"type": "string",
                                              "description": "Optional: restrict to one service, e.g. kafka-broker"},
                              }}},
            {"name": "read_runbook", "strict": True,
             "description": "Read one whole document by its ID (for example RB-002 or POL-SEC-004), when a "
                            "search result references another document or you need the full procedure.",
             "input_schema": {"type": "object", "additionalProperties": False, "required": ["doc_id"],
                              "properties": {"doc_id": {"type": "string"}}}},
        ]
        messages: list = [{"role": "user", "content": question}]
        sources: list[dict] = []       # search_result_index in citations counts across the whole conversation
        calls: list[dict] = []
        resp = None
        totals = {"input_tokens": 0, "output_tokens": 0, "model_calls": 0}
        for _ in range(self.s.agent_max_steps):
            resp = self._create(system=AGENT_PROMPT, messages=messages, tools=tools)
            totals["input_tokens"] += resp.usage.input_tokens
            totals["output_tokens"] += resp.usage.output_tokens
            totals["model_calls"] += 1
            # Append the full content (thinking blocks included) so the next turn sees the same history.
            messages.append({"role": "assistant", "content": [b.model_dump(exclude_none=True) for b in resp.content
                                                               if b.type != "fallback"]})
            if resp.stop_reason != "tool_use":
                break
            results = []
            for block in resp.content:
                if block.type != "tool_use":
                    continue
                results.append(self._run_tool(block, search_fn, read_fn, sources, calls))
            messages.append({"role": "user", "content": results})   # all results in ONE message
        else:
            log.warning("agent hit max steps (%s)", self.s.agent_max_steps)
        answer = self._to_answer(resp, sources)
        answer.tool_calls = calls
        answer.usage = totals          # summed over every model call in the loop
        return answer

    @staticmethod
    def _run_tool(block, search_fn, read_fn, sources: list[dict], calls: list[dict]) -> dict:
        args = block.input if isinstance(block.input, dict) else json.loads(block.input)
        calls.append({"tool": block.name, "input": args})
        if block.name == "search_runbooks":
            hits = search_fn(args["query"], Filters(doc_type=args.get("doc_type"), service=args.get("service")), 5)
            if not hits:
                return {"type": "tool_result", "tool_use_id": block.id,
                        "content": [{"type": "text", "text": "No matching runbook sections."}]}
            for h in hits:
                sources.append({"source": h.chunk_id, "doc_id": h.doc_id,
                                "title": f"{h.doc_id}: {h.title} > {h.section}"})
            return {"type": "tool_result", "tool_use_id": block.id, "content": [hit_to_block(h) for h in hits]}
        if block.name == "read_runbook":
            doc = read_fn(args["doc_id"].strip().upper())
            if doc is None:
                return {"type": "tool_result", "tool_use_id": block.id, "is_error": True,
                        "content": [{"type": "text", "text": f"No document with id {args['doc_id']}. "
                                                             "Search first to find valid IDs."}]}
            sources.append({"source": doc["doc_id"], "doc_id": doc["doc_id"], "title": doc["title"]})
            return {"type": "tool_result", "tool_use_id": block.id,
                    "content": [_search_result_block(doc["doc_id"], f"{doc['doc_id']}: {doc['title']}", doc["body"])]}
        return {"type": "tool_result", "tool_use_id": block.id, "is_error": True,
                "content": [{"type": "text", "text": f"Unknown tool {block.name}"}]}

    # ------------------------------------------------------------------ response -> Answer
    def _to_answer(self, resp, sources: list[dict]) -> Answer:
        if resp.stop_reason == "refusal":
            return Answer(text="The model declined to answer this request.", citations=[], sources=sources,
                          model=resp.model, stop_reason=resp.stop_reason, usage=resp.usage.model_dump())
        parts: list[str] = []
        numbers: dict[int, int] = {}            # search_result_index -> [n] shown to the user
        citations: list[Citation] = []
        for block in resp.content:
            if block.type != "text":
                continue
            parts.append(block.text)
            marks = []
            for c in block.citations or []:
                if c.type != "search_result_location":
                    continue
                idx = c.search_result_index
                if idx not in numbers:
                    numbers[idx] = len(numbers) + 1
                    src = sources[idx] if idx < len(sources) else {"doc_id": c.source}
                    citations.append(Citation(numbers[idx], src["doc_id"], c.title or "", c.cited_text))
                marks.append(f"[{numbers[idx]}]")
            if marks:
                parts.append("".join(dict.fromkeys(marks)))
        return Answer(text="".join(parts).strip(), citations=citations, sources=sources, model=resp.model,
                      stop_reason=resp.stop_reason, usage=resp.usage.model_dump(exclude_none=True))
