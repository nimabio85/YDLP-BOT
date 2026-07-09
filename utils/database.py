"""
SQLite-based persistent storage for history, stats, user prefs, and cache.
"""
import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from config import DATA_PATH

logger = logging.getLogger(__name__)

HISTORY_FILE = Path(DATA_PATH) / "history.json"
STATS_FILE = Path(DATA_PATH) / "stats.json"
PREFS_FILE = Path(DATA_PATH) / "prefs.json"
BLOCKED_FILE = Path(DATA_PATH) / "blocked_users.json"
CACHE_FILE = Path(DATA_PATH) / "file_cache.json"
DB_FILE = Path(DATA_PATH) / "ytdl_bot.db"


@contextmanager
def _get_conn():
    conn = sqlite3.connect(DB_FILE, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    Path(DATA_PATH).mkdir(parents=True, exist_ok=True)
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                title TEXT,
                url TEXT,
                fmt TEXT,
                size_mb REAL,
                platform TEXT,
                date TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS downloads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                fmt TEXT,
                size_mb REAL,
                success INTEGER,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS preferences (
                user_id INTEGER,
                key TEXT,
                value TEXT,
                PRIMARY KEY (user_id, key)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS blocked_users (
                user_id INTEGER PRIMARY KEY
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS download_cache (
                cache_key TEXT PRIMARY KEY,
                entry_json TEXT,
                cached_at TEXT
            )
        """)
        conn.commit()


def migrate_json_to_sqlite():
    # 1. History
    if HISTORY_FILE.exists():
        try:
            history_data = json.loads(HISTORY_FILE.read_text())
            with _get_conn() as conn:
                for uid_str, entries in history_data.items():
                    try:
                        uid = int(uid_str)
                    except ValueError:
                        continue
                    for entry in entries:
                        conn.execute(
                            "INSERT INTO history (user_id, title, url, fmt, size_mb, platform, date) VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (uid, entry.get("title"), entry.get("url"), entry.get("fmt"), entry.get("size_mb"), entry.get("platform"), entry.get("date"))
                        )
                conn.commit()
            HISTORY_FILE.rename(HISTORY_FILE.with_suffix(".json.bak"))
            logger.info("Migrated history.json to SQLite")
        except Exception as e:
            logger.error(f"Failed to migrate history.json: {e}")

    # 2. Stats
    if STATS_FILE.exists():
        try:
            stats_data = json.loads(STATS_FILE.read_text())
            with _get_conn() as conn:
                downloads_count = stats_data.get("downloads", 0)
                audio_count = stats_data.get("audio", 0)
                video_count = stats_data.get("video", 0)
                failed_count = stats_data.get("failed", 0)
                total_mb = stats_data.get("total_mb", 0.0)
                user_ids = stats_data.get("user_ids", [])
                
                # Insert failed downloads
                for _ in range(failed_count):
                    uid = user_ids[0] if user_ids else 0
                    conn.execute(
                        "INSERT INTO downloads (user_id, fmt, size_mb, success) VALUES (?, ?, ?, ?)",
                        (uid, "unknown", 0.0, 0)
                    )
                
                # Insert successful downloads (estimate sizes)
                success_count = audio_count + video_count
                avg_size = total_mb / success_count if success_count > 0 else 0.0
                
                for _ in range(audio_count):
                    uid = user_ids[0] if user_ids else 0
                    conn.execute(
                        "INSERT INTO downloads (user_id, fmt, size_mb, success) VALUES (?, ?, ?, ?)",
                        (uid, "audio", avg_size, 1)
                    )
                for _ in range(video_count):
                    uid = user_ids[0] if user_ids else 0
                    conn.execute(
                        "INSERT INTO downloads (user_id, fmt, size_mb, success) VALUES (?, ?, ?, ?)",
                        (uid, "video", avg_size, 1)
                    )
                conn.commit()
            STATS_FILE.rename(STATS_FILE.with_suffix(".json.bak"))
            logger.info("Migrated stats.json to SQLite")
        except Exception as e:
            logger.error(f"Failed to migrate stats.json: {e}")

    # 3. Prefs
    if PREFS_FILE.exists():
        try:
            prefs_data = json.loads(PREFS_FILE.read_text())
            with _get_conn() as conn:
                for uid_str, user_prefs in prefs_data.items():
                    try:
                        uid = int(uid_str)
                    except ValueError:
                        continue
                    for key, val in user_prefs.items():
                        conn.execute(
                            "INSERT OR REPLACE INTO preferences (user_id, key, value) VALUES (?, ?, ?)",
                            (uid, key, json.dumps(val))
                        )
                conn.commit()
            PREFS_FILE.rename(PREFS_FILE.with_suffix(".json.bak"))
            logger.info("Migrated prefs.json to SQLite")
        except Exception as e:
            logger.error(f"Failed to migrate prefs.json: {e}")

    # 4. Blocked
    if BLOCKED_FILE.exists():
        try:
            blocked_data = json.loads(BLOCKED_FILE.read_text())
            with _get_conn() as conn:
                for uid in blocked_data.get("users", []):
                    try:
                        uid_val = int(uid)
                    except ValueError:
                        continue
                    conn.execute(
                        "INSERT OR REPLACE INTO blocked_users (user_id) VALUES (?)",
                        (uid_val,)
                    )
                conn.commit()
            BLOCKED_FILE.rename(BLOCKED_FILE.with_suffix(".json.bak"))
            logger.info("Migrated blocked_users.json to SQLite")
        except Exception as e:
            logger.error(f"Failed to migrate blocked_users.json: {e}")

    # 5. Cache
    if CACHE_FILE.exists():
        try:
            cache_data = json.loads(CACHE_FILE.read_text())
            with _get_conn() as conn:
                for key, entry in cache_data.items():
                    cached_at = entry.get("cached_at", "")
                    conn.execute(
                        "INSERT OR REPLACE INTO download_cache (cache_key, entry_json, cached_at) VALUES (?, ?, ?)",
                        (key, json.dumps(entry), cached_at)
                    )
                conn.commit()
            CACHE_FILE.rename(CACHE_FILE.with_suffix(".json.bak"))
            logger.info("Migrated file_cache.json to SQLite")
        except Exception as e:
            logger.error(f"Failed to migrate file_cache.json: {e}")


# ── History ────────────────────────────────────────────────────────────────────

def add_history(user_id: int, title: str, url: str, fmt: str, size_mb: float, platform: str):
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO history (user_id, title, url, fmt, size_mb, platform, date) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, title, url, fmt, round(size_mb, 1), platform, date_str)
        )
        conn.execute(
            """
            DELETE FROM history 
            WHERE user_id = ? 
              AND id NOT IN (
                  SELECT id FROM history 
                  WHERE user_id = ? 
                  ORDER BY id DESC 
                  LIMIT 10
              )
            """,
            (user_id, user_id)
        )
        conn.commit()


def get_history(user_id: int) -> list:
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT title, url, fmt, size_mb, platform, date FROM history WHERE user_id = ? ORDER BY id DESC LIMIT 10",
            (user_id,)
        ).fetchall()
        return [dict(row) for row in rows]


# ── Stats ──────────────────────────────────────────────────────────────────────

def record_download(user_id: int, fmt: str, size_mb: float, success: bool):
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO downloads (user_id, fmt, size_mb, success) VALUES (?, ?, ?, ?)",
            (user_id, fmt, size_mb, 1 if success else 0)
        )
        conn.commit()


def get_stats() -> dict:
    with _get_conn() as conn:
        row_users = conn.execute("SELECT COUNT(DISTINCT user_id) FROM downloads").fetchone()
        row_downloads = conn.execute("SELECT COUNT(*) FROM downloads WHERE success = 1").fetchone()
        row_audio = conn.execute("SELECT COUNT(*) FROM downloads WHERE success = 1 AND fmt = 'audio'").fetchone()
        row_video = conn.execute("SELECT COUNT(*) FROM downloads WHERE success = 1 AND fmt != 'audio'").fetchone()
        row_failed = conn.execute("SELECT COUNT(*) FROM downloads WHERE success = 0").fetchone()
        row_mb = conn.execute("SELECT SUM(size_mb) FROM downloads WHERE success = 1").fetchone()
        
        users_count = row_users[0] if row_users else 0
        downloads_count = row_downloads[0] if row_downloads else 0
        audio_count = row_audio[0] if row_audio else 0
        video_count = row_video[0] if row_video else 0
        failed_count = row_failed[0] if row_failed else 0
        total_mb = row_mb[0] if row_mb and row_mb[0] is not None else 0.0
        
        return {
            "users": users_count,
            "downloads": downloads_count,
            "audio": audio_count,
            "video": video_count,
            "failed": failed_count,
            "total_mb": round(total_mb, 2)
        }


def get_known_user_ids() -> list[int]:
    users: set[int] = set()
    with _get_conn() as conn:
        for r in conn.execute("SELECT DISTINCT user_id FROM downloads"):
            if r[0] is not None:
                users.add(r[0])
        for r in conn.execute("SELECT DISTINCT user_id FROM history"):
            if r[0] is not None:
                users.add(r[0])
        for r in conn.execute("SELECT DISTINCT user_id FROM preferences"):
            if r[0] is not None:
                users.add(r[0])
    return sorted(users)


# Cached Telegram file IDs

def get_cached_download(cache_key: str) -> Optional[dict]:
    with _get_conn() as conn:
        row = conn.execute("SELECT entry_json FROM download_cache WHERE cache_key = ?", (cache_key,)).fetchone()
        if row:
            try:
                return json.loads(row["entry_json"])
            except Exception:
                pass
    return None


def set_cached_download(cache_key: str, entry: dict):
    with _get_conn() as conn:
        full_entry = {
            **entry,
            "cached_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        conn.execute(
            "INSERT OR REPLACE INTO download_cache (cache_key, entry_json, cached_at) VALUES (?, ?, ?)",
            (cache_key, json.dumps(full_entry), full_entry["cached_at"])
        )
        conn.commit()


def delete_cached_download(cache_key: str):
    with _get_conn() as conn:
        conn.execute("DELETE FROM download_cache WHERE cache_key = ?", (cache_key,))
        conn.commit()


def cleanup_download_cache(ttl_days: int = 60, max_entries: int = 1000) -> int:
    now = datetime.now()
    cutoff = now - timedelta(days=max(1, ttl_days))
    removed = 0
    
    with _get_conn() as conn:
        rows = conn.execute("SELECT cache_key, entry_json, cached_at FROM download_cache").fetchall()
        
        kept: list[tuple[str, str, datetime]] = []
        for row in rows:
            key = row["cache_key"]
            entry_json = row["entry_json"]
            cached_at_raw = row["cached_at"] or ""
            try:
                cached_at = datetime.strptime(cached_at_raw, "%Y-%m-%d %H:%M")
            except (TypeError, ValueError):
                cached_at = now
            
            if cached_at < cutoff:
                conn.execute("DELETE FROM download_cache WHERE cache_key = ?", (key,))
                removed += 1
            else:
                kept.append((key, entry_json, cached_at))
        
        kept.sort(key=lambda item: item[2], reverse=True)
        
        if max_entries > 0 and len(kept) > max_entries:
            to_remove = kept[max_entries:]
            for key, _, _ in to_remove:
                conn.execute("DELETE FROM download_cache WHERE cache_key = ?", (key,))
                removed += 1
                
        conn.commit()
    return removed


# ── User preferences ───────────────────────────────────────────────────────────

def get_pref(user_id: int, key: str, default=None):
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM preferences WHERE user_id = ? AND key = ?",
            (user_id, key)
        ).fetchone()
        if row:
            try:
                return json.loads(row["value"])
            except Exception:
                pass
    return default


def set_pref(user_id: int, key: str, value):
    with _get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO preferences (user_id, key, value) VALUES (?, ?, ?)",
            (user_id, key, json.dumps(value))
        )
        conn.commit()


# Blocked users

def get_blocked_users() -> list[int]:
    with _get_conn() as conn:
        rows = conn.execute("SELECT user_id FROM blocked_users").fetchall()
        return sorted(row["user_id"] for row in rows)


def is_blocked(user_id: int) -> bool:
    with _get_conn() as conn:
        row = conn.execute("SELECT 1 FROM blocked_users WHERE user_id = ?", (user_id,)).fetchone()
        return row is not None


def block_user(user_id: int):
    with _get_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO blocked_users (user_id) VALUES (?)", (user_id,))
        conn.commit()


def unblock_user(user_id: int):
    with _get_conn() as conn:
        conn.execute("DELETE FROM blocked_users WHERE user_id = ?", (user_id,))
        conn.commit()


# Initialize database and migrate data on load
init_db()
migrate_json_to_sqlite()
