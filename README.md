# ytdl-bot

_A Telegram bot that downloads video, audio, and gallery posts from dozens of platforms._

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python: 3.12+](https://img.shields.io/badge/Python-3.12%2B-3776AB.svg)](https://www.python.org/)
[![Telegram Bot](https://img.shields.io/badge/Telegram-Bot-26A5E4.svg)](https://core.telegram.org/bots)

---

## ✨ Overview

ytdl-bot downloads videos, audio, image posts, and direct files from dozens of platforms using [yt-dlp](https://github.com/yt-dlp/yt-dlp), [gallery-dl](https://github.com/mikf/gallery-dl), [spotdl](https://github.com/spotDL/spotify-downloader), and [Shazam](https://www.shazam.com/). Send a link, pick a format, and the bot delivers the file straight to your chat.

- **No re-encoding by default** — files are pulled at requested quality, not transcoded unless splitting/compression is needed.
- **No external database** — history, stats, prefs, and cache are all local JSON.
- **No duplicate polling** — a process lock prevents two instances from fighting over the same bot token.

## 🚀 Features

- **Video downloads** — Best, 4K, 1080p, 720p, 480p
- **Audio extraction** — MP3, M4A, FLAC, WAV with embedded metadata and cover art
- **Music identification** — Recognize songs from voice notes, audio, or video messages via Shazam, then download them in one tap
- **Multi-platform support** — YouTube, Instagram, TikTok, Reddit, Twitter/X, Facebook, Twitch, SoundCloud, Spotify, PixelDrain, KrakenFiles, Google Drive, and most other yt-dlp-supported sites
- **Direct file downloads** — Unknown or direct URLs are downloaded as files, with optional `aria2c` acceleration
- **Image and gallery posts** — Uses `gallery-dl` for photo/gallery platforms
- **Search** — Search YouTube and SoundCloud directly from Telegram
- **Automatic file splitting** — Oversized videos and files are split into uploadable parts
- **Download caching** — Repeated requests for the same media are served instantly from a configurable file-id cache
- **Queueing and cancellation** — Concurrency limits with a real cancel button for active downloads
- **Admin controls** — Owner panel, block/unblock users, broadcast, and stats
- **Access control** — Optional user whitelist and per-user blocking
- **Local Bot API support** — Optional 2 GB uploads when using a local Telegram Bot API server

## 📋 Requirements

- [Python 3.12+](https://www.python.org/)
- [ffmpeg](https://ffmpeg.org/) — required for stream merging, audio extraction, and splitting
- [aria2](https://aria2.github.io/) *(optional)* — speeds up direct-file downloads
- A Telegram bot token from [@BotFather](https://t.me/botfather)

> The Docker image already includes ffmpeg and aria2.

## 📦 Installation

### Option A — Docker (recommended)

```bash
git clone https://github.com/nimabio85/YDLP-BOT.git
cd YDLP-BOT

cp .env.example .env
# Edit .env and set BOT_TOKEN=your_token_here

docker compose up -d
docker compose logs -f
```

### Option B — Bare VPS (systemd)

```bash
# 1. Install system dependencies
sudo apt update && sudo apt install -y python3.12 python3.12-venv ffmpeg aria2

# 2. Clone the repository
mkdir -p /root/apps && cd /root/apps
git clone https://github.com/nimabio85/YDLP-BOT.git
cd YDLP-BOT

# 3. Create a virtual environment and install dependencies
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 4. Configure
cp .env.example .env
nano .env   # Set BOT_TOKEN

# 5. Install and start the systemd service
sudo cp ytdl-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ytdl-bot
sudo systemctl status ytdl-bot
```

> View logs with `journalctl -u ytdl-bot -f`.

### Option C — Local development

```bash
cp .env.example .env
# Fill in BOT_TOKEN

pip install -r requirements.txt
python bot.py
```

## 🎛 Configuration

All settings live in `.env`. Copy `.env.example` to get started — no UI panel is included, so every option below is set via environment variables.

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `BOT_TOKEN` | string | — (required) | Bot token from @BotFather |
| `OWNER_ID` | int | `0` | Telegram user ID with admin access (`/stats`, `/admin`, etc.) |
| `ALLOWED_USERS` | string | *(all)* | Comma-separated Telegram user IDs to whitelist |
| `LOCAL_API_URL` | string | *(blank)* | Local Telegram Bot API URL for larger uploads |
| `MAX_FILE_SIZE_MB` | int | `50` *(2000 with local API)* | Maximum upload size in MB |
| `COMPRESS_THRESHOLD_MB` | int | `MAX_FILE_SIZE_MB` | Size above which compression is offered |
| `DOWNLOAD_PATH` | string | `/tmp/ytdl-bot` | Temporary directory for downloads |
| `DATA_PATH` | string | `data` | Directory for history, stats, prefs, and cache |
| `COOKIES_FILE` | string | *(blank)* | Fallback Netscape cookies file |
| `YOUTUBE_COOKIES_FILE` | string | *(blank)* | Site-specific cookies file |
| `INSTAGRAM_COOKIES_FILE` | string | *(blank)* | Site-specific cookies file |
| `TIKTOK_COOKIES_FILE` | string | *(blank)* | Site-specific cookies file |
| `SPOTIFY_COOKIES_FILE` | string | *(blank)* | Site-specific cookies file |
| `TWITTER_COOKIES_FILE` | string | *(blank)* | Site-specific cookies file |
| `FACEBOOK_COOKIES_FILE` | string | *(blank)* | Site-specific cookies file |
| `MAX_CONCURRENT_DOWNLOADS` | int | `2` | Number of simultaneous downloads |
| `MAX_DURATION_SECONDS` | int | `10800` | Reject videos longer than this many seconds |
| `CACHE_TTL_DAYS` | int | `60` | How long cached file IDs remain valid |
| `CACHE_MAX_ENTRIES` | int | `1000` | Maximum number of cached downloads |
| `ENABLE_ARIA2` | bool | `false` | Use `aria2c` for faster direct downloads |
| `SPOTIFY_CLIENT_ID` | string | *(blank)* | Spotify API client ID |
| `SPOTIFY_CLIENT_SECRET` | string | *(blank)* | Spotify API client secret |

## 📖 Usage

1. Start a chat with your bot and run `/start`.
2. Paste a supported media URL or a direct file URL.
3. Pick a format from the inline keyboard when prompted.
4. The bot downloads and sends the file directly to your chat.

### Commands

| Command | Description |
| --- | --- |
| `/start` | Start the bot and view the welcome message |
| `/menu` | Open the main menu |
| `/help` | Show help |
| `/search <query>` | Search YouTube, SoundCloud, or Spotify |
| `/shazam` | Identify music from a voice note, audio, or video |
| `/thumbnail <url>` | Fetch a YouTube thumbnail |
| `/history` | Show your recent downloads |
| `/setformat` | Choose your default download format |
| `/sites` | List supported sites |
| `/stats` | Owner-only bot statistics |
| `/admin` | Owner-only admin panel |
| `/broadcast <message>` | Owner-only broadcast to all users |
| `/block <user_id>` | Block a user (owner only) |
| `/unblock <user_id>` | Unblock a user (owner only) |
| `/blocked` | List blocked users (owner only) |

### Supported Sites

- YouTube / YouTube Shorts
- Instagram (posts, reels, stories)
- TikTok
- X / Twitter
- Facebook / fb.watch
- Reddit / v.redd.it
- SoundCloud
- Spotify (tracks, albums, playlists)
- Twitch (clips)
- PixelDrain, KrakenFiles, Google Drive (direct links)
- Direct files: MP4, MKV, MP3, ZIP, PDF, APK, and more
- Any other site supported by yt-dlp

## 🔑 Cookies for Login-Gated Content

Some platforms block bots or require login. Use a **Netscape-format `cookies.txt`** exported from a browser session that can access the content.

Common use cases:

1. **instagram.com** — private/login-gated posts, reels, stories, rate limits
2. **tiktok.com** — bot checks, region/login-gated videos
3. **youtube.com** — age checks, member/private/unlisted content
4. **spotify.com** / **youtube.com** — helps spotdl find matches more reliably

Place exported files in the `cookies/` folder and reference them in `.env`:

```env
YOUTUBE_COOKIES_FILE=cookies/youtube.txt
INSTAGRAM_COOKIES_FILE=cookies/instagram.txt
TIKTOK_COOKIES_FILE=cookies/tiktok.txt
SPOTIFY_COOKIES_FILE=cookies/spotify.txt
```

A single fallback file can be set with `COOKIES_FILE=cookies.txt`, but separate per-site files are easier to manage.

> Keep cookies private. They can grant access to your logged-in accounts.

## 📡 Local Bot API Server (2 GB Uploads)

By default, Telegram limits bot uploads to 50 MB. Running a local Bot API server raises this to 2 GB. The included `install-local-api.sh` script builds and installs the official server on a VPS.

1. Get an `API_ID` and `API_HASH` from <https://my.telegram.org/apps>.
2. Run the installer:

   ```bash
   sudo bash install-local-api.sh
   ```

3. Add to `.env`:

   ```env
   LOCAL_API_URL=http://localhost:8081
   MAX_FILE_SIZE_MB=2000
   ```

4. Restart the bot.

## 🖼 Preview

<!-- Add a screenshot or GIF here, e.g. -->
<!-- ![ytdl-bot in action](docs/preview.png) -->

_Feel free to add a screenshot of the bot's inline format picker and download flow._

## 🛠 Troubleshooting

There's no built-in diagnostics command — check logs first (`docker compose logs -f` or `journalctl -u ytdl-bot -f`).

| Problem | Solution |
| --- | --- |
| Download fails with "Sign in to confirm you're not a bot" | Add a site-specific cookies file (see [Cookies](#-cookies-for-login-gated-content)) |
| Upload fails for large files | Set up a [local Bot API server](#-local-bot-api-server-2-gb-uploads) or lower `MAX_FILE_SIZE_MB` |
| Audio has no cover art / metadata | Confirm ffmpeg is installed and on `PATH` |
| Spotify tracks won't match | Set `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` and add a Spotify cookies file |
| Bot doesn't respond, no errors | Check for a second running instance — the process lock silently blocks duplicate pollers |
| Site suddenly stops working | Run `pip install -U yt-dlp` (see [Updating yt-dlp](#-updating-yt-dlp)) |

## 💻 Development

### Project structure

```text
.
├── bot.py                 # Entry point: handlers, callbacks, main loop
├── config.py              # Loads and validates environment configuration
├── docker-compose.yml     # Container orchestration
├── Dockerfile             # Container image definition
├── install-local-api.sh   # Local Telegram Bot API server installer
├── requirements.txt       # Python dependencies
├── ytdl-bot.service       # systemd unit file
├── cookies/               # Per-site Netscape cookies (gitignored)
├── data/                  # History, stats, prefs, and cache (gitignored)
└── utils/
    ├── database.py        # JSON-based persistent storage
    ├── downloader.py      # yt-dlp / gallery-dl / spotdl / direct downloads
    ├── formatting.py      # Message templates and markdown helpers
    ├── keyboards.py       # Inline keyboard builders
    ├── shazam_finder.py   # Audio fingerprinting and recognition
    └── url_store.py       # Short key to URL mapping for callbacks
```

### Updating yt-dlp

yt-dlp is updated frequently to keep up with site changes. Update it regularly.

**Docker:**

```bash
docker compose build --no-cache
docker compose up -d
```

**Bare VPS:**

```bash
source /root/apps/YDLP-BOT/venv/bin/activate
pip install -U yt-dlp
sudo systemctl restart ytdl-bot
```

### How it works

- `bot.py` wires up Telegram handlers/callbacks and runs the main polling loop.
- `config.py` loads and validates all `.env` variables on startup.
- `utils/downloader.py` dispatches each URL to yt-dlp, gallery-dl, spotdl, or a raw HTTP/aria2c download based on the platform.
- `utils/database.py` persists history, stats, prefs, and the file-id cache as JSON under `DATA_PATH`.
- A process lock prevents two bot instances from polling the same token simultaneously.

## 📄 License

Licensed under the [Apache License, Version 2.0](LICENSE).

## 🙏 Acknowledgements

- [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- [gallery-dl](https://github.com/mikf/gallery-dl) by mikf
- [spotdl](https://github.com/spotDL/spotify-downloader)
- [Shazam](https://www.shazam.com/)
