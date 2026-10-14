import json
import sys
import types
import unittest.mock as mock


def _install_fake_instaloader(two_fa=False, bad_creds=False, bad_2fa=False):
    """Install fake instaloader module with login + 2FA behavior. Returns module."""
    mod = types.ModuleType("instaloader")
    exc = types.ModuleType("instaloader.exceptions")

    class LoginException(Exception):
        pass

    class BadCredentialsException(LoginException):
        pass

    class TwoFactorAuthRequiredException(LoginException):
        pass

    class InvalidArgumentException(LoginException):
        pass

    exc.LoginException = LoginException
    exc.BadCredentialsException = BadCredentialsException
    exc.TwoFactorAuthRequiredException = TwoFactorAuthRequiredException
    exc.InvalidArgumentException = InvalidArgumentException

    class FakeJar:
        def __init__(self, cookies):
            self._c = cookies

        def __iter__(self):
            from http.cookiejar import Cookie
            out = []
            for k, v in self._c.items():
                c = Cookie(0, k, v, None, False, ".instagram.com", True, False,
                           "/", True, False, 0, False, None, None, None)
                out.append(c)
            return iter(out)

    class FakeSession:
        def __init__(self, cookies):
            self.cookies = FakeJar(cookies)

    class FakeContext:
        def __init__(self, cookies):
            self._session = FakeSession(cookies)

    class FakeLoader:
        def __init__(self, *a, **k):
            self.context = FakeContext({"sessionid": "SID123", "ds_user_id": "9", "csrftoken": "CSRF"})
            self.saved_to = None

        def login(self, user, pw):
            if bad_creds:
                raise BadCredentialsException("wrong")
            if two_fa and not getattr(self, "_did_2fa", False):
                raise TwoFactorAuthRequiredException("2fa needed")

        def two_factor_login(self, code):
            if bad_2fa or code != "123456":
                raise BadCredentialsException("bad 2fa")
            self._did_2fa = True

        def save_session_to_file(self, fn=None):
            self.saved_to = fn or "default"

    mod.Instaloader = FakeLoader
    mod.exceptions = exc
    sys.modules["instaloader"] = mod
    sys.modules["instaloader.exceptions"] = exc
    return mod


def test_login_simple_no_2fa(tmp_path):
    from insta_reposts import auth
    _install_fake_instaloader(two_fa=False)
    sf = str(tmp_path / "session.json")
    cf = str(tmp_path / "cookies.txt")
    res = auth.login_with_password("u", "p", session_file=sf, cookies_out=cf, via="instaloader")
    assert res["ok"] and res["via"] == "instaloader"
    assert res["cookies"]["sessionid"] == "SID123"
    data = json.loads(open(sf).read())
    assert data["sessionid"] == "SID123"
    assert "sessionid\tSID123" in open(cf).read()


def test_login_2fa_ok(tmp_path):
    from insta_reposts import auth
    _install_fake_instaloader(two_fa=True)
    res = auth.login_with_password("u", "p", verification_code="123456",
                                   session_file=str(tmp_path / "s.json"),
                                   cookies_out=str(tmp_path / "c.txt"), via="instaloader")
    assert res["ok"]


def test_login_2fa_missing_code():
    from insta_reposts import auth
    _install_fake_instaloader(two_fa=True)
    with mock.patch("getpass.getpass", return_value=""):
        res = auth.login_with_password("u", "p", verification_code=None,
                                       session_file="x.json", cookies_out=None, via="instaloader")
    assert not res["ok"] and "2FA" in res["error"]


def test_login_bad_password():
    from insta_reposts import auth
    _install_fake_instaloader(bad_creds=True)
    res = auth.login_with_password("u", "wrong", session_file="x.json", cookies_out=None, via="instaloader")
    assert not res["ok"] and "bad credentials" in res["error"].lower()


def test_session_file_roundtrip(tmp_path):
    from insta_reposts import auth
    sf = tmp_path / "session.json"
    sf.write_text(json.dumps({"username": "u", "sessionid": "ABC"}))
    c = auth.resolve_cookies(session_file=str(sf))
    assert c["sessionid"] == "ABC"


def test_cli_login_args():
    from insta_reposts.cli import build
    p = build()
    a = p.parse_args(["login", "--username", "u", "--password", "p",
                      "--verification-code", "123456", "--session-file", "s.json"])
    assert a.cmd == "login" and a.verification_code == "123456"
    b = p.parse_args(["fish", "someuser", "--session-file", "s.json"])
    assert b.session_file == "s.json"
