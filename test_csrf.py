"""Self-check for CSRF and session token handling. Run: python -I test_csrf.py"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from leetcode_client import LeetCodeClient

def test_token_cleaning_and_headers():
    # 1. Cleaning dirty tokens with prefixes, quotes, semicolons
    c = LeetCodeClient(
        session_token='LEETCODE_SESSION="my_session_123";',
        csrf_token='csrftoken="my_csrf_456";'
    )
    assert c.session_token == "my_session_123"
    assert c.csrf_token == "my_csrf_456"

    # 2. Header generation includes explicit x-csrftoken and Cookie header
    h = c._build_headers("https://leetcode.com/problems/two-sum/", json_ct=True)
    assert h["x-csrftoken"] == "my_csrf_456"
    assert h["Cookie"] == "LEETCODE_SESSION=my_session_123; csrftoken=my_csrf_456"
    assert h["Origin"] == "https://leetcode.com"
    assert h["Referer"] == "https://leetcode.com/problems/two-sum/"
    assert h["Content-Type"] == "application/json"

    # 3. Update credentials cleanly updates headers
    c.update_credentials("new_session_999", "new_csrf_888")
    assert c.session_token == "new_session_999"
    assert c.csrf_token == "new_csrf_888"
    h2 = c._build_headers()
    assert h2["x-csrftoken"] == "new_csrf_888"
    assert h2["Cookie"] == "LEETCODE_SESSION=new_session_999; csrftoken=new_csrf_888"

    print("ALL CSRF & Session verification tests passed successfully!")

if __name__ == "__main__":
    test_token_cleaning_and_headers()
