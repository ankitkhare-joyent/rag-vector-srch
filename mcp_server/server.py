"""Runbook search as an MCP server, so any agent (Claude Code, Claude Desktop, the learn-ai-agent
LangGraph/Strands agents) can use retrieval as a *tool*. This is "RAG as a tool": the agent decides
when to search, the server owns how.

    python mcp_server/server.py --transport stdio    # spawned by a local client
    python mcp_server/server.py --transport http     # Streamable HTTP on :8101/mcp (published as localhost:47101) (compose service `mcp`)

The server is a thin adapter over the RAG API: no database credentials, no models, no secrets here.
Tools are read-only and return compact, bounded output because every byte lands in the model's context.
"""
import argparse
import logging
from contextlib import asynccontextmanager
from typing import Annotated, Literal

import httpx
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger("runbook-mcp")
READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MCP_", extra="ignore")
    rag_api_url: str = "http://localhost:47100"
    allowed_hosts: list[str] = ["localhost:47101", "127.0.0.1:47101", "mcp:8101", "localhost:8101"]


settings = Settings()


class Section(BaseModel):
    doc_id: str = Field(description="Document ID; pass to read_runbook for the full text")
    title: str
    section: str
    doc_type: str
    relevance: float = Field(description="Reranker score; higher is more relevant, below 0 is usually off-topic")
    text: str


class SearchOutput(BaseModel):
    query: str
    results: list[Section]


class RunbookOutput(BaseModel):
    doc_id: str
    title: str
    doc_type: str
    team: str
    updated: str | None
    body: str


@asynccontextmanager
async def lifespan(server: MCPServer):
    async with httpx.AsyncClient(base_url=settings.rag_api_url, timeout=30) as http:
        yield {"http": http}


def build_server() -> MCPServer:
    mcp = MCPServer(
        name="ec2-runbooks", title="EC2 Runbooks", version="1.0.0", lifespan=lifespan,
        instructions=("Search and read the platform team's EC2 operations runbooks, policies (POL-*), guides and "
                      "postmortems (PM-*). Use search_runbooks with specific terms (error codes, service names), then "
                      "read_runbook for the full procedure. Quote document IDs in answers."),
    )

    def http(ctx: Context) -> httpx.AsyncClient:
        return ctx.request_context.lifespan_context["http"]

    @mcp.tool(annotations=READ_ONLY, title="Search runbooks")
    async def search_runbooks(
        query: Annotated[str, Field(min_length=2, max_length=300, description="What to look for")],
        ctx: Context,
        doc_type: Literal["runbook", "policy", "guide", "postmortem"] | None = None,
        service: Annotated[str | None, Field(description="e.g. kafka-broker, checkout-api")] = None,
        limit: Annotated[int, Field(ge=1, le=8)] = 5,
    ) -> SearchOutput:
        """Hybrid search (keywords + meaning, reranked) over EC2 operations runbooks, policies, guides and
        postmortems. Returns the most relevant sections with their document IDs."""
        try:
            r = await http(ctx).post("/search", json={"query": query, "k": limit,
                                                      "filters": {"doc_type": doc_type, "service": service}})
        except httpx.TimeoutException:
            raise ToolError("runbook search timed out (the RAG API is busy); retry once") from None
        if r.status_code != 200:
            raise ToolError(f"runbook search failed ({r.status_code}): {r.text[:200]}")
        hits = r.json()["hits"]
        return SearchOutput(query=query, results=[
            Section(doc_id=h["doc_id"], title=h["title"], section=h["section"], doc_type=h["doc_type"],
                    relevance=round(h["rerank_score"] if h["rerank_score"] is not None else h["score"], 3),
                    text=h["content"]) for h in hits])

    @mcp.tool(annotations=READ_ONLY, title="Read a runbook")
    async def read_runbook(
        doc_id: Annotated[str, Field(pattern=r"^[A-Za-z]+(-[A-Za-z]+)?-\d{3,4}(-\d{2})?$",
                                     description="Document ID such as RB-002, POL-SEC-004, PM-2026-05")],
        ctx: Context,
    ) -> RunbookOutput:
        """Read one whole document by ID, when a search result references it or you need every step."""
        r = await http(ctx).get(f"/documents/{doc_id}")
        if r.status_code == 404:
            raise ToolError(f"no document {doc_id}; use search_runbooks to find valid IDs")
        if r.status_code != 200:
            raise ToolError(f"read failed ({r.status_code})")
        d = r.json()
        return RunbookOutput(doc_id=d["doc_id"], title=d["title"], doc_type=d["doc_type"], team=d["team"],
                             updated=d["updated"], body=d["body"])

    return mcp


def main():
    logging.basicConfig(level=logging.INFO)
    p = argparse.ArgumentParser()
    p.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8101)
    args = p.parse_args()
    mcp = build_server()
    if args.transport == "stdio":
        mcp.run("stdio")
    else:
        # LOCAL: no auth, published on 127.0.0.1 only. Production: OAuth 2.1 resource server, as in
        # learn-ai-agent/mcp_server/server.py (audience-checked tokens, no token passthrough).
        mcp.run("streamable-http", host=args.host, port=args.port, stateless_http=True, json_response=True,
                transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True,
                                                             allowed_hosts=settings.allowed_hosts))


if __name__ == "__main__":
    main()
