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

from telegram import Update
from telegram import BotCommand
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters,
)
from telegram.constants import ParseMode, ChatAction
from telegram.error import BadRequest

from config import (
    BOT_TOKEN, OWNER_ID, MAX_FILE_SIZE_MB,
    ALLOWED_USERS, DOWNLOAD_PATH, LOCAL_API_URL,
    MAX_CONCURRENT_DOWNLOADS, MAX_DURATION_SECONDS, COOKIES_FILE,
    ENABLE_ARIA2, DATA_PATH,
)
from utils.downloader import (
    detect_platform, get_info, download_media, download_spotify,
    compress_video, fetch_thumb, embed_mp3_metadata, search_platform,
    download_image, download_direct_file, split_video, split_file, CANCELLED,
    get_cookie_file,
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
    kb_cancel_job, kb_admin_panel, kb_main_menu,
)
from utils.database import (
    add_history, get_history, record_download, get_stats,
    get_pref, set_pref, is_blocked, block_user, unblock_user,
    get_blocked_users,
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
# Platforms that only support video (no audio-only streams worth downloading)
VIDEO_ONLY_PLATFORMS = set()
# Platforms that can be attempted through yt-dlp even when they are not named.
UNSUPPORTED_PLATFORMS = set()
# Platforms where image posts are common and we should warn
IMAGE_PLATFORMS = {"instagram", "twitter", "reddit", "tiktok", "facebook"}

def is_allowed(user_id: int) -> bool:
    if is_owner(user_id):
        return True
    if is_blocked(user_id):
        return False
    return not ALLOWED_USERS or user_id in ALLOWED_USERS

def is_owner(user_id: int) -> bool:
    return OWNER_ID != 0 and user_id == OWNER_ID

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

# ─── Spotify playlist downloader ───────────────────────────────────────────────

async def handle_spotify_playlist(query, url: str, audio_format: str, audio_quality: str):
    await safe_edit(query,
        f"🎵 *Spotify Playlist*\n\n"
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

        # Find downloaded files
        files = []
        for ext in [audio_format, "mp3", "m4a", "opus", "flac", "wav"]:
            files = sorted(Path(tmpdir).glob(f"*.{ext}"))
            if files:
                break

        files = files[:PLAYLIST_LIMIT]

        if not files:
            logger.error(f"Playlist stderr: {proc.stderr[:500]}")
            await safe_edit(query, "❌ *No tracks downloaded.*\n\nspotdl couldn't find matches for this playlist.")
            record_download(query.from_user.id, "audio", 0, False)
            return

        await safe_edit(query, f"📤 *Uploading {len(files)} tracks...*")

        sent = 0
        for i, fpath in enumerate(files, 1):
            try:
                await safe_edit(query, f"📤 Uploading track *{i}/{len(files)}*\n`{fpath.stem[:40]}`")
                sz = fpath.stat().st_size / (1024 * 1024)
                with open(fpath, "rb") as f:
                    await query.message.reply_audio(
                        audio=f,
                        title=fpath.stem,
                        performer="Spotify",
                    )
                sent += 1
                record_download(query.from_user.id, "audio", sz, True)
            except Exception as e:
                logger.error(f"Playlist upload track {i} failed: {e}")
                continue

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
                    await query.message.reply_video(video=f, supports_streaming=True)
                else:
                    await query.message.reply_photo(photo=f)
            sent += 1
        except Exception as e:
            logger.error(f"Gallery fallback send failed: {e}")

    if sent:
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

    try:
        async with sem:
            if cancel_event.is_set():
                await safe_edit(query, "❌ *Download cancelled.*")
                record_download(query.from_user.id, fmt, 0, False)
                return

            # Spotify playlist
            if platform == "spotify" and "playlist" in url:
                await handle_spotify_playlist(query, url, audio_format, audio_quality)
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
                        f"Part limit: *{fmt_size(MAX_FILE_SIZE_MB)}*",
                    )
                    try:
                        if fmt == "video":
                            upload_paths = await loop.run_in_executor(
                                None, split_video, filepath, split_dir, MAX_FILE_SIZE_MB
                            )
                            split_mode = "video"
                        else:
                            upload_paths = await loop.run_in_executor(
                                None, split_file, filepath, split_dir, MAX_FILE_SIZE_MB
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

                        if fmt == "audio" or platform == "spotify":
                            embed_mp3_metadata(part_path, info or {"title": title, "uploader": artist}, thumb_bytes)
                            with open(part_path, "rb") as f:
                                await query.message.reply_audio(
                                    audio=f, title=title, performer=artist, thumbnail=thumb_bytes,
                                )
                        elif platform == "direct" or split_mode == "document":
                            caption = f"📎 {part_label}" if part_label else None
                            with open(part_path, "rb") as f:
                                await query.message.reply_document(
                                    document=f,
                                    filename=Path(part_path).name,
                                    caption=caption,
                                )
                        else:
                            caption = f"🎬 {part_label}" if part_label else None
                            with open(part_path, "rb") as f:
                                await query.message.reply_video(
                                    video=f,
                                    supports_streaming=True,
                                    caption=caption,
                                )

                    elapsed = time.time() - start_time
                    suffix = f" ({len(upload_paths)} parts)" if len(upload_paths) > 1 else ""
                    await safe_edit(query, msg_done(title + suffix, size_mb, elapsed))
                    add_history(query.from_user.id, title, url, fmt, size_mb, platform)
                    record_download(query.from_user.id, fmt, size_mb, True)

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
                await query.message.reply_video(video=f, supports_streaming=True)
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
        "`/stats`",
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


# ─── URL message handler ───────────────────────────────────────────────────────

async def handle_url_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text(msg_not_authorized(), parse_mode=ParseMode.MARKDOWN)
        return

    text = update.message.text or ""
    match = URL_RE.search(text)
    if not match:
        return

    url = match.group(0)
    platform = detect_platform(url)

    await update.message.chat.send_action(ChatAction.TYPING)

    # Spotify — skip get_info (DRM), go straight to format picker
    if platform == "spotify":
        k = store_url(url)
        is_playlist = "playlist" in url
        if is_playlist:
            await update.message.reply_text(
                f"🎵 *Spotify Playlist*\n\n"
                f"Choose audio format (up to {PLAYLIST_LIMIT} tracks will be downloaded) 👇",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_audio_format_picker(k, "spotify"),
            )
        else:
            await update.message.reply_text(
                "🎵 *Spotify Track*\n\nChoose your audio format 👇",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_audio_format_picker(k, "spotify"),
            )
        return

    # Fetch info
    info = await get_info(url)

    if not info:
        if platform in IMAGE_PLATFORMS:
            msg = await update.message.reply_text(
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
                        with open(fpath, "rb") as f:
                            if str(fpath).endswith(".mp4"):
                                await update.message.reply_video(video=f)
                            else:
                                await update.message.reply_photo(photo=f)
                    else:
                        # Send in groups of 10 (Telegram limit)
                        for i in range(0, len(files), 10):
                            batch = files[i:i+10]
                            media = []
                            for fpath in batch:
                                with open(fpath, "rb") as f:
                                    data = f.read()
                                if str(fpath).endswith(".mp4"):
                                    media.append(InputMediaVideo(media=data))
                                else:
                                    media.append(InputMediaPhoto(media=data))
                            await update.message.reply_media_group(media=media)
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
            await update.message.reply_text(
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
        await update.message.reply_text(
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
            await update.message.reply_photo(
                photo=thumb, caption=caption,
                parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard,
            )
            return
        except Exception as e:
            logger.warning(f"Failed to reply with photo (thumb: {thumb}): {e}. Falling back to text.")

    await update.message.reply_text(
        caption, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard,
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
                "🎵 *Spotify Track*\n\nChoose your audio format 👇",
                reply_markup=kb_audio_format_picker(nk, "spotify"),
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
        await application.bot.set_my_commands([
            BotCommand("start", "Start the bot"),
            BotCommand("menu", "Open the main menu"),
            BotCommand("help", "Show help"),
            BotCommand("search", "Search media"),
            BotCommand("thumbnail", "Get a YouTube thumbnail"),
            BotCommand("history", "Show download history"),
            BotCommand("setformat", "Set default format"),
            BotCommand("admin", "Owner admin panel"),
        ])

    builder = (
        Application.builder()
        .token(BOT_TOKEN)
        .read_timeout(600)
        .write_timeout(600)
        .connect_timeout(60)
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
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("block", cmd_block))
    app.add_handler(CommandHandler("unblock", cmd_unblock))
    app.add_handler(CommandHandler("blocked", cmd_blocked))
    app.add_handler(CommandHandler("setformat", cmd_setformat))
    app.add_handler(CommandHandler("thumbnail", cmd_thumbnail))
    app.add_handler(CommandHandler("search", cmd_search))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url_message))
    app.add_handler(CallbackQueryHandler(callback_handler))

    logger.info("✅ Bot started.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
