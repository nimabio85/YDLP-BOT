import asyncio
import mimetypes
import logging
import math
import re
import shutil
import subprocess
import time
import urllib.request
from urllib.parse import unquote, urlparse
from uuid import uuid4
from pathlib import Path
from typing import Optional, Callable

import yt_dlp

from config import COOKIES_FILE, DOWNLOAD_PATH, ENABLE_ARIA2, SITE_COOKIES

logger = logging.getLogger(__name__)
CANCELLED = "__CANCELLED__"


class DownloadCancelled(Exception):
    pass

PLATFORM_DOMAINS = {
    "youtube": ["youtube.com", "youtu.be"],
    "instagram": ["instagram.com"],
    "twitter": ["twitter.com", "x.com"],
    "facebook": ["facebook.com", "fb.watch"],
    "soundcloud": ["soundcloud.com"],
    "twitch": ["twitch.tv", "clips.twitch.tv"],
    "reddit": ["reddit.com", "v.redd.it"],
    "tiktok": ["tiktok.com"],
    "spotify": ["open.spotify.com"],
    "pixeldrain": ["pixeldrain.com"],
    "krakenfiles": ["krakenfiles.com"],
    "google_drive": ["drive.google.com"],
}

AUDIO_PLATFORMS = {"soundcloud", "spotify"}  # default to audio
DIRECT_EXTENSIONS = {
    ".mp4", ".mkv", ".mov", ".avi", ".webm", ".mp3", ".m4a", ".flac", ".wav",
    ".ogg", ".opus", ".zip", ".rar", ".7z", ".pdf", ".apk", ".exe",
}


def detect_platform(url: str) -> str:
    url_lower = url.lower()
    for platform, domains in PLATFORM_DOMAINS.items():
        if any(d in url_lower for d in domains):
            return platform
    parsed = urlparse(url_lower)
    if Path(parsed.path).suffix in DIRECT_EXTENSIONS:
        return "direct"
    return "generic"


def is_audio_platform(platform: str) -> bool:
    return platform in AUDIO_PLATFORMS


def get_cookie_file(platform_or_url: str = "") -> str:
    key = platform_or_url
    if "://" in platform_or_url:
        key = detect_platform(platform_or_url)
    if key == "spotify":
        return SITE_COOKIES.get("spotify") or SITE_COOKIES.get("youtube") or COOKIES_FILE
    return SITE_COOKIES.get(key, "") or COOKIES_FILE


def ydl_base_opts(extra: dict = None, url: str = "") -> dict:
    cookie_file = get_cookie_file(url)
    opts = {
        "quiet": True,
        "no_warnings": True,
        "retries": 3,
        "fragment_retries": 3,
        "socket_timeout": 30,
        "concurrent_fragment_downloads": 8,
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/138.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },
        'js_runtimes': {
            'node': {},
            'deno': {}
        },
        **({"cookiefile": cookie_file} if cookie_file else {}),
    }
    
    # Explicit env override only — never clobber per-site cookies with the default file
    import os
    env_cookie = os.getenv('YT_DLP_COOKIE_FILE')
    if env_cookie and os.path.exists(env_cookie):
        opts['cookiefile'] = env_cookie

    if extra:
        opts.update(extra)
    return opts


# ── Info cache: avoid re-extracting the same URL twice (big win for Instagram) ──
_INFO_CACHE: dict[str, tuple[float, dict]] = {}
_INFO_CACHE_TTL = 600  # seconds


def _cache_info(url: str, info: Optional[dict]):
    if not info or not url:
        return
    if len(_INFO_CACHE) >= 64:
        oldest = min(_INFO_CACHE, key=lambda k: _INFO_CACHE[k][0])
        _INFO_CACHE.pop(oldest, None)
    _INFO_CACHE[url] = (time.time(), info)


def _cached_info(url: str) -> Optional[dict]:
    entry = _INFO_CACHE.get(url)
    if entry:
        if time.time() - entry[0] < _INFO_CACHE_TTL:
            return entry[1]
        _INFO_CACHE.pop(url, None)
    return None


async def get_info(url: str) -> Optional[dict]:
    cached = _cached_info(url)
    if cached:
        return cached
    opts = ydl_base_opts({"skip_download": True}, url=url)
    try:
        loop = asyncio.get_event_loop()
        def _extract():
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(url, download=False)
        info = await loop.run_in_executor(None, _extract)
        _cache_info(url, info)
        return info
    except Exception as e:
        logger.error(f"Info extraction failed: {e}")
        return None


async def search_platform(query: str, platform: str, max_results: int = 5) -> list[dict]:
    """Search a platform and return list of result dicts."""
    search_map = {
        "youtube": f"ytsearch{max_results}:{query}",
        "soundcloud": f"scsearch{max_results}:{query}",
    }
    search_url = search_map.get(platform)
    if not search_url:
        return []

    opts = ydl_base_opts({"skip_download": True, "extract_flat": True}, url=search_url)
    try:
        loop = asyncio.get_event_loop()
        def _search():
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(search_url, download=False)
                entries = info.get("entries", []) if info else []
                normalized = []
                for entry in entries:
                    if not entry:
                        continue
                    item = dict(entry)
                    webpage_url = item.get("webpage_url") or item.get("original_url")
                    raw_url = item.get("url") or ""
                    video_id = item.get("id") or raw_url
                    if platform == "youtube":
                        if not webpage_url:
                            if raw_url.startswith("http"):
                                webpage_url = raw_url
                            elif video_id:
                                webpage_url = f"https://www.youtube.com/watch?v={video_id}"
                    elif platform == "soundcloud" and not webpage_url and raw_url.startswith("http"):
                        webpage_url = raw_url
                    if webpage_url:
                        item["url"] = webpage_url
                        item["webpage_url"] = webpage_url
                        normalized.append(item)
                return normalized
        return await loop.run_in_executor(None, _search)
    except Exception as e:
        logger.error(f"Search failed: {e}")
        return []


def make_progress_hook(callback: Callable, cancel_event=None) -> Callable:
    """Returns a yt-dlp progress hook that calls callback(percent, speed, eta, downloaded, total)."""
    def hook(d):
        if cancel_event and cancel_event.is_set():
            raise DownloadCancelled("Download cancelled")
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
            downloaded = d.get("downloaded_bytes", 0)
            percent = (downloaded / total * 100) if total else 0
            speed = d.get("_speed_str", "?").strip()
            eta = d.get("_eta_str", "?").strip()
            try:
                callback(percent, speed, eta, downloaded, total)
            except Exception:
                pass
    return hook


def _format_speed(bytes_per_second: float) -> str:
    if bytes_per_second <= 0:
        return "?"
    units = ["B/s", "KB/s", "MB/s", "GB/s"]
    value = float(bytes_per_second)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}"
        value /= 1024
    return "?"


def _format_eta(seconds: float) -> str:
    if seconds <= 0:
        return "?"
    seconds = int(seconds)
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}:{sec:02d}"


def _filename_from_headers(url: str, headers) -> str:
    disposition = headers.get("Content-Disposition", "")
    if "filename=" in disposition:
        name = disposition.split("filename=", 1)[1].strip().strip('"')
    else:
        name = Path(unquote(urlparse(url).path)).name

    name = "".join(ch for ch in name if ch not in '<>:"/\\|?*').strip()
    if not name:
        content_type = headers.get_content_type() if hasattr(headers, "get_content_type") else ""
        ext = mimetypes.guess_extension(content_type) or ".bin"
        name = f"download-{uuid4().hex[:8]}{ext}"
    return name[:180]


async def download_direct_file(
    url: str,
    out_dir: str,
    progress_callback: Optional[Callable] = None,
    cancel_event=None,
) -> Optional[str]:
    """Download a plain/direct file URL with browser-like headers and progress."""
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138 Safari/537.36"
        ),
        "Accept": "*/*",
    }

    try:
        loop = asyncio.get_event_loop()

        def _download():
            if ENABLE_ARIA2 and shutil.which("aria2c"):
                return _download_direct_with_aria2(url, out_dir, progress_callback, cancel_event)

            try:
                # Try downloading using curl_cffi to bypass Cloudflare
                from curl_cffi import requests as curl_requests
                
                response = curl_requests.get(url, headers=headers, impersonate="chrome", stream=True, timeout=900)
                response.raise_for_status()
                
                total = int(response.headers.get("Content-Length") or 0)
                filename = _filename_from_headers(url, response.headers)
                target = Path(out_dir) / filename

                downloaded = 0
                start = last_report = time.time()
                with open(target, "wb") as f:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if cancel_event and cancel_event.is_set():
                            raise DownloadCancelled("Download cancelled")
                        if not chunk:
                            continue
                        f.write(chunk)
                        downloaded += len(chunk)

                        if progress_callback and total:
                            now = time.time()
                            if now - last_report >= 2:
                                elapsed = max(now - start, 0.1)
                                speed = downloaded / elapsed
                                remaining = max(total - downloaded, 0)
                                progress_callback(
                                    downloaded / total * 100,
                                    _format_speed(speed),
                                    _format_eta(remaining / speed if speed else 0),
                                    downloaded,
                                    total,
                                )
                                last_report = now
                return str(target)
            except Exception as e:
                # Fallback to standard urllib.request if curl_cffi fails or is not installed
                logger.warning(f"curl_cffi download failed or not installed: {e}. Falling back to urllib.")
                request = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(request, timeout=900) as response:
                    total = int(response.headers.get("Content-Length") or 0)
                    filename = _filename_from_headers(url, response.headers)
                    target = Path(out_dir) / filename

                    downloaded = 0
                    start = last_report = time.time()
                    with open(target, "wb") as f:
                        while True:
                            if cancel_event and cancel_event.is_set():
                                raise DownloadCancelled("Download cancelled")
                            chunk = response.read(1024 * 1024)
                            if not chunk:
                                break
                            f.write(chunk)
                            downloaded += len(chunk)

                            if progress_callback and total:
                                now = time.time()
                                if now - last_report >= 2:
                                    elapsed = max(now - start, 0.1)
                                    speed = downloaded / elapsed
                                    remaining = max(total - downloaded, 0)
                                    progress_callback(
                                        downloaded / total * 100,
                                        _format_speed(speed),
                                        _format_eta(remaining / speed if speed else 0),
                                        downloaded,
                                        total,
                                    )
                                    last_report = now
                return str(target)

        return await loop.run_in_executor(None, _download)
    except DownloadCancelled:
        return CANCELLED
    except Exception as e:
        logger.error(f"Direct download failed: {e}")
        return None



def _download_direct_with_aria2(url: str, out_dir: str, progress_callback=None, cancel_event=None) -> str:
    cmd = [
        "aria2c",
        "--max-tries=3",
        "--max-connection-per-server=16",
        "--split=16",
        "--summary-interval=1",
        "--console-log-level=notice",
        "--allow-overwrite=true",
        "-d", out_dir,
        url,
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        universal_newlines=True,
    )
    try:
        while proc.poll() is None:
            if cancel_event and cancel_event.is_set():
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                raise DownloadCancelled("Download cancelled")

            line = proc.stdout.readline() if proc.stdout else ""
            if not line:
                time.sleep(0.2)
                continue
            if progress_callback:
                match = re.search(r"\((\d+)%\).*?DL:([^\s]+).*?ETA:([^\]\s]+)", line)
                if match:
                    progress_callback(float(match.group(1)), match.group(2), match.group(3), None, None)

        if proc.returncode != 0:
            raise RuntimeError(f"aria2c failed with exit code {proc.returncode}")

        files = [p for p in Path(out_dir).iterdir() if p.is_file() and not p.name.endswith(".aria2")]
        if not files:
            raise RuntimeError("aria2c completed but no file was created")
        return str(max(files, key=lambda p: p.stat().st_size))
    finally:
        if proc.poll() is None:
            proc.kill()


async def download_media(
    url: str,
    fmt: str,
    quality: str,
    out_dir: str,
    audio_format: str = "mp3",
    audio_quality: str = "192",
    progress_callback: Optional[Callable] = None,
    cancel_event=None,
) -> Optional[str]:
    Path(out_dir).mkdir(parents=True, exist_ok=True)

    hooks = [make_progress_hook(progress_callback, cancel_event)] if progress_callback else []

    if fmt == "audio":
        codec_map = {
            "mp3": ("mp3", audio_quality),
            "m4a": ("m4a", "0"),
            "flac": ("flac", "0"),
            "wav": ("wav", "0"),
            "ogg": ("vorbis", "0"),
        }
        codec, quality_val = codec_map.get(audio_format, ("mp3", "192"))

        opts = ydl_base_opts({
            "format": "bestaudio/best",
            "outtmpl": f"{out_dir}/%(title)s.%(ext)s",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": codec,
                "preferredquality": quality_val,
            }],
            "progress_hooks": hooks,
        }, url=url)
    else:
        quality_map = {
            "best": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "2160": "bestvideo[height<=2160][ext=mp4]+bestaudio[ext=m4a]/best[height<=2160]",
            "1080": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best[height<=1080]",
            "720":  "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best[height<=720]",
            "480":  "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best[height<=480]",
        }
        opts = ydl_base_opts({
            "format": quality_map.get(quality, "best"),
            "outtmpl": f"{out_dir}/%(title)s.%(ext)s",
            "merge_output_format": "mp4",
            "progress_hooks": hooks,
        }, url=url)

    # aria2c multi-connection downloads (opt-in; per-chunk progress not reported)
    if ENABLE_ARIA2 and shutil.which("aria2c"):
        opts["external_downloader"] = {"default": "aria2c"}
        opts["external_downloader_args"] = {"aria2c": ["-x", "16", "-s", "16", "-k", "1M"]}

    try:
        loop = asyncio.get_event_loop()
        def _download():
            with yt_dlp.YoutubeDL(opts) as ydl:
                if cancel_event and cancel_event.is_set():
                    raise DownloadCancelled("Download cancelled")
                info = ydl.extract_info(url, download=True)
                _cache_info(url, info)  # reuse for the post-download metadata lookup
                filename = ydl.prepare_filename(info)
                if fmt == "audio":
                    filename = Path(filename).with_suffix(f".{audio_format}").as_posix()
                base = Path(filename).stem
                matches = list(Path(filename).parent.glob(f"{base}*"))
                return str(matches[0]) if matches else filename
        return await loop.run_in_executor(None, _download)
    except DownloadCancelled:
        return CANCELLED
    except Exception as e:
        logger.error(f"Download failed: {e}")
        return None


async def download_spotify(
    url: str,
    out_dir: str,
    audio_format: str = "mp3",
    audio_quality: str = "192",
) -> Optional[str]:
    """Download Spotify track via spotdl."""
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    try:
        loop = asyncio.get_event_loop()
        def _dl():
            cmd = [
                shutil.which("spotdl") or "spotdl", url,
                "--output", out_dir,
                "--format", audio_format,
            ]
            if audio_quality and audio_quality != "0":
                cmd += ["--bitrate", f"{audio_quality}k"]
            cookie_file = get_cookie_file("spotify")
            if cookie_file:
                cmd += ["--cookie-file", cookie_file]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if result.returncode != 0:
                logger.error(f"spotdl error: {result.stderr}")
                return None
            # Find downloaded file
            matches = list(Path(out_dir).rglob(f"*.{audio_format}"))
            if not matches:
                matches = [
                    p for p in Path(out_dir).rglob("*")
                    if p.is_file() and p.suffix.lower().lstrip(".") in {"mp3", "m4a", "opus", "flac", "wav"}
                ]
            return str(matches[0]) if matches else None
        return await loop.run_in_executor(None, _dl)
    except Exception as e:
        logger.error(f"Spotify download failed: {e}")
        return None


async def get_spotify_info(url: str) -> Optional[dict]:
    """Get Spotify track info via spotdl."""
    try:
        loop = asyncio.get_event_loop()
        def _info():
            result = subprocess.run(
                ["spotdl", "--print-errors", url, "--output", "/tmp"],
                capture_output=True, text=True, timeout=30
            )
            return result.stdout
        await loop.run_in_executor(None, _info)
        return None  # spotdl doesn't easily return structured info; use yt_dlp for preview
    except Exception:
        return None


def compress_video(input_path: str, output_path: str, target_mb: int = 1900) -> bool:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", input_path],
            capture_output=True, text=True
        )
        duration = float(result.stdout.strip() or 0)
        audio_kbps = 128
        if duration > 0:
            video_kbps = max(200, min(int((target_mb * 8192) / duration) - audio_kbps, 8000))
            bitrate_args = ["-b:v", f"{video_kbps}k", "-b:a", f"{audio_kbps}k"]
        else:
            bitrate_args = ["-crf", "28", "-b:a", f"{audio_kbps}k"]

        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-c:v", "libx264", "-preset", "fast",
            *bitrate_args,
            "-c:a", "aac",
            "-movflags", "+faststart",
            output_path
        ]
        r = subprocess.run(cmd, capture_output=True, timeout=3600)
        return r.returncode == 0
    except Exception as e:
        logger.error(f"Compression failed: {e}")
        return False


def split_video(input_path: str, out_dir: str, max_part_mb: int) -> list[str]:
    """Split a video into playable parts under max_part_mb using ffmpeg stream copy."""
    source = Path(input_path)
    output_dir = Path(out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    size_mb = source.stat().st_size / (1024 * 1024)
    if size_mb <= max_part_mb:
        return [str(source)]

    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(source)],
        capture_output=True, text=True, timeout=60
    )
    duration = float(result.stdout.strip() or 0)
    if duration <= 0:
        raise RuntimeError("Could not read video duration for splitting")

    target_mb = max(1, int(max_part_mb * 0.82))
    parts = max(2, math.ceil(size_mb / target_mb))
    suffix = source.suffix or ".mp4"

    for attempt in range(8):
        for old_part in output_dir.glob(f"{source.stem}.part*{suffix}"):
            old_part.unlink(missing_ok=True)

        part_duration = duration / parts
        outputs = []
        for index in range(parts):
            start = index * part_duration
            output = output_dir / f"{source.stem}.part{index + 1:03d}{suffix}"
            cmd = [
                "ffmpeg", "-y",
                "-ss", str(start),
                "-i", str(source),
                "-t", str(part_duration),
                "-c", "copy",
                "-avoid_negative_ts", "make_zero",
                str(output),
            ]
            proc = subprocess.run(cmd, capture_output=True, timeout=3600)
            if proc.returncode != 0 or not output.exists():
                raise RuntimeError("ffmpeg split failed")
            outputs.append(str(output))

        largest_mb = max(Path(part).stat().st_size / (1024 * 1024) for part in outputs)
        if largest_mb <= max_part_mb:
            return outputs

        parts = max(parts + 1, math.ceil(parts * largest_mb / max_part_mb) + 1)

    raise RuntimeError("Could not split video below Telegram size limit")


def split_file(input_path: str, out_dir: str, max_part_mb: int) -> list[str]:
    """Split any file into binary parts small enough for Telegram document upload."""
    source = Path(input_path)
    size_mb = source.stat().st_size / (1024 * 1024)
    if size_mb <= max_part_mb:
        return [str(source)]

    output_dir = Path(out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    chunk_size = max(1, int(max_part_mb * 0.92)) * 1024 * 1024
    outputs = []
    with open(source, "rb") as src:
        index = 1
        while True:
            chunk = src.read(chunk_size)
            if not chunk:
                break
            output = output_dir / f"{source.name}.part{index:03d}"
            with open(output, "wb") as dst:
                dst.write(chunk)
            outputs.append(str(output))
            index += 1
    return outputs


async def download_image(url: str) -> list[str]:
    """Download images using gallery-dl. Returns list of downloaded file paths."""
    import tempfile
    out_dir = tempfile.mkdtemp(dir=DOWNLOAD_PATH)
    try:
        loop = asyncio.get_event_loop()
        def _dl():
            cmd = [
                "gallery-dl",
                "--dest", out_dir,
                "--no-mtime",
                "-q",
            ]
            cookie_file = get_cookie_file(url)
            if cookie_file:
                cmd += ["--cookies", cookie_file]
            cmd.append(url)
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            logger.info(f"gallery-dl stdout: {result.stdout[:300]}")
            if result.returncode != 0:
                logger.error(f"gallery-dl stderr: {result.stderr[:300]}")
            # Find all downloaded images
            files = []
            for ext in ["jpg", "jpeg", "png", "webp", "gif", "mp4"]:
                files += list(Path(out_dir).rglob(f"*.{ext}"))
            return sorted(files)
        return await loop.run_in_executor(None, _dl)
    except Exception as e:
        logger.error(f"gallery-dl failed: {e}")
        return []
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.read()
    except Exception:
        return None


def embed_mp3_metadata(filepath: str, info: dict, thumb_bytes: Optional[bytes] = None):
    try:
        from mutagen.id3 import ID3, TIT2, TPE1, TALB, TDRC, APIC, ID3NoHeaderError
        try:
            tags = ID3(filepath)
        except ID3NoHeaderError:
            tags = ID3()
        tags["TIT2"] = TIT2(encoding=3, text=info.get("title", ""))
        tags["TPE1"] = TPE1(encoding=3, text=info.get("uploader") or info.get("channel") or "")
        tags["TALB"] = TALB(encoding=3, text=info.get("album") or info.get("title") or "")
        upload_date = info.get("upload_date", "")
        if upload_date:
            tags["TDRC"] = TDRC(encoding=3, text=upload_date[:4])
        if thumb_bytes:
            tags["APIC"] = APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=thumb_bytes)
        tags.save(filepath, v2_version=3)
    except Exception as e:
        logger.warning(f"Metadata embed failed: {e}")


def extract_audio_cover(filepath: str) -> bytes | None:
    """Return embedded cover art bytes from a downloaded audio file, if present."""
    try:
        from mutagen import File
        audio = File(filepath)
        if not audio or not audio.tags:
            return None

        tags = audio.tags
        for key, value in tags.items():
            key_lower = str(key).lower()
            if key_lower.startswith("apic"):
                return getattr(value, "data", None)
            if key_lower == "covr":
                covers = value if isinstance(value, list) else [value]
                for cover in covers:
                    return bytes(cover)
            if key_lower in {"metadata_block_picture", "coverart"}:
                items = value if isinstance(value, list) else [value]
                for item in items:
                    data = getattr(item, "data", None)
                    if data:
                        return data
                    if isinstance(item, bytes):
                        return item
    except Exception as e:
        logger.warning(f"Audio cover extraction failed: {e}")
    return None

def fetch_thumb(url) -> bytes | None:
    if not url:
        return None
    try:
        import urllib.request
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.read()
    except Exception:
        return None
