"""Shared HTTP + parsing helpers. No login required for basic fetches."""
import json
import re
import pathlib

try:
    from curl_cffi import requests as _cr
    HAS_CURL_CFFI = True
except ImportError:  # pragma: no cover
    _cr = None
    HAS_CURL_CFFI = False

import requests as _rq

DEFAULT_HEADERS = {
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
}

SHORTCODE_RE = re.compile(r"https?://(?:www\.)?instagram\.com/(?:p|reel|tv)/([A-Za-z0-9_-]{5,})/?")


def load_cookies(path):
    """Load Netscape cookies.txt or JSON {name: value} into dict."""
    p = pathlib.Path(path)
    if not p.exists():
        return {}
    txt = p.read_text(errors="ignore").strip()
    if txt.startswith("{"):
        try:
            return json.loads(txt)
        except Exception:
            return {}
    out = {}
    for line in txt.splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 7:
            out[parts[5]] = parts[6]
        elif len(parts) == 2:
            out[parts[0]] = parts[1]
    return out


def http_get(url, cookies=None, timeout=25):
    """GET with TLS impersonation if available, else plain requests."""
    cookies = cookies or {}
    if HAS_CURL_CFFI:
        try:
            r = _cr.get(url, impersonate="chrome136", headers=DEFAULT_HEADERS,
                        cookies=cookies or None, timeout=timeout)
            return r.status_code, r.text, dict(r.headers)
        except Exception:
            pass
    r = _rq.get(url, headers=DEFAULT_HEADERS, cookies=cookies, timeout=timeout)
    return r.status_code, r.text, dict(r.headers)


def http_get_json(url, params=None, cookies=None, headers=None, timeout=25):
    """GET returning (status, parsed_json_or_None, raw_text). Monkeypatch point for tests."""
    cookies = cookies or {}
    h = dict(DEFAULT_HEADERS)
    h["Accept"] = "application/json"
    if headers:
        h.update(headers)
    if HAS_CURL_CFFI:
        try:
            r = _cr.get(url, impersonate="chrome136", headers=h, params=params,
                        cookies=cookies or None, timeout=timeout)
            try:
                return r.status_code, r.json(), r.text
            except Exception:
                return r.status_code, None, r.text
        except Exception as e:
            return 0, None, f"{type(e).__name__}: {e}"
    r = _rq.get(url, headers=h, params=params, cookies=cookies, timeout=timeout)
    try:
        return r.status_code, r.json(), r.text
    except Exception:
        return r.status_code, None, r.text


def extract_data_sjs(html):
    """Return list of parsed JSON objects from <script data-sjs> tags."""
    raws = re.findall(r'<script type="application/json"[^>]*data-sjs>(.*?)</script>', html, re.DOTALL)
    out = []
    for s in raws:
        try:
            out.append(json.loads(s))
        except Exception:
            continue
    return out


def walk_find(node, pred, found):
    if pred(node):
        found.append(node)
        return
    if isinstance(node, dict):
        for v in node.values():
            walk_find(v, pred, found)
    elif isinstance(node, list):
        for v in node:
            walk_find(v, pred, found)


def find_user_pk(scripts, username):
    """Find pk for username in Relay xig_user_by_username payloads."""
    found = []
    def pred(n):
        return isinstance(n, dict) and n.get("username", "").lower() == username.lower() and "pk" in n
    for s in scripts:
        walk_find(s, pred, found)
    if found:
        return str(found[0]["pk"])
    return None


def extract_media_nodes(scripts):
    """Collect all XIGPolaris media nodes (have code + pk). Dedupe by code, prefer richest node."""
    found = []
    def pred(n):
        return (isinstance(n, dict) and "code" in n and ("pk" in n or "id" in n)
                and isinstance(n.get("code"), str) and 5 <= len(n["code"]) <= 30)
    for s in scripts:
        walk_find(s, pred, found)
    # unwrap gated wrappers: outer node often has no media, inner if_not_gated_logged_out does
    expanded = []
    for n in found:
        expanded.append(n)
        inner = n.get("if_not_gated_logged_out")
        if isinstance(inner, dict) and inner.get("code", n.get("code")) == n.get("code"):
            merged = dict(n)
            merged.update({k: v for k, v in inner.items() if v})
            expanded.append(merged)
            expanded.append(inner)
    def _score(n):
        return sum(bool(n.get(k)) for k in ("display_uri", "display_url", "image_versions2",
                                            "video_versions", "carousel_media", "caption", "user"))
    seen = {}
    for n in expanded:
        code = n["code"]
        if code not in seen or _score(n) > _score(seen[code]):
            seen[code] = n
    return list(seen.values())


def node_to_record(node):
    # unwrap logged-out gating wrapper
    inner = node.get("if_not_gated_logged_out")
    if isinstance(inner, dict) and inner.get("code", node.get("code")) == node.get("code"):
        base = dict(node)
        base.update({k: v for k, v in inner.items() if v})
        node = base
    code = node.get("code")
    pk = str(node.get("pk", node.get("id", "")))
    user = node.get("user") or node.get("owner") or {}
    creator = user.get("username") if isinstance(user, dict) else None
    caption = ""
    cap = node.get("caption")
    if isinstance(cap, dict):
        caption = cap.get("text", "")
    elif isinstance(cap, str):
        caption = cap
    typename = node.get("__typename", "")
    if "Video" in typename or node.get("media_type") == 2 or node.get("product_type") == "clips":
        mtype = "Reel" if node.get("product_type") == "clips" else "Video"
    elif "Carousel" in typename or "Album" in typename:
        mtype = "Carousel"
    else:
        mtype = "Photo"
    display = node.get("display_uri") or node.get("display_url") or ""
    if not display:
        iv = node.get("image_versions2") or node.get("image_versions") or {}
        cands = (iv.get("candidates") or []) if isinstance(iv, dict) else []
        if cands:
            display = cands[0].get("url", "")
    video = ""
    vv = node.get("video_versions") or []
    if isinstance(vv, list) and vv:
        video = vv[0].get("url", "")
    post_url = f"https://www.instagram.com/reel/{code}/" if mtype == "Reel" else f"https://www.instagram.com/p/{code}/"
    return {
        "shortcode": code,
        "pk": pk,
        "post_url": post_url,
        "post_type": mtype,
        "creator_username": creator,
        "caption_text": caption[:2000],
        "display_url": display,
        "video_url": video,
        "taken_at": node.get("taken_at") or node.get("caption", {}).get("created_at") if isinstance(node.get("caption"), dict) else None,
    }


def extract_post_urls_from_text(text):
    """Generic fisher: pull instagram post/reel URLs from any text/HTML/JSON."""
    urls = []
    for m in SHORTCODE_RE.finditer(text):
        full = m.group(0)
        if not full.endswith("/"):
            full += "/"
        urls.append(full)
    # dedupe preserve order
    seen, out = set(), []
    for u in urls:
        code = SHORTCODE_RE.search(u).group(1)
        if code not in seen:
            seen.add(code)
            out.append(u)
    return out
