import os
import json
import time
import secrets
import hashlib
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional
from fastapi import Request, HTTPException, Security, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from firebase_sync import firebase_sync

BASE_DIR = Path(__file__).resolve().parent
USERS_FILE = BASE_DIR / "users.json"
SESSIONS_FILE = BASE_DIR / "sessions.json"
AUDIT_LOG_FILE = BASE_DIR / "audit_logs.json"

security_bearer = HTTPBearer(auto_error=False)

class AuthManager:
    def __init__(self):
        self.users: Dict[str, Dict[str, Any]] = {}
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.audit_logs: List[Dict[str, Any]] = []
        self._load_data()
        self._ensure_default_admin()

    def _hash_pwd(self, password: str, salt: Optional[str] = None) -> tuple:
        if not salt:
            salt = secrets.token_hex(16)
        key = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt.encode('utf-8'),
            100000
        ).hex()
        return salt, key

    def _load_data(self):
        if USERS_FILE.exists():
            try:
                with open(USERS_FILE, "r", encoding="utf-8") as f:
                    self.users = json.load(f)
            except Exception as e:
                print(f"[Auth] Error loading users: {e}")

        if SESSIONS_FILE.exists():
            try:
                with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
                    self.sessions = json.load(f)
            except Exception as e:
                print(f"[Auth] Error loading sessions: {e}")

        if AUDIT_LOG_FILE.exists():
            try:
                with open(AUDIT_LOG_FILE, "r", encoding="utf-8") as f:
                    self.audit_logs = json.load(f)
            except Exception as e:
                print(f"[Auth] Error loading audit logs: {e}")

    def _save_users(self):
        try:
            with open(USERS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.users, f, indent=2)
        except Exception as e:
            print(f"[Auth] Error saving users: {e}")
        firebase_sync.schedule_save("users", self.users)

    def _save_sessions(self):
        try:
            with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.sessions, f, indent=2)
        except Exception as e:
            print(f"[Auth] Error saving sessions: {e}")

    def _save_audit_logs(self):
        try:
            with open(AUDIT_LOG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.audit_logs[-500:], f, indent=2)
        except Exception as e:
            print(f"[Auth] Error saving audit logs: {e}")
        firebase_sync.schedule_save("audit_logs", self.audit_logs[-100:])

    def _ensure_default_admin(self):
        admin_email = "surajdas@surajdas.com"
        admin_pwd = os.environ.get("SUPER_ADMIN_PASSWORD", "SurajSir")
        if admin_email not in self.users:
            salt, hashed = self._hash_pwd(admin_pwd)
            self.users[admin_email] = {
                "email": admin_email,
                "name": "Suraj Sir (Super Admin)",
                "salt": salt,
                "password_hash": hashed,
                "role": "admin",
                "is_active": True,
                "created_at": time.time(),
                "last_login": None,
                "user_settings": {}
            }
            self._save_users()
            print(f"[Auth] Super Admin account initialized: {admin_email}")

    def authenticate(
        self,
        email: str,
        password: str,
        ip: str,
        user_agent: str,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        accuracy: Optional[float] = None
    ) -> Dict[str, Any]:
        email_clean = email.strip().lower()
        user = self.users.get(email_clean)

        # Mandatory Geolocation Enforcement
        if latitude is None or longitude is None:
            self._log_audit(
                email=email_clean,
                status="FAILED_NO_LOCATION",
                ip=ip,
                user_agent=user_agent,
                lat=latitude,
                lon=longitude,
                acc=accuracy,
                reason="Location permission required"
            )
            return {
                "success": False,
                "error": "Location verification required! Please allow high-accuracy GPS/Location permission in your browser to proceed."
            }

        if not user:
            self._log_audit(email_clean, "FAILED_USER_NOT_FOUND", ip, user_agent, latitude, longitude, accuracy)
            return {"success": False, "error": "Invalid email or password."}

        if not user.get("is_active", True):
            self._log_audit(email_clean, "FAILED_ACCOUNT_DISABLED", ip, user_agent, latitude, longitude, accuracy)
            return {"success": False, "error": "This account has been disabled by the Administrator."}

        # Verify password with salt
        salt = user.get("salt")
        _, test_hash = self._hash_pwd(password, salt)
        if not secrets.compare_digest(user.get("password_hash", ""), test_hash):
            self._log_audit(email_clean, "FAILED_WRONG_PASSWORD", ip, user_agent, latitude, longitude, accuracy)
            return {"success": False, "error": "Invalid email or password."}

        # Generate cryptographically secure session token (256-bit entropy)
        token = secrets.token_urlsafe(48)
        now = time.time()
        expires_at = now + (7 * 24 * 3600)  # 7 days session

        self.sessions[token] = {
            "email": email_clean,
            "role": user.get("role", "user"),
            "name": user.get("name", email_clean),
            "created_at": now,
            "expires_at": expires_at,
            "ip": ip,
            "lat": latitude,
            "lon": longitude,
            "accuracy": accuracy
        }
        self._save_sessions()

        user["last_login"] = now
        user["last_ip"] = ip
        user["last_location"] = {"lat": latitude, "lon": longitude, "accuracy": accuracy}
        self._save_users()

        self._log_audit(
            email=email_clean,
            status="SUCCESS",
            ip=ip,
            user_agent=user_agent,
            lat=latitude,
            lon=longitude,
            acc=accuracy
        )

        return {
            "success": True,
            "token": token,
            "user": {
                "email": user["email"],
                "name": user.get("name", user["email"]),
                "role": user.get("role", "user")
            }
        }

    def _log_audit(self, email: str, status: str, ip: str, user_agent: str, lat=None, lon=None, acc=None, reason=None):
        log_entry = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "email": email,
            "status": status,
            "ip": ip,
            "user_agent": user_agent[:120] if user_agent else "Unknown",
            "lat": lat,
            "lon": lon,
            "accuracy_meters": acc,
            "reason": reason
        }
        self.audit_logs.append(log_entry)
        self._save_audit_logs()

    def get_user_from_token(self, token: str) -> Optional[Dict[str, Any]]:
        if not token:
            return None
        sess = self.sessions.get(token)
        if not sess:
            return None
        if time.time() > sess.get("expires_at", 0):
            del self.sessions[token]
            self._save_sessions()
            return None
        user = self.users.get(sess["email"])
        if not user or not user.get("is_active", True):
            return None
        return {
            "email": user["email"],
            "name": user.get("name", user["email"]),
            "role": user.get("role", "user"),
            "token": token
        }

    def logout(self, token: str):
        if token in self.sessions:
            del self.sessions[token]
            self._save_sessions()

    # Admin Methods
    def list_users(self) -> List[Dict[str, Any]]:
        res = []
        for u in self.users.values():
            res.append({
                "email": u["email"],
                "name": u.get("name", ""),
                "role": u.get("role", "user"),
                "is_active": u.get("is_active", True),
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(u.get("created_at", time.time()))),
                "last_login": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(u["last_login"])) if u.get("last_login") else "Never",
                "last_ip": u.get("last_ip", "-"),
                "last_location": u.get("last_location")
            })
        return res

    def create_user(self, email: str, password: str, name: str = "", role: str = "user") -> Dict[str, Any]:
        email_clean = email.strip().lower()
        if not email_clean or "@" not in email_clean:
            return {"success": False, "error": "Invalid email address format."}
        if not password or len(password) < 6:
            return {"success": False, "error": "Password must be at least 6 characters long."}
        if email_clean in self.users:
            return {"success": False, "error": f"User with email '{email_clean}' already exists."}

        salt, hashed = self._hash_pwd(password)
        self.users[email_clean] = {
            "email": email_clean,
            "name": name.strip() or email_clean.split("@")[0],
            "salt": salt,
            "password_hash": hashed,
            "role": "admin" if role == "admin" else "user",
            "is_active": True,
            "created_at": time.time(),
            "last_login": None,
            "user_settings": {}
        }
        self._save_users()
        return {"success": True, "message": f"User {email_clean} created successfully!"}

    def delete_user(self, email: str) -> Dict[str, Any]:
        email_clean = email.strip().lower()
        if email_clean == "surajdas@surajdas.com":
            return {"success": False, "error": "Cannot delete the Super Admin account."}
        if email_clean in self.users:
            del self.users[email_clean]
            self._save_users()
            # Clean sessions
            to_del = [t for t, s in self.sessions.items() if s.get("email") == email_clean]
            for t in to_del:
                del self.sessions[t]
            self._save_sessions()
            return {"success": True, "message": f"User {email_clean} deleted."}
        return {"success": False, "error": "User not found."}

    def toggle_user_active(self, email: str, is_active: bool) -> Dict[str, Any]:
        email_clean = email.strip().lower()
        if email_clean == "surajdas@surajdas.com":
            return {"success": False, "error": "Cannot deactivate the Super Admin account."}
        if email_clean in self.users:
            self.users[email_clean]["is_active"] = is_active
            self._save_users()
            if not is_active:
                to_del = [t for t, s in self.sessions.items() if s.get("email") == email_clean]
                for t in to_del:
                    del self.sessions[t]
                self._save_sessions()
            return {"success": True, "message": f"User status updated to {'Active' if is_active else 'Disabled'}."}
        return {"success": False, "error": "User not found."}

    def reset_user_password(self, email: str, new_password: str) -> Dict[str, Any]:
        email_clean = email.strip().lower()
        if not new_password or len(new_password) < 6:
            return {"success": False, "error": "Password must be at least 6 characters."}
        if email_clean in self.users:
            salt, hashed = self._hash_pwd(new_password)
            self.users[email_clean]["salt"] = salt
            self.users[email_clean]["password_hash"] = hashed
            self._save_users()
            return {"success": True, "message": f"Password reset for {email_clean}."}
        return {"success": False, "error": "User not found."}

    def get_audit_logs(self, limit: int = 100) -> List[Dict[str, Any]]:
        return list(reversed(self.audit_logs[-limit:]))

auth_mgr = AuthManager()

async def get_current_user(
    request: Request,
    auth: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer)
) -> Dict[str, Any]:
    token = None
    if auth and auth.credentials:
        token = auth.credentials
    if not token:
        token = request.headers.get("X-Auth-Token")
    if not token:
        token = request.cookies.get("session_token")

    if not token:
        raise HTTPException(status_code=401, detail="Authentication required. Please login.")

    user = auth_mgr.get_user_from_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Session expired or invalid. Please login again.")
    return user

async def require_admin(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Forbidden: Administrator access required.")
    return user
