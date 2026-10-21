"""Offline tests: the network is replaced by fakes, so they are fast and deterministic."""
import httpx
import pytest

import server

REAL_GET_JSON = server._get_json  # the autouse fixture replaces it per-test

COUNTRIES = [
    {"name": {"common": "Türkiye", "official": "Republic of Türkiye"}, "altSpellings": ["TR", "Turkey"],
     "cca2": "TR", "cca3": "TUR", "capital": ["Ankara"], "region": "Asia", "subregion": "Western Asia",
     "currencies": {"TRY": {"name": "Turkish lira", "symbol": "₺"}}, "languages": {"tur": "Turkish"},
     "borders": ["GRC"], "area": 783562, "landlocked": False, "flag": "🇹🇷"},
    {"name": {"common": "Greece", "official": "Hellenic Republic"}, "altSpellings": ["GR"], "cca2": "GR",
     "cca3": "GRC", "capital": ["Athens"], "region": "Europe", "borders": ["TUR"]},
    {"name": {"common": "Turkmenistan", "official": "Turkmenistan"}, "altSpellings": [], "cca2": "TM",
     "cca3": "TKM", "capital": ["Ashgabat"], "region": "Asia"},
]
POP_PAYLOAD = [{"page": 1}, [{"countryiso3code": "TUR", "value": 85000000},
                             {"countryiso3code": "GRC", "value": None}]]


@pytest.fixture(autouse=True)
def fake_network(monkeypatch):
    server._cache.clear()

    def fake_get_json(url, params=None):
        return COUNTRIES if url == server.COUNTRIES_URL else POP_PAYLOAD

    monkeypatch.setattr(server, "_get_json", fake_get_json)


def failing(exc_factory):
    def _raise(url, params=None):
        raise server.UpstreamError(exc_factory)
    return _raise


# --- search_countries -------------------------------------------------------
def test_search_returns_model_friendly_shape_and_exact_first():
    res = server.search_countries("turk")
    assert [r["name"] for r in res] == ["Türkiye", "Turkmenistan"]
    assert set(res[0]) == {"name", "capital", "region", "population"}
    assert res[0]["population"] == 85000000


def test_search_is_case_and_accent_insensitive_and_uses_alt_spellings():
    assert server.search_countries("TURKIYE")[0]["name"] == "Türkiye"
    assert server.search_countries("turkey")[0]["name"] == "Türkiye"


def test_search_no_match_is_empty_list_not_error():
    assert server.search_countries("atlantis") == []


@pytest.mark.parametrize("bad", ["", "   ", None, 42, "x" * 101])
def test_search_rejects_bad_query(bad):
    res = server.search_countries(bad)
    assert len(res) == 1 and "error" in res[0]


@pytest.mark.parametrize("bad", ["3", None, 2.5, True])
def test_search_rejects_non_integer_limit(bad):
    assert "error" in server.search_countries("tur", limit=bad)[0]


def test_search_clamps_limit():
    assert len(server.search_countries("tur", limit=0)) == 1
    assert len(server.search_countries("tur", limit=-5)) == 1
    assert len(server.search_countries("tur", limit=10_000)) == 2


def test_search_special_characters_are_just_text():
    assert server.search_countries("../../etc/passwd") == []
    assert server.search_countries("tur?x=1&y=2#") == []


def test_search_upstream_failure_returns_error_item(monkeypatch):
    monkeypatch.setattr(server, "_get_json", failing("boom"))
    res = server.search_countries("tur")
    assert "upstream request failed" in res[0]["error"]


def test_population_source_down_still_returns_countries(monkeypatch):
    def partial(url, params=None):
        if url == server.COUNTRIES_URL:
            return COUNTRIES
        raise server.UpstreamError("worldbank down")
    monkeypatch.setattr(server, "_get_json", partial)
    res = server.search_countries("turkiye")
    assert res[0]["name"] == "Türkiye" and res[0]["population"] is None


# --- get_country_details ----------------------------------------------------
def test_details_shape():
    d = server.get_country_details("Turkey")
    assert d["found"] is True and d["name"] == "Türkiye"
    assert d["currencies"] == [{"code": "TRY", "name": "Turkish lira", "symbol": "₺"}]
    assert d["languages"] == ["Turkish"]
    assert d["borders"] == [{"code": "GRC", "name": "Greece"}]
    assert d["flag_url"] == "https://flagcdn.com/w320/tr.png"
    assert d["population"] == 85000000


def test_details_missing_optional_fields_do_not_crash():
    d = server.get_country_details("Turkmenistan")
    assert d["found"] and d["currencies"] == [] and d["languages"] == [] and d["borders"] == []


def test_details_not_found_is_structured():
    d = server.get_country_details("atlantis")
    assert d["found"] is False and d["suggestions"] == []


def test_details_ambiguous_partial_name_lists_candidates():
    d = server.get_country_details("tur")
    assert d["found"] is False and d["ambiguous"] is True
    assert set(d["candidates"]) == {"Türkiye", "Turkmenistan"}


def test_details_exact_match_beats_partial():
    assert server.get_country_details("greece")["name"] == "Greece"


@pytest.mark.parametrize("bad", ["", "  ", None, 7, "y" * 101])
def test_details_rejects_bad_name(bad):
    assert "error" in server.get_country_details(bad)


def test_details_upstream_failure(monkeypatch):
    monkeypatch.setattr(server, "_get_json", failing("boom"))
    assert "upstream request failed" in server.get_country_details("Turkey")["error"]


# --- the HTTP layer ----------------------------------------------------------
def _boom(exc):
    def handler(request):
        raise exc
    return handler


@pytest.mark.parametrize(
    "handler, expected",
    [
        (lambda r: httpx.Response(503), "HTTP 503"),
        (lambda r: httpx.Response(200, text="<html>not json</html>"), "invalid JSON"),
        (_boom(httpx.ReadTimeout("slow")), "timed out"),
        (_boom(httpx.ConnectError("dns")), "network error"),
    ],
)
def test_get_json_maps_every_failure_to_upstream_error(monkeypatch, handler, expected):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(server.httpx, "get", lambda url, params=None, **kw: client.get(url, params=params))
    with pytest.raises(server.UpstreamError, match=expected):
        REAL_GET_JSON("https://example.test/x")


def test_get_json_returns_parsed_json_on_success(monkeypatch):
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": 1})))
    monkeypatch.setattr(server.httpx, "get", lambda url, params=None, **kw: client.get(url, params=params))
    assert REAL_GET_JSON("https://example.test/x") == {"ok": 1}
