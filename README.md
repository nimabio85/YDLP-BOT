# 📥 ytdl-bot — Media Downloader Telegram Bot

A Telegram bot that downloads videos, audio, image posts, and direct files using [yt-dlp](https://github.com/yt-dlp/yt-dlp), `gallery-dl`, and optional `spotdl`.

---

## Features

- **Video downloads** — Best, 4K, 1080p, 720p, 480p
- **Audio extraction** — MP3, M4A, FLAC, WAV
- **Video info** — Title, channel, views, likes, description
- **Multi-platform support** — YouTube, Instagram, TikTok, Reddit, Twitter/X, Facebook, Twitch, SoundCloud, Spotify, PixelDrain, KrakenFiles, and most yt-dlp sites
- **Direct file downloads** — Unknown/direct URLs can be downloaded as files
- **Optional aria2 acceleration** — Direct-file downloads can use `aria2c` when installed
- **Image posts** — Uses `gallery-dl` for photo/gallery platforms
- **Search** — YouTube and SoundCloud search from Telegram
- **History and stats** — User history plus owner-only `/stats`
- **Queueing** — Limits concurrent downloads
- **Real cancel button** — Stop active downloads from Telegram
- **Automatic file splitting** — Oversized videos/direct files are split into uploadable parts
- **Admin controls** — Owner panel plus block/unblock commands
- **Process lock** — Prevents duplicate bot instances from polling the same token
- **User whitelist** — Optional `ALLOWED_USERS` restriction
- **File size guard** — Auto-rejects files exceeding Telegram's limit
- **Local Bot API support** — Optional 2 GB uploads when using a local Telegram Bot API server

---

## Quick Start

### 1. Create your bot

Talk to [@BotFather](https://t.me/botfather) on Telegram:
```
/newbot
```
Copy the token it gives you.

---

### Option A — Docker (recommended)

```bash
git clone https://github.com/yourname/ytdl-bot
cd ytdl-bot

cp .env.example .env
# Edit .env and set BOT_TOKEN=your_token_here

docker compose up -d
docker compose logs -f
```

---

### Option B — Bare VPS (systemd)

```bash
# 1. Install dependencies
sudo apt update && sudo apt install -y python3.12 python3.12-venv ffmpeg aria2

# 2. Clone and set up
mkdir -p /root/apps && cd /root/apps
git clone https://github.com/yourname/ytdl-bot
cd ytdl-bot

# 3. Virtual env
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 4. Configure
cp .env.example .env
nano .env   # Set BOT_TOKEN

# 5. Install and start systemd service
sudo cp ytdl-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ytdl-bot
sudo systemctl status ytdl-bot
```

View logs:
```bash
journalctl -u ytdl-bot -f
```

---

### Option C — Local (dev)

```bash
cp .env.example .env
# Fill in BOT_TOKEN

pip install -r requirements.txt
python bot.py
```

---

## Configuration (`.env`)

| Variable | Required | Default | Description |
|---|---|---|---|
| `BOT_TOKEN` | ✅ | — | From @BotFather |
| `OWNER_ID` | ❌ | `0` | Telegram user ID allowed to use `/stats` |
| `LOCAL_API_URL` | ❌ | *(blank)* | Local Telegram Bot API URL for larger uploads |
| `MAX_FILE_SIZE_MB` | ❌ | `50` | Max upload size. Use up to 2000 with local Bot API |
| `ALLOWED_USERS` | ❌ | *(all)* | Comma-separated Telegram user IDs to whitelist |
| `DOWNLOAD_PATH` | ❌ | `/tmp/ytdl-bot` | Temp directory for downloads |
| `DATA_PATH` | ❌ | `/tmp/ytdl-bot-data` | JSON history/stats/preferences directory |
| `COOKIES_FILE` | ❌ | *(blank)* | Cookies file for sites that require login |
| `MAX_CONCURRENT_DOWNLOADS` | ❌ | `2` | Number of simultaneous downloads |
| `MAX_DURATION_SECONDS` | ❌ | `10800` | Reject videos longer than this many seconds |
| `ENABLE_ARIA2` | ❌ | `false` | Use `aria2c` for faster direct downloads when installed |

---

## Usage

1. Start a chat with your bot: `/start`
2. Paste a supported media URL or direct file URL
3. Pick your format from the inline keyboard when available
4. Bot downloads and sends the file directly

Useful commands:

- `/menu` — open the button menu
- `/search <query>` — search YouTube/SoundCloud
- `/thumbnail <url>` — fetch YouTube thumbnails
- `/history` — show your last downloads
- `/setformat` — choose your default download format
- `/stats` — owner-only bot stats
- `/admin` — owner admin panel
- `/block <user_id>` — block a user
- `/unblock <user_id>` — unblock a user
- `/blocked` — list blocked users

---

## Notes

- Telegram bots can send files up to **50 MB** without Telegram Premium/API tricks. Use `MAX_FILE_SIZE_MB=50`.
- ffmpeg is **required** — yt-dlp uses it to merge video+audio streams, extract MP3, and split large videos.
- aria2 is optional. Set `ENABLE_ARIA2=true` after installing `aria2c` for faster direct-file downloads.
- yt-dlp is updated frequently; run `pip install -U yt-dlp` or rebuild Docker periodically to keep up with YouTube changes.

---

## Cookies

Some platforms block bots or require login cookies. Use a **Netscape-format `cookies.txt`** exported from the same browser account that can view the content.

Most useful cookies:

- `instagram.com` — private/login-gated posts, reels, stories, rate limits
- `tiktok.com` — bot checks, region/login-gated videos
- `youtube.com` — age checks, member/private/unlisted content you can access
- `spotify.com` / `youtube.com` — helps `spotdl` find/download matches more reliably

Put the exported files in the `cookies/` folder:

```env
YOUTUBE_COOKIES_FILE=cookies/youtube.txt
INSTAGRAM_COOKIES_FILE=cookies/instagram.txt
TIKTOK_COOKIES_FILE=cookies/tiktok.txt
SPOTIFY_COOKIES_FILE=cookies/spotify.txt
```

You can also use one fallback file with `COOKIES_FILE=cookies.txt`, but separate files are easier to manage.

Keep this file private. It can grant access to your logged-in accounts.

---

## Update yt-dlp (Docker)

```bash
docker compose build --no-cache
docker compose up -d
```

## Update yt-dlp (bare VPS)

```bash
source /root/apps/ytdl-bot/venv/bin/activate
pip install -U yt-dlp
sudo systemctl restart ytdl-bot
```
