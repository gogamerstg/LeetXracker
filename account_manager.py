"""
Multi-Account LeetCode Credential Manager
Stores multiple LeetCode accounts per web user and manages which accounts are active for auto-solve.
"""
import json
import time
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from firebase_sync import firebase_sync

BASE_DIR = Path(__file__).resolve().parent

def _safe_email_path(email: str) -> str:
    return email.replace(".", "_").replace("@", "_at_")

@dataclass
class LeetCodeAccount:
    id: str
    email: str  # web user email
    username: str = ""       # LeetCode username display
    session: str = ""
    csrf_token: str = ""
    is_active: bool = False  # selected for auto-solve
    accuracy_mode: str = "realistic"  # realistic | fast | perfect
    daily_limit: int = 5    # max problems per daily run
    created_at: float = field(default_factory=time.time)
    last_used: Optional[float] = None
    solved_today: int = 0
    last_run_date: Optional[str] = None  # "YYYY-MM-DD"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "email": self.email,
            "username": self.username,
            "session": self.session,
            "csrf_token": self.csrf_token,
            "is_active": self.is_active,
            "accuracy_mode": self.accuracy_mode,
            "daily_limit": self.daily_limit,
            "created_at": self.created_at,
            "last_used": self.last_used,
            "solved_today": self.solved_today,
            "last_run_date": self.last_run_date
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "LeetCodeAccount":
        return LeetCodeAccount(
            id=d.get("id", ""),
            email=d.get("email", ""),
            username=d.get("username", ""),
            session=d.get("session", ""),
            csrf_token=d.get("csrf_token", ""),
            is_active=d.get("is_active", False),
            accuracy_mode=d.get("accuracy_mode", "realistic"),
            daily_limit=d.get("daily_limit", 5),
            created_at=d.get("created_at", time.time()),
            last_used=d.get("last_used"),
            solved_today=d.get("solved_today", 0),
            last_run_date=d.get("last_run_date")
        )


class AccountManager:
    """
    Manages multiple LeetCode accounts per web user.
    - Each web user (email) can have multiple LeetCode accounts
    - Each account can be toggled on/off for auto-solve
    - Daily quota tracked per account
    """

    def __init__(self):
        self._lock = asyncio.Lock()
        self._accounts: Dict[str, Dict[str, LeetCodeAccount]] = {}  # web_email -> {account_id -> Account}
        self._active_clients: Dict[str, LeetCodeClient] = {}  # web_email -> LeetCodeClient (current active)
        self._load_all()

    def _get_file_path(self, web_email: str) -> Path:
        safe = _safe_email_path(web_email)
        path = BASE_DIR / "user_data" / safe / "accounts.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _load_all(self):
        """Load all accounts from disk."""
        user_data_dir = BASE_DIR / "user_data"
        if not user_data_dir.exists():
            return
        for email_dir in user_data_dir.iterdir():
            if email_dir.is_dir():
                acc_file = email_dir / "accounts.json"
                if acc_file.exists():
                    try:
                        with open(acc_file, "r", encoding="utf-8") as f:
                            raw = json.load(f)
                            web_email = raw.get("_web_email", email_dir.name.replace("_at_", "@").replace("_", ".", 1) if "_at_" in email_dir.name else email_dir.name)
                            # Reconstruct email from dir name
                            parts = email_dir.name.split("_at_")
                            if len(parts) >= 2:
                                web_email = parts[0] + "@" + "_".join(parts[1:]).replace("_", ".")
                            accounts = {}
                            for acc_id, acc_data in raw.items():
                                if acc_id.startswith("_"):
                                    continue
                                accounts[acc_id] = LeetCodeAccount.from_dict(acc_data)
                            # Find actual web email
                            for a in accounts.values():
                                web_email = a.get("email", web_email)
                                break
                            self._accounts[web_email] = accounts
                    except Exception as e:
                        print(f"[AccountManager] Error loading accounts from {acc_file}: {e}")

    def _save_accounts(self, web_email: str):
        """Save accounts for a web user to disk + Firebase."""
        accounts = self._accounts.get(web_email, {})
        data = {"_web_email": web_email}
        for acc_id, acc in accounts.items():
            data[acc_id] = acc.to_dict()
        try:
            path = self._get_file_path(web_email)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[AccountManager] Error saving accounts: {e}")
        firebase_sync.schedule_save(f"accounts/{_safe_email_path(web_email)}", data)

    def _gen_id(self) -> str:
        return f"acc_{int(time.time() * 1000)}"

    # ── CRUD ─────────────────────────────────────────────────────────────────

    def add_account(self, web_email: str, username: str, session: str, csrf_token: str) -> Dict[str, Any]:
        """Add a new LeetCode account for a web user. Returns the new account."""
        if web_email not in self._accounts:
            self._accounts[web_email] = {}

        # Check if this session already exists for this user
        for acc in self._accounts[web_email].values():
            if acc.session == session:
                return {"success": False, "error": "This LeetCode session is already added."}

        acc_id = self._gen_id()
        acc = LeetCodeAccount(
            id=acc_id,
            email=web_email,
            username=username,
            session=session,
            csrf_token=csrf_token,
            is_active=False,
            accuracy_mode="realistic",
            daily_limit=5
        )
        self._accounts[web_email][acc_id] = acc
        self._save_accounts(web_email)
        return {"success": True, "account": acc.to_dict()}

    def update_account(self, web_email: str, account_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        if web_email not in self._accounts or account_id not in self._accounts[web_email]:
            return {"success": False, "error": "Account not found."}
        acc = self._accounts[web_email][account_id]
        allowed = {"username", "is_active", "accuracy_mode", "daily_limit", "session", "csrf_token"}
        for k, v in updates.items():
            if k in allowed:
                setattr(acc, k, v)
        self._save_accounts(web_email)
        return {"success": True, "account": acc.to_dict()}

    def remove_account(self, web_email: str, account_id: str) -> Dict[str, Any]:
        if web_email not in self._accounts or account_id not in self._accounts[web_email]:
            return {"success": False, "error": "Account not found."}
        acc = self._accounts[web_email][account_id]
        if acc.is_active:
            # Remove active client
            if web_email in self._active_clients:
                del self._active_clients[web_email]
        del self._accounts[web_email][account_id]
        self._save_accounts(web_email)
        return {"success": True}

    def get_accounts(self, web_email: str) -> List[Dict[str, Any]]:
        if web_email not in self._accounts:
            return []
        return [acc.to_dict() for acc in self._accounts[web_email].values()]

    def get_active_account(self, web_email: str) -> Optional[LeetCodeAccount]:
        """Get the currently selected active account for a web user."""
        if web_email not in self._accounts:
            return None
        for acc in self._accounts[web_email].values():
            if acc.is_active:
                return acc
        # Default to first account if none active
        if self._accounts[web_email]:
            return next(iter(self._accounts[web_email].values()))
        return None

    def get_all_active_accounts(self) -> List[LeetCodeAccount]:
        """Get all accounts across all web users that are marked active."""
        result = []
        for accounts in self._accounts.values():
            for acc in accounts.values():
                if acc.is_active:
                    result.append(acc)
        return result

    def set_active_account(self, web_email: str, account_id: str):
        """Set one account as active, deactivate others for this web user."""
        if web_email not in self._accounts:
            return {"success": False, "error": "User has no accounts."}
        if account_id not in self._accounts[web_email]:
            return {"success": False, "error": "Account not found."}

        for acc in self._accounts[web_email].values():
            acc.is_active = (acc.id == account_id)

        self._save_accounts(web_email)
        # Clear cached client
        if web_email in self._active_clients:
            del self._active_clients[web_email]
        return {"success": True}

    # ── Daily Quota Tracking ─────────────────────────────────────────────────

    def check_daily_reset(self):
        """Reset solved_today counter if new day."""
        today = time.strftime("%Y-%m-%d")
        for accounts in self._accounts.values():
            for acc in accounts.values():
                if acc.last_run_date != today:
                    acc.solved_today = 0
                    acc.last_run_date = today

    def record_solved(self, web_email: str):
        """Increment solved counter for today's run."""
        self.check_daily_reset()
        acc = self.get_active_account(web_email)
        if acc:
            acc.solved_today += 1
            acc.last_used = time.time()
            self._save_accounts(web_email)

    def can_solve_more(self, web_email: str) -> bool:
        """Check if active account has remaining daily quota."""
        self.check_daily_reset()
        acc = self.get_active_account(web_email)
        if not acc:
            return False
        return acc.solved_today < acc.daily_limit

    def get_remaining_quota(self, web_email: str) -> int:
        """Get remaining daily quota for active account."""
        self.check_daily_reset()
        acc = self.get_active_account(web_email)
        if not acc:
            return 0
        return max(0, acc.daily_limit - acc.solved_today)

    # ── LeetCode Client Factory ──────────────────────────────────────────────

    def get_client(self, web_email: str) -> Optional["LeetCodeClient"]:
        """Get or create a LeetCodeClient for the active account."""
        acc = self.get_active_account(web_email)
        if not acc:
            return None
        return LeetCodeClient(session_token=acc.session, csrf_token=acc.csrf_token)


account_mgr = AccountManager()
