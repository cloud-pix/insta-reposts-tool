import json
from insta_reposts import utils

SAMPLE_HTML = (
    '<html><body>'
    '<script type="application/json" nonce="x" data-sjs>{"a": {"username": "someuser", "pk": "123", "is_private": false}}</script>'
    '<script type="application/json" nonce="x" data-sjs>{"b": {"__typename": "XIGPolarisVideoMedia", "pk": "999", "code": "AbC123XyZ12", "display_uri": "https://example.com/a.jpg", "product_type": "clips", "user": {"username": "creator1"}, "caption": {"text": "hi #t"}}}</script>'
    '</body></html>'
)

def test_extract_data_sjs():
    scripts = utils.extract_data_sjs(SAMPLE_HTML)
    assert len(scripts) == 2

def test_find_user_pk():
    scripts = utils.extract_data_sjs(SAMPLE_HTML)
    assert utils.find_user_pk(scripts, "someuser") == "123"

def test_extract_media_nodes():
    scripts = utils.extract_data_sjs(SAMPLE_HTML)
    nodes = utils.extract_media_nodes(scripts)
    assert any(n["code"] == "AbC123XyZ12" for n in nodes)
    rec = utils.node_to_record(next(n for n in nodes if n["code"] == "AbC123XyZ12"))
    assert rec["post_url"].endswith("/AbC123XyZ12/")
    assert rec["creator_username"] == "creator1"

def test_gated_unwrap():
    node = {"code": "AbC123XyZ12", "pk": "1",
            "if_not_gated_logged_out": {"code": "AbC123XyZ12", "display_uri": "https://example.com/g.jpg",
                                        "user": {"username": "c2"}}}
    rec = utils.node_to_record(node)
    assert rec["display_url"] == "https://example.com/g.jpg"
    assert rec["creator_username"] == "c2"

def test_extract_urls():
    txt = "see https://www.instagram.com/reel/AbC123XyZ12/ and https://www.instagram.com/p/DePb6WLuVae"
    urls = utils.extract_post_urls_from_text(txt)
    assert len(urls) == 2

def test_fish_manual_links(tmp_path):
    from insta_reposts import fish
    f = tmp_path / "links.txt"
    f.write_text("https://www.instagram.com/reel/AbC123XyZ12/\nhttps://www.instagram.com/p/DePb6WLuVae/\n")
    res = fish.fish_manual(str(f))
    assert res["ok"] and len(res["items"]) == 2

def test_private_needs_login():
    from insta_reposts import fish
    html = ('<html><body><script type="application/json" nonce="x" data-sjs>'
            '{"x": {"username": "privuser", "pk": "555", "is_private": true}}</script></body></html>')
    import unittest.mock as mock
    with mock.patch("insta_reposts.fish.utils.http_get", return_value=(200, html, {})):
        res = fish.fish_instagram("privuser", cookies={})
        assert res["ok"] is False and "private" in res["error"].lower()
