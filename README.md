# ytdl-bot

A Telegram bot that downloads videos, audio, image posts, and direct files
from dozens of platforms using [yt-dlp](https://github.com/yt-dlp/yt-dlp),
[gallery-dl](https://github.com/mikf/gallery-dl),
[spotdl](https://github.com/spotDL/spotify-downloader), and
[Shazam](https://www.shazam.com/).

Send a link, pick a format, and the bot delivers the file straight to your
chat.

---

## Features

- **Video downloads** — Best, 4K, 1080p, 720p, 480p
- **Audio extraction** — MP3, M4A, FLAC, WAV with embedded metadata and cover art
- **Music identification** — Recognize songs from voice notes, audio, or video
  messages via Shazam, then download them in one tap
- **Multi-platform support** — YouTube, Instagram, TikTok, Reddit, Twitter/X,
  Facebook, Twitch, SoundCloud, Spotify, PixelDrain, KrakenFiles, Google Drive,
  and most other yt-dlp-supported sites
- **Direct file downloads** — Unknown or direct URLs are downloaded as files,
  with optional `aria2c` acceleration
- **Image and gallery posts** — Uses `gallery-dl` for photo/gallery platforms
- **Search** — Search YouTube and SoundCloud directly from Telegram
- **Automatic file splitting** — Oversized videos and files are split into
  uploadable parts
- **Download caching** — Repeated requests for the same media are served
  instantly from a configurable file-id cache
- **Queueing and cancellation** — Concurrency limits with a real cancel button
  for active downloads
- **Admin controls** — Owner panel, block/unblock users, broadcast, and stats
- **Access control** — Optional user whitelist and per-user blocking
- **Process lock** — Prevents duplicate bot instances from polling the same token
- **Local Bot API support** — Optional 2 GB uploads when using a local Telegram
  Bot API server

---

## Prerequisites

- **Python 3.12+**
- **ffmpeg** — required for stream merging, audio extraction, and splitting
- **aria2** *(optional)* — speeds up direct-file downloads
- **A Telegram bot token** from [@BotFather](https://t.me/botfather)

The Docker image already includes ffmpeg and aria2.

---

## Quick Start

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

View logs:

```bash
journalctl -u ytdl-bot -f
```

### Option C — Local development

```bash
cp .env.example .env
# Fill in BOT_TOKEN

pip install -r requirements.txt
python bot.py
```

---

## Configuration

All settings live in `.env`. Copy `.env.example` to get started.

| Variable | Required | Default | Description |
|---|---|---|---|
| `BOT_TOKEN` | Yes | — | Bot token from @BotFather |
| `OWNER_ID` | No | `0` | Telegram user ID with admin access (`/stats`, `/admin`, etc.) |
| `ALLOWED_USERS` | No | *(all)* | Comma-separated Telegram user IDs to whitelist |
| `LOCAL_API_URL` | No | *(blank)* | Local Telegram Bot API URL for larger uploads |
| `MAX_FILE_SIZE_MB` | No | `50` *(2000 with local API)* | Maximum upload size in MB |
| `COMPRESS_THRESHOLD_MB` | No | `MAX_FILE_SIZE_MB` | Size above which compression is offered |
| `DOWNLOAD_PATH` | No | `/tmp/ytdl-bot` | Temporary directory for downloads |
| `DATA_PATH` | No | `data` | Directory for history, stats, prefs, and cache |
| `COOKIES_FILE` | No | *(blank)* | Fallback Netscape cookies file |
| `YOUTUBE_COOKIES_FILE` | No | *(blank)* | Site-specific cookies file |
| `INSTAGRAM_COOKIES_FILE` | No | *(blank)* | Site-specific cookies file |
| `TIKTOK_COOKIES_FILE` | No | *(blank)* | Site-specific cookies file |
| `SPOTIFY_COOKIES_FILE` | No | *(blank)* | Site-specific cookies file |
| `TWITTER_COOKIES_FILE` | No | *(blank)* | Site-specific cookies file |
| `FACEBOOK_COOKIES_FILE` | No | *(blank)* | Site-specific cookies file |
| `MAX_CONCURRENT_DOWNLOADS` | No | `2` | Number of simultaneous downloads |
| `MAX_DURATION_SECONDS` | No | `10800` | Reject videos longer than this many seconds |
| `CACHE_TTL_DAYS` | No | `60` | How long cached file IDs remain valid |
| `CACHE_MAX_ENTRIES` | No | `1000` | Maximum number of cached downloads |
| `ENABLE_ARIA2` | No | `false` | Use `aria2c` for faster direct downloads |
| `SPOTIFY_CLIENT_ID` | No | *(blank)* | Spotify API client ID |
| `SPOTIFY_CLIENT_SECRET` | No | *(blank)* | Spotify API client secret |

---

## Usage

1. Start a chat with your bot and run `/start`.
2. Paste a supported media URL or a direct file URL.
3. Pick a format from the inline keyboard when prompted.
4. The bot downloads and sends the file directly to your chat.

### Commands

| Command | Description |
|---|---|
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

---

## Supported Sites

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

---

## Cookies

Some platforms block bots or require login. Use a **Netscape-format
`cookies.txt`** exported from a browser session that can access the content.

Common use cases:

- **instagram.com** — private/login-gated posts, reels, stories, rate limits
- **tiktok.com** — bot checks, region/login-gated videos
- **youtube.com** — age checks, member/private/unlisted content
- **spotify.com** / **youtube.com** — helps spotdl find matches more reliably

Place exported files in the `cookies/` folder and reference them in `.env`:

```env
YOUTUBE_COOKIES_FILE=cookies/youtube.txt
INSTAGRAM_COOKIES_FILE=cookies/instagram.txt
TIKTOK_COOKIES_FILE=cookies/tiktok.txt
SPOTIFY_COOKIES_FILE=cookies/spotify.txt
```

A single fallback file can be set with `COOKIES_FILE=cookies.txt`, but
separate per-site files are easier to manage.

> Keep cookies private. They can grant access to your logged-in accounts.

---

## Local Bot API Server (2 GB uploads)

By default, Telegram limits bot uploads to 50 MB. Running a local Bot API
server raises this to 2 GB. The included `install-local-api.sh` script builds
and installs the official server on a VPS.

You will need an `API_ID` and `API_HASH` from <https://my.telegram.org/apps>.

```bash
sudo bash install-local-api.sh
```

Then add to `.env`:

```env
LOCAL_API_URL=http://localhost:8081
MAX_FILE_SIZE_MB=2000
```

Restart the bot afterward.

---

## Updating yt-dlp

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

---

## Project Structure

```
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

---

## Notes

- Telegram bots can send files up to **50 MB** on the public Bot API. Use
  `MAX_FILE_SIZE_MB=50` unless you run a local Bot API server.
- ffmpeg is **required** — yt-dlp uses it to merge video and audio streams,
  extract audio, and split large files.
- aria2 is optional. Enable it with `ENABLE_ARIA2=true` after installing
  `aria2c` for faster direct-file downloads.
- Rebuild Docker or run `pip install -U yt-dlp` periodically to keep up with
  YouTube and other site changes.

---

## License

Licensed under the Apache License, Version 2.0. See the [LICENSE](LICENSE) file
for details.
