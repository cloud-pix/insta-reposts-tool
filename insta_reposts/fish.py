"""Fish repost links.

Backends:
- instagram: fetch /<user>/reposts/ with optional login cookies (curl_cffi).
  Anonymous HTML currently falls back to posts tab (Instagram requires login
  for Reposts tab), so without cookies this returns posts + warns.
  With --cookies sessionid login it parses the real reposts Relay payload.
- manual: parse a saved IGExport/viewer HTML, JSON, CSV or plain links.txt.
- apify: optional, needs APIFY_TOKEN.
"""
import json
import csv
import os
import pathlib
from . import utils

# Reversed from web bundles (Oct 2026, rev 1050178870; bundle r96NAw9.js).
# Entry point PolarisProfileRepostsTabRoot.entrypoint, root field fetch__XDTUserDict,
# content variables = {"user_id": <pk>}. Rotate when IG ships new bundles.
REPOSTS_CONTENT_DOC_ID = "28594321130221951"
REPOSTS_REFETCH_DOC_ID = "28844503865240264"
TAGGED_CONTENT_DOC_ID = "28463910693308962"
GRAPHQL_URL = "https://www.instagram.com/graphql/query/"


# Reversed from web bundles (Oct 2026, rev 1050178870; bundle r96NAw9.js).
# Entry point PolarisProfileRepostsTabRoot.entrypoint, root field fetch__XDTUserDict,
# content variables = {"user_id": <pk>}; refetch paginates with {"id": <pk>, "max_id": <cursor>}.
# Response: data.fetch__XDTUserDict.user_reposts_timeline.{repost_grid_items[]:{media},
# repost_more_available, repost_next_max_id}. Rotate when IG ships new bundles.
REPOSTS_CONTENT_DOC_ID = "28594321130221951"
REPOSTS_REFETCH_DOC_ID = "28844503865240264"
TAGGED_CONTENT_DOC_ID = "28463910693308962"
GRAPHQL_URL = "https://www.instagram.com/graphql/query/"
# Third-party fallback (no login needed). Reversed from repostpro.app viewer JS.
# Guest gate: HTTP 402 {"error":"high_traffic","wait":N,"token":T} -> sleep N -> retry with &gateToken=T.
REPOSTPRO_BACKEND = "https://test-scrrps-53b332f45565.herokuapp.com"

REPOSTPRO_BACKEND = os.environ.get("REPOSTPRO_BACKEND", REPOSTPRO_BACKEND)


RELAY_PROVIDER_VAR = "__relay_internal__pv__PolarisShortDramaEnabledrelayprovider"


def extract_boot_tokens(html):
    """Pull Relay POST tokens from any authed page HTML (lsd, fb_dtsg, __hsdp...)."""
    import re
    html = html or ""

    def grab(pat):
        m = re.search(pat, html)
        return m.group(1) if m else ""
    return {
        "lsd": grab(r'LSD",\[\],\{"token":"([^"]+)"'),
        "fb_dtsg": grab(r'"dtsg":\{"token":"([^"]+)"'),
        "hsdp": grab(r'"__hsdp":"([^"]+)"'),
        "hsi": grab(r'"hsi":"(\d+)"') or "7696147530141082471",
        "rev": grab(r'"rev":(\d+)') or "1050178870",
    }


def graphql_bootstrap(cookies, username="instagram"):
    """One authed page load -> tokens for Relay POSTs. Returns dict (may be partial)."""
    status, html, _ = utils.http_get(
        f"https://www.instagram.com/{username}/reposts/", cookies=cookies)
    if status != 200:
        return {}
    return extract_boot_tokens(html)


def graphql_query(cookies, doc_id, friendly_name, variables, boot=None):
    """Persisted-query POST mirroring the web Relay layer (Oct 2026).

    Minimal doc_id+variables GETs are rejected with 'execution error'; the full
    async-param body (lsd, caller class, friendly name, timestamps, __hsdp,
    __rev, fb_dtsg, provider vars) executes. Returns (data_or_None, error_or_None).
    """
    import re
    cookies = cookies or {}
    boot = boot or {}
    lsd = boot.get("lsd", "")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
        "X-IG-App-ID": "936619743392459",
        "X-CSRFToken": cookies.get("csrftoken", ""),
        "X-Requested-With": "XMLHttpRequest",
        "X-FB-Friendly-Name": friendly_name,
        "X-FB-LSD": lsd,
    }
    body = {
        "lsd": lsd,
        "fb_api_caller_class": "RelayModern",
        "fb_api_req_friendly_name": friendly_name,
        "server_timestamps": "true",
        "variables": json.dumps(variables),
        "doc_id": doc_id,
        "__hsdp": boot.get("hsdp", ""),
        "__rev": boot.get("rev", "1050178870"),
        "__hsi": boot.get("hsi", ""),
        "__comet_req": "7",
        "jazoest": "26204",
        "fb_dtsg": boot.get("fb_dtsg", ""),
        "dpr": "1",
    }
    try:
        from curl_cffi import requests as _cr
    except ImportError:
        return None, "curl_cffi not installed"
    try:
        r = _cr.post(GRAPHQL_URL, impersonate="chrome136", headers=headers,
                     data=body, cookies=cookies or None, timeout=25)
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"
    ctype = r.headers.get("content-type", "")
    if "javascript" not in ctype and "json" not in ctype:
        return None, f"HTTP {r.status_code} non-JSON ({ctype or 'no ctype'})"
    try:
        payload = r.json()
    except Exception:
        return None, f"HTTP {r.status_code} unparseable"
    if payload.get("errors"):
        msg = "; ".join(e.get("message", "?") for e in payload["errors"])
        return None, msg
    return payload.get("data"), None


def parse_reposts_response(data):
    """Parse GraphQL data -> (records, more_available, next_max_id).

    Path (from compiled Relay AST): fetch__XDTUserDict.user_reposts_timeline.
    Media nodes are XDT-shaped, so utils.node_to_record maps them directly.
    """
    records, more_available, next_max_id = [], False, None
    try:
        tl = (data or {}).get("fetch__XDTUserDict", {}).get("user_reposts_timeline", {}) or {}
    except AttributeError:
        return records, False, None
    for item in tl.get("repost_grid_items", []) or []:
        media = (item or {}).get("media") if isinstance(item, dict) else None
        if not media or not media.get("code"):
            continue
        try:
            records.append(utils.node_to_record(media))
        except Exception:
            continue
    more_available = bool(tl.get("repost_more_available"))
    next_max_id = tl.get("repost_next_max_id") or None
    return records, more_available, next_max_id


def resolve_user_pk(username, cookies):
    """pk from profile HTML payload: anon attempt first (public), then authed."""
    for ck in ({}, cookies or {}):
        try:
            status, html, _ = utils.http_get(f"https://www.instagram.com/{username}/", cookies=ck)
        except Exception:
            continue
        if status != 200:
            continue
        pk = utils.find_user_pk(utils.extract_data_sjs(html), username)
        if pk:
            return pk
    return None


def fish_graphql(username, cookies=None, max_items=200):
    """PRIMARY first-party backend: exact Reposts-tab query. Needs healthy login."""
    cookies = cookies or {}
    if not cookies.get("sessionid"):
        return {"ok": False, "error": "graphql backend needs login cookies (--cookies/--session-file/--sessionid)",
                "items": [], "source": "graphql"}
    username = username.lstrip("@").split("/")[3] if "instagram.com/" in username else username.lstrip("@")
    pk = resolve_user_pk(username, cookies)
    if not pk:
        return {"ok": False, "error": f"could not resolve pk for @{username} (session may be restricted)",
                "items": [], "source": "graphql"}
    boot = graphql_bootstrap(cookies, username)
    if not boot.get("lsd"):
        return {"ok": False, "error": "could not bootstrap Relay tokens (page load blocked?)",
                "items": [], "source": "graphql", "user_pk": pk}
    items = []
    base_vars = {"user_id": str(pk), RELAY_PROVIDER_VAR: False}
    data, err = graphql_query(cookies, REPOSTS_CONTENT_DOC_ID,
                              "PolarisProfileRepostsTabContentQuery", base_vars, boot)
    if err:
        return {"ok": False, "error": f"graphql: {err}", "items": [], "source": "graphql", "user_pk": pk}
    recs, more, cursor = parse_reposts_response(data)
    items.extend(recs)
    while more and cursor and len(items) < max_items:
        data, err = graphql_query(cookies, REPOSTS_REFETCH_DOC_ID,
                                  "PolarisProfileRepostsTabContentRefetchQuery",
                                  {"id": str(pk), "max_id": cursor, RELAY_PROVIDER_VAR: False}, boot)
        if err:
            break
        recs, more, cursor = parse_reposts_response(data)
        if not recs:
            break
        items.extend(recs)
    return {"ok": True, "username": username, "user_pk": pk, "items": items[:max_items],
            "source": "graphql", "is_reposts_tab": True}


def repostpro_item_to_record(it):
    code = it.get("code") or ""
    url = it.get("permalink") or (f"https://www.instagram.com/p/{code}/" if code else "")
    m = utils.SHORTCODE_RE.search(url or "")
    if m:
        code = m.group(1)
    t = (it.get("type") or "").lower()
    mtype = "Reel" if t == "video" else ("Carousel" if t == "carousel" else "Photo")
    return {
        "shortcode": code,
        "pk": "",
        "post_url": url,
        "post_type": mtype,
        "creator_username": it.get("author"),
        "caption_text": (it.get("caption") or "")[:2000],
        "display_url": it.get("thumbnail") or "",
        "video_url": it.get("videoUrl") or "",
        "taken_at": it.get("takenAt"),
        "repost_note": it.get("note"),
    }


def fish_repostpro(username, max_items=200, _sleep=None):
    """FALLBACK third-party backend (repostpro.app API, no login needed).

    Handles guest gate: 402 high_traffic -> wait -> retry with gateToken.
    """
    import time
    import urllib.parse
    sleep = _sleep or time.sleep
    username = username.lstrip("@").split("/")[3] if "instagram.com/" in username else username.lstrip("@")
    items, cursor, gate, pages = [], None, None, 0
    while True:
        if pages >= 50:
            break
        url = f"{REPOSTPRO_BACKEND}/api/instagram-reposts?username=" + urllib.parse.quote(username)
        if cursor:
            url += "&cursor=" + urllib.parse.quote(cursor)
        if gate:
            url += "&gateToken=" + urllib.parse.quote(gate)
        status, payload, raw = utils.http_get_json(
            url, cookies={}, headers={"Referer": "https://repostpro.app/instagram-repost-viewer",
                                      "Origin": "https://repostpro.app"})
        if payload is None:
            return {"ok": False, "error": f"repostpro HTTP {status} ({raw[:120]})",
                    "items": [], "source": "repostpro"}
        if payload.get("error") == "high_traffic":
            try:
                sleep(int(payload.get("wait", 20)) + 2)
            except Exception:
                pass
            gate = payload.get("token")
            if not gate:
                return {"ok": False, "error": "repostpro gate gave no token", "items": [], "source": "repostpro"}
            continue
        if payload.get("error"):
            extra = payload.get("message", "")
            if payload.get("nextLimit"):
                extra += f" (resets: {payload.get('nextLimit')})"
            return {"ok": False, "error": f"repostpro: {payload.get('error')}: {extra}",
                    "items": [], "source": "repostpro"}
        pages += 1
        for it in payload.get("items", []) or []:
            try:
                items.append(repostpro_item_to_record(it))
            except Exception:
                continue
            if len(items) >= max_items:
                break
        if len(items) >= max_items:
            break
        if payload.get("moreAvailable") and payload.get("nextCursor"):
            cursor = payload["nextCursor"]
        else:
            break
    return {"ok": True, "username": payload.get("username", username) if isinstance(payload, dict) else username,
            "items": items[:max_items], "source": "repostpro", "is_reposts_tab": True}


def session_health(cookies):
    """Check whether a session can actually execute the primary path.

    Returns {logged_in, page_ok, graphql_ok, www_claim, error}. One page load
    + one minimal control query (tagged tab, count 3, on self pk).
    """
    cookies = cookies or {}
    out = {"logged_in": False, "page_ok": False, "graphql_ok": False,
           "www_claim": False, "error": None}
    if not cookies.get("sessionid"):
        out["error"] = "no sessionid (pass --cookies/--session-file/--sessionid)"
        return out
    out["logged_in"] = True
    try:
        status, html, headers = utils.http_get(
            "https://www.instagram.com/", cookies=cookies)
    except Exception as e:
        out["error"] = f"page load failed: {e}"
        return out
    out["page_ok"] = status == 200
    out["www_claim"] = bool(headers and headers.get("x-ig-set-www-claim"))
    if status != 200:
        out["error"] = f"page HTTP {status}"
        return out
    if "usePolarisNotificationsNavItemQueryRelayPreloader" not in html:
        out["error"] = "page does not show logged-in state (session may be dead)"
        return out
    self_pk = cookies.get("ds_user_id")
    if not self_pk:
        out["error"] = "no ds_user_id in session; cannot self-test GraphQL"
        return out
    boot = extract_boot_tokens(html)
    data, err = graphql_query(cookies, TAGGED_CONTENT_DOC_ID,
                              "PolarisProfileTaggedTabContentQuery",
                              {"user_id": str(self_pk), "count": 3,
                               RELAY_PROVIDER_VAR: False}, boot)
    if err:
        out["error"] = f"graphql blocked: {err} (account restricted; wait or use another account)"
        return out
    out["graphql_ok"] = True
    return out


def fish_graphql_raw(user_pk, cookies, doc_id=REPOSTS_CONTENT_DOC_ID,
                     friendly_name="PolarisProfileRepostsTabContentQuery", count=None):
    """Low-level single GraphQL call (debug/introspection)."""
    variables = {"user_id": str(user_pk), RELAY_PROVIDER_VAR: False}
    if count:
        variables["count"] = count
    data, err = graphql_query(cookies or {}, doc_id, friendly_name, variables,
                              graphql_bootstrap(cookies or {}))
    if err:
        return {"ok": False, "error": err}
    return {"ok": True, "data": data}


def fish_instagram(username, cookies=None, max_items=200):
    username = username.lstrip("@").split("/")[3] if "instagram.com/" in username else username.lstrip("@")
    cookies = cookies or {}
    base = f"https://www.instagram.com/{username}/reposts/"
    status, html, _ = utils.http_get(base, cookies=cookies)
    if status in (404,):
        return {"ok": False, "error": f"profile not found: {username}", "items": [], "source": "instagram"}
    if status != 200:
        return {"ok": False, "error": f"HTTP {status} for {base}", "items": [], "source": "instagram"}
    scripts = utils.extract_data_sjs(html)
    pk = utils.find_user_pk(scripts, username)
    # private-profile detection (public payload includes is_private)
    is_private = None
    try:
        found = []
        def _p(n):
            return isinstance(n, dict) and n.get("username", "").lower() == username.lower() and "is_private" in n
        for s in scripts:
            utils.walk_find(s, _p, found)
        if found:
            is_private = bool(found[0]["is_private"])
    except Exception:
        pass
    if is_private and not (cookies and cookies.get("sessionid")):
        return {"ok": False, "error": f"@{username} is private: re-run with --cookies cookies.txt / --sessionid from a follower account",
                "items": [], "source": "instagram", "is_private": True, "user_pk": pk}
    nodes = utils.extract_media_nodes(scripts)
    # Detect whether page actually preloaded a Reposts tab query
    is_reposts_query = "RepostsTabContentQuery" in html
    items = [utils.node_to_record(n) for n in nodes[:max_items]]
    warn = None
    if not is_reposts_query:
        if cookies and cookies.get("sessionid"):
            warn = ("page preloaded PostsTab, not RepostsTab even with login; "
                    "your session may lack access (private/not-following) or Instagram changed the query. "
                    "Fallback: export links from IGExport viewer in a browser, then 'fish --from-file'.")
        else:
            warn = ("logged-out HTML preloads PostsTab, not RepostsTab; "
                    "Instagram gates Reposts tab AND private profiles behind login. "
                    "Re-run with --cookies cookies.txt / --sessionid (follower account for private) "
                    "or use 'fish --from-file' with links exported from IGExport viewer in a real browser.")
    return {"ok": True, "username": username, "user_pk": pk, "items": items,
            "source": "instagram", "warning": warn, "is_reposts_tab": is_reposts_query,
            "is_private": is_private}


def fish_manual(path):
    """Parse IGExport/manual export: .txt links, .json dataset, .csv, or saved .html."""
    p = pathlib.Path(path)
    if not p.exists():
        return {"ok": False, "error": f"not found: {path}", "items": []}
    suf = p.suffix.lower()
    text = p.read_text(errors="ignore")
    items = []
    if suf == ".json":
        try:
            data = json.loads(text)
            rows = data if isinstance(data, list) else data.get("items") or data.get("data") or []
            for r in rows:
                if isinstance(r, dict) and r.get("post_url"):
                    code = utils.SHORTCODE_RE.search(r["post_url"])
                    items.append({
                        "shortcode": code.group(1) if code else r.get("shortcode", ""),
                        "post_url": r.get("post_url"),
                        "post_type": r.get("post_type", ""),
                        "creator_username": r.get("creator_username"),
                        "caption_text": r.get("caption_text", "")[:2000],
                        "display_url": r.get("media_url") or r.get("display_url") or "",
                        "video_url": r.get("video_url", ""),
                    })
                elif isinstance(r, str):
                    for u in utils.extract_post_urls_from_text(r):
                        code = utils.SHORTCODE_RE.search(u).group(1)
                        items.append({"shortcode": code, "post_url": u})
            if items:
                return {"ok": True, "items": items, "source": "manual-json"}
        except Exception:
            pass
    if suf == ".csv":
        try:
            with p.open() as f:
                for row in csv.DictReader(f):
                    url = row.get("post_url") or row.get("url") or row.get("permalink") or ""
                    if url:
                        code_m = utils.SHORTCODE_RE.search(url)
                        items.append({"shortcode": code_m.group(1) if code_m else "",
                                      "post_url": url,
                                      "creator_username": row.get("creator_username"),
                                      "caption_text": (row.get("caption_text") or "")[:2000]})
            if items:
                return {"ok": True, "items": items, "source": "manual-csv"}
        except Exception:
            pass
    # fallback: regex URLs from any text/html
    for u in utils.extract_post_urls_from_text(text):
        code = utils.SHORTCODE_RE.search(u).group(1)
        items.append({"shortcode": code, "post_url": u})
    # also try embedded JSON media nodes
    try:
        scripts = utils.extract_data_sjs(text)
        for n in utils.extract_media_nodes(scripts):
            rec = utils.node_to_record(n)
            if all(r["shortcode"] != rec["shortcode"] for r in items):
                items.append(rec)
    except Exception:
        pass
    return {"ok": bool(items), "items": items, "source": "manual-scan",
            "error": None if items else "no instagram post URLs found"}


def fish_apify(username, token, max_items=100):
    """Call data-slayer/instagram-reposts actor. Needs APIFY_TOKEN."""
    import urllib.request
    import time
    if not token:
        return {"ok": False, "error": "APIFY_TOKEN missing", "items": []}
    actor = "data-slayer~instagram-reposts"
    payload = json.dumps({"username": username.lstrip("@"), "maxResults": max_items}).encode()
    req = urllib.request.Request(
        f"https://api.apify.com/v2/acts/{actor}/runs?token={token}",
        data=payload, headers={"Content-Type": "application/json"})
    try:
        run = json.load(urllib.request.urlopen(req, timeout=30))
        run_id = run["data"]["id"]
    except Exception as e:
        return {"ok": False, "error": f"apify run start failed: {e}", "items": []}
    for _ in range(60):
        try:
            st = json.load(urllib.request.urlopen(
                f"https://api.apify.com/v2/actor-runs/{run_id}?token={token}", timeout=20))
            status = st["data"]["status"]
            if status == "SUCCEEDED":
                ds = st["data"].get("defaultDatasetId")
                rows = json.load(urllib.request.urlopen(
                    f"https://api.apify.com/v2/datasets/{ds}/items?token={token}", timeout=30))
                items = [{"shortcode": (utils.SHORTCODE_RE.search(r.get("post_url", "")) or [None, ""])[1]
                                     if isinstance(r.get("post_url"), str) else "",
                          "post_url": r.get("post_url", ""), "post_type": r.get("post_type", ""),
                          "creator_username": r.get("creator_username"),
                          "caption_text": (r.get("caption_text") or "")[:2000],
                          "display_url": r.get("media_url", ""), "video_url": r.get("video_url", "")}
                         for r in rows if isinstance(r, dict) and r.get("post_url")]
                return {"ok": True, "items": items, "source": "apify"}
            if status in ("FAILED", "ABORTED", "TIMED-OUT"):
                return {"ok": False, "error": f"apify run {status}", "items": []}
        except Exception as e:
            return {"ok": False, "error": f"apify poll failed: {e}", "items": []}
        time.sleep(5)
    return {"ok": False, "error": "apify timeout", "items": []}
