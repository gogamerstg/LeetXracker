import os
import json
import httpx
from typing import Dict, Any, Optional

FIREBASE_URL = os.environ.get("FIREBASE_DATABASE_URL", "").rstrip("/")
FIREBASE_AUTH = os.environ.get("FIREBASE_AUTH_SECRET", "")  # Optional auth secret/token

class FirebaseSync:
    """
    Lightweight, zero-dependency Firebase Realtime Database cloud sync via REST API.
    Provides persistent cloud backup for user accounts, settings, and submission history.
    """
    def __init__(self):
        self.enabled = bool(FIREBASE_URL)
        if self.enabled:
            print(f"[Firebase] Connected to cloud persistence at: {FIREBASE_URL}")

    def _get_url(self, path: str) -> str:
        clean_path = path.strip("/").replace(".", "_")
        url = f"{FIREBASE_URL}/{clean_path}.json"
        if FIREBASE_AUTH:
            url += f"?auth={FIREBASE_AUTH}"
        return url

    async def get_data(self, path: str) -> Optional[Any]:
        if not self.enabled:
            return None
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(self._get_url(path))
                if res.status_code == 200:
                    return res.json()
        except Exception as e:
            print(f"[Firebase] Error reading {path}: {e}")
        return None

    async def save_data(self, path: str, data: Any) -> bool:
        if not self.enabled:
            return False
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.put(self._get_url(path), json=data)
                return res.status_code in [200, 204]
        except Exception as e:
            print(f"[Firebase] Error saving {path}: {e}")
            return False

    async def patch_data(self, path: str, data: Dict[str, Any]) -> bool:
        if not self.enabled:
            return False
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.patch(self._get_url(path), json=data)
                return res.status_code in [200, 204]
        except Exception as e:
            print(f"[Firebase] Error patching {path}: {e}")
            return False

firebase_sync = FirebaseSync()
