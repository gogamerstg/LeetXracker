import os
import json
import asyncio
import httpx
from typing import Dict, Any, Optional

FIREBASE_PROJECT_ID = os.environ.get("FIREBASE_PROJECT_ID", "leetxracker")
FIREBASE_API_KEY = os.environ.get("FIREBASE_API_KEY", "AIzaSyCS8fWFuqIaK6tQNmy-S5VWxQvumr55iQE")
FIREBASE_URL = os.environ.get("FIREBASE_DATABASE_URL", f"https://{FIREBASE_PROJECT_ID}-default-rtdb.asia-southeast1.firebasedatabase.app").rstrip("/")
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

    def _sanitize(self, data: Any) -> Any:
        if isinstance(data, dict):
            return {
                (k.replace(".", "_") if isinstance(k, str) else k): self._sanitize(v)
                for k, v in data.items()
            }
        elif isinstance(data, list):
            return [self._sanitize(item) for item in data]
        return data

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
            print(f"[Firebase] Note: Cloud fetch for {path}: {e}")
        return None

    async def save_data(self, path: str, data: Any) -> bool:
        if not self.enabled:
            return False
        try:
            clean_data = self._sanitize(data)
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.put(self._get_url(path), json=clean_data)
                return res.status_code in [200, 204]
        except Exception as e:
            print(f"[Firebase] Note: Cloud save for {path}: {e}")
            return False

    async def patch_data(self, path: str, data: Dict[str, Any]) -> bool:
        if not self.enabled:
            return False
        try:
            clean_data = self._sanitize(data)
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.patch(self._get_url(path), json=clean_data)
                return res.status_code in [200, 204]
        except Exception as e:
            print(f"[Firebase] Note: Cloud patch for {path}: {e}")
            return False

    def get_data_sync(self, path: str) -> Optional[Any]:
        if not self.enabled:
            return None
        try:
            import urllib.request
            url = self._get_url(path)
            req = urllib.request.Request(url, headers={"User-Agent": "LeetXracker/1.0"})
            with urllib.request.urlopen(req, timeout=4) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode())
        except Exception:
            pass
        return None

    def schedule_save(self, path: str, data: Any):
        """Safely schedule a cloud save without failing if event loop isn't running yet."""
        if not self.enabled:
            return
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.save_data(path, data))
        except RuntimeError:
            try:
                import threading
                clean_data = self._sanitize(data)
                def _bg_save():
                    try:
                        import urllib.request
                        url = self._get_url(path)
                        req = urllib.request.Request(url, data=json.dumps(clean_data).encode("utf-8"), headers={"Content-Type": "application/json", "User-Agent": "LeetXracker/1.0"}, method="PUT")
                        urllib.request.urlopen(req, timeout=5)
                    except Exception:
                        pass
                threading.Thread(target=_bg_save, daemon=True).start()
            except Exception:
                pass

firebase_sync = FirebaseSync()


