# insta-reposts-tool (FOSS, AGPL-3.0-or-later)

Fish all repost links of an Instagram profile, then download them — `yt-dlp`-style CLI, login optional.

## Why this exists
- `instaloader` 4.15.3 has no `--reposts` / `get_reposts` (only posts/reels/tagged). Anonymous use gets `429` immediately.
- Instagram gates the Reposts tab (launched Aug 2025) behind login. Logged-out `/user/reposts/` HTML only preloads PostsTab.
- `igexport.com/api/ig-reposts/` is behind Cloudflare (403 programmatically) — works in a real browser only.
- This tool fishes links via login cookies when available, else via manual browser export, then downloads.

## Backends (fish)
- `graphql` (PRIMARY, first-party): the exact web query `PolarisProfileRepostsTabContentQuery`
  (`doc_id 28594321130221951`, refetch `28844503865240264`, reversed Oct 2026 from IG web
  bundle `r96NAw9.js`, rev 1050178870). Needs a **web-login** session (`login` command or
  browser cookies): mobile-API-born sessions get `execution error` on every query.
  Minimal doc_id-only calls are also rejected — the tool mirrors the Relay POST
  (lsd, caller class, friendly name, async params, provider vars), paginates via `max_id`,
  and is verified live (49/49 current reposts). `check` tests your session first.
- `instagram`: profile `/reposts/` HTML Relay payload (needs login for real tab; anon returns PostsTab + warns).
- `repostpro` (FALLBACK, third-party): `repostpro.app` viewer API, no login. Guest gate
  (`402 high_traffic` → wait → `gateToken` retry) and guest view quota (`login_required`
  when exhausted, resets over time) are handled/surfaced. Override host via `REPOSTPRO_BACKEND`.
  Third parties can degrade or die — prefer `graphql`.
- `manual`: your own browser export (links.txt/JSON/CSV/saved HTML). Always works.
- `apify`: paid, needs `APIFY_TOKEN`.

## Install
```bash
pip install -e .
pip install curl_cffi yt-dlp  # recommended: TLS impersonation + video downloader
```

## Use
```bash
# 1. fish. auto = first-party graphql when logged in, else repostpro fallback (no login)
insta-reposts fish someuser -o reposts.json --links links.txt --max 200
insta-reposts fish someuser -o reposts.json --session-file session.json --max 200
insta-reposts fish someuser --backend graphql -o r.json     # force first-party (needs login)
insta-reposts fish someuser --backend repostpro -o r.json   # force third-party (no login, guest quota)

# 1b. session health first (primary needs a working web session)
insta-reposts check --session-file session.json

# 1c. manual path: export from real browser, then:
# open https://igexport.com/en/instagram-repost-viewer in browser, View Reposts, copy links -> links.txt
insta-reposts fish --from-file links.txt -o reposts.json --links links.txt
insta-reposts fish --from-file saved-viewer.html -o reposts.json

# optional paid fisher
APIFY_TOKEN=xxx insta-reposts fish instagram --backend apify --max 100

# 2. download
insta-reposts download reposts.json -o ./out --downloader direct
insta-reposts download links.txt -o ./out --downloader yt-dlp --cookies cookies.txt
insta-reposts download links.txt -o ./out --downloader gallery-dl

# all-in-one
insta-reposts all instagram -o ./out --downloader direct --cookies cookies.txt
```

## Login + private profiles (username + password + 2FA supported)
Yes. Uses FOSS `instaloader` (pure Python, Termux-compatible) for `login(user, passwd)` +
`two_factor_login(code)`; `aiograpi` is tried opportunistically on desktop (no Termux wheel).
```bash
# username + password + 2FA code (args, env, or prompted; password never logged)
insta-reposts login --username myuser --password '...' --verification-code 123456 \
  --session-file session.json --cookies-out cookies.txt
INSTAGRAM_USERNAME=u INSTAGRAM_PASSWORD=p INSTAGRAM_2FA_CODE=123456 \
  insta-reposts login --session-file session.json

# then reuse for private profiles (must follow the private account)
insta-reposts fish privateuser -o r.json --session-file session.json --max 200
insta-reposts download r.json -o ./out-private --session-file session.json --downloader direct
insta-reposts all privateuser -o ./out-private --session-file session.json

# other session inputs (all commands accept all three)
insta-reposts fish privateuser -o r.json --cookies cookies.txt
export INSTAGRAM_SESSIONID=xxx
insta-reposts all privateuser -o ./out-private --sessionid "$INSTAGRAM_SESSIONID"
```
Without login, private fish fails fast with `@{user} is private: re-run with --cookies...`.
With login, the same cookies are used for fish + media download, so private `display_url`/`video_url` resolve.

Cookies: Netscape `cookies.txt` (yt-dlp `--cookies-from-browser chrome` export) or JSON `{"sessionid":"..."}`.

## Notes
- Public anon OK for link fishing (posts preload) + photo/thumbnail download; real Reposts tab + videos + private need login.
- Be gentle: single residential IP ~200 req/hr; add delays for bulk.
- Not affiliated with Instagram/Meta.
