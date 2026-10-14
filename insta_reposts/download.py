"""Download repost items: direct (photos anonymous OK) + yt-dlp/gallery-dl passthrough."""
import json
import pathlib
import shutil
import subprocess
import urllib.request
from . import utils


def fetch_post_media(shortcode, cookies=None):
    """Fetch single post page, return display/video/carousel URLs. Anonymous OK for photos."""
    code = shortcode.strip().split("/")[-2] if "/" in shortcode else shortcode
    # normalize full URL -> code
    m = utils.SHORTCODE_RE.search(shortcode)
    if m:
        code = m.group(1)
    for kind in ("reel", "p"):
        url = f"https://www.instagram.com/{kind}/{code}/"
        try:
            status, html, _ = utils.http_get(url, cookies=cookies)
            if status != 200:
                continue
            scripts = utils.extract_data_sjs(html)
            nodes = utils.extract_media_nodes(scripts)
            target = next((n for n in nodes if n.get("code") == code), nodes[0] if nodes else None)
            if not target:
                continue
            rec = utils.node_to_record(target)
            # carousel slides
            slides = []
            car = target.get("carousel_media") or target.get("carousel_media_count") or []
            if isinstance(car, list):
                for s in car:
                    if isinstance(s, dict):
                        vv = s.get("video_versions") or []
                        slides.append({"video_url": vv[0]["url"] if vv else "",
                                       "display_url": (s.get("image_versions2", {}).get("candidates", [{}])[0].get("url", "")
                                                       if isinstance(s.get("image_versions2"), dict) else s.get("display_uri", ""))})
            rec["slides"] = slides
            rec["page_url"] = url
            return {"ok": True, "record": rec}
        except Exception as e:
            last = str(e)
    return {"ok": False, "error": f"fetch failed for {code}: {last if 'last' in dir() else 'http'}"}


def download_url(url, dest):
    dest = pathlib.Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.instagram.com/"})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)
    return str(dest)


def download_items(items, outdir, cookies=None, downloader="direct", links_only=False):
    """Download each item. Returns manifest list."""
    outdir = pathlib.Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    manifest = []
    (outdir / "links.txt").write_text("\n".join(i.get("post_url", "") for i in items if i.get("post_url")) + "\n")
    if links_only:
        return manifest
    if downloader in ("ytdlp", "yt-dlp") and shutil.which("yt-dlp"):
        cmd = ["yt-dlp", "--no-warnings", "-a", str(outdir / "links.txt"),
               "-o", str(outdir / "%(uploader|creator)s_%(id)s.%(ext)s")]
        if cookies and isinstance(cookies, dict) and cookies.get("sessionid"):
            # write temp netscape file for yt-dlp
            cf = outdir / "cookies.txt"
            cf.write_text("# Netscape HTTP Cookie File\n.instagram.com\tTRUE\t/\tTRUE\t0\tsessionid\t" + cookies["sessionid"] + "\n")
            cmd[1:1] = ["--cookies", str(cf)]
        try:
            subprocess.run(cmd, check=False, timeout=600)
        except Exception as e:
            manifest.append({"warning": f"yt-dlp failed: {e}"})
        return manifest
    if downloader == "gallery-dl" and shutil.which("gallery-dl"):
        try:
            subprocess.run(["gallery-dl", "-a", str(outdir / "links.txt"), "-d", str(outdir)], check=False, timeout=600)
        except Exception as e:
            manifest.append({"warning": f"gallery-dl failed: {e}"})
        return manifest
    # direct backend
    for it in items:
        code = it.get("shortcode") or ""
        if not code and it.get("post_url"):
            m = utils.SHORTCODE_RE.search(it["post_url"])
            code = m.group(1) if m else ""
        if not code:
            continue
        meta = it.copy()
        if not meta.get("display_url") or not meta.get("video_url"):
            fetched = fetch_post_media(code, cookies=cookies)
            if fetched.get("ok"):
                for k, v in fetched["record"].items():
                    meta.setdefault(k, v)
        # save metadata sidecar
        (outdir / f"{code}.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
        # download best media: video > display, plus slides
        try:
            if meta.get("video_url"):
                ext = ".mp4"
                download_url(meta["video_url"], outdir / f"{code}{ext}")
                manifest.append({"shortcode": code, "file": f"{code}{ext}", "type": meta.get("post_type")})
            elif meta.get("display_url"):
                ext = ".jpg"
                download_url(meta["display_url"], outdir / f"{code}{ext}")
                manifest.append({"shortcode": code, "file": f"{code}{ext}", "type": meta.get("post_type")})
            for j, s in enumerate(meta.get("slides", [])):
                u = s.get("video_url") or s.get("display_url")
                if u:
                    ext = ".mp4" if s.get("video_url") else ".jpg"
                    download_url(u, outdir / f"{code}-{j+1}{ext}")
        except Exception as e:
            manifest.append({"shortcode": code, "error": str(e)})
    (outdir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest
