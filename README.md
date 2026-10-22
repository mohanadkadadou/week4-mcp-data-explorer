# Week 5 — Data Explorer MCP server

An [MCP](https://modelcontextprotocol.io) server (FastMCP, **STDIO** transport) that gives an agent two tools for exploring country data.
Student: Mohanad Kadadou (2309115218), JOB191 AI-Augmented Software Engineering.

## Install
```bash
python3 -m venv .venv && source .venv/bin/activate     # or: uv venv --python 3.12 .venv
pip install -r requirements.txt                         # mcp<2, httpx, pytest
```
> `requirements.txt` pins **`mcp<2`**: the starter's unpinned `mcp` now installs 2.x, where `FastMCP` was renamed
> and `from mcp.server.fastmcp import FastMCP` fails.

## Run
```bash
python server.py            # speaks MCP over stdin/stdout; it waits silently for a client
python -m pytest -q         # 32 offline tests (network faked)
python client_demo.py       # drives the real server over STDIO and prints a transcript
```

## Register in an MCP client
**Claude Desktop** — edit `~/Library/Application Support/Claude/claude_desktop_config.json` (use absolute paths), then restart:
```json
{
  "mcpServers": {
    "data-explorer": {
      "command": "/ABSOLUTE/PATH/week4-mcp-data-explorer/.venv/bin/python",
      "args": ["/ABSOLUTE/PATH/week4-mcp-data-explorer/server.py"]
    }
  }
}
```
**Claude Code:** `claude mcp add data-explorer -- /ABS/PATH/.venv/bin/python /ABS/PATH/server.py`.
Other MCP-aware IDEs accept the same `command` + `args`.

## Tool reference

### `search_countries(query: str, limit: int = 5) -> list[dict]`
Partial, case- and accent-insensitive name search (also matches official names and alternative spellings, e.g. `turkey` finds Türkiye). Exact matches come first. `limit` is clamped to 1–25.
| Case | Result |
|---|---|
| match | `[{"name","capital","region","population"}, ...]` |
| no match | `[]` (not an error) |
| empty / non-string / >100 chars query, non-integer `limit`, upstream failure | `[{"error": "<message>"}]` |

Example: `search_countries({"query": "japan", "limit": 1})` →
`[{"name": "Japan", "capital": "Tokyo", "region": "Asia", "population": 123366734}]`

### `get_country_details(name: str) -> dict`
Details for one country.
| Case | Result |
|---|---|
| found | `{"found": true, "name", "official_name", "capital", "region", "subregion", "population", "area_km2", "currencies": [{code,name,symbol}], "languages": [...], "borders": [{code,name}], "landlocked", "flag_url", "flag_emoji"}` |
| no match | `{"found": false, "message": "...", "suggestions": []}` |
| partial name matches several | `{"found": false, "ambiguous": true, "candidates": [...]}` |
| bad input / upstream failure | `{"error": "<message>"}` |

Example: `get_country_details({"name": "Turkey"})` → `{"found": true, "name": "Türkiye", "capital": "Ankara", "currencies": [{"code": "TRY", "name": "Turkish lira", "symbol": "₺"}], "languages": ["Turkish"], "borders": [{"code": "GRC", "name": "Greece"}, ...], "flag_url": "https://flagcdn.com/w320/tr.png", ...}`

## Error handling (hardening)
| Failure | Handling |
|---|---|
| empty / blank / non-string / over-long input | validated up front; structured `error` |
| HTTP 4xx/5xx, timeouts (5 s connect, 10 s read), DNS/network errors, invalid JSON | one `UpstreamError` type, turned into a structured `error` |
| redirects | `follow_redirects=True` |
| path/URL injection (`../../x`, `?a=b`) | input is never put in a URL; matching happens locally on text |
| population source down | countries still returned, `population: null` |
| no result | empty list / `found: false`, never an exception |

## Why not restcountries.com? (deviation from the starter)
The starter calls `https://restcountries.com/v3.1/name/...`. On 2026-10-21 that endpoint answers **HTTP 301** and then a JSON body saying the version is deprecated; its replacement (`/v5`) needs an account and an API key, which breaks the assignment's "free, no-key" premise.
This server therefore uses key-less public sources fetched over HTTP at runtime: the [`mledoze/countries`](https://github.com/mledoze/countries) dataset (the data REST Countries was built from) via jsDelivr for names, capitals, currencies, languages, borders; the World Bank API for population; flagcdn for the flag image URL. The two-tool design, return shapes and error-handling pattern are unchanged.
