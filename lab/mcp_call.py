"""Talk to the runbook MCP server the way an MCP client (Claude Code, an agent) does. No Claude call.

    mise run -q lab:mcp                                   # list tools, call each once, then a bad call
    mise run -q lab:mcp -- "kafka broker retirement"      # your own search query

Connects over Streamable HTTP to http://localhost:47101/mcp (the compose service `mcp`).
"""
import asyncio
import json
import os
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

URL = os.environ.get("MCP_URL", "http://localhost:47101/mcp")


async def main() -> None:
    query = " ".join(sys.argv[1:]) or "an i4i kafka broker got a retirement notice"
    async with streamable_http_client(URL) as streams, ClientSession(streams[0], streams[1]) as s:
        init = await s.initialize()
        print("server:", init.server_info.name, init.server_info.version, "| protocol:", init.protocol_version)
        print("instructions:", (init.instructions or "")[:100], "…")
        for t in (await s.list_tools()).tools:
            print(f"tool {t.name}: input {sorted(t.input_schema['properties'])}, "
                  f"output schema: {'yes' if t.output_schema else 'no'}, read-only: {t.annotations.read_only_hint}")
        res = await s.call_tool("search_runbooks", {"query": query, "limit": 3})
        for r in res.structured_content["results"]:
            print(f"  {r['relevance']:>6}  {r['doc_id']:<11} {r['section']}")
        doc = await s.call_tool("read_runbook", {"doc_id": res.structured_content["results"][0]["doc_id"]})
        print("read_runbook:", doc.structured_content["doc_id"], "-", len(doc.structured_content["body"]), "chars")
        bad = await s.call_tool("read_runbook", {"doc_id": "RB-999"})
        print("bad call: isError =", bad.is_error, "|", bad.content[0].text[:110])
        worse = await s.call_tool("read_runbook", {"doc_id": "../etc/passwd"})
        print("invalid input: isError =", worse.is_error, "|", json.dumps(worse.content[0].text)[:110])


if __name__ == "__main__":
    asyncio.run(main())
