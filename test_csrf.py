"""Self-check for CSRF and session token handling. Run: python -I test_csrf.py"""
from leetcode_client import LeetCodeClient


class _FakeResp:
    def __init__(self, headers):
        self.headers = type("H", (), {
            "get_list": lambda self_inner, key: headers.get(key.lower(), [])
        })()


def test_token_cleaning_and_headers():
    # 1. Cleaning dirty tokens with prefixes, quotes, semicolons
    c = LeetCodeClient(
        session_token='LEETCODE_SESSION="my_session_123";',
        csrf_token='csrftoken="my_csrf_456";'
    )
    assert c.session_token == "my_session_123"
    assert c.csrf_token == "my_csrf_456"

    # 2. Header generation includes explicit x-csrftoken and Cookie header
    h = c._req_headers("https://leetcode.com/problems/two-sum/")
    assert h["x-csrftoken"] == "my_csrf_456"
    assert h["Cookie"] == "LEETCODE_SESSION=my_session_123; csrftoken=my_csrf_456"
    assert h["Origin"] == "https://leetcode.com"
    assert h["Referer"] == "https://leetcode.com/problems/two-sum/"

    # 3. Cookie harvesting updates tokens when server rotates them
    resp = _FakeResp({
        "set-cookie": [
            "csrftoken=NEW_ROTATED_CSRF_789; Path=/; Domain=.leetcode.com; Secure",
            'LEETCODE_SESSION="NEW_SESSION_999"; Path=/; Domain=.leetcode.com; Secure'
        ]
    })
    c._harvest_cookies(resp)
    assert c.csrf_token == "NEW_ROTATED_CSRF_789"
    assert c.session_token == "NEW_SESSION_999"

    h2 = c._req_headers()
    assert h2["x-csrftoken"] == "NEW_ROTATED_CSRF_789"
    assert "LEETCODE_SESSION=NEW_SESSION_999" in h2["Cookie"]

    # 4. Critical: server expires=1970 wipe attempt must NOT delete active session!
    wipe_resp = _FakeResp({
        "set-cookie": [
            'LEETCODE_SESSION=""; expires=Thu, 01-Jan-1970 00:00:00 GMT; Max-Age=0; path=/; domain=.leetcode.com'
        ]
    })
    c._harvest_cookies(wipe_resp)
    # Session must remain preserved!
    assert c.session_token == "NEW_SESSION_999"
    h3 = c._req_headers()
    assert "LEETCODE_SESSION=NEW_SESSION_999" in h3["Cookie"]

    print("ALL CSRF & Session verification tests passed successfully!")


if __name__ == "__main__":
    test_token_cleaning_and_headers()
