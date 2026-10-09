import asyncio
import re
import html
import httpx
from typing import Dict, Any, List, Optional, Tuple

class LeetCodeClient:
    BASE_URL = "https://leetcode.com"
    GRAPHQL_URL = "https://leetcode.com/graphql"

    def __init__(self, session_token: str = "", csrf_token: str = ""):
        self.session_token = session_token
        self.csrf_token = csrf_token
        self.headers = self._build_headers()

    def update_credentials(self, session_token: str, csrf_token: str):
        self.session_token = session_token
        self.csrf_token = csrf_token
        self.headers = self._build_headers()

    def _build_headers(self) -> Dict[str, str]:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://leetcode.com",
            "Referer": "https://leetcode.com/problemset/all/",
            "Connection": "keep-alive"
        }
        if self.csrf_token:
            headers["x-csrftoken"] = self.csrf_token

        cookie_parts = []
        if self.session_token:
            cookie_parts.append(f"LEETCODE_SESSION={self.session_token}")
        if self.csrf_token:
            cookie_parts.append(f"csrftoken={self.csrf_token}")

        if cookie_parts:
            headers["Cookie"] = "; ".join(cookie_parts)
        return headers

    async def test_connection(self) -> Dict[str, Any]:
        """Verify if current session & csrf credentials are valid."""
        query = """
        query globalData {
            userStatus {
                isSignedIn
                username
                realName
                avatar
                userSlug
            }
        }
        """
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.post(
                    self.GRAPHQL_URL,
                    json={"query": query},
                    headers=self.headers
                )
                if resp.status_code == 200:
                    data = resp.json().get("data", {}).get("userStatus", {})
                    is_signed_in = data.get("isSignedIn", False)
                    return {
                        "success": is_signed_in,
                        "username": data.get("username", "Anonymous"),
                        "isSignedIn": is_signed_in,
                        "raw": data
                    }
                return {"success": False, "error": f"HTTP {resp.status_code}"}
            except Exception as e:
                return {"success": False, "error": str(e)}

    async def get_user_stats(self, username: str) -> Dict[str, Any]:
        """Fetch user solved statistics."""
        query = """
        query userProblemsSolved($username: String!) {
            allQuestionsCount {
                difficulty
                count
            }
            matchedUser(username: $username) {
                submitStatsGlobal {
                    acSubmissionNum {
                        difficulty
                        count
                        submissions
                    }
                }
            }
        }
        """
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.post(
                    self.GRAPHQL_URL,
                    json={"query": query, "variables": {"username": username}},
                    headers=self.headers
                )
                if resp.status_code == 200:
                    return resp.json().get("data", {})
            except Exception as e:
                print(f"[LeetCode] get_user_stats error: {e}")
        return {}

    async def get_problem_list(
        self,
        category: str = "",
        limit: int = 50,
        skip: int = 0,
        difficulty: str = "ALL",
        status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Fetch list of problems based on filter criteria."""
        query = """
        query problemsetQuestionList($categorySlug: String, $limit: Int, $skip: Int, $filters: QuestionListFilterInput) {
            problemsetQuestionList: questionList(
                categorySlug: $categorySlug
                limit: $limit
                skip: $skip
                filters: $filters
            ) {
                total: totalNum
                questions: data {
                    frontendQuestionId: questionFrontendId
                    title
                    titleSlug
                    difficulty
                    paidOnly: isPaidOnly
                    status
                    topicTags {
                        name
                        slug
                    }
                }
            }
        }
        """
        filters: Dict[str, Any] = {}
        if difficulty in ["EASY", "MEDIUM", "HARD"]:
            filters["difficulty"] = difficulty
        if status in ["NOT_STARTED", "TRIED", "AC"]:
            filters["status"] = status

        variables = {
            "categorySlug": category,
            "skip": skip,
            "limit": limit,
            "filters": filters
        }

        async with httpx.AsyncClient(timeout=20.0) as client:
            try:
                resp = await client.post(
                    self.GRAPHQL_URL,
                    json={"query": query, "variables": variables},
                    headers=self.headers
                )
                if resp.status_code == 200:
                    data = resp.json().get("data", {}).get("problemsetQuestionList", {})
                    return data.get("questions", [])
            except Exception as e:
                print(f"[LeetCode] get_problem_list error: {e}")
        return []

    async def fetch_problem_list(
        self,
        category: str = "",
        limit: int = 50,
        skip: int = 0,
        difficulty: str = "ALL",
        status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        return await self.get_problem_list(category=category, limit=limit, skip=skip, difficulty=difficulty, status=status)

    async def get_problem_details(self, title_slug: str) -> Optional[Dict[str, Any]]:
        """Fetch question description, code snippets, testcases, and questionId."""
        query = """
        query questionData($titleSlug: String!) {
            question(titleSlug: $titleSlug) {
                questionId
                questionFrontendId
                title
                titleSlug
                content
                isPaidOnly
                difficulty
                exampleTestcaseList
                sampleTestCase
                codeSnippets {
                    lang
                    langSlug
                    code
                }
                hints
            }
        }
        """
        async with httpx.AsyncClient(timeout=20.0) as client:
            try:
                resp = await client.post(
                    self.GRAPHQL_URL,
                    json={"query": query, "variables": {"titleSlug": title_slug}},
                    headers=self.headers
                )
                if resp.status_code == 200:
                    data = resp.json().get("data", {}).get("question")
                    if data and data.get("content"):
                        # Clean HTML content to readable plain text
                        raw_html = data["content"]
                        clean_text = self._clean_html(raw_html)
                        data["clean_description"] = clean_text
                    return data
            except Exception as e:
                print(f"[LeetCode] get_problem_details error for {title_slug}: {e}")
        return None

    def _clean_html(self, raw_html: str) -> str:
        """Strip HTML tags and unescape entities for LLM prompt readability."""
        text = re.sub(r'<[^>]+>', ' ', raw_html)
        text = html.unescape(text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    async def submit_code(
        self,
        title_slug: str,
        question_id: str,
        lang_slug: str,
        code: str
    ) -> Dict[str, Any]:
        """Submit code solution to LeetCode."""
        submit_url = f"{self.BASE_URL}/problems/{title_slug}/submit/"
        headers = self.headers.copy()
        headers["Referer"] = f"{self.BASE_URL}/problems/{title_slug}/"
        headers["Content-Type"] = "application/json"

        payload = {
            "lang": lang_slug,
            "question_id": question_id,
            "typed_code": code
        }

        async with httpx.AsyncClient(timeout=25.0) as client:
            try:
                resp = await client.post(
                    submit_url,
                    json=payload,
                    headers=headers
                )
                if resp.status_code == 200:
                    return resp.json()
                elif resp.status_code == 429:
                    return {"error": "Rate limit exceeded (HTTP 429)", "rate_limited": True}
                elif resp.status_code == 403:
                    return {"error": "Authentication/CSRF token expired or invalid (HTTP 403)", "auth_error": True}
                else:
                    return {"error": f"Submit failed: HTTP {resp.status_code} - {resp.text}"}
            except Exception as e:
                return {"error": f"Network exception: {str(e)}"}

    async def check_submission(self, submission_id: int, max_retries: int = 12) -> Dict[str, Any]:
        """Poll the submission result until evaluated or timeout."""
        check_url = f"{self.BASE_URL}/submissions/detail/{submission_id}/check/"

        async with httpx.AsyncClient(timeout=15.0) as client:
            for _ in range(max_retries):
                try:
                    resp = await client.get(check_url, headers=self.headers)
                    if resp.status_code == 200:
                        data = resp.json()
                        state = data.get("state")
                        if state == "SUCCESS":
                            return {
                                "success": True,
                                "status_msg": data.get("status_msg"), # "Accepted", "Wrong Answer", etc.
                                "status_code": data.get("status_code"),
                                "runtime": data.get("status_runtime"),
                                "memory": data.get("status_memory"),
                                "runtime_percentile": data.get("runtime_percentile"),
                                "memory_percentile": data.get("memory_percentile"),
                                "total_correct": data.get("total_correct"),
                                "total_testcases": data.get("total_testcases"),
                                "last_testcase": data.get("last_testcase"),
                                "expected_output": data.get("expected_output"),
                                "code_output": data.get("code_output"),
                                "compile_error": data.get("full_compile_error"),
                                "runtime_error": data.get("full_runtime_error"),
                                "raw": data
                            }
                    await asyncio.sleep(1.5)
                except Exception as e:
                    print(f"[LeetCode] check_submission polling error: {e}")
                    await asyncio.sleep(1.5)

        return {"success": False, "status_msg": "Timeout waiting for judge result"}
