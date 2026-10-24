"""
Automatic LeetCode login script using Playwright.
Usage: python login_script.py <username> <password> [output_json_path]
"""

import asyncio
import json
import sys
import os

def get_chromium_executable():
    """Find chromium executable from playwright browsers."""
    import glob
    base = os.path.expanduser(r"~\.cache\ms-playwright")
    paths = glob.glob(os.path.join(base, "chromium-*", "chrome-win", "chrome.exe"))
    if paths:
        return paths[0]
    paths = glob.glob(os.path.join(base, "chromium-*", "chromium", "chrome-linux", "chrome"))
    if paths:
        return paths[0]
    return None


async def login_and_get_cookies(username: str, password: str, output_path: str = None):
    """Login to LeetCode and return session/csrf tokens."""
    from playwright.async_api import async_playwright

    cookies_result = {"session": None, "csrf": None, "success": False, "username": None}

    async with async_playwright() as p:
        # Try to use installed chromium
        try:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        except Exception as e:
            print(f"Browser launch failed: {e}")
            return cookies_result

        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            locale="en-US"
        )

        page = await context.new_page()

        try:
            print("Navigating to LeetCode login page...")
            await page.goto("https://leetcode.com/accounts/login/", timeout=30000)
            await asyncio.sleep(3)  # Wait for page to fully load

            # Fill in username
            print(f"Filling username: {username}")
            await page.fill('input[id="id_login"]', username, timeout=5000)
            await asyncio.sleep(0.5)

            # Fill in password
            print("Filling password...")
            await page.fill('input[id="id_password"]', password, timeout=5000)
            await asyncio.sleep(0.5)

            # Click login button
            print("Clicking login button...")
            await page.click('button[type="submit"]', timeout=5000)

            # Wait for navigation or response
            await asyncio.sleep(5)

            # Check if logged in
            current_url = page.url
            print(f"Current URL after login: {current_url}")

            if "leetcode.com" in current_url and "login" not in current_url.lower():
                print("Login appeared successful!")
            else:
                # Check for error messages
                try:
                    error = await page.text_content(".form-message-error, .error-message, [class*='error']")
                    if error:
                        print(f"Login error: {error}")
                except:
                    pass

            # Extract cookies
            print("Extracting cookies...")
            all_cookies = await context.cookies()

            for cookie in all_cookies:
                print(f"  Cookie: {cookie['name']} = {cookie['value'][:30]}..." if len(cookie['value']) > 30 else f"  Cookie: {cookie['name']} = {cookie['value']}")
                if cookie["name"] == "LEETCODE_SESSION":
                    cookies_result["session"] = cookie["value"]
                elif cookie["name"] == "csrftoken":
                    cookies_result["csrf"] = cookie["value"]

            # Also check if logged in via graphql
            if cookies_result["session"]:
                cookies_result["success"] = True
                # Try to get username
                try:
                    resp = await page.evaluate("""
                        async () => {
                            const r = await fetch('https://leetcode.com/graphql', {
                                method: 'POST',
                                headers: {'Content-Type': 'application/json'},
                                body: JSON.stringify({query: "{ me { username } }"})
                            });
                            return await r.json();
                        }
                    """)
                    if resp.get("data", {}).get("me", {}).get("username"):
                        cookies_result["username"] = resp["data"]["me"]["username"]
                except:
                    pass

                print(f"\n✅ LOGIN SUCCESS!")
                print(f"   LEETCODE_SESSION: {cookies_result['session'][:40]}...")
                print(f"   csrftoken: {cookies_result['csrf']}")

        except Exception as e:
            print(f"Login script error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            await browser.close()

    if output_path:
        with open(output_path, "w") as f:
            json.dump(cookies_result, f, indent=2)
        print(f"Cookies saved to {output_path}")

    return cookies_result


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python login_script.py <username> <password> [output_path]")
        sys.exit(1)

    username = sys.argv[1]
    password = sys.argv[2]
    output_path = sys.argv[3] if len(sys.argv) > 3 else None

    result = asyncio.run(login_and_get_cookies(username, password, output_path))

    if result["success"]:
        print(f"\n📋 COPY THESE VALUES:")
        print(f"LEETCODE_SESSION={result['session']}")
        print(f"CSRF_TOKEN={result['csrf']}")
        sys.exit(0)
    else:
        print("\n❌ Login failed. Please get cookies manually.")
        sys.exit(1)
