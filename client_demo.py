"""Drive server.py over STDIO with the official MCP Python client and print a transcript.

Run:  python client_demo.py
"""
import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

CALLS = [
    ("search_countries", {"query": "turk"}),
    ("search_countries", {"query": "japan", "limit": 1}),
    ("get_country_details", {"name": "Turkey"}),
    ("get_country_details", {"name": "Japan"}),
    # --- bad input: must return structured messages, never crash the server ---
    ("search_countries", {"query": "   "}),
    ("search_countries", {"query": "x" * 200}),
    ("search_countries", {"query": "atlantis"}),
    ("search_countries", {"query": "france", "limit": "many"}),
    ("get_country_details", {"name": ""}),
    ("get_country_details", {"name": "atlantis"}),
    ("get_country_details", {"name": "republic"}),
    ("get_country_details", {"name": "../../etc/passwd"}),
    ("search_countries", {"query": "japan"}),  # still alive after all the abuse
]


async def main() -> None:
    params = StdioServerParameters(command=sys.executable, args=["server.py"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print(f"# connected to MCP server: {init.serverInfo.name}")
            tools = await session.list_tools()
            for t in tools.tools:
                print(f"# tool: {t.name}  params={list(t.inputSchema.get('properties', {}))}")
            for name, args in CALLS:
                print(f"\n> {name}({json.dumps(args, ensure_ascii=False)})")
                res = await session.call_tool(name, args)
                if res.isError:
                    print("  [protocol-level error]", res.content[0].text[:200])
                    continue
                payload = res.structuredContent.get("result", res.structuredContent) if res.structuredContent else res.content[0].text
                text = json.dumps(payload, ensure_ascii=False, indent=2)
                print("  " + text.replace("\n", "\n  ")[:1500])


asyncio.run(main())
