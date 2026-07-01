"""
Beautiful message templates for the bot.
All user-facing text lives here.
"""
import re
from typing import Optional


def escape_markdown(text: str) -> str:
    if not text:
        return ""
    # Characters that are special in standard Markdown: _ * ` [
    # We escape them by prefixing a backslash
    return re.sub(r"([_*`\[])", r"\\\1", str(text))



def fmt_duration(seconds: int) -> str:
    seconds = int(seconds or 0)
    h, m, s = seconds // 3600, (seconds % 3600) // 60, seconds % 60
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    return f"{m}:{s:02d}"


def fmt_size(mb: float) -> str:
    if mb >= 1024:
        return f"{mb/1024:.1f} GB"
    return f"{mb:.1f} MB"


def fmt_number(n: int) -> str:
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1000:.1f}K"
    return str(n)


# ── Welcome ────────────────────────────────────────────────────────────────────

def msg_start(username: str, max_mb: int, local_api: bool) -> str:
    tier = "🚀 *2 GB limit active*" if local_api else "⚡ *50 MB limit*"
    username_esc = escape_markdown(username)
    return (
        f"╔══════════════════════════╗\n"
        f"║   🎬 *MediaFetch Bot*       ║\n"
        f"╚══════════════════════════╝\n\n"
        f"Hey *{username_esc}*! 👋\n\n"
        f"I can download from:\n"
        f"  🔴 YouTube  •  🎵 Spotify\n"
        f"  📸 Instagram  •  🎶 SoundCloud\n"
        f"  🐦 Twitter/X  •  📘 Facebook\n"
        f"  🎮 Twitch  •  🤖 Reddit  •  🎵 TikTok\n"
        f"  📁 PixelDrain/KrakenFiles  •  🌐 direct links\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{tier}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"*How to use:*\n"
        f"  • Paste any supported link\n"
        f"  • Send/forward a voice note or video to identify music\n"
        f"  • Use /search to find content\n"
        f"  • Use /thumbnail to grab covers\n"
        f"  • Use /history to see past downloads\n\n"
        f"Type /help for full command list"
    )


def msg_help(max_mb: int) -> str:
    return (
        f"📖 *Command Reference*\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"*📥 Downloads*\n"
        f"  Just paste any supported URL\n\n"
        f"*🔍 Search*\n"
        f"  `/search <query>` — search across platforms\n\n"
        f"*🖼 Thumbnails*\n"
        f"  `/thumbnail <url>` — get video cover art\n\n"
        f"*📋 History*\n"
        f"  `/history` — your last 10 downloads\n\n"
        f"*🎙️ Music Finder*\n"
        f"  `/shazam` — identify music in voice notes/audio/videos\n\n"
        f"*⚙️ Settings*\n"
        f"  `/setformat` — set your default format\n\n"
        f"*🛡️ Admin*\n"
        f"  `/admin` — owner panel\n"
        f"  `/block <user_id>` — block a user\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"*Supported Platforms*\n"
        f"  🔴 YouTube  🎵 Spotify  📸 Instagram\n"
        f"  🐦 Twitter/X  📘 Facebook  🎶 SoundCloud\n"
        f"  🎮 Twitch  🤖 Reddit  🎵 TikTok\n"
        f"  📁 PixelDrain/KrakenFiles  🌐 Direct file links\n"
        f"  plus most sites supported by yt-dlp\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 *Max file size:* {max_mb} MB"
    )


# ── Video info card ────────────────────────────────────────────────────────────

def msg_video_card(info: dict, platform: str = "youtube") -> str:
    title = escape_markdown(info.get("title", "Unknown")[:60])
    uploader = escape_markdown(info.get("uploader") or info.get("channel") or "Unknown")
    duration = fmt_duration(info.get("duration", 0))
    views = fmt_number(info.get("view_count") or 0)
    likes = fmt_number(info.get("like_count") or 0)

    platform_icons = {
        "youtube": "🔴", "spotify": "🎵", "soundcloud": "🎶",
        "instagram": "📸", "twitter": "🐦", "facebook": "📘",
        "twitch": "🎮", "reddit": "🤖", "tiktok": "🎵",
    }
    icon = platform_icons.get(platform, "🌐")

    return (
        f"{icon} *{title}*\n\n"
        f"👤 {uploader}\n"
        f"⏱ {duration}  •  👁 {views}  •  👍 {likes}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Choose your format below 👇"
    )


def msg_spotify_card(track: dict) -> str:
    name = escape_markdown(track.get("name", "Unknown")[:60])
    artists = escape_markdown(", ".join(a["name"] for a in track.get("artists", [])))
    album = escape_markdown(track.get("album", {}).get("name", "Unknown"))
    duration = fmt_duration(track.get("duration_ms", 0) // 1000)
    return (
        f"🎵 *{name}*\n\n"
        f"👤 {artists}\n"
        f"💿 {album}\n"
        f"⏱ {duration}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Choose audio format below 👇"
    )


# ── Search results ─────────────────────────────────────────────────────────────

def msg_search_pick_platform() -> str:
    return (
        f"🔍 *Search*\n\n"
        f"Which platform do you want to search?\n\n"
        f"Pick one below 👇"
    )


def msg_search_results(query: str, platform: str, count: int) -> str:
    icons = {
        "youtube": "🔴 YouTube", "soundcloud": "🎶 SoundCloud", "spotify": "🎵 Spotify"
    }
    query_esc = escape_markdown(query)
    return (
        f"🔍 *{icons.get(platform, platform)} Results*\n\n"
        f"Query: `{query_esc}`\n"
        f"Found *{count}* results — pick one below 👇"
    )


def msg_search_result_item(i: int, title: str, uploader: str, duration: str) -> str:
    title_esc = escape_markdown(title[:45])
    uploader_esc = escape_markdown(uploader)
    return f"{i}. *{title_esc}*\n    👤 {uploader_esc}  •  ⏱ {duration}"


# ── Download status ────────────────────────────────────────────────────────────

def msg_downloading(fmt: str, quality: str, queue_pos: int = 0) -> str:
    fmt_label = {
        "audio": "🎵 Audio",
        "video": f"🎬 Video {quality}p" if quality != "best" else "🎬 Video (Best)",
    }.get(fmt, fmt)

    queue_note = f"\n⏳ *Queue position:* #{queue_pos}" if queue_pos > 1 else ""
    return (
        f"⬇️ *Downloading*\n\n"
        f"Format: {fmt_label}{queue_note}\n\n"
        f"Please wait..."
    )


def msg_progress(percent: float, speed: str, eta: str, fmt_label: str) -> str:
    filled = int(percent / 10)
    bar = "█" * filled + "░" * (10 - filled)
    return (
        f"⬇️ *Downloading*\n\n"
        f"`[{bar}]` {percent:.0f}%\n\n"
        f"⚡ {speed}  •  ⏳ ETA: {eta}\n"
        f"Format: {fmt_label}"
    )


def msg_compressing() -> str:
    return (
        f"🗜 *Compressing*\n\n"
        f"File is large — re-encoding with optimized settings...\n"
        f"This may take a few minutes ⏳"
    )


def msg_uploading(size_mb: float) -> str:
    return (
        f"📤 *Uploading*\n\n"
        f"Size: *{fmt_size(size_mb)}*\n"
        f"Sending to Telegram... 🚀"
    )


def msg_done(title: str, size_mb: float, duration_s: float) -> str:
    title_esc = escape_markdown(title[:50])
    return (
        f"✅ *Done!*\n\n"
        f"📄 {title_esc}\n"
        f"📦 {fmt_size(size_mb)}  •  ⏱ took {duration_s:.0f}s"
    )


# ── Errors ─────────────────────────────────────────────────────────────────────

def msg_error_too_long(duration: int, max_h: int) -> str:
    return (
        f"⛔ *Video Too Long*\n\n"
        f"Duration: *{fmt_duration(duration)}*\n"
        f"Limit: *{max_h}h*\n\n"
        f"Sorry, I can't download videos longer than {max_h} hours."
    )


def msg_error_too_large(size_mb: float, limit_mb: int, is_audio: bool) -> str:
    tip = "Try a lower quality option." if not is_audio else "The audio file is too large."
    return (
        f"⚠️ *File Too Large*\n\n"
        f"Size: *{fmt_size(size_mb)}*\n"
        f"Limit: *{fmt_size(limit_mb)}*\n\n"
        f"{tip}"
    )


def msg_offer_compress(size_mb: float, limit_mb: int) -> str:
    return (
        f"⚠️ *File Too Large*\n\n"
        f"Size: *{fmt_size(size_mb)}*  •  Limit: *{fmt_size(limit_mb)}*\n\n"
        f"I can compress this video using optimized H.264 settings.\n"
        f"Quality will be slightly reduced but the file will be much smaller.\n\n"
        f"Want me to compress it? 👇"
    )


def msg_error_download_failed() -> str:
    return (
        f"❌ *Download Failed*\n\n"
        f"Possible reasons:\n"
        f"  • Video is private or deleted\n"
        f"  • Geo-restricted content\n"
        f"  • Platform blocked the request\n\n"
        f"Try refreshing your cookies or use a different link."
    )


def msg_error_upload_failed(reason: str) -> str:
    reason_esc = escape_markdown(reason[:100])
    return (
        f"❌ *Upload Failed*\n\n"
        f"Reason: `{reason_esc}`\n\n"
        f"Please try again."
    )


def msg_not_authorized() -> str:
    return "⛔ *Not Authorized*\n\nYou don't have permission to use this bot."


def msg_queue_full(position: int) -> str:
    return (
        f"⏳ *Queue Full*\n\n"
        f"Your download is queued at position *#{position}*\n"
        f"Please wait for current downloads to finish."
    )


# ── History ────────────────────────────────────────────────────────────────────

def msg_history(entries: list) -> str:
    if not entries:
        return (
            f"📋 *Download History*\n\n"
            f"No downloads yet!\n"
            f"Send me a link to get started 🚀"
        )
    lines = [f"📋 *Your Last {len(entries)} Downloads*\n"]
    for i, e in enumerate(entries, 1):
        icon = "🎵" if e.get("fmt") == "audio" else "🎬"
        title_esc = escape_markdown(e.get('title', 'Unknown')[:40])
        lines.append(
            f"{i}. {icon} *{title_esc}*\n"
            f"    📦 {fmt_size(e.get('size_mb', 0))}  •  🕐 {e.get('date', '')}"
        )
    return "\n\n".join(lines)


# ── Admin ──────────────────────────────────────────────────────────────────────

def msg_admin_stats(stats: dict) -> str:
    return (
        f"📊 *Admin Stats*\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 *Total Users:* {stats.get('users', 0)}\n"
        f"📥 *Total Downloads:* {stats.get('downloads', 0)}\n"
        f"📦 *Data Transferred:* {fmt_size(stats.get('total_mb', 0))}\n"
        f"🎵 *Audio Downloads:* {stats.get('audio', 0)}\n"
        f"🎬 *Video Downloads:* {stats.get('video', 0)}\n"
        f"❌ *Failed:* {stats.get('failed', 0)}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🟢 *Bot Status:* Online\n"
        f"⚡ *Queue:* {stats.get('queue', 0)} active\n"
        f"📥 *Running Jobs:* {stats.get('active', 0)}\n"
        f"🚀 *aria2:* {'enabled' if stats.get('aria2') else 'off'}"
    )


# ── Thumbnail ──────────────────────────────────────────────────────────────────

def msg_thumbnail_pick() -> str:
    return (
        f"🖼 *Thumbnail Downloader*\n\n"
        f"Choose thumbnail quality 👇"
    )


# ── Spotify confirm ────────────────────────────────────────────────────────────

def msg_spotify_confirm(track_name: str, artist: str, yt_title: str) -> str:
    track_name_esc = escape_markdown(track_name)
    artist_esc = escape_markdown(artist)
    yt_title_esc = escape_markdown(yt_title[:60])
    return (
        f"🎵 *Spotify Match Found*\n\n"
        f"*Track:* {track_name_esc}\n"
        f"*Artist:* {artist_esc}\n\n"
        f"📺 *Will download from:*\n"
        f"`{yt_title_esc}`\n\n"
        f"Does this look correct? 👇"
    )


# ── Format picker ──────────────────────────────────────────────────────────────

def msg_format_audio_pick() -> str:
    return (
        f"🎵 *Choose Audio Format*\n\n"
        f"Pick your preferred format and quality 👇"
    )

