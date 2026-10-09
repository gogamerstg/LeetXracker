import asyncio
import time
import random
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from config import config, BASE_DIR, get_user_history_path, get_user_settings_path
from leetcode_client import LeetCodeClient
from ai_solver import MultiAISolver
from firebase_sync import firebase_sync

HISTORY_FILE = BASE_DIR / "history.json"

class BotRunner:
    def __init__(self):
        self.active_user_email: str = "surajdas@surajdas.com"
        self.lc_client = LeetCodeClient(
            session_token=config.get("leetcode_session", ""),
            csrf_token=config.get("csrf_token", "")
        )
        self.ai_solver = MultiAISolver(
            omniroute_base_url=config.get("omniroute_base_url", "http://localhost:20128/v1"),
            omniroute_api_key=config.get("omniroute_api_key", ""),
            omniroute_model=config.get("omniroute_model", ""),
            groq_api_key=config.get("groq_api_key", ""),
            gemini_api_key=config.get("gemini_api_key", ""),
            openrouter_api_key=config.get("openrouter_api_key", ""),
            groq_model=config.get("groq_model", "openai/gpt-oss-120b"),
            gemini_model=config.get("gemini_model", "gemini-flash-latest"),
            openrouter_model=config.get("openrouter_model", "nvidia/nemotron-3.5-lightning:free"),
            priority=config.get("ai_provider_priority", ["omniroute", "groq", "openrouter", "gemini"])
        )

        self.status = "IDLE"  # IDLE, RUNNING, PAUSED, STOPPED, ERROR
        self.current_task: Optional[asyncio.Task] = None
        self.current_problem: Optional[Dict[str, Any]] = None

        self.solved_count = 0
        self.failed_count = 0
        self.total_processed = 0
        self.start_time: Optional[float] = None

        self.logs: List[Dict[str, Any]] = []
        self.history: List[Dict[str, Any]] = []
        self.max_logs = 200

        self.load_history()

    def get_user_history(self, email: str) -> List[Dict[str, Any]]:
        """Retrieve history specific to a user email."""
        u_path = get_user_history_path(email)
        if u_path.exists():
            try:
                with open(u_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
            except Exception as e:
                print(f"[BotRunner] Error reading user history for {email}: {e}")
        elif email == "surajdas@surajdas.com" and HISTORY_FILE.exists():
            try:
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
            except Exception as e:
                print(f"[BotRunner] Error reading root history: {e}")
        return []

    def load_history(self, email: Optional[str] = None):
        """Load persistent history records."""
        target_email = email or self.active_user_email
        self.history = self.get_user_history(target_email)
        self.solved_count = sum(1 for h in self.history if h.get("status") == "Accepted")
        self.failed_count = sum(1 for h in self.history if h.get("status") != "Accepted")
        self.total_processed = len(self.history)

    def save_history(self):
        """Save history records to per-user file and sync to cloud."""
        target_email = self.active_user_email
        u_path = get_user_history_path(target_email)
        try:
            with open(u_path, "w", encoding="utf-8") as f:
                json.dump(self.history, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[BotRunner] Error saving user history for {target_email}: {e}")

        if target_email == "surajdas@surajdas.com":
            try:
                with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                    json.dump(self.history, f, indent=2, ensure_ascii=False)
            except Exception as e:
                print(f"[BotRunner] Error saving global history: {e}")

        if firebase_sync.enabled:
            safe_email = target_email.replace(".", "_")
            asyncio.create_task(firebase_sync.save_data(f"history/{safe_email}", self.history[-100:]))

    def add_log(self, message: str, level: str = "info", extra: Dict[str, Any] = None):
        log_entry = {
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "message": message,
            "level": level,  # info, success, warning, error
            "extra": extra or {}
        }
        self.logs.append(log_entry)
        if len(self.logs) > self.max_logs:
            self.logs.pop(0)
        try:
            print(f"[{log_entry['timestamp']}][{level.upper()}] {message}")
        except UnicodeEncodeError:
            print(f"[{log_entry['timestamp']}][{level.upper()}] {message.encode('ascii', 'replace').decode('ascii')}")

    def sync_config(self, email: Optional[str] = None):
        """Update active client & AI instances with latest configuration."""
        target_email = email or self.active_user_email
        user_cfg = config.load_user_settings(target_email)

        self.lc_client.update_credentials(
            session_token=user_cfg.get("leetcode_session", ""),
            csrf_token=user_cfg.get("csrf_token", "")
        )
        self.ai_solver.update_keys(
            groq_key=user_cfg.get("groq_api_key", ""),
            gemini_key=user_cfg.get("gemini_api_key", ""),
            openrouter_key=user_cfg.get("openrouter_api_key", ""),
            omniroute_base_url=user_cfg.get("omniroute_base_url", "http://localhost:20128/v1"),
            omniroute_key=user_cfg.get("omniroute_api_key", ""),
            omniroute_model=user_cfg.get("omniroute_model", "")
        )
        self.ai_solver.priority = user_cfg.get("ai_provider_priority", ["omniroute", "groq", "openrouter", "gemini"])
        self.ai_solver.groq_model = user_cfg.get("groq_model", "openai/gpt-oss-120b")
        self.ai_solver.gemini_model = user_cfg.get("gemini_model", "gemini-flash-latest")
        self.ai_solver.openrouter_model = user_cfg.get("openrouter_model", "nvidia/nemotron-3.5-lightning:free")

    def get_state(self, email: Optional[str] = None) -> Dict[str, Any]:
        target_email = email or self.active_user_email
        user_cfg = config.load_user_settings(target_email)
        user_hist = self.get_user_history(target_email) if target_email != self.active_user_email else self.history

        uptime_sec = int(time.time() - self.start_time) if (self.start_time and self.status == "RUNNING") else 0
        return {
            "status": self.status,
            "active_user": self.active_user_email,
            "solved_count": self.solved_count if target_email == self.active_user_email else sum(1 for h in user_hist if h.get("status") == "Accepted"),
            "failed_count": self.failed_count if target_email == self.active_user_email else sum(1 for h in user_hist if h.get("status") != "Accepted"),
            "total_processed": len(user_hist),
            "target_count": user_cfg.get("target_count", 50),
            "delay_seconds": user_cfg.get("delay_seconds", 1),
            "difficulty": user_cfg.get("difficulty", "ALL"),
            "language": user_cfg.get("language", "python3"),
            "skip_paid_only": user_cfg.get("skip_paid_only", True),
            "skip_already_solved": user_cfg.get("skip_already_solved", True),
            "uptime_seconds": uptime_sec,
            "current_problem": self.current_problem,
            "recent_logs": self.logs[-30:],
            "history": user_hist[-25:],
            "history_total_count": len(user_hist)
        }

    async def start(self, user_email: Optional[str] = None):
        if self.status == "RUNNING":
            return {"status": "already_running"}

        if user_email:
            self.active_user_email = user_email
            self.load_history(user_email)

        self.sync_config(self.active_user_email)

        # Verify credentials first
        conn_check = await self.lc_client.test_connection()
        if not conn_check.get("success"):
            self.add_log("LeetCode Session Invalid or not logged in! Check Settings.", "error")
            self.status = "ERROR"
            return {"status": "auth_failed", "error": conn_check.get("error", "Invalid Session")}

        username = conn_check.get("username", "User")
        self.add_log(f"Connected to LeetCode as: {username} ({self.active_user_email})", "success")

        self.status = "RUNNING"
        self.start_time = time.time()
        self.current_task = asyncio.create_task(self._main_loop())
        return {"status": "started", "username": username}

    async def pause(self):
        if self.status == "RUNNING":
            self.status = "PAUSED"
            self.add_log("Bot paused by user.", "warning")
        return {"status": self.status}

    async def resume(self):
        if self.status == "PAUSED":
            self.status = "RUNNING"
            self.add_log("Bot resumed.", "info")
            if not self.current_task or self.current_task.done():
                self.current_task = asyncio.create_task(self._main_loop())
        return {"status": self.status}

    async def stop(self):
        self.status = "STOPPED"
        if self.current_task and not self.current_task.done():
            self.current_task.cancel()
        self.current_problem = None
        self.add_log("Bot stopped.", "warning")
        return {"status": "stopped"}

    async def _main_loop(self):
        self.add_log(f"Automation engine initialized for {self.active_user_email}.", "info")
        user_cfg = config.load_user_settings(self.active_user_email)
        target_count = user_cfg.get("target_count", 50)
        difficulty = user_cfg.get("difficulty", "ALL")
        language = user_cfg.get("language", "python3")
        max_retries = user_cfg.get("max_retries_per_problem", 2)
        skip_paid = user_cfg.get("skip_paid_only", True)
        skip_solved = user_cfg.get("skip_already_solved", True)

        skip_offset = 0

        while self.status == "RUNNING":
            if target_count > 0 and self.solved_count >= target_count:
                self.add_log(f"🎉 Target reached! Solved {self.solved_count} problems.", "success")
                self.status = "IDLE"
                break

            try:
                self.add_log(f"Fetching problem batch (offset: {skip_offset})...", "info")
                problems = await self.lc_client.get_problem_list(
                    category="",
                    difficulty=difficulty,
                    limit=25,
                    skip=skip_offset
                )

                if not problems:
                    self.add_log("No more problems found matching current filters.", "warning")
                    self.status = "IDLE"
                    break

                if user_cfg.get("randomize_order", False):
                    random.shuffle(problems)

                processed_any = False

                for prob in problems:
                    if self.status != "RUNNING":
                        break

                    if target_count > 0 and self.solved_count >= target_count:
                        break

                    frontend_id = prob.get("frontendQuestionId") or prob.get("questionFrontendId")
                    title = prob.get("title")
                    title_slug = prob.get("titleSlug")
                    is_paid = prob.get("paidOnly", False)
                    status_flag = prob.get("status")  # "ac", "notac", None

                    # Check skip rules
                    if skip_paid and is_paid:
                        continue

                    if skip_solved and status_flag == "ac":
                        continue

                    # Also check our local history for already accepted
                    if skip_solved and any(h.get("id") == frontend_id and h.get("status") == "Accepted" for h in self.history):
                        continue

                    processed_any = True
                    self.current_problem = {
                        "id": frontend_id,
                        "title": title,
                        "slug": title_slug,
                        "step": "fetching_details"
                    }
                    self.add_log(f"Processing #{frontend_id}: {title}...", "info")

                    # Fetch problem full details
                    details = await self.lc_client.get_problem_details(title_slug)
                    if not details or not details.get("content"):
                        self.add_log(f"Failed to fetch details for #{frontend_id}. Skipping.", "warning")
                        continue

                    question_id = details.get("questionId")
                    clean_desc = details.get("clean_description", "")
                    snippets = details.get("codeSnippets", [])
                    q_diff = details.get("difficulty", "Medium")

                    # Determine code snippet and language
                    chosen_lang, starter_code = self._get_snippet_and_lang(language, snippets)
                    if not starter_code:
                        self.add_log(f"Starter code not found for language '{language}'. Skipping.", "warning")
                        continue

                    # Solve problem using Multi-AI Failover
                    self.current_problem["step"] = "ai_solving"
                    self.add_log(f"Generating solution for #{frontend_id} ({chosen_lang}) using Multi-AI...", "info")

                    solve_res = await self.ai_solver.solve_problem(
                        problem_title=f"#{frontend_id} - {title}",
                        difficulty=q_diff,
                        description=clean_desc,
                        starter_code=starter_code,
                        language=chosen_lang
                    )

                    if not solve_res.get("success"):
                        self.add_log(f"AI failed to generate solution for #{frontend_id}: {solve_res.get('error')}", "error")
                        self.failed_count += 1
                        continue

                    code = solve_res.get("code")
                    provider_used = solve_res.get("provider", "Unknown")
                    model_used = solve_res.get("model", "")
                    self.add_log(f"Generated solution via [{provider_used} - {model_used}]. Submitting to LeetCode...", "info")

                    # Submit solution
                    self.current_problem["step"] = "submitting"
                    submission_result = await self._submit_and_evaluate(
                        title_slug=title_slug,
                        question_id=question_id,
                        lang_slug=chosen_lang,
                        code=code,
                        title=title,
                        clean_desc=clean_desc,
                        starter_code=starter_code,
                        max_retries=max_retries
                    )

                    self.total_processed += 1
                    status_msg = submission_result.get("status_msg", "Error")
                    history_entry = {
                        "id": frontend_id,
                        "title": title,
                        "slug": title_slug,
                        "difficulty": q_diff,
                        "language": chosen_lang,
                        "status": status_msg,
                        "runtime": submission_result.get("runtime", "-"),
                        "runtime_percentile": submission_result.get("runtime_percentile", "-"),
                        "memory": submission_result.get("memory", "-"),
                        "memory_percentile": submission_result.get("memory_percentile", "-"),
                        "provider": provider_used,
                        "code": submission_result.get("code", code),
                        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }
                    self.history.append(history_entry)
                    self.save_history()

                    if status_msg == "Accepted":
                        self.solved_count += 1
                        self.add_log(
                            f"Accepted #{frontend_id} ({title})! Runtime: {submission_result.get('runtime', '')} ({submission_result.get('runtime_percentile', '')}%), Memory: {submission_result.get('memory', '')}",
                            "success"
                        )
                    else:
                        self.failed_count += 1
                        self.add_log(
                            f"Problem #{frontend_id} not accepted: {status_msg}",
                            "warning"
                        )

                    # Cooldown delay between questions
                    self.current_problem = None
                    if self.status == "RUNNING":
                        cfg_now = config.load_user_settings(self.active_user_email)
                        current_delay = cfg_now.get("delay_seconds", 1)
                        if current_delay > 0:
                            self.add_log(f"Waiting {current_delay}s cooldown...", "info")
                            await asyncio.sleep(current_delay)

                if not processed_any:
                    skip_offset += 25

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.add_log(f"Unexpected error in loop: {e}", "error")
                await asyncio.sleep(5)

        self.current_problem = None
        if self.status == "RUNNING":
            self.status = "IDLE"

    async def _submit_and_evaluate(
        self,
        title_slug: str,
        question_id: str,
        lang_slug: str,
        code: str,
        title: str,
        clean_desc: str,
        starter_code: str,
        max_retries: int
    ) -> Dict[str, Any]:
        current_code = code
        attempts = 0

        while attempts <= max_retries:
            sub_resp = await self.lc_client.submit_code(
                title_slug=title_slug,
                question_id=question_id,
                lang_slug=lang_slug,
                code=current_code
            )

            if sub_resp.get("error"):
                return {"status_msg": sub_resp["error"], "success": False}

            submission_id = sub_resp.get("submission_id")
            if not submission_id:
                return {"status_msg": "No submission_id returned", "success": False}

            # Poll check result
            check_result = await self.lc_client.check_submission(submission_id)
            check_result["code"] = current_code
            status_msg = check_result.get("status_msg")

            if status_msg == "Accepted":
                return check_result

            # If failed, attempt AI repair
            attempts += 1
            if attempts <= max_retries:
                self.add_log(
                    f"Submission returned '{status_msg}'. Auto-repair attempt {attempts}/{max_retries}...",
                    "warning"
                )
                error_context = (
                    f"Status: {status_msg}\n"
                    f"Compile Error: {check_result.get('compile_error', '')}\n"
                    f"Runtime Error: {check_result.get('runtime_error', '')}\n"
                    f"Last Testcase: {check_result.get('last_testcase', '')}\n"
                    f"Expected Output: {check_result.get('expected_output', '')}\n"
                    f"Actual Output: {check_result.get('code_output', '')}"
                )

                fix_res = await self.ai_solver.fix_code(
                    problem_title=title,
                    description=clean_desc,
                    failed_code=current_code,
                    error_message=error_context,
                    language=lang_slug,
                    starter_code=starter_code
                )

                if fix_res.get("success"):
                    current_code = fix_res.get("code")
                    self.add_log("AI generated patch. Retrying submission...", "info")
                    await asyncio.sleep(2)
                else:
                    self.add_log(f"AI failed to repair code: {fix_res.get('error')}", "error")
                    return check_result
            else:
                return check_result

        return {"status_msg": "Max retries reached", "success": False}

    def _get_snippet_and_lang(self, chosen_lang: str, snippets: List[Dict[str, str]]) -> Tuple[str, str]:
        """Match language preference against available problem snippets."""
        if not snippets:
            return chosen_lang, ""

        if chosen_lang == "MIX":
            preferred_langs = ["python3", "cpp", "java", "javascript", "golang", "typescript", "c", "mysql", "postgresql", "bash", "pythondata"]
            for plang in preferred_langs:
                for s in snippets:
                    if s.get("langSlug") == plang:
                        return plang, s.get("code", "")
            first = snippets[0]
            return first.get("langSlug", "python3"), first.get("code", "")

        for s in snippets:
            if s.get("langSlug") == chosen_lang:
                return chosen_lang, s.get("code", "")

        first = snippets[0]
        return first.get("langSlug", chosen_lang), first.get("code", "")

bot_runner = BotRunner()
