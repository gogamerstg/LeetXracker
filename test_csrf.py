"""Self-check for CSRF rotation reading. Run: python -I test_csrf.py"""
from leetcode_client import LeetCodeClient


class _FakeCookie:
    def __init__(self, name, value):
        self.name = name
        self.value = value


class _FakeClient:
    def __init__(self, cookies):
        self.cookies = type("C", (), {"jar": cookies})()


def test_current_csrf():
    c = LeetCodeClient("sess", "SEED")
    # No live client yet -> falls back to seed token.
    assert c._current_csrf() == "SEED"

    # Live jar wins over seed.
    c._client = _FakeClient([_FakeCookie("x", "1"), _FakeCookie("csrftoken", "ROT1")])
    assert c._current_csrf() == "ROT1"

    # Rotation: duplicate csrftoken names, freshest (last) wins, no CookieConflict.
    c._client = _FakeClient([_FakeCookie("csrftoken", "A"), _FakeCookie("csrftoken", "B")])
    assert c._current_csrf() == "B"

    # Header syncs to live token and carries NO manual Cookie (jar handles it).
    h = c._req_headers()
    assert h["x-csrftoken"] == "B"
    assert "Cookie" not in h
    print("csrf rotation ok")


if __name__ == "__main__":
    test_current_csrf()
