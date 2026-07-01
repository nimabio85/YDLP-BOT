"""
Inline keyboards. All take a short key (8-char hash) not a full URL.
Keys are created by store_url() in bot.py before calling these.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def kb_format_picker(k: str, platform: str = "youtube") -> InlineKeyboardMarkup:
    if platform in ("soundcloud", "spotify"):
        return kb_audio_format_picker(k, platform)
    rows = [
        [
            InlineKeyboardButton("🎬 Best",   callback_data=f"dl|video|best|{k}"),
            InlineKeyboardButton("🔵 4K",     callback_data=f"dl|video|2160|{k}"),
        ],
        [
            InlineKeyboardButton("📱 1080p",  callback_data=f"dl|video|1080|{k}"),
            InlineKeyboardButton("📺 720p",   callback_data=f"dl|video|720|{k}"),
        ],
        [
            InlineKeyboardButton("📼 480p",   callback_data=f"dl|video|480|{k}"),
            InlineKeyboardButton("🎵 Audio",  callback_data=f"dl|audio|pick|{k}"),
        ],
        [
            InlineKeyboardButton("📋 Info",       callback_data=f"info|{k}"),
            InlineKeyboardButton("🎙️ Find Music",  callback_data=f"shazamurl|{k}"),
        ],
    ]
    return InlineKeyboardMarkup(rows)


def kb_direct_download(k: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 Download file", callback_data=f"direct|{k}")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")],
    ])


def kb_cancel_job(job_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancel download", callback_data=f"canceljob|{job_id}")],
    ])


def kb_admin_panel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Stats", callback_data="admin|stats"),
            InlineKeyboardButton("🚫 Blocked", callback_data="admin|blocked"),
        ],
    ])


def kb_main_menu(is_owner: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("📖 Help", callback_data="menu|help"),
            InlineKeyboardButton("📋 History", callback_data="menu|history"),
        ],
        [
            InlineKeyboardButton("🔍 Search", callback_data="menu|search"),
            InlineKeyboardButton("🖼 Thumbnail", callback_data="menu|thumbnail"),
        ],
        [InlineKeyboardButton("⚙️ Settings", callback_data="menu|settings")],
    ]
    if is_owner:
        rows.append([InlineKeyboardButton("🛡 Admin", callback_data="menu|admin")])
    return InlineKeyboardMarkup(rows)


def kb_audio_format_picker(k: str, platform: str = "youtube") -> InlineKeyboardMarkup:
    prefix = "spotdl" if platform == "spotify" else "audio"
    rows = [
        [
            InlineKeyboardButton("🎵 MP3 320k", callback_data=f"{prefix}|mp3|320|{k}"),
            InlineKeyboardButton("🎵 MP3 192k", callback_data=f"{prefix}|mp3|192|{k}"),
        ],
        [
            InlineKeyboardButton("🎵 MP3 128k", callback_data=f"{prefix}|mp3|128|{k}"),
            InlineKeyboardButton("🍎 M4A",      callback_data=f"{prefix}|m4a|0|{k}"),
        ],
        [
            InlineKeyboardButton("🎼 FLAC",     callback_data=f"{prefix}|flac|0|{k}"),
            InlineKeyboardButton("🔊 WAV",      callback_data=f"{prefix}|wav|0|{k}"),
        ],
        [InlineKeyboardButton("« Back", callback_data=f"back|{k}")],
    ]
    return InlineKeyboardMarkup(rows)


def kb_compress(url: str, fmt: str, quality: str) -> InlineKeyboardMarkup:
    from hashlib import md5
    k = md5(url.encode()).hexdigest()[:8]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes, compress it", callback_data=f"compress|{fmt}|{quality}|{k}")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")],
    ])


def kb_search_platform() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔴 YouTube",    callback_data="searchp|youtube"),
            InlineKeyboardButton("🎶 SoundCloud", callback_data="searchp|soundcloud"),
        ],
        [InlineKeyboardButton("🎵 Spotify", callback_data="searchp|spotify")],
    ])


def kb_search_results(results: list, platform: str) -> InlineKeyboardMarkup:
    rows = []
    for i, r in enumerate(results[:5]):
        title = (r.get("title") or r.get("name") or "Unknown")[:35]
        k = r.get("_cache_key")
        if not k:
            continue
        rows.append([InlineKeyboardButton(
            f"{i+1}. {title}",
            callback_data=f"searchr|{platform}|{k}",
        )])
    rows.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    return InlineKeyboardMarkup(rows)


def kb_spotify_confirm(k: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Correct",     callback_data=f"spotdl|mp3|192|{k}"),
            InlineKeyboardButton("❌ Wrong match", callback_data="cancel"),
        ],
        [
            InlineKeyboardButton("🎵 MP3 320k", callback_data=f"spotdl|mp3|320|{k}"),
            InlineKeyboardButton("🍎 M4A",      callback_data=f"spotdl|m4a|0|{k}"),
        ],
    ])


def kb_thumbnail_quality(k: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🖼 Max",   callback_data=f"thumbq|maxres|{k}"),
            InlineKeyboardButton("📸 720p",  callback_data=f"thumbq|hq|{k}"),
        ],
        [
            InlineKeyboardButton("📷 480p",  callback_data=f"thumbq|mq|{k}"),
            InlineKeyboardButton("🔍 240p",  callback_data=f"thumbq|lq|{k}"),
        ],
    ])


def kb_setformat() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎬 Always ask",    callback_data="setfmt|ask"),
            InlineKeyboardButton("🎵 Always audio",  callback_data="setfmt|audio"),
        ],
        [
            InlineKeyboardButton("📱 Always 720p",   callback_data="setfmt|720"),
            InlineKeyboardButton("📺 Always 1080p",  callback_data="setfmt|1080"),
        ],
    ])


def kb_shazam_result(k: str, shazam_url: str | None = None) -> InlineKeyboardMarkup:
    rows = []
    # Row 1: Fast download buttons
    rows.append([
        InlineKeyboardButton("🎵 Download Audio", callback_data=f"shazamdl|audio|{k}"),
        InlineKeyboardButton("🎬 Download Video", callback_data=f"shazamdl|video|{k}"),
    ])
    # Row 2: Search or Link
    row2 = []
    if shazam_url:
        row2.append(InlineKeyboardButton("🔗 Shazam Link", url=shazam_url))
    row2.append(InlineKeyboardButton("🔍 Search manually", callback_data=f"shazamdl|search|{k}"))
    rows.append(row2)
    # Row 3: Dismiss
    rows.append([InlineKeyboardButton("❌ Dismiss", callback_data="cancel")])
    return InlineKeyboardMarkup(rows)
