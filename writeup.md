# Week 5 Write-up — Build a Custom MCP Server: The Data Explorer

**Student:** Mohanad Kadadou (2309115218) · Python 3.12, `mcp` 1.30.0 (FastMCP), `httpx`, STDIO transport

## What I did
1. **Studied `search_countries`** in the starter: it validates input, calls the API with a timeout, treats 404 as "no results" (not an error), catches `httpx.HTTPError`, and returns a small, flat, model-friendly dict list.
2. **Found the starter was broken before I wrote any code.** Two environment changes:
   - REST Countries v3.1 now returns `301` → a "deprecated" JSON body (new API needs an account + key). With the starter's `httpx.get` (no `follow_redirects`) the tool would just return `upstream request failed`.
   - Unpinned `mcp` resolves to 2.x where `FastMCP` no longer exists (`ModuleNotFoundError`). Fixed with `mcp<2`.
   I switched the data source to key-less public datasets (details in README, "Why not restcountries.com?") and kept the tool contracts.
3. **Implemented `get_country_details(name)`** returning currencies, languages, borders (code + resolved name), flag URL, plus capital/region/population/area.
4. **Hardened both tools** (table in README). 32 offline pytest tests with the network faked: bad input, every HTTP failure mode (503, bad JSON, timeout, connection error) via `httpx.MockTransport`, ambiguous names, missing optional fields, population source down, injection-looking strings.
5. **Drove the server from an MCP client over STDIO** (`client_demo.py`, official Python client): full transcript in `transcript.txt`. 

## Transcript of an agent (MCP client) calling both tools
(Abridged from `transcript.txt`, the real output.)
```text
# connected to MCP server: data-explorer
# tool: search_countries  params=['query', 'limit']
# tool: get_country_details  params=['name']

> search_countries({"query": "japan", "limit": 1})
  [{"name": "Japan", "capital": "Tokyo", "region": "Asia", "population": 123366734}]

> get_country_details({"name": "Turkey"})
  {"found": true, "name": "Türkiye", "official_name": "Republic of Türkiye", "capital": "Ankara",
   "currencies": [{"code": "TRY", "name": "Turkish lira", "symbol": "₺"}], "languages": ["Turkish"],
   "borders": [ARM, AZE, BGR, GEO, GRC, IRN, IRQ, SYR with names], "flag_url": "https://flagcdn.com/w320/tr.png", ...}

> search_countries({"query": "   "})            -> [{"error": "query must not be empty"}]
> search_countries({"query": "x"*200})          -> [{"error": "query must be at most 100 characters"}]
> search_countries({"query": "atlantis"})       -> []
> search_countries({"query": "france", "limit": "many"})
     -> MCP-level validation error (schema says integer); the server stays up
> get_country_details({"name": ""})             -> {"error": "name must not be empty"}
> get_country_details({"name": "atlantis"})     -> {"found": false, "message": "no country matches 'atlantis'", "suggestions": []}
> get_country_details({"name": "republic"})     -> {"found": false, "ambiguous": true, "candidates": ["Afghanistan", "Angola", ...]}
> get_country_details({"name": "../../etc/passwd"}) -> {"found": false, ...}   (never reaches a URL)
> search_countries({"query": "japan"})          -> still answers: the server survived all the bad input
```
**Registration.** The README has the Claude Desktop / Claude Code config. In this session I verified the registration contract by launching the server exactly as a client config does (`command` + `args` over STDIO) with the Python MCP client. I did not edit the Claude Desktop config on the machine; the JSON in the README is what needs to be pasted (with absolute paths) for a Desktop run.

## How I handled errors
- One exception type, `UpstreamError`, raised by the single HTTP helper; every tool catches it and returns data (`{"error": ...}`), so the server process never dies and the agent can read what went wrong and recover.
- Distinguish **"nothing found"** (empty list / `found: false`: a normal outcome) from **"something broke"** (`error`). For ambiguity I return candidates so the agent can retry with a precise name instead of guessing.
- Optional data degrades (`population: null` when the World Bank is down) rather than failing the whole call.
- Matching is local text comparison: user text is never interpolated into a URL.

## What I learned
An MCP server is a context boundary: the agent can only know what the tools return, so the *shape* of the return value is the design. Flat, named fields, `found: false` vs `error`, and candidate lists for ambiguous names tell the model how to recover without me writing agent logic. Limiting what a tool can reach (two read-only tools, bounded input, no raw URL passthrough, a capped `limit`) controls what context and side effects an agent can ever get, which matters as much as the features. I also learned that "free API" assumptions rot: a dependency's deprecation and an unpinned package broke the starter, so pinning versions and testing against the live service are part of delivering a tool.
