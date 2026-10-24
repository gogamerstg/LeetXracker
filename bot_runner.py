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

        safe_email = target_email.replace(".", "_")
        firebase_sync.schedule_save(f"history/{safe_email}", self.history[-100:])

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
        mode = "daily" if (self.current_problem and self.current_problem.get("mode") == "daily") else "continuous"

        # Daily quota for active account
        quota_remaining = 0
        quota_today = 0
        try:
            from account_manager import account_mgr
            account_mgr.check_daily_reset()
            acc = account_mgr.get_active_account(target_email)
            if acc:
                quota_remaining = max(0, acc.daily_limit - acc.solved_today)
                quota_today = acc.daily_limit
        except Exception:
            pass

        return {
            "status": self.status,
            "mode": mode,
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
            "history_total_count": len(user_hist),
            "daily_quota_remaining": quota_remaining,
            "daily_quota_today": quota_today
        }

    async def start(self, user_email: Optional[str] = None, daily_mode: bool = False):
        if self.status == "RUNNING":
            return {"status": "already_running"}

        if user_email:
            self.active_user_email = user_email
            self.load_history(user_email)

        self.sync_config(self.active_user_email)

        # Verify credentials first (optional, proceed if problem list works)
        conn_check = await self.lc_client.test_connection()
        if not conn_check.get("success"):
            self.add_log("LeetCode session check warning (proceeding anyway): " + str(conn_check.get("error", "")), "warning")

        username = conn_check.get("username", "User")
        self.add_log(f"Connected to LeetCode as: {username} ({self.active_user_email})", "success")

        self.status = "RUNNING"
        self.start_time = time.time()
        self.current_task = asyncio.create_task(
            self._daily_loop() if daily_mode else self._main_loop()
        )
        return {"status": "started", "username": username, "mode": "daily" if daily_mode else "continuous"}

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
        seen_in_session = set()

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

                for prob in problems:
                    if self.status != "RUNNING":
                        break

                    if target_count > 0 and self.solved_count >= target_count:
                        break

                    frontend_id = str(prob.get("frontendQuestionId") or prob.get("questionFrontendId") or "")
                    title = prob.get("title")
                    title_slug = prob.get("titleSlug")
                    is_paid = prob.get("paidOnly", False)
                    status_flag = prob.get("status")  # "ac", "notac", None

                    if not frontend_id or not title_slug:
                        continue

                    # Avoid re-attempting problems seen in this session
                    if frontend_id in seen_in_session:
                        continue
                    seen_in_session.add(frontend_id)

                    # Check skip rules
                    if skip_paid and is_paid:
                        continue

                    if skip_solved and status_flag == "ac":
                        continue

                    # Also check our local history for already accepted
                    if skip_solved and any(str(h.get("id")) == frontend_id and h.get("status") == "Accepted" for h in self.history):
                        continue

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

                    # Auth failure won't recover by itself — stop and tell the user
                    if submission_result.get("auth_error"):
                        err_detail = submission_result.get("status_msg") or "Invalid session/CSRF token"
                        self.add_log(f"LeetCode Auth/CSRF Error: {err_detail}", "error")
                        self.add_log("Update your LEETCODE_SESSION cookie in Settings, then restart.", "error")
                        self.status = "ERROR"
                        self.current_problem = None
                        break

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
                        # Update streak and XP via account manager
                        try:
                            from account_manager import account_mgr
                            account_mgr.update_streak_and_xp(self.active_user_email, 1)
                            account_mgr.award_based_on_progress(self.active_user_email)
                        except Exception as e:
                            self.add_log(f"Stats update error: {e}", "warning")
                    else:
                        self.failed_count += 1
                        self.add_log(
                            f"Problem #{frontend_id} not accepted: {status_msg}",
                            "warning"
                        )
                        if "429" in str(status_msg) or "Rate limit" in str(status_msg):
                            self.add_log("LeetCode rate limit encountered! Cooling down 15s...", "warning")
                            await asyncio.sleep(15)

                    # Cooldown delay between questions
                    self.current_problem = None
                    if self.status == "RUNNING":
                        cfg_now = config.load_user_settings(self.active_user_email)
                        current_delay = cfg_now.get("delay_seconds", 1)
                        if current_delay > 0:
                            self.add_log(f"Waiting {current_delay}s cooldown...", "info")
                            await asyncio.sleep(current_delay)

                # Advance batch offset to fetch the next set of problems
                skip_offset += len(problems)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.add_log(f"Unexpected error in loop: {e}", "error")
                await asyncio.sleep(5)

        self.current_problem = None
        if self.status == "RUNNING":
            self.status = "IDLE"

    async def _daily_loop(self):
        """Daily mode: solve 2-5 random problems then auto-stop. Realistic + natural."""
        self.add_log(f"[DAILY MODE] Starting daily solve for {self.active_user_email}.", "info")
        user_cfg = config.load_user_settings(self.active_user_email)
        difficulty = user_cfg.get("difficulty", "ALL")
        language = user_cfg.get("language", "MIX")
        max_retries = 1  # Keep retries low for natural feel
        skip_solved = True

        # Natural daily quota: 2-5 problems randomly chosen
        daily_count = random.randint(2, 5)
        self.add_log(f"[DAILY MODE] Target: ~{daily_count} problems today.", "info")

        # Fetch a batch and pick random unsolved ones
        try:
            problems = await self.lc_client.get_problem_list(
                category="",
                difficulty=difficulty,
                limit=50,  # Larger batch for random selection
                skip=0
            )
        except Exception as e:
            self.add_log(f"[DAILY MODE] Failed to fetch problems: {e}", "error")
            self.status = "IDLE"
            return

        if not problems:
            self.add_log("[DAILY MODE] No problems found.", "warning")
            self.status = "IDLE"
            return

        # Filter: skip paid, skip already solved
        filtered = []
        seen_ids = set()
        for prob in problems:
            fid = str(prob.get("frontendQuestionId") or prob.get("questionFrontendId") or "")
            title_slug = prob.get("titleSlug", "")
            is_paid = prob.get("paidOnly", False)
            status_flag = prob.get("status")

            if not fid or not title_slug or fid in seen_ids:
                continue
            seen_ids.add(fid)

            if is_paid and user_cfg.get("skip_paid_only", True):
                continue
            if skip_solved and status_flag == "ac":
                continue
            if any(str(h.get("id")) == fid and h.get("status") == "Accepted" for h in self.history):
                continue

            filtered.append(prob)

        # Randomly pick daily_count problems from filtered list
        random.shuffle(filtered)
        selected = filtered[:daily_count]
        if not selected:
            self.add_log("[DAILY MODE] All problems already solved or none available.", "info")
            self.status = "IDLE"
            return

        self.add_log(f"[DAILY MODE] Selected {len(selected)} random problems.", "info")

        # Accuracy simulation: "realistic" mode
        # ~70% success rate - let some fail naturally
        import random as _r
        _r.seed(None)  # True randomness per day
        should_succeed = {prob.get("titleSlug"): _r.random() < 0.70 for prob in selected}

        for prob in selected:
            if self.status != "RUNNING":
                break

            fid = str(prob.get("frontendQuestionId") or prob.get("questionFrontendId") or "")
            title = prob.get("title", "Unknown")
            title_slug = prob.get("titleSlug", "")

            if not title_slug:
                continue

            self.current_problem = {
                "id": fid,
                "title": title,
                "slug": title_slug,
                "mode": "daily"
            }
            self.add_log(f"[DAILY] Processing #{fid}: {title}...", "info")

            try:
                details = await self.lc_client.get_problem_details(title_slug)
                if not details or not details.get("content"):
                    self.add_log(f"[DAILY] Failed to fetch #{fid}. Skipping.", "warning")
                    continue

                snippets = details.get("codeSnippets", [])
                q_diff = details.get("difficulty", "Medium")
                chosen_lang, starter_code = self._get_snippet_and_lang(language, snippets)
                if not starter_code:
                    self.add_log(f"[DAILY] No starter code for #{fid}. Skipping.", "warning")
                    continue

                # Solve
                solve_res = await self.ai_solver.solve_problem(
                    problem_title=f"#{fid} - {title}",
                    difficulty=q_diff,
                    description=details.get("clean_description", ""),
                    starter_code=starter_code,
                    language=chosen_lang
                )

                if not solve_res.get("success"):
                    self.add_log(f"[DAILY] AI failed #{fid}: {solve_res.get('error')}", "error")
                    self.failed_count += 1
                    self._record_history(fid, title, title_slug, chosen_lang, q_diff, "AI Failed", solve_res.get("code", ""), solve_res.get("provider", "?"), solve_res.get("model", ""))
                    continue

                code = solve_res.get("code", "")
                provider = solve_res.get("provider", "?")
                model_used = solve_res.get("model", "")

                # Submit
                sub_result = await self._submit_and_evaluate(
                    title_slug=title_slug,
                    question_id=details.get("questionId", ""),
                    lang_slug=chosen_lang,
                    code=code,
                    title=title,
                    clean_desc=details.get("clean_description", ""),
                    starter_code=starter_code,
                    max_retries=max_retries
                )

                status_msg = sub_result.get("status_msg", "Error")

                # Inject realism: if should_succeed=False and it's WA, try once more
                # but make it fail for natural look (skip repair retry)
                if status_msg == "Accepted":
                    self.solved_count += 1
                    self.add_log(f"[DAILY] Accepted #{fid} ({title})!", "success")
                    # Update streak and XP via account manager for daily mode
                    try:
                        from account_manager import account_mgr
                        account_mgr.update_streak_and_xp(self.active_user_email, 1)
                        account_mgr.award_based_on_progress(self.active_user_email)
                    except Exception as e:
                        self.add_log(f"[DAILY] Stats update error: {e}", "warning")
                else:
                    # Don't retry for realism — just mark as failed
                    self.failed_count += 1
                    self.add_log(f"[DAILY] #{fid}: {status_msg}", "warning")

                self._record_history(
                    fid, title, title_slug, chosen_lang, q_diff,
                    status_msg, code, provider, model_used,
                    runtime=sub_result.get("runtime"),
                    runtime_pct=sub_result.get("runtime_percentile"),
                    memory=sub_result.get("memory"),
                    memory_pct=sub_result.get("memory_percentile")
                )

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.add_log(f"[DAILY] Error on #{fid}: {e}", "error")

            # Short delay between daily problems (8-15s random)
            await asyncio.sleep(random.randint(8, 15))

        self.add_log(f"[DAILY MODE] Done! Solved {self.solved_count}/{len(selected)} today.", "success")
        self.status = "IDLE"
        self.current_problem = None

    def _record_history(self, fid, title, title_slug, lang, diff, status_msg, code, provider, model_used,
                        runtime="-", runtime_pct="-", memory="-", memory_pct="-"):
        entry = {
            "id": str(fid),
            "title": str(title),
            "slug": str(title_slug),
            "difficulty": str(diff),
            "language": str(lang),
            "status": str(status_msg),
            "runtime": str(runtime),
            "runtime_percentile": str(runtime_pct),
            "memory": str(memory),
            "memory_percentile": str(memory_pct),
            "provider": str(provider),
            "model": str(model_used),
            "code": str(code),
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        self.history.append(entry)
        self.save_history()

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
                return {"status_msg": sub_resp["error"], "success": False, "auth_error": sub_resp.get("auth_error", False)}

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
            # Select from available languages to give a realistic mix
            available = [s for s in snippets if s.get("langSlug") in ["python3", "cpp", "java", "javascript", "golang", "typescript"]]
            if available:
                selected = random.choice(available)
                return selected.get("langSlug", "python3"), selected.get("code", "")
            first = snippets[0]
            return first.get("langSlug", "python3"), first.get("code", "")

        for s in snippets:
            if s.get("langSlug") == chosen_lang:
                return chosen_lang, s.get("code", "")

        first = snippets[0]
        return first.get("langSlug", chosen_lang), first.get("code", "")

bot_runner = BotRunner()

if __name__ == "__main__":
    import sys
    email = sys.argv[1] if len(sys.argv) > 1 else "surajdas@surajdas.com"
    print(f"[BotRunner] Running standalone solver for {email}...")
    async def _run():
        await bot_runner.start(email)
        while bot_runner.status == "RUNNING":
            await asyncio.sleep(2)
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        print("\n[BotRunner] Stopped by user.")
