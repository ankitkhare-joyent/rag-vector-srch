"""RAG HTTP API.

    GET  /healthz                 liveness
    GET  /readyz                  readiness: database reachable with current dynamic credentials
    POST /search                  retrieval only (dense | lexical | hybrid, optional rerank)
    POST /ask                     retrieval + Claude answer with citations (mode: pipeline | agentic)
    GET  /documents/{doc_id}      one whole document (used by the agentic tool and the MCP server)

Run: uvicorn rag.api:app --host 0.0.0.0 --port 8100   (Swagger UI at /docs)

Security note: this local stack binds the API to 127.0.0.1 and has no end-user auth. In production
put it behind your identity-aware proxy or validate OIDC tokens here (learn-ai-agent shows the JWT
pattern), and pass the caller's identity into the filters so people only retrieve what they may read.
"""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from rag import models
from rag.bao import BaoClient, BaoError, DbCredentialProvider
from rag.db import make_pool
from rag.generate import Generator
from rag.search import Filters, search
from rag.settings import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("rag.api")
state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    bao = BaoClient(s)
    state.update(settings=s, bao=bao, pool=make_pool(s, DbCredentialProvider(bao, s.bao_db_role)))
    models.warm_up()
    log.info("ready: embed=%s rerank=%s llm=%s", s.embed_model, s.rerank_model, s.llm_model)
    yield
    state["pool"].close()


app = FastAPI(title="Runbook RAG", version="0.1.0", lifespan=lifespan)


class FilterIn(BaseModel):
    doc_type: Literal["runbook", "policy", "guide", "postmortem"] | None = None
    team: str | None = None
    service: str | None = None


class SearchIn(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    mode: Literal["dense", "lexical", "hybrid"] = "hybrid"
    rerank: bool = True
    k: int = Field(5, ge=1, le=20)
    filters: FilterIn = FilterIn()


class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    mode: Literal["pipeline", "agentic"] = "pipeline"
    k: int = Field(6, ge=1, le=12)
    filters: FilterIn = FilterIn()


def _search(q: str, mode="hybrid", rerank=True, k=5, filters: Filters | None = None):
    return search(state["pool"], state["settings"], q, mode=mode, rerank=rerank, k=k, filters=filters)


def _generator() -> Generator:
    """Build the Claude client from the key in OpenBao; re-read every 5 minutes so rotation needs no restart."""
    cached = state.get("generator")
    if cached and time.monotonic() - cached[1] < 300:
        return cached[0]
    try:
        key = state["bao"].kv_get("rag/anthropic")["api_key"]
    except (BaoError, KeyError) as e:
        raise HTTPException(503, "No Anthropic API key in OpenBao at secret/rag/anthropic; "
                                 "add it to .env and re-run bao-bootstrap.") from e
    gen = Generator(state["settings"], key)
    state["generator"] = (gen, time.monotonic())
    return gen


def _read_document(doc_id: str) -> dict | None:
    with state["pool"].connection() as conn:
        row = conn.execute("SELECT doc_id, title, doc_type, team, services, updated, body FROM documents "
                           "WHERE doc_id = %s", (doc_id,)).fetchone()
    if not row:
        return None
    return dict(zip(["doc_id", "title", "doc_type", "team", "services", "updated", "body"], row))


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/readyz")
def readyz():
    with state["pool"].connection() as conn:
        user, chunks = conn.execute("SELECT current_user, (SELECT count(*) FROM chunks)").fetchone()
    return {"status": "ready", "db_user": user, "chunks": chunks}


@app.post("/search")
async def search_endpoint(body: SearchIn):
    res = await run_in_threadpool(_search, body.query, body.mode, body.rerank, body.k, Filters(**body.filters.model_dump()))
    return {"hits": [h.to_dict() for h in res.hits], "timings_ms": res.timings_ms}


@app.post("/ask")
async def ask(body: AskIn):
    gen = _generator()
    f = Filters(**body.filters.model_dump())
    t0 = time.perf_counter()
    if body.mode == "pipeline":
        res = await run_in_threadpool(_search, body.question, "hybrid", True, body.k, f)
        ans = await run_in_threadpool(gen.answer_pipeline, body.question, res.hits)
    else:
        ans = await run_in_threadpool(
            gen.answer_agentic, body.question,
            lambda q, flt, k: _search(q, filters=Filters(doc_type=flt.doc_type or f.doc_type,
                                                         team=f.team, service=flt.service or f.service), k=k).hits,
            _read_document)
    return {"answer": ans.text, "citations": [c.__dict__ for c in ans.citations], "sources": ans.sources,
            "tool_calls": ans.tool_calls, "model": ans.model, "stop_reason": ans.stop_reason,
            "usage": ans.usage, "latency_ms": round((time.perf_counter() - t0) * 1000)}


@app.get("/documents/{doc_id}")
def get_document(doc_id: str):
    doc = _read_document(doc_id.upper())
    if not doc:
        raise HTTPException(404, f"no document {doc_id}")
    return doc
