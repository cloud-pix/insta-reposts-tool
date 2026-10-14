import json
from insta_reposts import fish, utils


GQL_PAGE1 = {
    "fetch__XDTUserDict": {
        "user_reposts_timeline": {
            "repost_grid_items": [
                {"media": {"code": "AbC123XyZ12", "pk": "111",
                           "user": {"username": "creator1"},
                           "caption": {"text": "hello"},
                           "product_type": "clips"}},
                {"media": None},
                {"nope": 1},
            ],
            "repost_more_available": True,
            "repost_next_max_id": "CURSOR1",
        }
    }
}
GQL_PAGE2 = {
    "fetch__XDTUserDict": {
        "user_reposts_timeline": {
            "repost_grid_items": [
                {"media": {"code": "QwE456RtY78", "pk": "222",
                           "user": {"username": "creator2"},
                           "caption": {"text": "world"},
                           "product_type": "feed"}},
            ],
            "repost_more_available": False,
            "repost_next_max_id": None,
        }
    }
}


def test_parse_reposts_response():
    recs, more, cursor = fish.parse_reposts_response(GQL_PAGE1)
    assert len(recs) == 1
    assert recs[0]["shortcode"] == "AbC123XyZ12"
    assert recs[0]["creator_username"] == "creator1"
    assert recs[0]["post_url"].endswith("/AbC123XyZ12/")
    assert more is True and cursor == "CURSOR1"
    recs2, more2, _ = fish.parse_reposts_response(GQL_PAGE2)
    assert len(recs2) == 1 and more2 is False
    assert fish.parse_reposts_response({}) == ([], False, None)
    assert fish.parse_reposts_response(None) == ([], False, None)


def test_fish_graphql_pagination(monkeypatch):
    calls = []

    def fake_query(cookies, doc_id, friendly, variables, boot=None):
        calls.append((doc_id, friendly, variables))
        assert boot == {"lsd": "L"}
        if doc_id == fish.REPOSTS_CONTENT_DOC_ID:
            assert friendly == "PolarisProfileRepostsTabContentQuery"
            assert variables == {"user_id": "999", fish.RELAY_PROVIDER_VAR: False}
            return GQL_PAGE1, None
        assert friendly == "PolarisProfileRepostsTabContentRefetchQuery"
        assert variables == {"id": "999", "max_id": "CURSOR1", fish.RELAY_PROVIDER_VAR: False}
        return GQL_PAGE2, None

    monkeypatch.setattr(fish, "graphql_query", fake_query)
    monkeypatch.setattr(fish, "graphql_bootstrap", lambda c, u="x": {"lsd": "L"})
    monkeypatch.setattr(fish, "resolve_user_pk", lambda u, c: "999")
    res = fish.fish_graphql("someuser", {"sessionid": "X"}, max_items=10)
    assert res["ok"] and res["source"] == "graphql" and res["is_reposts_tab"]
    assert [i["shortcode"] for i in res["items"]] == ["AbC123XyZ12", "QwE456RtY78"]
    assert len(calls) == 2


def test_fish_graphql_respects_max(monkeypatch):
    monkeypatch.setattr(fish, "graphql_query", lambda c, d, f, v, boot=None: (GQL_PAGE1, None))
    monkeypatch.setattr(fish, "graphql_bootstrap", lambda c, u="x": {"lsd": "L"})
    monkeypatch.setattr(fish, "resolve_user_pk", lambda u, c: "999")
    res = fish.fish_graphql("u", {"sessionid": "X"}, max_items=1)
    assert res["ok"] and len(res["items"]) == 1


def test_fish_graphql_needs_login():
    res = fish.fish_graphql("u", {}, max_items=10)
    assert not res["ok"] and "login" in res["error"]


def test_fish_graphql_query_error(monkeypatch):
    monkeypatch.setattr(fish, "graphql_query", lambda c, d, f, v, boot=None: (None, "execution error"))
    monkeypatch.setattr(fish, "graphql_bootstrap", lambda c, u="x": {"lsd": "L"})
    monkeypatch.setattr(fish, "resolve_user_pk", lambda u, c: "999")
    res = fish.fish_graphql("u", {"sessionid": "X"})
    assert not res["ok"] and "execution error" in res["error"]


RP_PAGE1 = {"username": "u", "items": [
    {"code": "Aa1", "permalink": "https://www.instagram.com/p/Aa1/", "author": "a1",
     "type": "video", "caption": "c1", "videoUrl": "https://cdn/v1.mp4",
     "thumbnail": "https://cdn/t1.jpg", "takenAt": None, "note": None}],
    "count": 1, "nextCursor": "C1", "moreAvailable": True}
RP_PAGE2 = {"username": "u", "items": [
    {"code": "Bb2", "permalink": "https://www.instagram.com/reel/Bb2/", "author": "a2",
     "type": "carousel", "caption": "c2", "thumbnail": "https://cdn/t2.jpg"}],
    "count": 1, "nextCursor": None, "moreAvailable": False}


def test_fish_repostpro_gate_and_pagination(monkeypatch):
    seen_urls = []
    sleeps = []
    state = {"n": 0}

    def fake_json(url, params=None, cookies=None, headers=None, timeout=25):
        seen_urls.append(url)
        state["n"] += 1
        if state["n"] == 1:
            return 402, {"error": "high_traffic", "wait": 20, "token": "TOK"}, ""
        if "cursor=C1" in url:
            assert "gateToken=TOK" in url
            return 200, RP_PAGE2, ""
        return 200, RP_PAGE1, ""

    monkeypatch.setattr(utils, "http_get_json", fake_json)
    res = fish.fish_repostpro("u", max_items=10, _sleep=sleeps.append)
    assert res["ok"] and res["source"] == "repostpro" and res["is_reposts_tab"]
    assert [i["shortcode"] for i in res["items"]] == ["Aa1", "Bb2"]
    assert res["items"][0]["creator_username"] == "a1"
    assert res["items"][0]["video_url"] == "https://cdn/v1.mp4"
    assert res["items"][1]["post_type"] == "Carousel"
    assert sleeps == [22]
    assert any("gateToken=TOK" in u for u in seen_urls)


def test_fish_repostpro_max_items(monkeypatch):
    monkeypatch.setattr(utils, "http_get_json", lambda *a, **k: (200, RP_PAGE1, ""))
    res = fish.fish_repostpro("u", max_items=1)
    assert res["ok"] and len(res["items"]) == 1


def test_fish_repostpro_http_error(monkeypatch):
    monkeypatch.setattr(utils, "http_get_json", lambda *a, **k: (403, None, "blocked"))
    res = fish.fish_repostpro("u")
    assert not res["ok"] and "403" in res["error"]


def test_cli_backend_choices():
    from insta_reposts.cli import build
    p = build()
    assert p.parse_args(["fish", "u", "--backend", "graphql"]).backend == "graphql"
    assert p.parse_args(["fish", "u", "--backend", "repostpro"]).backend == "repostpro"
    assert p.parse_args(["all", "u", "--backend", "graphql"]).backend == "graphql"


def test_extract_boot_tokens():
    html = ('LSD",[],{"token":"ABC123"},323] "dtsg":{"token":"DTSG1"} '
            '"__hsdp":":1,2,3" "hsi":"777" "rev":1050178870')
    boot = fish.extract_boot_tokens(html)
    assert boot["lsd"] == "ABC123" and boot["fb_dtsg"] == "DTSG1"
    assert boot["hsdp"] == ":1,2,3" and boot["hsi"] == "777"


def test_session_health_ok(monkeypatch):
    html = ("usePolarisNotificationsNavItemQueryRelayPreloader "
            'LSD",[],{"token":"L"} "dtsg":{"token":"D"}')
    monkeypatch.setattr(utils, "http_get", lambda *a, **k: (200, html, {"x-ig-set-www-claim": "C"}))
    monkeypatch.setattr(fish, "graphql_query", lambda c, d, f, v, boot=None: ({"x": 1}, None))
    out = fish.session_health({"sessionid": "S", "ds_user_id": "9"})
    assert out["logged_in"] and out["page_ok"] and out["graphql_ok"]


def test_session_health_blocked(monkeypatch):
    html = "usePolarisNotificationsNavItemQueryRelayPreloader"
    monkeypatch.setattr(utils, "http_get", lambda *a, **k: (200, html, {}))
    monkeypatch.setattr(fish, "graphql_query", lambda c, d, f, v, boot=None: (None, "execution error"))
    out = fish.session_health({"sessionid": "S", "ds_user_id": "9"})
    assert not out["graphql_ok"] and "execution error" in out["error"]


def test_session_health_no_session():
    out = fish.session_health({})
    assert not out["logged_in"] and "sessionid" in out["error"]
