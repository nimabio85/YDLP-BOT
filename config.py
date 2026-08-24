import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Required ───────────────────────────────────────────────────────────────────
BOT_TOKEN: str = os.environ["BOT_TOKEN"]

# ── Owner (admin) ──────────────────────────────────────────────────────────────
OWNER_ID: int = int(os.getenv("OWNER_ID", "0"))

# ── Local Bot API Server ───────────────────────────────────────────────────────
LOCAL_API_URL: str = os.getenv("LOCAL_API_URL", "")
MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "2000" if LOCAL_API_URL else "50"))
COMPRESS_THRESHOLD_MB: int = int(os.getenv("COMPRESS_THRESHOLD_MB", str(MAX_FILE_SIZE_MB)))

# ── Access control ─────────────────────────────────────────────────────────────
_raw_users = os.getenv("ALLOWED_USERS", "")
ALLOWED_USERS: set[int] = (
    {int(uid.strip()) for uid in _raw_users.split(",") if uid.strip()}
    if _raw_users else set()
)

# ── Paths ──────────────────────────────────────────────────────────────────────
DOWNLOAD_PATH: str = os.getenv("DOWNLOAD_PATH", "/tmp/ytdl-bot")
Path(DOWNLOAD_PATH).mkdir(parents=True, exist_ok=True)

DATA_PATH: str = os.getenv("DATA_PATH", "data")
Path(DATA_PATH).mkdir(parents=True, exist_ok=True)

BASE_DIR = Path(__file__).resolve().parent

# ── Cookies ────────────────────────────────────────────────────────────────────
def _resolve_path(path_str: str) -> str:
    if not path_str:
        return ""
    p = Path(path_str)
    if not p.is_absolute():
        p = BASE_DIR / p
    return str(p) if p.exists() else ""

_cookies = os.getenv("COOKIES_FILE", "cookies.txt")
COOKIES_FILE: str = _resolve_path(_cookies)

def _cookie_path(env_name: str, default_filename: str = "") -> str:
    value = os.getenv(env_name, "")
    if value:
        resolved = _resolve_path(value)
        if resolved:
            return resolved
    if default_filename:
        resolved = _resolve_path(f"cookies/{default_filename}")
        if resolved:
            return resolved
    return ""

SITE_COOKIES: dict[str, str] = {
    "youtube": _cookie_path("YOUTUBE_COOKIES_FILE", "youtube.txt"),
    "instagram": _cookie_path("INSTAGRAM_COOKIES_FILE", "instagram.txt"),
    "tiktok": _cookie_path("TIKTOK_COOKIES_FILE", "tiktok.txt"),
    "spotify": _cookie_path("SPOTIFY_COOKIES_FILE", "spotify.txt"),
    "twitter": _cookie_path("TWITTER_COOKIES_FILE", "twitter.txt"),
    "facebook": _cookie_path("FACEBOOK_COOKIES_FILE", "facebook.txt"),
    "pinterest": _cookie_path("PINTEREST_COOKIES_FILE", "pinterest.txt"),
}

# ── Queue ──────────────────────────────────────────────────────────────────────
import shutil
MAX_CONCURRENT_DOWNLOADS: int = int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "2"))
_raw_aria2 = os.getenv("ENABLE_ARIA2")
if _raw_aria2 is not None:
    ENABLE_ARIA2: bool = _raw_aria2.lower() in {"1", "true", "yes", "on"}
else:
    ENABLE_ARIA2: bool = shutil.which("aria2c") is not None

# ── Limits ─────────────────────────────────────────────────────────────────────
MAX_DURATION_SECONDS: int = int(os.getenv("MAX_DURATION_SECONDS", str(3 * 3600)))  # 3h
CACHE_TTL_DAYS: int = int(os.getenv("CACHE_TTL_DAYS", "60"))
CACHE_MAX_ENTRIES: int = int(os.getenv("CACHE_MAX_ENTRIES", "1000"))
RESTRICT_GROUP_DOWNLOADS: bool = os.getenv("RESTRICT_GROUP_DOWNLOADS", "true").lower() in {"1", "true", "yes", "on"}

# ── Spotify ────────────────────────────────────────────────────────────────────
SPOTIFY_CLIENT_ID: str = os.getenv("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET: str = os.getenv("SPOTIFY_CLIENT_SECRET", "")

# ── Executables & Auto-Updates ──────────────────────────────────────────────────
FFMPEG_LOCATION: str = os.getenv("FFMPEG_LOCATION", "")
AUTO_UPDATE_DEPS: bool = os.getenv("AUTO_UPDATE_DEPS", "true").lower() in {"1", "true", "yes", "on"}
UPDATE_INTERVAL_HOURS: int = int(os.getenv("UPDATE_INTERVAL_HOURS", "24"))

# ── Network & Proxy ────────────────────────────────────────────────────────────
PROXY_URL: str = os.getenv("PROXY_URL", os.getenv("HTTP_PROXY", os.getenv("HTTPS_PROXY", "")))



