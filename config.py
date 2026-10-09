import json
import os
from pathlib import Path
from typing import Dict, Any, List

BASE_DIR = Path(__file__).resolve().parent
SETTINGS_FILE = BASE_DIR / "settings.json"
USER_DATA_DIR = BASE_DIR / "user_data"
USER_DATA_DIR.mkdir(exist_ok=True)

DEFAULT_SETTINGS: Dict[str, Any] = {
    # LeetCode Credentials
    "leetcode_session": os.environ.get("LEETCODE_SESSION", ""),
    "csrf_token": os.environ.get("CSRF_TOKEN", ""),

    # AI API Keys & Endpoints
    "omniroute_base_url": os.environ.get("OMNIROUTE_BASE_URL", "http://localhost:20128/v1"),
    "omniroute_api_key": os.environ.get("OMNIROUTE_API_KEY", ""),
    "omniroute_model": os.environ.get("OMNIROUTE_MODEL", "auto/best-coding"),
    "groq_api_key": os.environ.get("GROQ_API_KEY", ""),
    "gemini_api_key": os.environ.get("GEMINI_API_KEY", ""),
    "openrouter_api_key": os.environ.get("OPENROUTER_API_KEY", ""),

    # Preferred AI Model Order
    "ai_provider_priority": ["omniroute", "groq", "gemini", "openrouter"],
    "groq_model": os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b"),
    "gemini_model": os.environ.get("GEMINI_MODEL", "gemini-flash-latest"),
    "openrouter_model": os.environ.get("OPENROUTER_MODEL", "nvidia/nemotron-3.5-lightning:free"),

    # Bot Automation Settings
    "auto_model_failover": True,
    "target_count": int(os.environ.get("TARGET_COUNT", 50)),
    "delay_seconds": int(os.environ.get("DELAY_SECONDS", 1)),
    "difficulty": os.environ.get("DIFFICULTY", "ALL"),
    "language": os.environ.get("LANGUAGE", "python3"),
    "max_retries_per_problem": int(os.environ.get("MAX_RETRIES", 2)),
    "skip_paid_only": True,
    "skip_already_solved": True,
    "randomize_order": False,
    "tags": []
}

def get_user_settings_path(email: str) -> Path:
    safe_name = "".join(c if c.isalnum() or c in ['_', '-'] else '_' for c in email.lower())
    user_dir = USER_DATA_DIR / safe_name
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir / "settings.json"

def get_user_history_path(email: str) -> Path:
    safe_name = "".join(c if c.isalnum() or c in ['_', '-'] else '_' for c in email.lower())
    user_dir = USER_DATA_DIR / safe_name
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir / "history.json"

class ConfigManager:
    def __init__(self):
        self.settings: Dict[str, Any] = DEFAULT_SETTINGS.copy()
        self.load()

    def load(self) -> Dict[str, Any]:
        if SETTINGS_FILE.exists():
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    self.settings.update(saved)
            except Exception as e:
                print(f"[Config] Error loading settings: {e}")
        else:
            self.save()
        return self.settings

    def save(self, new_data: Dict[str, Any] = None) -> Dict[str, Any]:
        if new_data:
            self.settings.update(new_data)
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=2)
        except Exception as e:
            print(f"[Config] Error saving settings: {e}")
        return self.settings

    def get(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, default)

    def load_user_settings(self, email: str) -> Dict[str, Any]:
        """Loads isolated settings for a specific user."""
        user_file = get_user_settings_path(email)
        user_cfg = self.settings.copy()
        if user_file.exists():
            try:
                with open(user_file, "r", encoding="utf-8") as f:
                    user_cfg.update(json.load(f))
            except Exception as e:
                print(f"[Config] Error loading user settings for {email}: {e}")
        elif email == "surajdas@surajdas.com":
            # For super admin, seed with global/env settings
            self.save_user_settings(email, self.settings)
        return user_cfg

    def save_user_settings(self, email: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Saves isolated settings for a specific user."""
        user_file = get_user_settings_path(email)
        current = self.load_user_settings(email)
        current.update(updates)
        try:
            with open(user_file, "w", encoding="utf-8") as f:
                json.dump(current, f, indent=2)
        except Exception as e:
            print(f"[Config] Error saving user settings for {email}: {e}")

        # If super admin, keep global settings in sync
        if email == "surajdas@surajdas.com":
            self.save(updates)
        return current

config = ConfigManager()
