import io
import zipfile
import re
import os
import uvicorn
from pathlib import Path
from fastapi import FastAPI, Request, Response, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from config import config
from bot_runner import bot_runner
from leetcode_client import LeetCodeClient
from ai_solver import MultiAISolver
from auth_manager import auth_mgr, get_current_user, require_admin
from account_manager import account_mgr

app = FastAPI(title="LeetXracker - Multi-AI Auto Engine")

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "error": exc.detail}
    )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    print(f"[Server Error] {request.url.path}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"success": False, "error": f"Server error: {str(exc)}"}
    )

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.on_event("startup")
async def startup_event():
    auto_start = os.environ.get("AUTO_START_BOT", "true").lower() in ("true", "1")
    if auto_start:
        admin_email = "surajdas@surajdas.com"
        print(f"[Server] Auto-starting LeetXracker solver for {admin_email}...")
        import asyncio
        asyncio.create_task(bot_runner.start(admin_email))

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = STATIC_DIR / "index.html"
    with open(index_file, "r", encoding="utf-8") as f:
        return HTMLResponse(
            content=f.read(),
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )

# ================= AUTH ENDPOINTS =================
class LoginPayload(BaseModel):
    email: str
    password: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    accuracy: Optional[float] = None

@app.post("/api/auth/login")
async def login(payload: LoginPayload, request: Request, response: Response):
    client_ip = request.client.host if request.client else "Unknown"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
    user_agent = request.headers.get("user-agent", "Unknown")

    res = auth_mgr.authenticate(
        email=payload.email,
        password=payload.password,
        ip=client_ip,
        user_agent=user_agent,
        latitude=payload.latitude,
        longitude=payload.longitude,
        accuracy=payload.accuracy
    )
    if res.get("success"):
        response.set_cookie(
            key="session_token",
            value=res["token"],
            httponly=True,
            max_age=7*24*3600,
            samesite="lax"
        )
    return res

@app.post("/api/auth/logout")
async def logout(request: Request, response: Response, current_user: dict = Depends(get_current_user)):
    token = current_user.get("token")
    if token:
        auth_mgr.logout(token)
    response.delete_cookie("session_token")
    return {"success": True, "message": "Logged out successfully."}

@app.get("/api/auth/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return {
        "authenticated": True,
        "user": {
            "email": current_user["email"],
            "name": current_user.get("name", current_user["email"]),
            "role": current_user.get("role", "user")
        }
    }

# ================= ADMIN USER MANAGEMENT =================
class CreateUserPayload(BaseModel):
    email: str
    password: str
    name: Optional[str] = ""
    role: Optional[str] = "user"

@app.get("/api/admin/users")
async def admin_list_users(admin: dict = Depends(require_admin)):
    return {
        "success": True,
        "users": auth_mgr.list_users(),
        "audit_logs": auth_mgr.get_audit_logs(limit=50)
    }

@app.post("/api/admin/users")
async def admin_create_user(payload: CreateUserPayload, admin: dict = Depends(require_admin)):
    return auth_mgr.create_user(
        email=payload.email,
        password=payload.password,
        name=payload.name,
        role=payload.role
    )

@app.delete("/api/admin/users/{email}")
async def admin_delete_user(email: str, admin: dict = Depends(require_admin)):
    return auth_mgr.delete_user(email)

class ToggleUserPayload(BaseModel):
    is_active: bool

@app.post("/api/admin/users/{email}/toggle")
async def admin_toggle_user(email: str, payload: ToggleUserPayload, admin: dict = Depends(require_admin)):
    return auth_mgr.toggle_user_active(email, payload.is_active)

class ResetPasswordPayload(BaseModel):
    new_password: str

@app.post("/api/admin/users/{email}/reset-password")
async def admin_reset_password(email: str, payload: ResetPasswordPayload, admin: dict = Depends(require_admin)):
    return auth_mgr.reset_user_password(email, payload.new_password)

# ================= PROTECTED BOT ENDPOINTS =================
@app.get("/api/settings")
async def get_settings(current_user: dict = Depends(get_current_user)):
    return config.load_user_settings(current_user["email"])

class SettingsPayload(BaseModel):
    leetcode_session: Optional[str] = None
    csrf_token: Optional[str] = None
    omniroute_base_url: Optional[str] = None
    omniroute_api_key: Optional[str] = None
    omniroute_model: Optional[str] = None
    groq_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None
    openrouter_api_key: Optional[str] = None
    target_count: Optional[int] = None
    target_easy: Optional[int] = None
    target_medium: Optional[int] = None
    target_hard: Optional[int] = None
    delay_seconds: Optional[int] = None
    difficulty: Optional[str] = None
    language: Optional[str] = None
    groq_model: Optional[str] = None
    gemini_model: Optional[str] = None
    openrouter_model: Optional[str] = None
    ai_provider_priority: Optional[List[str]] = None
    skip_paid_only: Optional[bool] = None
    skip_already_solved: Optional[bool] = None

@app.post("/api/settings")
async def update_settings(payload: SettingsPayload, current_user: dict = Depends(get_current_user)):
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    saved = config.save_user_settings(current_user["email"], updates)
    bot_runner.sync_config(current_user["email"])
    return {"success": True, "settings": saved}

class FetchModelsPayload(BaseModel):
    base_url: str
    api_key: Optional[str] = ""

@app.post("/api/fetch-models")
async def fetch_models(payload: FetchModelsPayload, current_user: dict = Depends(get_current_user)):
    res = await MultiAISolver.fetch_models_from_endpoint(payload.base_url, payload.api_key)
    return res

class AuthTestPayload(BaseModel):
    session: str
    csrf: str

@app.post("/api/test-auth")
async def test_auth(payload: AuthTestPayload, current_user: dict = Depends(get_current_user)):
    client = LeetCodeClient(session_token=payload.session, csrf_token=payload.csrf)
    res = await client.test_connection()
    return res

@app.get("/api/bot/state")
async def get_bot_state(current_user: dict = Depends(get_current_user)):
    return bot_runner.get_state(current_user["email"])

@app.get("/api/history")
async def get_history(current_user: dict = Depends(get_current_user)):
    user_hist = bot_runner.get_user_history(current_user["email"])
    return {
        "success": True,
        "count": len(user_hist),
        "history": user_hist
    }

@app.get("/api/history/download")
async def download_all_solutions(current_user: dict = Depends(get_current_user)):
    """Package all solved solutions from history into a well-formatted ZIP archive."""
    user_hist = bot_runner.get_user_history(current_user["email"])
    LANG_EXT = {
        "python3": "py",
        "python": "py",
        "cpp": "cpp",
        "java": "java",
        "javascript": "js",
        "typescript": "ts",
        "golang": "go",
        "rust": "rs",
        "c": "c",
        "mysql": "sql",
        "postgresql": "sql",
        "mssql": "sql",
        "bash": "sh",
        "pythondata": "py"
    }

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        readme_lines = [
            f"# LeetXracker Solved Problems ({current_user['email']})",
            f"Total Submissions: {len(user_hist)}",
            "",
            "| # | Problem | Difficulty | Language | Status | Runtime | Memory |",
            "|---|---|---|---|---|---|---|"
        ]

        for idx, item in enumerate(user_hist, 1):
            q_id = str(item.get("id", idx))
            title = item.get("title", f"problem_{idx}")
            clean_title = re.sub(r'[^a-zA-Z0-9_\- ]', '', title).replace(' ', '_')
            lang = item.get("language", "python3").lower()
            ext = LANG_EXT.get(lang, "txt")
            status = item.get("status", "Unknown")
            diff = item.get("difficulty", "N/A")
            runtime = item.get("runtime", "-")
            memory = item.get("memory", "-")
            code = item.get("code", "")

            filename = f"solutions/{q_id.zfill(4)}_{clean_title}.{ext}"
            file_header = (
                f"/*\n"
                f" * Problem #{q_id}: {title}\n"
                f" * Difficulty: {diff}\n"
                f" * Language: {lang}\n"
                f" * Status: {status}\n"
                f" * Runtime: {runtime}\n"
                f" * Memory: {memory}\n"
                f" * AI Provider: {item.get('provider', 'Multi-AI')}\n"
                f" */\n\n"
            ) if ext in ["cpp", "java", "js", "ts", "go", "rs", "c"] else (
                f"# Problem #{q_id}: {title}\n"
                f"# Difficulty: {diff}\n"
                f"# Language: {lang}\n"
                f"# Status: {status}\n"
                f"# Runtime: {runtime}\n"
                f"# Memory: {memory}\n"
                f"# AI Provider: {item.get('provider', 'Multi-AI')}\n\n"
            )

            zf.writestr(filename, file_header + (code or "// Code not stored"))
            readme_lines.append(f"| {q_id} | {title} | {diff} | {lang} | {status} | {runtime} | {memory} |")

        zf.writestr("README.md", "\n".join(readme_lines))

    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=leetxracker_solutions_{current_user['email'].split('@')[0]}.zip"}
    )

@app.post("/api/bot/start")
async def start_bot(current_user: dict = Depends(get_current_user)):
    return await bot_runner.start(user_email=current_user["email"])

@app.post("/api/bot/pause")
async def pause_bot(current_user: dict = Depends(get_current_user)):
    return await bot_runner.pause()

@app.post("/api/bot/resume")
async def resume_bot(current_user: dict = Depends(get_current_user)):
    return await bot_runner.resume()

@app.post("/api/bot/stop")
async def stop_bot(current_user: dict = Depends(get_current_user)):
    return await bot_runner.stop()

@app.post("/api/bot/daily")
async def run_daily(current_user: dict = Depends(get_current_user)):
    """Trigger daily mode: solve 2-5 random problems then auto-stop."""
    return await bot_runner.start(user_email=current_user["email"], daily_mode=True)

# ── Multi-Account LeetCode Management ─────────────────────────────────────────

@app.get("/api/accounts")
async def list_accounts(current_user: dict = Depends(get_current_user)):
    """List all LeetCode accounts for the current user."""
    return {"accounts": account_mgr.get_accounts(current_user["email"])}

@app.post("/api/accounts")
async def add_account(
    body: dict,
    current_user: dict = Depends(get_current_user)
):
    """Add a LeetCode account (session cookie + CSRF token)."""
    username = body.get("username", "").strip()
    session = body.get("session", "").strip()
    csrf_token = body.get("csrf_token", "").strip()
    if not session or not csrf_token:
        return {"success": False, "error": "Session and CSRF token are required."}
    result = account_mgr.add_account(
        web_email=current_user["email"],
        username=username,
        session=session,
        csrf_token=csrf_token
    )
    # Auto-set first account as active
    if result.get("success") and len(account_mgr.get_accounts(current_user["email"])) == 1:
        account_mgr.set_active_account(current_user["email"], result["account"]["id"])
    return result

@app.put("/api/accounts/{account_id}")
async def update_account(
    account_id: str,
    body: dict,
    current_user: dict = Depends(get_current_user)
):
    """Update account settings (username, active status, daily_limit, accuracy_mode)."""
    return account_mgr.update_account(current_user["email"], account_id, body)

@app.post("/api/accounts/{account_id}/activate")
async def activate_account(
    account_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Set this account as the active one for auto-solving."""
    return account_mgr.set_active_account(current_user["email"], account_id)

@app.delete("/api/accounts/{account_id}")
async def delete_account(
    account_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Remove a LeetCode account."""
    return account_mgr.remove_account(current_user["email"], account_id)

# ── User Stats (Streak, XP, Badges) ─────────────────────────────────────

@app.get("/api/user/stats")
async def get_user_stats(current_user: dict = Depends(get_current_user)):
    """Get user statistics including streak, XP, and badges."""
    stats = account_mgr.get_user_stats(current_user["email"])
    return {
        "streak": stats.get("streak", 0),
        "xp": stats.get("xp", 0),
        "badge_count": len(stats.get("badges", [])),
        "last_solved_date": stats.get("last_solved_date"),
        "badges": stats.get("badges", [])
    }

@app.get("/api/user/badges")
async def get_user_badges(current_user: dict = Depends(get_current_user)):
    """Get detailed badge information for the user."""
    stats = account_mgr.get_user_stats(current_user["email"])
    return {
        "badges": stats.get("badges", []),
        "total_xp": stats.get("xp", 0),
        "streak": stats.get("streak", 0)
    }

# ── Cron / GitHub Actions Trigger (secret-key protected) ──────────────────────

@app.post("/api/cron/daily")
async def cron_daily(request: Request):
    """
    Secret-key protected endpoint for GitHub Actions cron.
    Set LEETXRACKER_CRON_SECRET env var on Render and add it to GitHub Secrets.
    """
    cron_secret = os.environ.get("LEETXRACKER_CRON_SECRET", "")

    # Verify secret from header
    key_header = request.headers.get("X-Cron-Secret", "")
    body = await request.json()
    key_body = body.get("key", "")

    if not cron_secret:
        return JSONResponse({"error": "Cron endpoint disabled — no secret configured."}, status_code=503)
    if key_header != cron_secret and key_body != cron_secret:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    # Trigger daily mode for super admin
    result = await bot_runner.start(user_email="surajdas@surajdas.com", daily_mode=True)
    return {"status": "ok", "trigger": "daily", "result": result}

@app.get("/api/accounts/active")
async def get_active_account(current_user: dict = Depends(get_current_user)):
    """Get the currently active LeetCode account."""
    acc = account_mgr.get_active_account(current_user["email"])
    if acc:
        return {"account": acc.to_dict()}
    return {"account": None}

# ── Admin: All Users' Account Summary ────────────────────────────────────────

@app.get("/api/admin/accounts", dependencies=[Depends(require_admin)])
async def admin_list_all_accounts():
    """Super admin: list all accounts across all users."""
    from auth_manager import auth_mgr as _am
    users = _am.list_users()
    summary = []
    for user in users:
        email = user["email"]
        accounts = account_mgr.get_accounts(email)
        active = account_mgr.get_active_account(email)
        summary.append({
            "email": email,
            "name": user["name"],
            "total_accounts": len(accounts),
            "active_account": active.username if active else None,
            "last_login": user.get("last_login"),
            "is_active": user.get("is_active", True)
        })
    return {"users": summary}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print("\n" + "="*60)
    print("🚀 LeetXracker - Multi-AI Auto-Solving Engine")
    print(f"👉 Local Access: http://localhost:{port}")
    print("👉 Super Admin: surajdas@surajdas.com")
    print("="*60 + "\n")
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)
