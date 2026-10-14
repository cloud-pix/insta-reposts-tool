"""Login/session handling, including private-profile support.

Supported logins (FOSS, Termux-compatible primary first):
1. instaloader (pure Python, works on Termux): login(user, passwd) + two_factor_login(code),
   session pickle + portable session.json + Netscape cookies.txt export.
2. aiograpi (opportunistic, desktop only; fails to build on Termux due to orjson/Rust):
   async login(user, pw, verification_code), dump_settings.
3. Manual: paste sessionid / export cookies.txt via browser or yt-dlp.

Priority for fish/download cookies:
--cookies file > --session-file > --sessionid > INSTAGRAM_SESSIONID env.
"""
import getpass
import json
import os
import pathlib
from . import utils


def cookies_from_sessionid(sessionid, ds_user_id=None, csrftoken=None):
    c = {"sessionid": sessionid}
    if ds_user_id:
        c["ds_user_id"] = ds_user_id
    if csrftoken:
        c["csrftoken"] = csrftoken
    return c


def resolve_cookies(cookies_path=None, sessionid=None):
    cookies = {}
    if cookies_path:
        cookies.update(utils.load_cookies(cookies_path))
    if sessionid:
        cookies["sessionid"] = sessionid
    env_sid = os.environ.get("INSTAGRAM_SESSIONID")
    if env_sid and "sessionid" not in cookies:
        cookies["sessionid"] = env_sid
    for k in ("INSTAGRAM_DS_USER_ID", "INSTAGRAM_CSRFTOKEN"):
        v = os.environ.get(k)
        if v:
            cookies[k.lower().replace("instagram_", "")] = v
    return cookies


def has_login(cookies):
    return bool(cookies and cookies.get("sessionid"))


def _write_portable_session(cookies, username, session_file):
    data = {"username": username, **{k: v for k, v in cookies.items()
                                     if k in ("sessionid", "ds_user_id", "csrftoken", "mid", "rur")}}
    pathlib.Path(session_file).write_text(json.dumps(data, indent=2))
    return session_file


def _write_netscape_cookies(cookies, path):
    lines = ["# Netscape HTTP Cookie File"]
    for k, v in cookies.items():
        lines.append(f".instagram.com\tTRUE\t/\tTRUE\t0\t{k}\t{v}")
    pathlib.Path(path).write_text("\n".join(lines) + "\n")
    return path


def _extract_instaloader_cookies(loader):
    try:
        jar = loader.context._session.cookies
        return {c.name: c.value for c in jar}
    except Exception:
        return {}


def login_with_password(username, password, verification_code=None, session_file="session.json",
                        cookies_out="cookies.txt", via="auto"):
    """Username + password + optional 2FA login. Returns {ok, via, session_file, cookies}.

    via: 'auto' (instaloader first, aiograpi fallback), 'instaloader', 'aiograpi'.
    2FA: pass verification_code directly, or it is prompted via getpass when required.
    Never logs the password. Session is saved to session_file (portable JSON).
    """
    if not username or not password:
        return {"ok": False, "error": "username and password required"}
    order = ["instaloader", "aiograpi"] if via == "auto" else [via]
    last_err = None
    for backend in order:
        if backend == "instaloader":
            try:
                import instaloader as _il
            except ImportError:
                last_err = "instaloader not installed (pip install instaloader)"
                continue
            try:
                loader = _il.Instaloader(quiet=True, download_pictures=False,
                                         download_videos=False, download_video_thumbnails=False,
                                         save_metadata=False, compress_json=False)
                try:
                    loader.login(username, password)
                except _il.exceptions.TwoFactorAuthRequiredException:
                    code = verification_code
                    if not code:
                        try:
                            code = getpass.getpass("2FA code (SMS/authenticator, 6 digits): ").strip()
                        except Exception:
                            code = ""
                    if not code:
                        return {"ok": False, "error": "2FA required but no verification code given", "via": "instaloader"}
                    loader.two_factor_login(code)
                # persist native session + portable copies
                native = session_file if session_file.endswith((".session", ".pickle")) else None
                try:
                    loader.save_session_to_file(native)
                except Exception:
                    pass
                cookies = _extract_instaloader_cookies(loader)
                if not cookies.get("sessionid"):
                    last_err = "instaloader login ok but no sessionid cookie found"
                    continue
                _write_portable_session(cookies, username, session_file)
                if cookies_out:
                    _write_netscape_cookies(cookies, cookies_out)
                return {"ok": True, "via": "instaloader", "session_file": session_file,
                        "cookies_file": cookies_out, "cookies": cookies, "username": username}
            except _il.exceptions.BadCredentialsException:
                return {"ok": False, "error": "bad credentials (wrong username/password)", "via": "instaloader"}
            except _il.exceptions.InvalidArgumentException as e:
                # e.g. bad 2FA code raises BadCredentialsException subclass; keep message
                return {"ok": False, "error": f"login failed: {e}", "via": "instaloader"}
            except _il.exceptions.LoginException as e:
                last_err = f"instaloader LoginException: {e}"
                continue
            except Exception as e:
                last_err = f"instaloader failed: {e}"
                continue
        elif backend == "aiograpi":
            try:
                import asyncio
                from aiograpi import Client
            except ImportError:
                last_err = "aiograpi not installed (pip install aiograpi; note: no Termux/aarch64 wheel due to orjson/Rust)"
                continue
            try:
                async def _go():
                    cl = Client()
                    await cl.login(username, password, verification_code=verification_code or "")
                    cl.dump_settings(session_file)
                    try:
                        jar = cl.cookie_jar
                        cookies = {c.key: c.value for c in jar} if hasattr(jar, "__iter__") else {}
                    except Exception:
                        cookies = {}
                    if not cookies.get("sessionid"):
                        # fall back to settings file parse
                        try:
                            settings = json.loads(pathlib.Path(session_file).read_text())
                            auth_data = settings.get("authorization_data") or {}
                            sid = auth_data.get("sessionid") or settings.get("sessionid")
                            if sid:
                                cookies["sessionid"] = sid
                        except Exception:
                            pass
                    return cookies
                cookies = asyncio.run(_go())
                if not cookies.get("sessionid"):
                    last_err = "aiograpi login ok but no sessionid extracted"
                    continue
                _write_portable_session(cookies, username, session_file)
                if cookies_out:
                    _write_netscape_cookies(cookies, cookies_out)
                return {"ok": True, "via": "aiograpi", "session_file": session_file,
                        "cookies_file": cookies_out, "cookies": cookies, "username": username}
            except Exception as e:
                msg = str(e)
                if "two_factor" in msg.lower() or "2fa" in msg.lower() or "verification" in msg.lower():
                    return {"ok": False, "error": f"2FA required/failed: {e}", "via": "aiograpi"}
                last_err = f"aiograpi failed: {e}"
                continue
    return {"ok": False, "error": last_err or "no login backend available (pip install instaloader)"}


def load_session_file(path):
    """Load cookies from our session.json, Netscape cookies.txt, or aiograpi dump_settings JSON."""
    p = pathlib.Path(path)
    if not p.exists():
        return {}
    # 1. try instaloader pickle session (binary) -> needs username; skip here, handled in resolve
    try:
        txt = p.read_text(errors="ignore").strip()
    except Exception:
        return {}
    if not txt:
        return {}
    if txt.startswith("{"):
        try:
            data = json.loads(txt)
            # our portable format or aiograpi dump
            if "sessionid" in data:
                return {k: data[k] for k in ("sessionid", "ds_user_id", "csrftoken", "mid", "rur") if k in data}
            auth_data = data.get("authorization_data") or {}
            if auth_data.get("sessionid"):
                return {"sessionid": auth_data["sessionid"]}
            cookies = data.get("cookies") or data.get("cookie_jar") or {}
            if isinstance(cookies, dict) and cookies.get("sessionid"):
                return cookies
        except Exception:
            pass
    return utils.load_cookies(path)


def resolve_cookies(cookies_path=None, sessionid=None, session_file=None):
    cookies = {}
    if session_file and pathlib.Path(session_file).exists():
        # instaloader pickle? try native load
        try:
            raw = pathlib.Path(session_file).read_bytes()[:4]
            if raw[:2] == b"\x80\x04" or b"pickle" in raw.lower() or session_file.endswith((".session", ".pickle")):
                import instaloader as _il
                # need username: stored alongside? try session.json sibling
                sib = pathlib.Path(str(session_file) + ".json")
                user = None
                if sib.exists():
                    try:
                        user = json.loads(sib.read_text()).get("username")
                    except Exception:
                        pass
                if user:
                    loader = _il.Instaloader(quiet=True)
                    loader.load_session_from_file(user, str(session_file))
                    cookies.update(_extract_instaloader_cookies(loader))
                else:
                    # cannot map pickle without username; fall through to normal parse (will be empty)
                    pass
            else:
                cookies.update(load_session_file(session_file))
        except Exception:
            cookies.update(load_session_file(session_file))
    if cookies_path:
        cookies.update(utils.load_cookies(cookies_path))
    if sessionid:
        cookies["sessionid"] = sessionid
    env_sid = os.environ.get("INSTAGRAM_SESSIONID")
    if env_sid and "sessionid" not in cookies:
        cookies["sessionid"] = env_sid
    return cookies


def login_interactive(username=None, session_file="session.json", password=None,
                      verification_code=None, cookies_out="cookies.txt", via="auto"):
    """Interactive login: username + password + 2FA code (prompted if missing)."""
    username = username or input("Instagram username: ").strip()
    if password is None:
        try:
            import os as _os
            password = _os.environ.get("INSTAGRAM_PASSWORD") or getpass.getpass("Instagram password: ")
        except Exception:
            password = ""
    if not password:
        # fall back to manual sessionid paste (previous behavior)
        print("No password given; falling back to manual sessionid.")
        sid = getpass.getpass("Paste sessionid value (or empty to abort): ").strip()
        if not sid:
            return {"ok": False, "error": "no password/sessionid provided"}
        pathlib.Path(session_file).write_text(json.dumps({"username": username, "sessionid": sid}))
        return {"ok": True, "session_file": session_file, "via": "manual-sessionid",
                "cookies": {"sessionid": sid}, "username": username}
    if verification_code is None:
        import os as _os
        verification_code = _os.environ.get("INSTAGRAM_2FA_CODE") or ""
    res = login_with_password(username, password, verification_code or None,
                              session_file, cookies_out, via)
    if not res.get("ok") and "2FA required but no verification code" in str(res.get("error")):
        try:
            code = getpass.getpass("2FA code (SMS/authenticator, 6 digits): ").strip()
        except Exception:
            code = ""
        if code:
            res = login_with_password(username, password, code, session_file, cookies_out, via)
    return res
