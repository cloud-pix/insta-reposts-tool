# insta-reposts-tool 📸

Grab **all the repost links** from any Instagram profile, then download them. A `yt-dlp`-style CLI — login optional, Termux-friendly.

Free and open source (AGPL-3.0-or-later).

## Why does this exist? 🤔

Instagram added a Reposts tab in 2025 but never gave tool authors a way to read it — `instaloader` still has no repost support, and logged-out scraping hits a wall (`429`) immediately. This tool fishes out the links first, downloads second.

## Install

```bash
pip install -e .
pip install curl_cffi yt-dlp  # recommended: nicer networking + video downloads
```

## Quickstart 🚀

```bash
# no login: fishes what it can through a public fallback
insta-reposts fish someuser -o reposts.json --links links.txt --max 200

# download everything you fished
insta-reposts download reposts.json -o ./out

# ...or do both in one go
insta-reposts all someuser -o ./out --downloader direct --cookies cookies.txt
```

## Logging in (for the good stuff) 🔑

Without login you get link previews and photos. With login you unlock the **real Reposts tab**, videos, and private profiles you follow:

```bash
# username + password (+ 2FA code if asked). Password is never logged.
insta-reposts login --username myuser --password '...' --verification-code 123456 \
  --session-file session.json --cookies-out cookies.txt

# or via env vars
INSTAGRAM_USERNAME=u INSTAGRAM_PASSWORD=p INSTAGRAM_2FA_CODE=123456 \
  insta-reposts login --session-file session.json

# then just reuse the session everywhere
insta-reposts fish someuser -o reposts.json --session-file session.json --max 200
insta-reposts fish privateuser -o r.json --session-file session.json --max 200
```

Other session flavors work on every command: `--cookies cookies.txt` (Netscape export, e.g. from `yt-dlp --cookies-from-browser chrome`), `--sessionid`, or `INSTAGRAM_SESSIONID`. Not sure your session is healthy? `insta-reposts check --session-file session.json` tells you before you waste time.

Private profiles need login *and* you must follow the account — otherwise it fails fast with a clear message instead of garbage output.

## How fishing works 🎣

The tool picks the best method automatically: first-party Instagram query when you're logged in, public fallback when you're not. You can force one with `--backend`:

| Backend | What it is | Needs |
|---|---|---|
| `graphql` ⭐ | Instagram's own Reposts-tab query | login |
| `repostpro` | Public viewer site, no account needed | nothing (has a guest quota — when it's used up, wait or log in) |
| `manual` | Paste links yourself (`links.txt`, JSON, CSV, or a saved page) | a browser |
| `instagram` | Profile page HTML | login for the real tab |
| `apify` | Paid API | `APIFY_TOKEN` |

When in doubt: log in and let it use `graphql`. It's the most reliable by far.

## Downloading 📥

```bash
insta-reposts download reposts.json -o ./out --downloader direct
insta-reposts download links.txt -o ./out --downloader yt-dlp --cookies cookies.txt
insta-reposts download links.txt -o ./out --downloader gallery-dl
```

Pick your downloader: `direct` (built in, simplest), `yt-dlp` (best for videos), or `gallery-dl`. Login cookies carry over to downloads, so private-account media resolves.

## Be nice out there 🤝

- Instagram allows roughly ~200 requests/hour from one home IP. Bulk jobs: add delays, don't hammer.
- Not affiliated with Instagram/Meta in any way.
