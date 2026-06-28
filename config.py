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

# ── Cookies ────────────────────────────────────────────────────────────────────
_cookies = os.getenv("COOKIES_FILE", "cookies.txt")
COOKIES_FILE: str = _cookies if Path(_cookies).exists() else ""

def _cookie_path(env_name: str) -> str:
    value = os.getenv(env_name, "")
    return value if value and Path(value).exists() else ""

SITE_COOKIES: dict[str, str] = {
    "youtube": _cookie_path("YOUTUBE_COOKIES_FILE"),
    "instagram": _cookie_path("INSTAGRAM_COOKIES_FILE"),
    "tiktok": _cookie_path("TIKTOK_COOKIES_FILE"),
    "spotify": _cookie_path("SPOTIFY_COOKIES_FILE"),
    "twitter": _cookie_path("TWITTER_COOKIES_FILE"),
    "facebook": _cookie_path("FACEBOOK_COOKIES_FILE"),
}

# ── Queue ──────────────────────────────────────────────────────────────────────
MAX_CONCURRENT_DOWNLOADS: int = int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "2"))
ENABLE_ARIA2: bool = os.getenv("ENABLE_ARIA2", "false").lower() in {"1", "true", "yes", "on"}

# ── Limits ─────────────────────────────────────────────────────────────────────
MAX_DURATION_SECONDS: int = int(os.getenv("MAX_DURATION_SECONDS", str(3 * 3600)))  # 3h

# ── Spotify ────────────────────────────────────────────────────────────────────
SPOTIFY_CLIENT_ID: str = os.getenv("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET: str = os.getenv("SPOTIFY_CLIENT_SECRET", "")
