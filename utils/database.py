"""
Simple JSON-based persistent storage for history, stats, user prefs.
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import DATA_PATH

logger = logging.getLogger(__name__)

HISTORY_FILE = Path(DATA_PATH) / "history.json"
STATS_FILE = Path(DATA_PATH) / "stats.json"
PREFS_FILE = Path(DATA_PATH) / "prefs.json"
BLOCKED_FILE = Path(DATA_PATH) / "blocked_users.json"
CACHE_FILE = Path(DATA_PATH) / "file_cache.json"


def _load(path: Path) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception as e:
        logger.warning(f"Load failed {path}: {e}")
    return {}


def _save(path: Path, data: dict):
    try:
        path.write_text(json.dumps(data, indent=2))
    except Exception as e:
        logger.warning(f"Save failed {path}: {e}")


# ── History ────────────────────────────────────────────────────────────────────

def add_history(user_id: int, title: str, url: str, fmt: str, size_mb: float, platform: str):
    data = _load(HISTORY_FILE)
    uid = str(user_id)
    if uid not in data:
        data[uid] = []
    data[uid].insert(0, {
        "title": title,
        "url": url,
        "fmt": fmt,
        "size_mb": round(size_mb, 1),
        "platform": platform,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })
    data[uid] = data[uid][:10]  # Keep last 10
    _save(HISTORY_FILE, data)


def get_history(user_id: int) -> list:
    data = _load(HISTORY_FILE)
    return data.get(str(user_id), [])


# ── Stats ──────────────────────────────────────────────────────────────────────

def record_download(user_id: int, fmt: str, size_mb: float, success: bool):
    data = _load(STATS_FILE)
    if "users" not in data:
        data = {"users": set(), "downloads": 0, "audio": 0, "video": 0,
                "failed": 0, "total_mb": 0.0, "user_ids": []}

    user_ids = set(data.get("user_ids", []))
    user_ids.add(user_id)
    data["user_ids"] = list(user_ids)
    data["users"] = len(user_ids)

    if success:
        data["downloads"] = data.get("downloads", 0) + 1
        data["total_mb"] = data.get("total_mb", 0.0) + size_mb
        if fmt == "audio":
            data["audio"] = data.get("audio", 0) + 1
        else:
            data["video"] = data.get("video", 0) + 1
    else:
        data["failed"] = data.get("failed", 0) + 1

    _save(STATS_FILE, data)


def get_stats() -> dict:
    data = _load(STATS_FILE)
    data.pop("user_ids", None)
    return data


def get_known_user_ids() -> list[int]:
    users: set[int] = set()

    stats = _load(STATS_FILE)
    for uid in stats.get("user_ids", []):
        try:
            users.add(int(uid))
        except (TypeError, ValueError):
            pass

    history = _load(HISTORY_FILE)
    for uid in history.keys():
        if str(uid).isdigit():
            users.add(int(uid))

    return sorted(users)


# Cached Telegram file IDs

def get_cached_download(cache_key: str) -> Optional[dict]:
    data = _load(CACHE_FILE)
    return data.get(cache_key)


def set_cached_download(cache_key: str, entry: dict):
    data = _load(CACHE_FILE)
    data[cache_key] = {
        **entry,
        "cached_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    _save(CACHE_FILE, data)


# ── User preferences ───────────────────────────────────────────────────────────

def get_pref(user_id: int, key: str, default=None):
    data = _load(PREFS_FILE)
    return data.get(str(user_id), {}).get(key, default)


def set_pref(user_id: int, key: str, value):
    data = _load(PREFS_FILE)
    uid = str(user_id)
    if uid not in data:
        data[uid] = {}
    data[uid][key] = value
    _save(PREFS_FILE, data)


# Blocked users

def get_blocked_users() -> list[int]:
    data = _load(BLOCKED_FILE)
    return sorted(int(uid) for uid in data.get("users", []) if str(uid).isdigit())


def is_blocked(user_id: int) -> bool:
    return user_id in set(get_blocked_users())


def block_user(user_id: int):
    users = set(get_blocked_users())
    users.add(user_id)
    _save(BLOCKED_FILE, {"users": sorted(users)})


def unblock_user(user_id: int):
    users = set(get_blocked_users())
    users.discard(user_id)
    _save(BLOCKED_FILE, {"users": sorted(users)})
