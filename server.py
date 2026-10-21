"""Data Explorer: an MCP server that exposes country data to an agent over STDIO.

Tools
-----
- search_countries(query, limit=5)  -> list of {name, capital, region, population}
- get_country_details(name)         -> {name, official_name, capital, region, subregion,
                                        population, currencies, languages, borders, flag_url, ...}

Data source (see README "Why not restcountries.com?"): the public, key-less country dataset
`mledoze/countries` (the data REST Countries was built on), served by jsDelivr, plus the World
Bank API for population. Both are fetched over HTTP at runtime, cached in memory, and every
failure mode is returned as structured data. A tool never raises, so the server never crashes.

Run (STDIO):  python server.py
"""
from __future__ import annotations

import unicodedata
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

COUNTRIES_URL = "https://cdn.jsdelivr.net/gh/mledoze/countries@master/dist/countries.json"
POPULATION_URL = "https://api.worldbank.org/v2/country/all/indicator/SP.POP.TOTL"
FLAG_URL = "https://flagcdn.com/w320/{cca2}.png"
TIMEOUT = httpx.Timeout(10.0, connect=5.0)
MAX_QUERY_LEN = 100
MAX_LIMIT = 25

mcp = FastMCP("data-explorer")

_cache: dict[str, Any] = {}


class UpstreamError(Exception):
    """A data source could not be reached or returned something unusable."""


def _get_json(url: str, params: dict | None = None) -> Any:
    try:
        resp = httpx.get(url, params=params, timeout=TIMEOUT, follow_redirects=True)
        resp.raise_for_status()
        return resp.json()
    except httpx.TimeoutException as exc:
        raise UpstreamError(f"timed out after {TIMEOUT.read:.0f}s calling {httpx.URL(url).host}") from exc
    except httpx.HTTPStatusError as exc:
        raise UpstreamError(f"{httpx.URL(url).host} returned HTTP {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise UpstreamError(f"network error calling {httpx.URL(url).host}: {type(exc).__name__}") from exc
    except ValueError as exc:  # invalid JSON
        raise UpstreamError(f"{httpx.URL(url).host} returned invalid JSON") from exc


def _countries() -> list[dict]:
    if "countries" not in _cache:
        data = _get_json(COUNTRIES_URL)
        if not isinstance(data, list) or not data:
            raise UpstreamError("country dataset has an unexpected shape")
        _cache["countries"] = data
    return _cache["countries"]


def _populations() -> dict[str, int]:
    """ISO3 code -> most recent population. Best effort: returns {} if the source is down."""
    if "population" not in _cache:
        try:
            data = _get_json(POPULATION_URL, {"format": "json", "mrnev": 1, "per_page": 400})
            rows = data[1] if isinstance(data, list) and len(data) > 1 and data[1] else []
            _cache["population"] = {
                r["countryiso3code"]: int(r["value"])
                for r in rows
                if r.get("countryiso3code") and r.get("value") is not None
            }
        except (UpstreamError, KeyError, TypeError, ValueError):
            return {}  # not cached, so a later call can retry
    return _cache["population"]


def _norm(text: str) -> str:
    """Case- and accent-insensitive form: 'Türkiye' -> 'turkiye'."""
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(ch)
    ).strip()


def _names(c: dict) -> list[str]:
    n = c.get("name") or {}
    return [n.get("common", ""), n.get("official", ""), *c.get("altSpellings", [])]


def _clean_query(value: Any) -> tuple[str | None, str | None]:
    """Return (normalized_query, error_message)."""
    if not isinstance(value, str):
        return None, "query must be a string"
    q = value.strip()
    if not q:
        return None, "query must not be empty"
    if len(q) > MAX_QUERY_LEN:
        return None, f"query must be at most {MAX_QUERY_LEN} characters"
    return _norm(q), None


def _summary(c: dict, pops: dict[str, int]) -> dict:
    return {
        "name": (c.get("name") or {}).get("common"),
        "capital": (c.get("capital") or [None])[0],
        "region": c.get("region"),
        "population": pops.get(c.get("cca3", "")),
    }


@mcp.tool()
def search_countries(query: str, limit: int = 5) -> list[dict]:
    """Search countries by name (partial, case- and accent-insensitive).

    Returns a list of {name, capital, region, population}. An empty list means no match.
    On bad input or an upstream failure it returns a single {"error": ...} item instead.
    Exact name matches are listed first. `limit` is clamped to 1..25.
    """
    q, err = _clean_query(query)
    if err:
        return [{"error": err}]
    if isinstance(limit, bool) or not isinstance(limit, int):
        return [{"error": "limit must be an integer"}]
    limit = max(1, min(limit, MAX_LIMIT))
    try:
        countries = _countries()
    except UpstreamError as exc:
        return [{"error": f"upstream request failed: {exc}"}]

    exact, partial = [], []
    for c in countries:
        names = [_norm(n) for n in _names(c) if n]
        if q in names:
            exact.append(c)
        elif any(q in n for n in names):
            partial.append(c)
    pops = _populations()
    return [_summary(c, pops) for c in (exact + partial)[:limit]]


@mcp.tool()
def get_country_details(name: str) -> dict:
    """Get details for ONE country: currencies, languages, bordering countries and flag URL.

    `name` is matched exactly (common name, official name or alternative spelling,
    case/accent-insensitive); if no exact match exists, a single partial match is accepted.
    Returns {"error": ...} for bad input or upstream failure, {"found": false, "suggestions": [...]}
    when nothing matches, and {"found": false, "ambiguous": true, "candidates": [...]} when a
    partial name matches several countries.
    """
    q, err = _clean_query(name)
    if err:
        return {"error": err.replace("query", "name")}
    try:
        countries = _countries()
    except UpstreamError as exc:
        return {"error": f"upstream request failed: {exc}"}

    exact = [c for c in countries if q in [_norm(n) for n in _names(c) if n]]
    matches = exact or [c for c in countries if any(q in _norm(n) for n in _names(c) if n)]
    if not matches:
        return {"found": False, "message": f"no country matches {name.strip()!r}", "suggestions": []}
    if len(matches) > 1:
        return {
            "found": False,
            "ambiguous": True,
            "message": f"{name.strip()!r} matches several countries; use a more specific name",
            "candidates": [(c.get("name") or {}).get("common") for c in matches[:10]],
        }

    c = matches[0]
    by_code = {x.get("cca3"): (x.get("name") or {}).get("common") for x in countries}
    cca2 = (c.get("cca2") or "").lower()
    return {
        "found": True,
        "name": (c.get("name") or {}).get("common"),
        "official_name": (c.get("name") or {}).get("official"),
        "capital": (c.get("capital") or [None])[0],
        "region": c.get("region"),
        "subregion": c.get("subregion"),
        "population": _populations().get(c.get("cca3", "")),
        "area_km2": c.get("area"),
        "currencies": [
            {"code": code, "name": v.get("name"), "symbol": v.get("symbol")}
            for code, v in (c.get("currencies") or {}).items()
        ],
        "languages": sorted((c.get("languages") or {}).values()),
        "borders": [{"code": b, "name": by_code.get(b)} for b in c.get("borders", [])],
        "landlocked": c.get("landlocked"),
        "flag_url": FLAG_URL.format(cca2=cca2) if cca2 else None,
        "flag_emoji": c.get("flag"),
    }


if __name__ == "__main__":
    mcp.run()
