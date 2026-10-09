import re
import httpx
from typing import Dict, Any, List, Optional, Tuple

class MultiAISolver:
    # Fallback models for each provider
    OMNIROUTE_FALLBACKS = [
        "auto/best-coding",
        "auto/pro-coding",
        "auto/best-reasoning",
        "auto/coding:reliable",
        "agentrouter/claude-opus-4-8",
        "auto/best-fast",
        "auto/coding:fast"
    ]
    GROQ_FALLBACKS = [
        "llama-3.3-70b-versatile",
        "qwen/qwen3.8-27b",
        "openai/gpt-oss-120b",
        "llama-3.1-8b-instant"
    ]
    GEMINI_FALLBACKS = [
        "gemini-flash-latest",
        "gemini-2.5-flash",
        "gemini-1.5-flash",
        "gemini-2.0-flash-lite"
    ]
    OPENROUTER_FALLBACKS = [
        "nvidia/nemotron-3.5-lightning:free",
        "cohere/north-mini-code:free",
        "google/gemma-4-26b-a4b-it:free",
        "nvidia/nemotron-3-super-120b-a12b:free",
        "meta-llama/llama-3.3-70b-instruct:free"
    ]

    def __init__(
        self,
        omniroute_base_url: str = "",
        omniroute_api_key: str = "",
        omniroute_model: str = "",
        groq_api_key: str = "",
        gemini_api_key: str = "",
        openrouter_api_key: str = "",
        groq_model: str = "openai/gpt-oss-120b",
        gemini_model: str = "gemini-flash-latest",
        openrouter_model: str = "nvidia/nemotron-3.5-lightning:free",
        priority: List[str] = None
    ):
        self.omniroute_base_url = omniroute_base_url
        self.omniroute_api_key = omniroute_api_key
        self.omniroute_model = omniroute_model
        self.groq_api_key = groq_api_key
        self.gemini_api_key = gemini_api_key
        self.openrouter_api_key = openrouter_api_key
        self.groq_model = groq_model
        self.gemini_model = gemini_model
        self.openrouter_model = openrouter_model
        self.priority = priority or ["omniroute", "groq", "openrouter", "gemini"]

    def update_keys(
        self,
        groq_key: str = "",
        gemini_key: str = "",
        openrouter_key: str = "",
        omniroute_base_url: str = None,
        omniroute_key: str = None,
        omniroute_model: str = None
    ):
        if groq_key is not None: self.groq_api_key = groq_key
        if gemini_key is not None: self.gemini_api_key = gemini_key
        if openrouter_key is not None: self.openrouter_api_key = openrouter_key
        if omniroute_base_url is not None: self.omniroute_base_url = omniroute_base_url
        if omniroute_key is not None: self.omniroute_api_key = omniroute_key
        if omniroute_model is not None: self.omniroute_model = omniroute_model

    def _get_active_providers(self) -> List[str]:
        """Order providers prioritizing those with configured credentials."""
        configured = []
        unconfigured = []
        for p in self.priority:
            has_creds = False
            if p == "omniroute" and (self.omniroute_api_key or (self.omniroute_base_url and "localhost" not in self.omniroute_base_url)):
                has_creds = True
            elif p == "groq" and self.groq_api_key:
                has_creds = True
            elif p == "gemini" and self.gemini_api_key:
                has_creds = True
            elif p == "openrouter" and self.openrouter_api_key:
                has_creds = True

            if has_creds:
                configured.append(p)
            else:
                unconfigured.append(p)
        return configured + unconfigured

    async def solve_problem(
        self,
        problem_title: str = "",
        title: str = "",
        difficulty: str = "Medium",
        description: str = "",
        starter_code: str = "",
        language: str = "python3",
        examples: List[Any] = None,
        hints: List[str] = None
    ) -> Dict[str, Any]:
        t = problem_title or title or "Problem"
        prompt = self._build_solve_prompt(t, description, difficulty, language, starter_code, examples, hints)
        return await self._execute_with_failover(prompt, language)

    async def fix_code(
        self,
        problem_title: str = "",
        title: str = "",
        description: str = "",
        failed_code: str = "",
        error_message: str = "",
        language: str = "python3",
        starter_code: str = "",
        error_type: str = "Submission Failed"
    ) -> Dict[str, Any]:
        t = problem_title or title or "Problem"
        error_details = {"diagnostic": error_message}
        prompt = self._build_repair_prompt(t, description, language, starter_code, failed_code, error_type, error_details)
        return await self._execute_with_failover(prompt, language)

    async def _execute_with_failover(self, prompt: str, language: str) -> Dict[str, Any]:
        errors = []
        active_order = self._get_active_providers()

        for provider in active_order:
            try:
                if provider == "omniroute" and (self.omniroute_base_url or self.omniroute_api_key):
                    code, model_used = await self._call_omniroute(prompt)
                    if code:
                        return {
                            "success": True,
                            "code": self._clean_code(code, language),
                            "provider": "OmniRoute",
                            "model": model_used
                        }
                elif provider == "groq" and self.groq_api_key:
                    code, model_used = await self._call_groq(prompt)
                    if code:
                        return {
                            "success": True,
                            "code": self._clean_code(code, language),
                            "provider": "Groq",
                            "model": model_used
                        }
                elif provider == "gemini" and self.gemini_api_key:
                    code, model_used = await self._call_gemini(prompt)
                    if code:
                        return {
                            "success": True,
                            "code": self._clean_code(code, language),
                            "provider": "Gemini",
                            "model": model_used
                        }
                elif provider == "openrouter" and self.openrouter_api_key:
                    code, model_used = await self._call_openrouter(prompt)
                    if code:
                        return {
                            "success": True,
                            "code": self._clean_code(code, language),
                            "provider": "OpenRouter",
                            "model": model_used
                        }
            except Exception as e:
                errors.append(f"{provider}: {str(e)}")
                continue

        return {
            "success": False,
            "error": "All AI providers failed: " + " | ".join(errors) if errors else "No AI providers configured with valid API keys."
        }

    @staticmethod
    async def fetch_models_from_endpoint(base_url: str, api_key: str = "") -> Dict[str, Any]:
        """Dynamically extract all available model IDs from OmniRoute or any OpenAI-compatible API."""
        if not base_url or not base_url.strip():
            return {"success": False, "error": "Base URL cannot be empty.", "models": []}

        clean_base = base_url.strip().rstrip('/')
        endpoints = []
        if clean_base.endswith("/v1"):
            endpoints = [f"{clean_base}/models", f"{clean_base[:-3]}/models", f"{clean_base}/v1/models"]
        else:
            endpoints = [f"{clean_base}/v1/models", f"{clean_base}/models", f"{clean_base}/api/v1/models"]

        headers = {"Accept": "application/json"}
        if api_key and api_key.strip():
            headers["Authorization"] = f"Bearer {api_key.strip()}"

        last_error = ""
        tested_eps = []

        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            for ep in endpoints:
                tested_eps.append(ep)
                try:
                    resp = await client.get(ep, headers=headers)
                    if resp.status_code == 200:
                        data = resp.json()
                        models_list = []
                        if isinstance(data, dict):
                            raw_models = data.get("data") or data.get("models") or []
                            if isinstance(raw_models, list):
                                for item in raw_models:
                                    if isinstance(item, dict) and item.get("id"):
                                        models_list.append(str(item["id"]))
                                    elif isinstance(item, str):
                                        models_list.append(item)
                        elif isinstance(data, list):
                            for item in data:
                                if isinstance(item, dict) and item.get("id"):
                                    models_list.append(str(item["id"]))
                                elif isinstance(item, str):
                                    models_list.append(item)
                        if models_list:
                            sorted_models = sorted(list(set(models_list)))
                            return {
                                "success": True,
                                "models": sorted_models,
                                "count": len(sorted_models),
                                "endpoint_used": ep
                            }
                    elif resp.status_code == 401:
                        last_error = "HTTP 401 Unauthorized: Invalid or missing API Key."
                    elif resp.status_code == 403:
                        last_error = "HTTP 403 Forbidden: Access denied."
                    elif resp.status_code == 404:
                        last_error = f"HTTP 404 Not Found at {ep}."
                    else:
                        last_error = f"HTTP {resp.status_code} at {ep}"
                except httpx.ConnectError:
                    last_error = f"Connection Refused. Endpoint not reachable."
                except Exception as ex:
                    last_error = f"Error querying {ep}: {str(ex)}"

        return {
            "success": False,
            "error": last_error or f"No models found. Tested: {', '.join(tested_eps)}",
            "models": []
        }

    async def _call_omniroute(self, prompt: str) -> Tuple[Optional[str], str]:
        clean_base = self.omniroute_base_url.strip().rstrip('/')
        if clean_base.endswith("/v1"):
            url = f"{clean_base}/chat/completions"
        else:
            url = f"{clean_base}/v1/chat/completions"

        headers = {"Content-Type": "application/json"}
        if self.omniroute_api_key:
            headers["Authorization"] = f"Bearer {self.omniroute_api_key}"

        models_to_try = [self.omniroute_model] + self.OMNIROUTE_FALLBACKS
        seen = set()
        models = [m for m in models_to_try if m and not (m in seen or seen.add(m))]

        last_err = ""
        # 12s timeout so if local omniroute is offline, we fall back to cloud AI fast
        async with httpx.AsyncClient(timeout=12.0) as client:
            for model_name in models:
                try:
                    payload = {
                        "model": model_name,
                        "messages": [
                            {"role": "system", "content": "You are an elite competitive programmer. Output ONLY the complete, working code without any markdown, explanation or commentary."},
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.1,
                        "max_tokens": 3000
                    }
                    resp = await client.post(url, json=payload, headers=headers)
                    if resp.status_code == 200:
                        data = resp.json()
                        content = data["choices"][0]["message"]["content"]
                        self.omniroute_model = model_name
                        return content, model_name
                    last_err = f"HTTP {resp.status_code}: {resp.text[:160]}"
                except Exception as e:
                    last_err = str(e)
                    continue

        raise Exception(f"OmniRoute failed: {last_err}")

    async def _call_groq(self, prompt: str) -> Tuple[Optional[str], str]:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.groq_api_key}",
            "Content-Type": "application/json"
        }
        models_to_try = [self.groq_model] + self.GROQ_FALLBACKS
        seen = set()
        models = [m for m in models_to_try if m and not (m in seen or seen.add(m))]

        last_err = ""
        async with httpx.AsyncClient(timeout=25.0) as client:
            for model_name in models:
                try:
                    payload = {
                        "model": model_name,
                        "messages": [
                            {"role": "system", "content": "You are an elite competitive programmer. Output ONLY the complete, working code without any markdown, explanation or commentary."},
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.1,
                        "max_tokens": 3000
                    }
                    resp = await client.post(url, json=payload, headers=headers)
                    if resp.status_code == 200:
                        self.groq_model = model_name
                        return resp.json()["choices"][0]["message"]["content"], model_name
                    last_err = f"HTTP {resp.status_code}: {resp.text[:150]}"
                except Exception as e:
                    last_err = str(e)
                    continue

        raise Exception(f"Groq failed on all models: {last_err}")

    async def _call_gemini(self, prompt: str) -> Tuple[Optional[str], str]:
        key = self.gemini_api_key
        models_to_try = [self.gemini_model] + self.GEMINI_FALLBACKS
        seen = set()
        models = [m for m in models_to_try if m and not (m in seen or seen.add(m))]

        last_err = ""
        async with httpx.AsyncClient(timeout=25.0) as client:
            for model_name in models:
                try:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={key}"
                    payload = {
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 3000}
                    }
                    resp = await client.post(url, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        self.gemini_model = model_name
                        return data["candidates"][0]["content"]["parts"][0]["text"], model_name
                    last_err = f"HTTP {resp.status_code}: {resp.text[:150]}"
                except Exception as e:
                    last_err = str(e)
                    continue

        raise Exception(f"Gemini failed on all models: {last_err}")

    async def _call_openrouter(self, prompt: str) -> Tuple[Optional[str], str]:
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8000",
            "X-Title": "LeetCode Auto Solver"
        }
        models_to_try = [self.openrouter_model] + self.OPENROUTER_FALLBACKS
        seen = set()
        models = [m for m in models_to_try if m and not (m in seen or seen.add(m))]

        last_err = ""
        async with httpx.AsyncClient(timeout=30.0) as client:
            for model_name in models:
                try:
                    payload = {
                        "model": model_name,
                        "messages": [
                            {"role": "system", "content": "You are an expert competitive programmer. Output ONLY the complete code."},
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.1,
                        "max_tokens": 3000
                    }
                    resp = await client.post(url, json=payload, headers=headers)
                    if resp.status_code == 200:
                        self.openrouter_model = model_name
                        return resp.json()["choices"][0]["message"]["content"], model_name
                    last_err = f"HTTP {resp.status_code}: {resp.text[:150]}"
                except Exception as e:
                    last_err = str(e)
                    continue

        raise Exception(f"OpenRouter failed on all models: {last_err}")

    def _build_solve_prompt(self, title, description, difficulty, language, starter_code, examples=None, hints=None):
        parts = [
            f"Solve this LeetCode problem optimally.\n\n",
            f"Title: {title} [{difficulty}]\n\n",
            f"Description:\n{description}\n"
        ]
        if examples:
            parts.append(f"\nExamples:\n" + "\n".join(str(e) for e in examples[:3]) + "\n")
        if hints:
            parts.append(f"\nHints: {', '.join(hints[:2])}\n")
        parts.append(
            f"\nLanguage: {language}\n"
            f"Use this exact template:\n```\n{starter_code}\n```\n\n"
            f"Rules:\n"
            f"1. Complete working code that fits the template exactly.\n"
            f"2. Handle all edge cases.\n"
            f"3. NO print statements, NO test code, NO markdown, NO explanations.\n"
            f"Output ONLY the raw code."
        )
        return "".join(parts)

    def _build_repair_prompt(self, title, description, language, starter_code, failed_code, error_type, error_details):
        parts = [
            f"Fix this LeetCode solution for '{title}'. Error: {error_type}\n\n",
            f"Problem:\n{description}\n\n",
            f"Template:\n```\n{starter_code}\n```\n\n",
            f"Failed code:\n```\n{failed_code}\n```\n\n",
            f"Diagnosis:\n"
        ]
        diag = error_details.get("diagnostic", "")
        if diag:
            parts.append(f"{diag}\n")
        parts.append("\nOutput ONLY the corrected raw code.")
        return "".join(parts)

    def _clean_code(self, raw_code: str, language: str) -> str:
        text = raw_code.strip()
        match = re.search(r"^```[a-zA-Z0-9_+\-]*\n([\s\S]*?)\n```$", text)
        if match:
            return match.group(1).strip()
        blocks = re.findall(r"```(?:[a-zA-Z0-9_+\-]*\n)?([\s\S]*?)```", text)
        if blocks:
            return max(blocks, key=len).strip()
        return text
