import asyncio
import atexit
import hashlib
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

from telegram import InputFile, Update
from telegram import BotCommand, BotCommandScopeChat
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters,
)
from telegram.constants import ParseMode, ChatAction
from telegram.error import BadRequest, NetworkError, TimedOut

from config import (
    BOT_TOKEN, OWNER_ID, MAX_FILE_SIZE_MB,
    ALLOWED_USERS, DOWNLOAD_PATH, LOCAL_API_URL,
    MAX_CONCURRENT_DOWNLOADS, MAX_DURATION_SECONDS, COOKIES_FILE,
    ENABLE_ARIA2, DATA_PATH, CACHE_TTL_DAYS, CACHE_MAX_ENTRIES,
)
from utils.downloader import (
    detect_platform, get_info, download_media, download_spotify,
    compress_video, fetch_thumb, embed_mp3_metadata, search_platform,
    download_image, download_direct_file, split_video, split_file, CANCELLED,
    get_cookie_file, extract_audio_cover,
)
from utils.formatting import (
    msg_start, msg_help, msg_video_card, msg_progress,
    msg_compressing, msg_done, msg_error_too_long,
    msg_error_too_large, msg_offer_compress, msg_error_download_failed,
    msg_error_upload_failed, msg_not_authorized, msg_history,
    msg_admin_stats, msg_thumbnail_pick, msg_spotify_confirm,
    msg_format_audio_pick, msg_search_pick_platform, msg_search_results,
    msg_search_result_item, fmt_duration, fmt_size, escape_markdown,
)
from utils.keyboards import (
    kb_format_picker, kb_audio_format_picker, kb_compress,
    kb_search_platform, kb_search_results, kb_spotify_confirm,
    kb_thumbnail_quality, kb_setformat, kb_direct_download,
    kb_cancel_job, kb_admin_panel, kb_main_menu, kb_shazam_result,
)
from utils.database import (
    add_history, get_history, record_download, get_stats,
    get_pref, set_pref, is_blocked, block_user, unblock_user,
    get_blocked_users, get_known_user_ids, get_cached_download,
    set_cached_download, delete_cached_download, cleanup_download_cache,
)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── URL cache (short key → full URL) ─────────────────────────────────────────
_URL_CACHE: dict[str, str] = {}
_ACTIVE_DOWNLOADS: dict[str, threading.Event] = {}
_LOCK_HANDLE = None

def store_url(url: str) -> str:
    key = hashlib.md5(url.encode()).hexdigest()[:8]
    _URL_CACHE[key] = url
    return key

def resolve_url(key: str) -> Optional[str]:
    return _URL_CACHE.get(key)

def build_final_caption(
    username: str,
    label: str | None = None,
    title: str | None = None,
    platform: str | None = None,
    url: str | None = None,
) -> str:
    lines = []
    if label:
        lines.append(label)
    if title:
        clean_title = " ".join(str(title).split())
        lines.append(f"🎬 {clean_title[:120]}")
    if platform:
        lines.append(f"🔗 {platform.title()}")
    elif url:
        lines.append("🔗 Source")
    lines.append(f"❤️ Downloaded via @{username}")
    return "\n".join(lines)

def final_caption(
    query,
    label: str | None = None,
    title: str | None = None,
    platform: str | None = None,
    url: str | None = None,
) -> str:
    username = "FullSavebot"
    try:
        bot = query.message.get_bot()
        username = getattr(bot, "username", None) or username
    except Exception:
        pass
    return build_final_caption(username, label, title, platform, url)

async def send_upload(send_factory):
    for attempt in range(2):
        try:
            return await send_factory()
        except (TimedOut, NetworkError):
            if attempt:
                raise
            await asyncio.sleep(3)

def upload_call(file_obj, method, **kwargs):
    file_obj.seek(0)
    return method(**kwargs)


class UploadProgressFile:
    def __init__(self, file_obj, total_bytes: int, callback):
        self.file_obj = file_obj
        self.total_bytes = max(total_bytes, 1)
        self.callback = callback
        self.bytes_read = 0
        self.started_at = time.time()
        self.name = getattr(file_obj, "name", "upload.bin")

    def read(self, size=-1):
        chunk = self.file_obj.read(size)
        if chunk:
            self.bytes_read += len(chunk)
            elapsed = max(time.time() - self.started_at, 0.1)
            self.callback(self.bytes_read, self.total_bytes, self.bytes_read / elapsed)
        return chunk

    def seek(self, offset, whence=0):
        pos = self.file_obj.seek(offset, whence)
        if offset == 0 and whence == 0:
            self.bytes_read = 0
            self.started_at = time.time()
        return pos

    def tell(self):
        return self.file_obj.tell()


def make_upload_input(path: str, file_obj, callback) -> InputFile:
    total_bytes = Path(path).stat().st_size
    progress_file = UploadProgressFile(file_obj, total_bytes, callback)
    return InputFile(
        progress_file,
        filename=Path(path).name,
        read_file_handle=False,
    )


def make_download_cache_key(
    url: str,
    fmt: str,
    quality: str,
    audio_format: str,
    audio_quality: str,
) -> str:
    raw = "|".join([url, fmt, quality, audio_format, audio_quality])
    return hashlib.sha256(raw.encode()).hexdigest()


async def send_cached_download(query, cache_key: str, cached: dict) -> bool:
    media_type = cached.get("media_type")
    file_ids = cached.get("file_ids") or []
    if not media_type or not file_ids:
        return False

    await safe_edit(query, "♻️ *Cached file found*\n\nSending instantly...")
    total = len(file_ids)
    try:
        for index, file_id in enumerate(file_ids, 1):
            part_label = f"Part {index}/{total}" if total > 1 else None
            caption = final_caption(
                query,
                f"🎬 {part_label}" if media_type == "video" and part_label else
                f"📎 {part_label}" if media_type == "document" and part_label else
                part_label,
                title=cached.get("title"),
                platform=cached.get("platform"),
            )
            if media_type == "audio":
                await query.message.reply_audio(
                    audio=file_id,
                    title=cached.get("title") or "Audio",
                    performer=cached.get("performer") or "Unknown",
                    caption=caption,
                    **UPLOAD_TIMEOUTS,
                )
            elif media_type == "document":
                await query.message.reply_document(
                    document=file_id,
                    caption=caption,
                    **UPLOAD_TIMEOUTS,
                )
            else:
                await query.message.reply_video(
                    video=file_id,
                    supports_streaming=True,
                    caption=caption,
                    **UPLOAD_TIMEOUTS,
                )
        try:
            await query.message.delete()
        except Exception:
            await safe_edit(query, "✅ *Sent from cache.*")
        return True
    except Exception as e:
        logger.warning(f"Cached send failed, will redownload: {e}")
        delete_cached_download(cache_key)
        return False

def new_job_id(user_id: int, url: str) -> str:
    raw = f"{user_id}:{url}:{time.time()}".encode()
    return hashlib.md5(raw).hexdigest()[:10]

def acquire_process_lock():
    global _LOCK_HANDLE
    lock_path = Path(DATA_PATH) / "bot.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    _LOCK_HANDLE = open(lock_path, "a+", encoding="utf-8")
    _LOCK_HANDLE.seek(0)
    if not _LOCK_HANDLE.read(1):
        _LOCK_HANDLE.write("0")
        _LOCK_HANDLE.flush()

    try:
        _LOCK_HANDLE.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(_LOCK_HANDLE.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(_LOCK_HANDLE.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as e:
        raise RuntimeError("Another bot instance is already running") from e

    _LOCK_HANDLE.seek(0)
    _LOCK_HANDLE.truncate()
    _LOCK_HANDLE.write(str(os.getpid()))
    _LOCK_HANDLE.flush()

    def _release_lock():
        global _LOCK_HANDLE
        if _LOCK_HANDLE is not None:
            try:
                if os.name == "nt":
                    import msvcrt
                    _LOCK_HANDLE.seek(0)
                    msvcrt.locking(_LOCK_HANDLE.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(_LOCK_HANDLE.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            _LOCK_HANDLE.close()
            _LOCK_HANDLE = None

    atexit.register(_release_lock)

# ─── Semaphore ─────────────────────────────────────────────────────────────────
_semaphore: Optional[asyncio.Semaphore] = None

def get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
    return _semaphore

# ─── Constants ─────────────────────────────────────────────────────────────────
URL_RE = re.compile(r"https?://[^\s]+")
SPOTDL_BIN = shutil.which("spotdl") or "spotdl"
PLAYLIST_LIMIT = 20
THUMBNAIL_QUALITY_MAP = {
    "maxres": "maxresdefault",
    "hq": "hqdefault",
    "mq": "mqdefault",
    "lq": "default",
}
UPLOAD_TIMEOUTS = {
    "read_timeout": 900,
    "write_timeout": 900,
    "connect_timeout": 60,
    "pool_timeout": 60,
}
SPLIT_PART_LIMIT_MB = MAX_FILE_SIZE_MB
if not LOCAL_API_URL:
    if MAX_FILE_SIZE_MB <= 10:
        SPLIT_PART_LIMIT_MB = max(1, MAX_FILE_SIZE_MB - 1)
    else:
        SPLIT_PART_LIMIT_MB = max(8, min(MAX_FILE_SIZE_MB - 5, int(MAX_FILE_SIZE_MB * 0.75)))
# Platforms that only support video (no audio-only streams worth downloading)
VIDEO_ONLY_PLATFORMS = set()
# Platforms that can be attempted through yt-dlp even when they are not named.
UNSUPPORTED_PLATFORMS = set()
# Platforms where image posts are common and we should warn
IMAGE_PLATFORMS = {"instagram", "twitter", "reddit", "tiktok", "facebook"}
SPOTIFY_COLLECTION_TYPES = {
    "playlist": "Playlist",
    "album": "Album",
    "artist": "Artist",
    "show": "Show",
}

def is_allowed(user_id: int) -> bool:
    if is_owner(user_id):
        return True
    if is_blocked(user_id):
        return False
    return not ALLOWED_USERS or user_id in ALLOWED_USERS

def is_owner(user_id: int) -> bool:
    return OWNER_ID != 0 and user_id == OWNER_ID

def spotify_collection_type(url: str) -> Optional[str]:
    url_lower = url.lower()
    for path_key, label in SPOTIFY_COLLECTION_TYPES.items():
        if f"/{path_key}/" in url_lower:
            return label
    return None

# ─── Safe message edit ─────────────────────────────────────────────────────────

async def safe_edit(query, text: str, reply_markup=None):
    """Edit message — tries caption first, falls back to text, falls back to plain text."""
    kw = {"parse_mode": ParseMode.MARKDOWN}
    if reply_markup:
        kw["reply_markup"] = reply_markup
    try:
        await query.edit_message_caption(caption=text, **kw)
        return
    except BadRequest:
        pass
    try:
        await query.edit_message_text(text=text, **kw)
        return
    except BadRequest:
        pass

    # Fallback to plain text if Markdown parsing fails
    kw_plain = {}
    if reply_markup:
        kw_plain["reply_markup"] = reply_markup
    try:
        await query.edit_message_caption(caption=text, **kw_plain)
        return
    except BadRequest:
        pass
    try:
        await query.edit_message_text(text=text, **kw_plain)
    except BadRequest:
        pass

# ─── Spotify collection downloader ─────────────────────────────────────────────

async def handle_spotify_playlist(query, url: str, audio_format: str, audio_quality: str):
    collection_type = spotify_collection_type(url) or "Playlist"
    await safe_edit(query,
        f"🎵 *Spotify {collection_type}*\n\n"
        f"Downloading up to *{PLAYLIST_LIMIT} tracks*...\n"
        f"Each track will be sent as it finishes ⏳"
    )

    with tempfile.TemporaryDirectory(dir=DOWNLOAD_PATH) as tmpdir:
        cmd = [
            SPOTDL_BIN, url,
            "--output", tmpdir,
            "--format", audio_format,
        ]
        if audio_quality and audio_quality != "0":
            cmd += ["--bitrate", f"{audio_quality}k"]
        cookie_file = get_cookie_file("spotify")
        if cookie_file:
            cmd += ["--cookie-file", cookie_file]

        try:
            proc = await asyncio.get_event_loop().run_in_executor(
                None, lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
            )
        except subprocess.TimeoutExpired:
            await safe_edit(query, "❌ *Playlist timed out.*\n\nTry with a smaller playlist or single tracks.")
            return

        # Find downloaded files. spotdl may create artist/playlist subfolders.
        files = []
        for ext in [audio_format, "mp3", "m4a", "opus", "flac", "wav"]:
            files = sorted(Path(tmpdir).rglob(f"*.{ext}"))
            if files:
                break

        files = files[:PLAYLIST_LIMIT]

        if not files:
            logger.error(f"Playlist stderr: {proc.stderr[:500]}")
            await safe_edit(query, f"❌ *No tracks downloaded.*\n\nspotdl couldn't find matches for this Spotify {collection_type.lower()}.")
            record_download(query.from_user.id, "audio", 0, False)
            return

        await safe_edit(query, f"📤 *Uploading {len(files)} tracks...*")

        sent = 0
        for i, fpath in enumerate(files, 1):
            try:
                await safe_edit(query, f"📤 Uploading track *{i}/{len(files)}*\n`{fpath.stem[:40]}`")
                sz = fpath.stat().st_size / (1024 * 1024)
                cover_bytes = extract_audio_cover(str(fpath))
                with open(fpath, "rb") as f:
                    await send_upload(
                        lambda: upload_call(
                            f,
                            query.message.reply_audio,
                            audio=f,
                            title=fpath.stem,
                            performer="Spotify",
                            thumbnail=cover_bytes,
                            caption=final_caption(
                                query,
                                title=fpath.stem,
                                platform="spotify",
                                url=url,
                            ),
                            **UPLOAD_TIMEOUTS,
                        )
                    )
                sent += 1
                record_download(query.from_user.id, "audio", sz, True)
            except Exception as e:
                logger.error(f"Playlist upload track {i} failed: {e}")
                continue

        try:
            await query.message.delete()
        except Exception:
            await safe_edit(query, f"✅ *Playlist done!*\n\nSent *{sent}/{len(files)}* tracks successfully.")


# ─── Core download + upload ────────────────────────────────────────────────────

async def send_gallery_fallback(query, url: str, platform: str) -> bool:
    """Try gallery-dl for platforms where posts may be photo/video galleries."""
    if platform not in IMAGE_PLATFORMS:
        return False

    await safe_edit(
        query,
        "🖼 *Trying gallery fallback...*\n\n"
        "This platform sometimes needs the gallery downloader instead of yt-dlp.",
    )
    files = await download_image(url)
    if not files:
        return False

    sent = 0
    total_mb = 0.0
    for fpath in files[:20]:
        path = Path(fpath)
        if not path.exists() or not path.is_file():
            continue
        size_mb = path.stat().st_size / (1024 * 1024)
        total_mb += size_mb
        if size_mb > MAX_FILE_SIZE_MB:
            logger.warning("Skipping gallery file over limit: %s", path)
            continue
        try:
            with open(path, "rb") as f:
                if path.suffix.lower() in {".mp4", ".mov", ".webm", ".mkv"}:
                    await send_upload(
                        lambda: upload_call(
                            f,
                            query.message.reply_video,
                            video=f,
                            supports_streaming=True,
                            caption=final_caption(query, title=path.stem, platform=platform, url=url),
                            **UPLOAD_TIMEOUTS,
                        )
                    )
                else:
                    await send_upload(
                        lambda: upload_call(
                            f,
                            query.message.reply_photo,
                            photo=f,
                            caption=final_caption(query, title=path.stem, platform=platform, url=url),
                            **UPLOAD_TIMEOUTS,
                        )
                    )
            sent += 1
        except Exception as e:
            logger.error(f"Gallery fallback send failed: {e}")

    if sent:
        try:
            await query.message.delete()
        except Exception:
            await safe_edit(query, f"✅ *Sent {sent} media file(s).*")
        add_history(query.from_user.id, f"{platform.title()} media", url, "media", total_mb, platform)
        record_download(query.from_user.id, "media", total_mb, True)
        return True
    return False


async def handle_download(
    query,
    url: str,
    fmt: str,
    quality: str,
    platform: str,
    audio_format: str = "mp3",
    audio_quality: str = "192",
):
    start_time = time.time()
    sem = get_semaphore()
    job_id = new_job_id(query.from_user.id, url)
    cancel_event = threading.Event()
    _ACTIVE_DOWNLOADS[job_id] = cancel_event

    # Show queue position if waiting
    queue_pos = MAX_CONCURRENT_DOWNLOADS - sem._value + 1
    if sem._value == 0:
        await safe_edit(
            query,
            f"⏳ *Queued*\n\nPosition: *#{queue_pos}*\nWaiting for current downloads to finish...",
            reply_markup=kb_cancel_job(job_id),
        )

    # Progress bar throttle
    _last_pct = [0.0]
    _last_upload_pct = [0.0]
    _last_upload_time = [0.0]
    loop = asyncio.get_running_loop()

    def fmt_bytes(num_bytes: int | float | None) -> str:
        if not num_bytes:
            return "?"
        return fmt_size(float(num_bytes) / (1024 * 1024))

    async def on_progress(pct, speed, eta, downloaded=None, total=None):
        if pct - _last_pct[0] < 8:
            return
        _last_pct[0] = pct
        filled = int(pct / 10)
        bar = "█" * filled + "░" * (10 - filled)
        if fmt == "audio":
            label = "🎵 Audio"
        elif fmt == "document":
            label = "📄 File"
        else:
            label = f"🎬 {quality}p" if quality != "best" else "🎬 Best"
        await safe_edit(query,
            f"⬇️ *Downloading* {label}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"`[{bar}]` *{pct:.0f}%*\n"
            f"📊 *{fmt_bytes(downloaded)} / {fmt_bytes(total)}*\n"
            f"⚡ *Speed:* {speed}\n"
            f"⏳ *ETA:* {eta}\n"
            f"━━━━━━━━━━━━━━━━━━━━",
            reply_markup=kb_cancel_job(job_id),
        )

    def sync_progress(pct, speed, eta, downloaded=None, total=None):
        try:
            asyncio.run_coroutine_threadsafe(
                on_progress(pct, speed, eta, downloaded, total), loop
            )
        except Exception:
            pass

    async def on_upload_progress(uploaded, total, speed, label="Upload", part_label=None, filename=""):
        pct = min(uploaded / total * 100, 100)
        now = time.time()
        if pct < 100 and pct - _last_upload_pct[0] < 5 and now - _last_upload_time[0] < 2:
            return
        _last_upload_pct[0] = pct
        _last_upload_time[0] = now
        filled = int(pct / 10)
        bar = "█" * filled + "░" * (10 - filled)
        heading = f"📤 *Uploading {part_label}*" if part_label else f"📤 *Uploading {label}*"
        name_line = f"\n`{filename[:60]}`" if filename else ""
        await safe_edit(
            query,
            f"{heading}{name_line}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"`[{bar}]` *{pct:.0f}%*\n"
            f"📊 *{fmt_size(uploaded / (1024 * 1024))} / {fmt_size(total / (1024 * 1024))}*\n"
            f"⚡ *Speed:* {fmt_size(speed / (1024 * 1024))}/s\n"
            f"━━━━━━━━━━━━━━━━━━━━",
            reply_markup=kb_cancel_job(job_id),
        )

    def make_upload_callback(label="Upload", part_label=None, filename=""):
        def _callback(uploaded, total, speed):
            try:
                asyncio.run_coroutine_threadsafe(
                    on_upload_progress(uploaded, total, speed, label, part_label, filename),
                    loop,
                )
            except Exception:
                pass
        return _callback

    try:
        async with sem:
            if cancel_event.is_set():
                await safe_edit(query, "❌ *Download cancelled.*")
                record_download(query.from_user.id, fmt, 0, False)
                return

            # Spotify playlists/albums/etc.
            if platform == "spotify" and spotify_collection_type(url):
                await handle_spotify_playlist(query, url, audio_format, audio_quality)
                return

            cache_key = make_download_cache_key(url, fmt, quality, audio_format, audio_quality)
            cached = get_cached_download(cache_key)
            if cached and await send_cached_download(query, cache_key, cached):
                add_history(
                    query.from_user.id,
                    cached.get("title") or "Cached media",
                    url,
                    fmt,
                    float(cached.get("size_mb") or 0),
                    platform,
                )
                record_download(query.from_user.id, fmt, float(cached.get("size_mb") or 0), True)
                return

            # Show downloading status
            if fmt == "audio":
                label = "🎵 Audio"
            elif fmt == "document":
                label = "📄 File"
            else:
                label = f"🎬 {quality}p" if quality != "best" else "🎬 Best Quality"
            await safe_edit(
                query,
                f"⬇️ *Downloading* {label}...\n\nPlease wait ⏳",
                reply_markup=kb_cancel_job(job_id),
            )

            with tempfile.TemporaryDirectory(dir=DOWNLOAD_PATH) as tmpdir:
                if platform == "spotify":
                    filepath = await download_spotify(url, tmpdir, audio_format, audio_quality)
                elif platform == "direct":
                    filepath = await download_direct_file(
                        url, tmpdir,
                        progress_callback=sync_progress,
                        cancel_event=cancel_event,
                    )
                else:
                    filepath = await download_media(
                        url, fmt, quality, tmpdir,
                        audio_format=audio_format,
                        audio_quality=audio_quality,
                        progress_callback=sync_progress,
                        cancel_event=cancel_event,
                    )

                if filepath == CANCELLED or cancel_event.is_set():
                    await safe_edit(query, "❌ *Download cancelled.*")
                    record_download(query.from_user.id, fmt, 0, False)
                    return

                if not filepath or not Path(filepath).exists():
                    if await send_gallery_fallback(query, url, platform):
                        return
                    await safe_edit(query, msg_error_download_failed())
                    record_download(query.from_user.id, fmt, 0, False)
                    return

                size_mb = Path(filepath).stat().st_size / (1024 * 1024)

                # Get metadata
                info = await get_info(url) if platform not in ("spotify", "direct") else None
                title = (info.get("title") if info else None) or Path(filepath).stem
                artist = (info.get("uploader") or info.get("channel") or "Unknown") if info else "Unknown"
                thumb_bytes = fetch_thumb(info.get("thumbnail") if info else None)

                upload_paths = [filepath]
                split_mode = None

                if size_mb > MAX_FILE_SIZE_MB:
                    if fmt == "audio":
                        await safe_edit(query, msg_error_too_large(size_mb, MAX_FILE_SIZE_MB, True))
                        return

                    split_dir = str(Path(tmpdir) / "parts")
                    await safe_edit(
                        query,
                        f"✂️ *Splitting file*\n\n"
                        f"Size: *{fmt_size(size_mb)}*\n"
                        f"Part limit: *{fmt_size(SPLIT_PART_LIMIT_MB)}*",
                    )
                    try:
                        if fmt == "video":
                            upload_paths = await loop.run_in_executor(
                                None, split_video, filepath, split_dir, SPLIT_PART_LIMIT_MB
                            )
                            split_mode = "video"
                        else:
                            upload_paths = await loop.run_in_executor(
                                None, split_file, filepath, split_dir, SPLIT_PART_LIMIT_MB
                            )
                            split_mode = "document"
                    except Exception as e:
                        logger.error(f"Split failed: {e}")
                        if fmt == "video":
                            await safe_edit(
                                query,
                                msg_offer_compress(size_mb, MAX_FILE_SIZE_MB),
                                reply_markup=kb_compress(url, fmt, quality),
                            )
                        else:
                            await safe_edit(query, msg_error_too_large(size_mb, MAX_FILE_SIZE_MB, False))
                        return

                    too_large_part = next(
                        (p for p in upload_paths if Path(p).stat().st_size / (1024 * 1024) > MAX_FILE_SIZE_MB),
                        None,
                    )
                    if too_large_part:
                        await safe_edit(
                            query,
                            "⚠️ *Split part is still too large.*\n\nTry a lower quality option or enable the local Bot API.",
                        )
                        return

                await safe_edit(query, f"📤 *Uploading*\n\nSize: *{fmt_size(size_mb)}* ⏳")

                try:
                    total_parts = len(upload_paths)
                    sent_file_ids = []
                    cached_media_type = "video"
                    for index, part_path in enumerate(upload_paths, 1):
                        if cancel_event.is_set():
                            await safe_edit(query, "❌ *Upload cancelled before next part.*")
                            record_download(query.from_user.id, fmt, size_mb, False)
                            return

                        part_label = f"Part {index}/{total_parts}" if total_parts > 1 else None
                        if total_parts > 1:
                            await safe_edit(
                                query,
                                f"📤 *Uploading {part_label}*\n\n"
                                f"`{Path(part_path).name}`",
                            )

                        _last_upload_pct[0] = 0.0
                        _last_upload_time[0] = 0.0
                        part_name = Path(part_path).name
                        if fmt == "audio" or platform == "spotify":
                            cached_media_type = "audio"
                            audio_thumb = thumb_bytes or extract_audio_cover(part_path)
                            embed_mp3_metadata(part_path, info or {"title": title, "uploader": artist}, audio_thumb)
                            with open(part_path, "rb") as f:
                                upload_file = make_upload_input(
                                    part_path,
                                    f,
                                    make_upload_callback("Audio", part_label, part_name),
                                )
                                sent_message = await send_upload(
                                    lambda: upload_call(
                                        upload_file.input_file_content,
                                        query.message.reply_audio,
                                        audio=upload_file,
                                        title=title,
                                        performer=artist,
                                        thumbnail=audio_thumb,
                                        caption=final_caption(
                                            query,
                                            part_label,
                                            title=title,
                                            platform=platform,
                                            url=url,
                                        ),
                                        **UPLOAD_TIMEOUTS,
                                    )
                                )
                            if sent_message and sent_message.audio:
                                sent_file_ids.append(sent_message.audio.file_id)
                        elif platform == "direct" or split_mode == "document":
                            cached_media_type = "document"
                            with open(part_path, "rb") as f:
                                upload_file = make_upload_input(
                                    part_path,
                                    f,
                                    make_upload_callback("File", part_label, part_name),
                                )
                                sent_message = await send_upload(
                                    lambda: upload_call(
                                        upload_file.input_file_content,
                                        query.message.reply_document,
                                        document=upload_file,
                                        filename=Path(part_path).name,
                                        caption=final_caption(
                                            query,
                                            f"📎 {part_label}" if part_label else None,
                                            title=title,
                                            platform=platform,
                                            url=url,
                                        ),
                                        **UPLOAD_TIMEOUTS,
                                    )
                                )
                            if sent_message and sent_message.document:
                                sent_file_ids.append(sent_message.document.file_id)
                        else:
                            cached_media_type = "video"
                            with open(part_path, "rb") as f:
                                upload_file = make_upload_input(
                                    part_path,
                                    f,
                                    make_upload_callback("Video", part_label, part_name),
                                )
                                sent_message = await send_upload(
                                    lambda: upload_call(
                                        upload_file.input_file_content,
                                        query.message.reply_video,
                                        video=upload_file,
                                        supports_streaming=True,
                                        caption=final_caption(
                                            query,
                                            f"🎬 {part_label}" if part_label else None,
                                            title=title,
                                            platform=platform,
                                            url=url,
                                        ),
                                        **UPLOAD_TIMEOUTS,
                                    )
                                )
                            if sent_message and sent_message.video:
                                sent_file_ids.append(sent_message.video.file_id)

                    elapsed = time.time() - start_time
                    suffix = f" ({len(upload_paths)} parts)" if len(upload_paths) > 1 else ""
                    try:
                        await query.message.delete()
                    except Exception:
                        await safe_edit(query, msg_done(title + suffix, size_mb, elapsed))
                    add_history(query.from_user.id, title, url, fmt, size_mb, platform)
                    record_download(query.from_user.id, fmt, size_mb, True)
                    if sent_file_ids:
                        set_cached_download(cache_key, {
                            "media_type": cached_media_type,
                            "file_ids": sent_file_ids,
                            "title": title,
                            "performer": artist,
                            "size_mb": round(size_mb, 1),
                            "platform": platform,
                        })

                except Exception as e:
                    logger.error(f"Upload error: {e}")
                    await safe_edit(query, msg_error_upload_failed(str(e)))
                    record_download(query.from_user.id, fmt, size_mb, False)
    finally:
        _ACTIVE_DOWNLOADS.pop(job_id, None)


async def handle_compress_upload(query, url: str, fmt: str, quality: str, platform: str):
    await safe_edit(query, msg_compressing())
    with tempfile.TemporaryDirectory(dir=DOWNLOAD_PATH) as tmpdir:
        filepath = await download_media(url, fmt, quality, tmpdir)
        if not filepath or not Path(filepath).exists():
            await safe_edit(query, msg_error_download_failed())
            return

        compressed = str(Path(tmpdir) / "compressed.mp4")
        success = await asyncio.get_event_loop().run_in_executor(
            None, compress_video, filepath, compressed, 1900
        )
        if not success or not Path(compressed).exists():
            await safe_edit(query, "❌ *Compression failed.*\nTry a lower quality option.")
            return

        size_mb = Path(compressed).stat().st_size / (1024 * 1024)
        info = await get_info(url)
        title = (info.get("title") if info else None) or "Video"

        await safe_edit(query, f"📤 *Uploading compressed video*\n{fmt_size(size_mb)} ⏳")
        try:
            with open(compressed, "rb") as f:
                await send_upload(
                    lambda: upload_call(
                        f,
                        query.message.reply_video,
                        video=f,
                        supports_streaming=True,
                        caption=final_caption(query, title=title, platform=platform, url=url),
                        **UPLOAD_TIMEOUTS,
                    )
                )
            try:
                await query.message.delete()
            except Exception:
                await safe_edit(query, msg_done(title, size_mb, 0))
            add_history(query.from_user.id, title, url, fmt, size_mb, platform)
            record_download(query.from_user.id, fmt, size_mb, True)
        except Exception as e:
            await safe_edit(query, msg_error_upload_failed(str(e)))


# ─── Command handlers ──────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name or "there"
    await update.message.reply_text(
        msg_start(name, MAX_FILE_SIZE_MB, bool(LOCAL_API_URL)),
        parse_mode=ParseMode.MARKDOWN,
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(msg_help(MAX_FILE_SIZE_MB), parse_mode=ParseMode.MARKDOWN)

async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text(msg_not_authorized(), parse_mode=ParseMode.MARKDOWN)
        return
    await update.message.reply_text(
        "📥 *Media Downloader Menu*\n\n"
        "Send any supported link to download it, or choose an action below.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb_main_menu(is_owner(update.effective_user.id)),
    )

async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    entries = get_history(update.effective_user.id)
    await update.message.reply_text(msg_history(entries), parse_mode=ParseMode.MARKDOWN)

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text(msg_not_authorized(), parse_mode=ParseMode.MARKDOWN)
        return
    stats = get_stats()
    stats["queue"] = MAX_CONCURRENT_DOWNLOADS - get_semaphore()._value
    stats["active"] = len(_ACTIVE_DOWNLOADS)
    stats["aria2"] = ENABLE_ARIA2 and bool(shutil.which("aria2c"))
    await update.message.reply_text(msg_admin_stats(stats), parse_mode=ParseMode.MARKDOWN)

async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text(msg_not_authorized(), parse_mode=ParseMode.MARKDOWN)
        return
    await update.message.reply_text(
        "🛡️ *Admin Panel*\n\n"
        "Commands:\n"
        "`/block <user_id>`\n"
        "`/unblock <user_id>`\n"
        "`/blocked`\n"
        "`/stats`\n"
        "`/broadcast <message>`",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb_admin_panel(),
    )

async def cmd_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text(msg_not_authorized(), parse_mode=ParseMode.MARKDOWN)
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: `/block <user_id>`", parse_mode=ParseMode.MARKDOWN)
        return
    user_id = int(context.args[0])
    if is_owner(user_id):
        await update.message.reply_text("I won't block the owner.")
        return
    block_user(user_id)
    await update.message.reply_text(f"✅ Blocked `{user_id}`", parse_mode=ParseMode.MARKDOWN)

async def cmd_unblock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text(msg_not_authorized(), parse_mode=ParseMode.MARKDOWN)
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: `/unblock <user_id>`", parse_mode=ParseMode.MARKDOWN)
        return
    user_id = int(context.args[0])
    unblock_user(user_id)
    await update.message.reply_text(f"✅ Unblocked `{user_id}`", parse_mode=ParseMode.MARKDOWN)

async def cmd_blocked(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text(msg_not_authorized(), parse_mode=ParseMode.MARKDOWN)
        return
    users = get_blocked_users()
    if not users:
        await update.message.reply_text("🚫 *Blocked Users*\n\nNo blocked users.", parse_mode=ParseMode.MARKDOWN)
        return
    lines = ["🚫 *Blocked Users*"] + [f"`{uid}`" for uid in users]
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text(msg_not_authorized(), parse_mode=ParseMode.MARKDOWN)
        return
    text = " ".join(context.args).strip()
    if not text:
        await update.message.reply_text("Usage: `/broadcast <message>`", parse_mode=ParseMode.MARKDOWN)
        return

    targets = set(get_known_user_ids())
    targets.update(ALLOWED_USERS)
    if OWNER_ID:
        targets.add(OWNER_ID)
    targets = {uid for uid in targets if uid and not is_blocked(uid)}

    sent = 0
    failed = 0
    for user_id in sorted(targets):
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"📢 {text}",
                disable_web_page_preview=True,
            )
            sent += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.warning(f"Broadcast failed for {user_id}: {e}")
            failed += 1

    await update.message.reply_text(f"✅ Broadcast complete.\n\nSent: {sent}\nFailed: {failed}")


async def cmd_sites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text(msg_not_authorized(), parse_mode=ParseMode.MARKDOWN)
        return

    await update.message.reply_text(
        "🌐 *Supported Sites*\n\n"
        "• YouTube / YouTube Shorts\n"
        "• Instagram posts, reels, stories\n"
        "• TikTok\n"
        "• X / Twitter\n"
        "• Facebook / fb.watch\n"
        "• Reddit / v.redd.it\n"
        "• SoundCloud\n"
        "• Spotify tracks, albums, playlists\n"
        "• Twitch clips\n"
        "• Direct files: MP4, MKV, MP3, ZIP, PDF, APK, and more\n"
        "• Pixeldrain, KrakenFiles, Google Drive direct links\n\n"
        "Send a link directly, or use `/search <name>`.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_setformat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚙️ *Default Format*\n\nPick your preferred default:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb_setformat(),
    )

async def cmd_thumbnail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text(
            "🖼 *Thumbnail*\n\nUsage: `/thumbnail <youtube_url>`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    url = args[0]
    k = store_url(url)
    await update.message.reply_text(
        msg_thumbnail_pick(), parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb_thumbnail_quality(k),
    )

async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text(msg_not_authorized(), parse_mode=ParseMode.MARKDOWN)
        return
    query_text = " ".join(context.args) if context.args else ""
    if not query_text:
        await update.message.reply_text(
            "🔍 *Search*\n\nUsage: `/search <query>`\nExample: `/search never gonna give you up`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    context.user_data["search_query"] = query_text
    await update.message.reply_text(
        msg_search_pick_platform(), parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb_search_platform(),
    )


async def cmd_shazam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text(msg_not_authorized(), parse_mode=ParseMode.MARKDOWN)
        return
    await update.message.reply_text(
        "🎙️ *Music Finder (Shazam)*\n\n"
        "Send or forward a voice note, audio file, video, or video note, and I will try to identify the song for you!",
        parse_mode=ParseMode.MARKDOWN,
    )


async def handle_media_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if not message:
        return

    if not is_allowed(update.effective_user.id):
        await message.reply_text(msg_not_authorized(), parse_mode=ParseMode.MARKDOWN)
        return

    voice = message.voice
    audio = message.audio
    video = message.video
    video_note = message.video_note

    media_obj = voice or audio or video or video_note
    if not media_obj:
        return

    status_msg = await message.reply_text("🎙️ *Downloading audio to identify...*", parse_mode=ParseMode.MARKDOWN)

    import tempfile
    from utils.shazam_finder import extract_audio_snippet, recognize_audio

    with tempfile.TemporaryDirectory(dir=DOWNLOAD_PATH) as tmpdir:
        try:
            file_obj = await media_obj.get_file()
            ext = "ogg"
            if audio:
                ext = Path(audio.file_name or "audio.mp3").suffix.lstrip(".") or "mp3"
            elif video:
                ext = Path(video.file_name or "video.mp4").suffix.lstrip(".") or "mp4"
            elif video_note:
                ext = "mp4"

            input_path = str(Path(tmpdir) / f"input.{ext}")
            snippet_path = str(Path(tmpdir) / "snippet.wav")

            await status_msg.edit_text("⏳ *Processing audio fingerprint...*", parse_mode=ParseMode.MARKDOWN)
            await file_obj.download_to_drive(input_path)

            success = await extract_audio_snippet(input_path, snippet_path)
            if not success or not Path(snippet_path).exists():
                await status_msg.edit_text("❌ *Failed to extract audio signature.*", parse_mode=ParseMode.MARKDOWN)
                return

            await status_msg.edit_text("🔍 *Searching Shazam database...*", parse_mode=ParseMode.MARKDOWN)
            result = await recognize_audio(snippet_path)

            if not result or "track" not in result:
                await status_msg.edit_text("❌ *Could not identify this music.*\n\nMake sure the song is playing clearly and there is minimal background noise.", parse_mode=ParseMode.MARKDOWN)
                return

            track = result["track"]
            title = track.get("title", "Unknown Title")
            artist = track.get("subtitle", "Unknown Artist")
            shazam_url = track.get("url")

            album = None
            genres = None
            sections = track.get("sections", [])
            for section in sections:
                if section.get("type") == "SONG":
                    metadata = section.get("metadata", [])
                    for item in metadata:
                        if item.get("title") == "Album":
                            album = item.get("text")
                elif section.get("type") == "GENRE":
                    genres = section.get("name")

            cover_art_url = None
            images = track.get("images")
            if images:
                cover_art_url = images.get("coverarthq") or images.get("coverart")

            search_query = f"{artist} - {title}"
            k = store_url(f"shazam:{search_query}")

            caption = (
                f"🎵 *Song Found!*\n\n"
                f"📌 *Title:* {escape_markdown(title)}\n"
                f"👤 *Artist:* {escape_markdown(artist)}\n"
            )
            if album:
                caption += f"💿 *Album:* {escape_markdown(album)}\n"
            if genres:
                caption += f"🏷️ *Genre:* {escape_markdown(genres)}\n"

            reply_markup = kb_shazam_result(k, shazam_url)

            sent_photo = False
            if cover_art_url:
                thumb_bytes = fetch_thumb(cover_art_url)
                if thumb_bytes:
                    try:
                        await message.reply_photo(
                            photo=thumb_bytes,
                            caption=caption,
                            parse_mode=ParseMode.MARKDOWN,
                            reply_markup=reply_markup
                        )
                        sent_photo = True
                        await status_msg.delete()
                    except Exception as e:
                        logger.warning(f"Failed to send cover art: {e}")

            if not sent_photo:
                await status_msg.edit_text(caption, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

        except Exception as e:
            logger.error(f"Error in handle_media_message: {e}", exc_info=True)
            await status_msg.edit_text(f"❌ *An error occurred during music identification:* {escape_markdown(str(e))}", parse_mode=ParseMode.MARKDOWN)


# ─── URL message handler ───────────────────────────────────────────────────────


async def handle_url_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if not message:
        return

    if not is_allowed(update.effective_user.id):
        await message.reply_text(msg_not_authorized(), parse_mode=ParseMode.MARKDOWN)
        return

    text = message.text or ""
    match = URL_RE.search(text)
    if not match:
        await message.reply_text(
            "Send me a media link to download.\n\n"
            "Examples:\n"
            "`https://youtu.be/...`\n"
            "`https://www.instagram.com/reel/...`\n\n"
            "You can also use `/search <name>` to find a video.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    url = match.group(0)
    platform = detect_platform(url)

    await message.chat.send_action(ChatAction.TYPING)

    # Spotify — skip get_info (DRM), go straight to format picker
    if platform == "spotify":
        k = store_url(url)
        collection_type = spotify_collection_type(url)
        if collection_type:
            await message.reply_text(
                f"🎵 *Spotify {collection_type}*\n\n"
                f"Choose audio format (up to {PLAYLIST_LIMIT} tracks will be downloaded) 👇",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_audio_format_picker(k, "spotify"),
            )
        else:
            await message.reply_text(
                "🎵 *Spotify Track*\n\nChoose your audio format 👇",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_audio_format_picker(k, "spotify"),
            )
        return

    # Fetch info
    info = await get_info(url)

    if not info:
        if platform in IMAGE_PLATFORMS:
            msg = await message.reply_text(
                "🖼 *Fetching media...*",
                parse_mode=ParseMode.MARKDOWN,
            )
            files = await download_image(url)
            if files:
                try:
                    # Send as media group if multiple, single photo if one
                    from telegram import InputMediaPhoto, InputMediaVideo
                    if len(files) == 1:
                        fpath = files[0]
                        media_caption = build_final_caption(
                            context.bot.username,
                            title=Path(fpath).stem,
                            platform=platform,
                            url=url,
                        )
                        with open(fpath, "rb") as f:
                            if str(fpath).endswith(".mp4"):
                                await message.reply_video(video=f, caption=media_caption)
                            else:
                                await message.reply_photo(photo=f, caption=media_caption)
                    else:
                        # Send in groups of 10 (Telegram limit)
                        for i in range(0, len(files), 10):
                            batch = files[i:i+10]
                            media = []
                            for j, fpath in enumerate(batch):
                                with open(fpath, "rb") as f:
                                    data = f.read()
                                caption = (
                                    build_final_caption(
                                        context.bot.username,
                                        title=f"{platform.title()} media",
                                        platform=platform,
                                        url=url,
                                    )
                                    if i == 0 and j == 0 else None
                                )
                                if str(fpath).endswith(".mp4"):
                                    media.append(InputMediaVideo(media=data, caption=caption))
                                else:
                                    media.append(InputMediaPhoto(media=data, caption=caption))
                            await message.reply_media_group(media=media)
                    await msg.delete()
                except Exception as e:
                    logger.error(f"Image send failed: {e}")
                    await msg.edit_text(
                        "❌ *Could not send media.*\n\nThe post may be private or deleted.",
                        parse_mode=ParseMode.MARKDOWN,
                    )
            else:
                await msg.edit_text(
                    "❌ *Media Not Found*\n\n"
                    "This post may be private, deleted, or requires login.\n"
                    "Try logging in and exporting cookies for this platform.",
                    parse_mode=ParseMode.MARKDOWN,
                )
        else:
            k = store_url(url)
            await message.reply_text(
                "📥 *Direct Download?*\n\n"
                "I couldn't read this as a media page, but it may be a direct file link.\n"
                "Tap below and I'll try downloading it as a file.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_direct_download(k),
            )
        return

    # Duration check
    duration = info.get("duration") or 0
    if duration > MAX_DURATION_SECONDS:
        await message.reply_text(
            msg_error_too_long(duration, MAX_DURATION_SECONDS // 3600),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    k = store_url(url)
    caption = msg_video_card(info, platform)
    thumb = info.get("thumbnail")
    keyboard = kb_format_picker(k, platform)

    if thumb:
        try:
            await message.reply_photo(
                photo=thumb, caption=caption,
                parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard,
            )
            return
        except Exception as e:
            logger.warning(f"Failed to reply with photo (thumb: {thumb}): {e}. Falling back to text.")

    await message.reply_text(
        caption, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard,
    )


async def handle_unknown_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if not message:
        return

    if not is_allowed(update.effective_user.id):
        await message.reply_text(msg_not_authorized(), parse_mode=ParseMode.MARKDOWN)
        return

    await message.reply_text(
        "I can download from links. Send a YouTube, Instagram, TikTok, X/Twitter, Facebook, Reddit, SoundCloud, Spotify, or direct file URL.\n\n"
        "Try `/search <name>` if you do not have a link yet.",
        parse_mode=ParseMode.MARKDOWN,
    )


# ─── Callback handler ──────────────────────────────────────────────────────────

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_allowed(query.from_user.id):
        await safe_edit(query, msg_not_authorized())
        return

    data = query.data

    if data.startswith("canceljob|"):
        job_id = data.split("|", 1)[1]
        event = _ACTIVE_DOWNLOADS.get(job_id)
        if event:
            event.set()
            await safe_edit(query, "❌ *Cancelling download...*")
        else:
            await safe_edit(query, "ℹ️ *That download is no longer active.*")
        return

    if data == "cancel":
        await safe_edit(query, "❌ *Cancelled.*")
        return

    if data.startswith("admin|"):
        if not is_owner(query.from_user.id):
            await safe_edit(query, msg_not_authorized())
            return
        action = data.split("|", 1)[1]
        if action == "stats":
            stats = get_stats()
            stats["queue"] = MAX_CONCURRENT_DOWNLOADS - get_semaphore()._value
            stats["active"] = len(_ACTIVE_DOWNLOADS)
            stats["aria2"] = ENABLE_ARIA2 and bool(shutil.which("aria2c"))
            await safe_edit(query, msg_admin_stats(stats), reply_markup=kb_admin_panel())
            return
        if action == "blocked":
            users = get_blocked_users()
            if users:
                text = "🚫 *Blocked Users*\n\n" + "\n".join(f"`{uid}`" for uid in users)
            else:
                text = "🚫 *Blocked Users*\n\nNo blocked users."
            await safe_edit(query, text, reply_markup=kb_admin_panel())
            return

    if data.startswith("menu|"):
        action = data.split("|", 1)[1]
        if action == "help":
            await safe_edit(query, msg_help(MAX_FILE_SIZE_MB), reply_markup=kb_main_menu(is_owner(query.from_user.id)))
            return
        if action == "history":
            await safe_edit(
                query,
                msg_history(get_history(query.from_user.id)),
                reply_markup=kb_main_menu(is_owner(query.from_user.id)),
            )
            return
        if action == "search":
            await safe_edit(
                query,
                "🔍 *Search*\n\n"
                "Use `/search <query>` to search YouTube, SoundCloud, or Spotify.\n\n"
                "Example:\n"
                "`/search passo marcado sped up`",
                reply_markup=kb_main_menu(is_owner(query.from_user.id)),
            )
            return
        if action == "thumbnail":
            await safe_edit(
                query,
                "🖼 *Thumbnail Downloader*\n\n"
                "Use `/thumbnail <youtube_url>` to fetch cover art.\n\n"
                "Example:\n"
                "`/thumbnail https://youtu.be/...`",
                reply_markup=kb_main_menu(is_owner(query.from_user.id)),
            )
            return
        if action == "settings":
            await safe_edit(
                query,
                "⚙️ *Default Format*\n\nPick your preferred default:",
                reply_markup=kb_setformat(),
            )
            return
        if action == "admin":
            if not is_owner(query.from_user.id):
                await safe_edit(query, msg_not_authorized())
                return
            await safe_edit(
                query,
                "🛡️ *Admin Panel*\n\nChoose an admin action below.",
                reply_markup=kb_admin_panel(),
            )
            return

    # Shazam download / search options
    if data.startswith("shazamdl|"):
        _, action, k = data.split("|", 2)
        shazam_query = resolve_url(k)
        if not shazam_query or not shazam_query.startswith("shazam:"):
            await safe_edit(query, "❌ Session expired. Try searching manually.")
            return

        search_query = shazam_query[len("shazam:"):]

        if action == "search":
            context.user_data["search_query"] = search_query
            search_query_esc = escape_markdown(search_query)
            await safe_edit(query, f"🔍 Searching *YouTube* for:\n`{search_query_esc}`...")
            results = await search_platform(search_query, "youtube")
            if not results:
                await safe_edit(query, "❌ No results found. Try a different query.")
                return
            keyed_results = []
            for result in results:
                result_url = result.get("webpage_url") or result.get("url") or ""
                if not result_url:
                    continue
                item = dict(result)
                item["_cache_key"] = store_url(result_url)
                keyed_results.append(item)
            if not keyed_results:
                await safe_edit(query, "❌ No playable results found.")
                return
            results = keyed_results
            context.user_data["search_results"] = results
            lines = [msg_search_results(search_query, "youtube", len(results))]
            for i, r in enumerate(results[:5], 1):
                title = r.get("title") or r.get("name") or "Unknown"
                uploader = r.get("uploader") or r.get("channel") or ""
                duration = fmt_duration(r.get("duration") or 0)
                lines.append(msg_search_result_item(i, title, uploader, duration))
            await safe_edit(query, "\n\n".join(lines), reply_markup=kb_search_results(results, "youtube"))
            return

        # Automatically download the first YouTube search result
        await safe_edit(query, f"⚡ *Searching for download link...*\n`{escape_markdown(search_query)}`")
        results = await search_platform(search_query, "youtube")
        if not results or not (results[0].get("webpage_url") or results[0].get("url")):
            await safe_edit(query, "❌ Could not find a downloadable match on YouTube.")
            return

        best_match_url = results[0].get("webpage_url") or results[0].get("url")
        platform = detect_platform(best_match_url)
        nk = store_url(best_match_url)

        if action == "audio":
            audio_fmt = get_pref(query.from_user.id, "audio_format", "mp3")
            audio_quality = get_pref(query.from_user.id, "audio_quality", "192")
            await handle_download(query, best_match_url, "audio", "audio", platform, audio_fmt, audio_quality)
        else:  # video
            default_fmt = get_pref(query.from_user.id, "default_format", "ask")
            if default_fmt in ("audio", "ask"):
                quality = "best"
            else:
                quality = default_fmt
            await handle_download(query, best_match_url, "video", quality, platform)
        return

    # Set format preference
    if data.startswith("setfmt|"):
        fmt = data.split("|", 1)[1]
        set_pref(query.from_user.id, "default_format", fmt)
        labels = {"ask": "Always ask", "audio": "Always audio", "720": "Always 720p", "1080": "Always 1080p"}
        await safe_edit(query, f"✅ *Default format set to:* {labels.get(fmt, fmt)}")
        return

    # Info card
    if data.startswith("info|"):
        k = data.split("|", 1)[1]
        url = resolve_url(k)
        if not url:
            await safe_edit(query, "❌ Session expired. Send the link again.")
            return
        info = await get_info(url)
        if not info:
            await safe_edit(query, "❌ Failed to fetch info.")
            return
        desc = escape_markdown((info.get("description") or "No description.")[:400])
        tags = escape_markdown(", ".join((info.get("tags") or [])[:8]) or "none")
        title_esc = escape_markdown(info.get('title', 'Unknown')[:60])
        uploader_esc = escape_markdown(info.get('uploader') or info.get('channel') or "Unknown")
        text = (
            f"📊 *Video Info*\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📄 *{title_esc}*\n"
            f"👤 {uploader_esc}\n"
            f"👁 {info.get('view_count', 0):,}  •  👍 {info.get('like_count', 0):,}\n"
            f"⏱ {fmt_duration(info.get('duration', 0))}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🏷 {tags}\n\n"
            f"📝 {desc}"
        )
        await safe_edit(query, text)
        return

    # Thumbnail picker
    if data.startswith("thumb|") and not data.startswith("thumbq|"):
        k = data.split("|", 1)[1]
        await safe_edit(query, msg_thumbnail_pick(), reply_markup=kb_thumbnail_quality(k))
        return

    if data.startswith("thumbq|"):
        _, quality_key, k = data.split("|", 2)
        url = resolve_url(k)
        if not url:
            await safe_edit(query, "❌ Session expired. Send the link again.")
            return
        info = await get_info(url)
        if not info:
            await safe_edit(query, "❌ Could not fetch video info.")
            return
        video_id = info.get("id", "")
        quality_label = THUMBNAIL_QUALITY_MAP.get(quality_key, "maxresdefault")
        thumb_url = f"https://img.youtube.com/vi/{video_id}/{quality_label}.jpg"
        thumb_bytes = fetch_thumb(thumb_url)
        if not thumb_bytes:
            await safe_edit(query, "❌ Could not fetch thumbnail.")
            return
        title = info.get("title", "Thumbnail")
        title_esc = escape_markdown(title)
        try:
            await query.message.reply_photo(
                photo=thumb_bytes,
                caption=f"🖼 *{title_esc[:60]}*",
                parse_mode=ParseMode.MARKDOWN,
            )
            await safe_edit(query, f"🖼 *Thumbnail sent!*\n📄 {title_esc[:50]}")
        except Exception as e:
            logger.warning(f"Failed to send thumbnail bytes: {e}")
            await safe_edit(query, "❌ *Failed to send thumbnail photo.*")
        return

    # Back to format picker
    if data.startswith("back|"):
        k = data.split("|", 1)[1]
        url = resolve_url(k)
        if not url:
            await safe_edit(query, "❌ Session expired. Send the link again.")
            return
        platform = detect_platform(url)
        nk = store_url(url)
        await safe_edit(query, "Choose your format 👇", reply_markup=kb_format_picker(nk, platform))
        return

    # Audio format picker (from video menu)
    if data.startswith("dl|audio|pick|"):
        k = data.split("|", 3)[3]
        url = resolve_url(k)
        if not url:
            await safe_edit(query, "❌ Session expired. Send the link again.")
            return
        nk = store_url(url)
        await safe_edit(query, msg_format_audio_pick(), reply_markup=kb_audio_format_picker(nk))
        return

    # Audio download (from audio format picker)
    if data.startswith("audio|"):
        _, audio_fmt, audio_quality, k = data.split("|", 3)
        url = resolve_url(k)
        if not url:
            await safe_edit(query, "❌ Session expired. Send the link again.")
            return
        platform = detect_platform(url)
        await handle_download(query, url, "audio", "audio", platform, audio_fmt, audio_quality)
        return

    # Spotify download
    if data.startswith("spotdl|"):
        _, audio_fmt, audio_quality, k = data.split("|", 3)
        url = resolve_url(k)
        if not url:
            await safe_edit(query, "❌ Session expired. Send the link again.")
            return
        await handle_download(query, url, "audio", "audio", "spotify", audio_fmt, audio_quality)
        return

    # Direct file download
    if data.startswith("direct|"):
        k = data.split("|", 1)[1]
        url = resolve_url(k)
        if not url:
            await safe_edit(query, "❌ Session expired. Send the link again.")
            return
        await handle_download(query, url, "document", "file", "direct")
        return

    # Compress and upload
    if data.startswith("compress|"):
        _, fmt, quality, k = data.split("|", 3)
        url = resolve_url(k)
        if not url:
            await safe_edit(query, "❌ Session expired. Send the link again.")
            return
        platform = detect_platform(url)
        await handle_compress_upload(query, url, fmt, quality, platform)
        return

    # Search: pick platform
    if data.startswith("searchp|"):
        platform = data.split("|", 1)[1]
        search_query = context.user_data.get("search_query", "")
        if not search_query:
            await safe_edit(query, "❌ Search query lost. Try /search again.")
            return
        search_query_esc = escape_markdown(search_query)
        await safe_edit(query, f"🔍 Searching *{platform.title()}* for:\n`{search_query_esc}`...")
        results = await search_platform(search_query, "youtube" if platform == "spotify" else platform)
        if not results:
            await safe_edit(query, "❌ No results found. Try a different query.")
            return
        keyed_results = []
        for result in results:
            result_url = result.get("webpage_url") or result.get("url") or ""
            if not result_url:
                continue
            item = dict(result)
            item["_cache_key"] = store_url(result_url)
            keyed_results.append(item)
        if not keyed_results:
            await safe_edit(query, "❌ No playable results found. Try a different query.")
            return
        results = keyed_results
        context.user_data["search_results"] = results
        lines = [msg_search_results(search_query, platform, len(results))]
        for i, r in enumerate(results[:5], 1):
            title = r.get("title") or r.get("name") or "Unknown"
            uploader = r.get("uploader") or r.get("channel") or ""
            duration = fmt_duration(r.get("duration") or 0)
            lines.append(msg_search_result_item(i, title, uploader, duration))
        await safe_edit(query, "\n\n".join(lines), reply_markup=kb_search_results(results, platform))
        return

    # Search: result selected
    if data.startswith("searchr|"):
        _, platform, k = data.split("|", 2)
        url = resolve_url(k)
        if not url:
            await safe_edit(query, "❌ Session expired. Try /search again.")
            return
        if platform == "spotify":
            nk = store_url(url)
            await safe_edit(query,
                "🎵 *Audio Result*\n\nChoose your audio format 👇",
                reply_markup=kb_audio_format_picker(nk),
            )
        else:
            info = await get_info(url)
            if not info:
                await safe_edit(query, "❌ Could not fetch info for this result.")
                return
            duration = info.get("duration", 0) or 0
            if duration > MAX_DURATION_SECONDS:
                await safe_edit(query, msg_error_too_long(duration, MAX_DURATION_SECONDS // 3600))
                return
            nk = store_url(url)
            caption = msg_video_card(info, platform)
            keyboard = kb_format_picker(nk, platform)
            thumb = info.get("thumbnail")
            if thumb:
                try:
                    await query.message.reply_photo(
                        photo=thumb, caption=caption,
                        parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard,
                    )
                    await safe_edit(query, "✅ Result loaded above 👆")
                    return
                except Exception as e:
                    logger.warning(f"Failed to reply with search result photo (thumb: {thumb}): {e}. Falling back to text.")

            await safe_edit(query, caption, reply_markup=keyboard)
        return

    # Video download
    if data.startswith("dl|"):
        _, fmt, quality, k = data.split("|", 3)
        url = resolve_url(k)
        if not url:
            await safe_edit(query, "❌ Session expired. Send the link again.")
            return
        platform = detect_platform(url)
        audio_fmt = get_pref(query.from_user.id, "audio_format", "mp3")
        audio_quality = get_pref(query.from_user.id, "audio_quality", "192")
        await handle_download(query, url, fmt, quality, platform, audio_fmt, audio_quality)
        return


# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    acquire_process_lock()
    async def post_init(application: Application):
        removed_cache_entries = cleanup_download_cache(CACHE_TTL_DAYS, CACHE_MAX_ENTRIES)
        if removed_cache_entries:
            logger.info(f"Cleaned {removed_cache_entries} cached file_id entrie(s).")

        public_commands = [
            BotCommand("start", "Start the bot"),
            BotCommand("menu", "Open the main menu"),
            BotCommand("help", "Show help"),
            BotCommand("search", "Search media"),
            BotCommand("shazam", "Identify music using Shazam"),
            BotCommand("sites", "Show supported sites"),
            BotCommand("thumbnail", "Get a YouTube thumbnail"),
            BotCommand("history", "Show download history"),
            BotCommand("setformat", "Set default format"),
        ]
        await application.bot.set_my_commands(public_commands)
        if OWNER_ID:
            await application.bot.set_my_commands(
                [
                    *public_commands,
                    BotCommand("admin", "Owner admin panel"),
                    BotCommand("broadcast", "Broadcast to users"),
                ],
                scope=BotCommandScopeChat(chat_id=OWNER_ID),
            )

    builder = (
        Application.builder()
        .token(BOT_TOKEN)
        .read_timeout(UPLOAD_TIMEOUTS["read_timeout"])
        .write_timeout(UPLOAD_TIMEOUTS["write_timeout"])
        .connect_timeout(UPLOAD_TIMEOUTS["connect_timeout"])
        .pool_timeout(UPLOAD_TIMEOUTS["pool_timeout"])
        .post_init(post_init)
    )
    if LOCAL_API_URL:
        builder = builder.base_url(f"{LOCAL_API_URL}/bot")
        builder = builder.base_file_url(f"{LOCAL_API_URL}/file/bot")
        logger.info(f"🚀 Local Bot API: {LOCAL_API_URL}")

    app = builder.build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("sites", cmd_sites))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app.add_handler(CommandHandler("block", cmd_block))
    app.add_handler(CommandHandler("unblock", cmd_unblock))
    app.add_handler(CommandHandler("blocked", cmd_blocked))
    app.add_handler(CommandHandler("setformat", cmd_setformat))
    app.add_handler(CommandHandler("thumbnail", cmd_thumbnail))
    app.add_handler(CommandHandler("search", cmd_search))
    app.add_handler(CommandHandler("shazam", cmd_shazam))
    app.add_handler(CommandHandler("findmusic", cmd_shazam))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url_message))
    app.add_handler(MessageHandler((filters.VOICE | filters.AUDIO | filters.VIDEO | filters.VIDEO_NOTE) & ~filters.COMMAND, handle_media_message))
    app.add_handler(MessageHandler(~filters.COMMAND, handle_unknown_message))
    app.add_handler(CallbackQueryHandler(callback_handler))

    logger.info("✅ Bot started.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
