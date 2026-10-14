"""CLI: fish repost links -> links.txt -> download media. Login optional, private supported via login."""
import argparse
import json
import os
import pathlib
import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from insta_reposts import fish, download, utils, auth


def build():
    p = argparse.ArgumentParser(prog="insta-reposts",
        description="Fish all repost links of an Instagram profile, then download (FOSS, login optional, private via login).")
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fish", help="fish repost links -> JSON + links.txt")
    f.add_argument("username", help="username, @user, or profile URL (private OK with --cookies/--sessionid from follower)")
    f.add_argument("-o", "--out", default="reposts.json")
    f.add_argument("--links", default="links.txt")
    f.add_argument("--max", type=int, default=200)
    f.add_argument("--backend", choices=["auto", "graphql", "instagram", "repostpro", "manual", "apify"], default="auto",
                   help="auto: graphql (first-party, needs login) else repostpro (no login)")
    f.add_argument("--from-file", help="manual export file (IGExport saved HTML/JSON/CSV/links.txt)")
    f.add_argument("--cookies", help="cookies.txt (Netscape) or JSON for login; enables real Reposts tab + private profiles")
    f.add_argument("--sessionid", help="Instagram sessionid value (or INSTAGRAM_SESSIONID env); follower account for private")
    f.add_argument("--session-file", help="session.json from `login` (or INSTAGRAM_SESSION_FILE env)")
    f.add_argument("--login", metavar="USER", help="interactive login, save session (needs aiograpi/instaloader or manual paste)")

    d = sub.add_parser("download", help="download items from fish JSON or links.txt (private needs login cookies)")
    d.add_argument("input", help="reposts.json or links.txt")
    d.add_argument("-o", "--outdir", default="./out")
    d.add_argument("--downloader", choices=["direct", "yt-dlp", "gallery-dl"], default="direct")
    d.add_argument("--cookies", help="cookies file for gated videos / private profiles")
    d.add_argument("--sessionid", help="sessionid value (or INSTAGRAM_SESSIONID env)")
    d.add_argument("--session-file", help="session.json from `login`")
    d.add_argument("--links-only", action="store_true")

    a = sub.add_parser("all", help="fish + download in one go (private needs --cookies/--sessionid)")
    a.add_argument("username", help="username or profile URL")
    a.add_argument("-o", "--outdir", default="./out")
    a.add_argument("--max", type=int, default=200)
    a.add_argument("--downloader", choices=["direct", "yt-dlp", "gallery-dl"], default="direct")
    a.add_argument("--cookies", help="cookies file (optional login; REQUIRED for private profiles)")
    a.add_argument("--sessionid", help="sessionid value")
    a.add_argument("--session-file", help="session.json from `login`")
    a.add_argument("--backend", choices=["auto", "graphql", "instagram", "repostpro", "apify"], default="auto",
                   help="auto: graphql (first-party, needs login) else repostpro (no login)")

    l = sub.add_parser("login", help="login with username+password+2FA and save session (private profiles)")
    l.add_argument("--username", default=None, help="IG username (or INSTAGRAM_USERNAME env)")
    l.add_argument("--password", default=None, help="IG password (or INSTAGRAM_PASSWORD env, else prompted; never logged)")
    l.add_argument("--verification-code", "--2fa-code", dest="verification_code", default=None,
                   help="2FA code (or INSTAGRAM_2FA_CODE env, else prompted when required)")
    l.add_argument("--session-file", default="session.json", help="portable session output (JSON)")
    l.add_argument("--cookies-out", default="cookies.txt", help="Netscape cookies export for yt-dlp (empty to skip)")
    l.add_argument("--via", choices=["auto", "instaloader", "aiograpi"], default="auto",
                   help="backend (default auto: instaloader first; aiograpi has no Termux wheel)")

    c = sub.add_parser("check", help="test whether your session can execute the primary graphql path")
    c.add_argument("--cookies", default=None)
    c.add_argument("--sessionid", default=None)
    c.add_argument("--session-file", default=None)
    return p


def load_cookies_arg(path, sessionid=None, session_file=None):
    return auth.resolve_cookies(path, sessionid, session_file)


def main(argv=None):
    p = build()
    a = p.parse_args(argv)
    if a.cmd == "login":
        username = a.username or os.environ.get("INSTAGRAM_USERNAME")
        res = auth.login_interactive(username, a.session_file, a.password,
                                     a.verification_code, a.cookies_out or None,
                                     getattr(a, "via", "auto"))
        print(json.dumps({k: v for k, v in res.items() if k != "cookies"}, indent=2))
        return 0 if res.get("ok") else 1
    if a.cmd == "check":
        cookies = load_cookies_arg(a.cookies, getattr(a, "sessionid", None),
                                   getattr(a, "session_file", None) or os.environ.get("INSTAGRAM_SESSION_FILE"))
        out = fish.session_health(cookies)
        print(json.dumps(out, indent=2))
        return 0 if out.get("graphql_ok") else 1
    if a.cmd == "fish":
        if getattr(a, "login", None):
            lr = auth.login_interactive(a.login, "session.json")
            if not lr.get("ok"):
                print("login failed: " + str(lr.get("error")))
                return 1
        cookies = load_cookies_arg(a.cookies, getattr(a, "sessionid", None),
                                   getattr(a, "session_file", None) or os.environ.get("INSTAGRAM_SESSION_FILE"))
        backend = a.backend
        if a.from_file:
            backend = "manual"
        if backend == "auto":
            # first-party first: exact Reposts-tab query when logged in,
            # third-party fallback when anonymous.
            backend = "graphql" if auth.has_login(cookies) else "repostpro"
        if backend == "manual":
            res = fish.fish_manual(a.from_file or a.username)
        elif backend == "apify":
            res = fish.fish_apify(a.username, os.environ.get("APIFY_TOKEN", ""), a.max)
        elif backend == "graphql":
            res = fish.fish_graphql(a.username, cookies, a.max)
            if not res.get("ok") and "needs login" not in str(res.get("error", "")):
                # healthy-session failure: fall through to third-party rather than dying
                print("graphql failed (" + str(res.get("error"))[:100] + "); falling back to repostpro")
                res = fish.fish_repostpro(a.username, a.max)
        elif backend == "repostpro":
            res = fish.fish_repostpro(a.username, a.max)
        else:
            res = fish.fish_instagram(a.username, cookies, a.max)
        pathlib.Path(a.out).write_text(json.dumps(res, indent=2, ensure_ascii=False))
        links = [i.get("post_url") for i in res.get("items", []) if i.get("post_url")]
        if a.links:
            pathlib.Path(a.links).write_text("\n".join(links) + ("\n" if links else ""))
        print(f"fish:{res.get('source')} ok={res.get('ok')} n={len(links)} -> {a.out} + {a.links}")
        if res.get("warning"):
            print("WARNING: " + res["warning"])
        if not res.get("ok"):
            print("ERROR: " + str(res.get("error")))
            return 1
        return 0
    if a.cmd == "download":
        cookies = load_cookies_arg(a.cookies, getattr(a, "sessionid", None),
                                   getattr(a, "session_file", None) or os.environ.get("INSTAGRAM_SESSION_FILE"))
        ip = pathlib.Path(a.input)
        if ip.suffix == ".json":
            data = json.loads(ip.read_text())
            items = data.get("items", data if isinstance(data, list) else [])
        else:
            items = [{"post_url": l.strip(), "shortcode": (utils.SHORTCODE_RE.search(l.strip()).group(1)
                      if utils.SHORTCODE_RE.search(l.strip()) else "")}
                     for l in ip.read_text().splitlines() if "instagram.com/" in l]
        man = download.download_items(items, a.outdir, cookies, a.downloader, a.links_only)
        print(f"download:{a.downloader} n={len(items)} manifest={len(man)} -> {a.outdir}")
        return 0
    if a.cmd == "all":
        cookies = load_cookies_arg(a.cookies, getattr(a, "sessionid", None),
                                   getattr(a, "session_file", None) or os.environ.get("INSTAGRAM_SESSION_FILE"))
        if a.backend == "apify":
            res = fish.fish_apify(a.username, os.environ.get("APIFY_TOKEN", ""), a.max)
        elif a.backend == "repostpro" or (a.backend == "auto" and not auth.has_login(cookies)):
            res = fish.fish_repostpro(a.username, a.max)
        elif a.backend == "instagram":
            res = fish.fish_instagram(a.username, cookies, a.max)
        else:
            res = fish.fish_graphql(a.username, cookies, a.max)
            if not res.get("ok") and "needs login" not in str(res.get("error", "")):
                print("graphql failed (" + str(res.get("error"))[:100] + "); falling back to repostpro")
                res = fish.fish_repostpro(a.username, a.max)
        outdir = pathlib.Path(a.outdir)
        outdir.mkdir(parents=True, exist_ok=True)
        (outdir / "reposts.json").write_text(json.dumps(res, indent=2, ensure_ascii=False))
        man = download.download_items(res.get("items", []), outdir, cookies, a.downloader)
        print(f"all:{res.get('source')} fished={len(res.get('items', []))} manifest={len(man)} -> {outdir}")
        if res.get("warning"):
            print("WARNING: " + res["warning"])
        return 0 if res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
