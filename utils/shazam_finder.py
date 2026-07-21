import asyncio
import logging
import subprocess
from pathlib import Path
from shazamio import Shazam

logger = logging.getLogger(__name__)

SNIPPET_SECONDS = 12


async def probe_duration(input_path: str) -> float:
    """Return media duration in seconds via ffprobe (0 on failure)."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        input_path,
    ]
    try:
        proc = await asyncio.get_event_loop().run_in_executor(
            None, lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        )
        return float(proc.stdout.strip() or 0)
    except Exception:
        return 0.0


async def extract_audio_snippet(
    input_path: str,
    output_path: str,
    duration: int = SNIPPET_SECONDS,
    start: float = 2.0,
) -> bool:
    """
    Extract a mono WAV snippet from input media using FFmpeg.
    This limits bandwidth and memory requirements, ensuring extremely fast recognition.
    """
    # -y: Overwrite output file
    # -ss start: Seek to snippet start (skips intros/silence when set to mid-track)
    # -vn: Disable video stream
    # -acodec pcm_s16le: 16-bit PCM WAV encoding
    # -ar 44100: Standard CD-quality sample rate
    # -ac 1: Mono audio channel
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(max(start, 0)),
        "-i", input_path,
        "-t", str(duration),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "44100",
        "-ac", "1",
        output_path
    ]
    try:
        # Run subprocess in an executor to avoid blocking the Telegram event loop
        proc = await asyncio.get_event_loop().run_in_executor(
            None, lambda: subprocess.run(cmd, capture_output=True, timeout=30)
        )
        if proc.returncode != 0:
            logger.error(f"FFmpeg snippet extraction failed: {proc.stderr.decode(errors='ignore')}")

            # Fallback: if the seek fails (short input), retry from 0s
            cmd_fallback = [
                "ffmpeg", "-y",
                "-i", input_path,
                "-t", str(duration),
                "-vn",
                "-acodec", "pcm_s16le",
                "-ar", "44100",
                "-ac", "1",
                output_path
            ]
            proc_fallback = await asyncio.get_event_loop().run_in_executor(
                None, lambda: subprocess.run(cmd_fallback, capture_output=True, timeout=30)
            )
            if proc_fallback.returncode != 0:
                logger.error(f"FFmpeg fallback snippet extraction failed: {proc_fallback.stderr.decode(errors='ignore')}")
                return False
        return True
    except Exception as e:
        logger.error(f"Error extracting audio snippet: {e}")
        return False


async def recognize_audio(file_path: str) -> dict | None:
    """
    Identify a song from an audio file using shazamio.
    """
    try:
        shazam = Shazam()
        result = await shazam.recognize(file_path)
        return result
    except Exception as e:
        logger.error(f"Shazam recognition error: {e}")
        return None


def snippet_starts(duration: float) -> list[float]:
    """
    Candidate snippet start times, best-first.
    Mid-track windows hit the chorus/hook and avoid intros, talking, and outros —
    much more accurate than always sampling the first seconds.
    """
    starts: list[float] = []
    if duration and duration > 3 * SNIPPET_SECONDS:
        starts.append(duration / 3)       # usually verse/chorus
        starts.append(duration * 0.6)     # second chorus
    starts.append(2.0)                    # last resort: near the beginning
    # Dedupe while preserving order
    seen = set()
    unique = []
    for s in starts:
        key = round(s, 1)
        if key not in seen:
            seen.add(key)
            unique.append(s)
    return unique


async def identify_song(input_path: str, tmpdir: str) -> dict | None:
    """
    Identify a song from a local media file. Tries mid-track snippets first,
    falling back to the beginning, and returns the first Shazam match.
    """
    duration = await probe_duration(input_path)
    for attempt, start in enumerate(snippet_starts(duration)):
        snippet_path = str(Path(tmpdir) / f"snippet_{attempt}.wav")
        ok = await extract_audio_snippet(input_path, snippet_path, start=start)
        if not ok or not Path(snippet_path).exists():
            continue
        result = await recognize_audio(snippet_path)
        if result and result.get("track"):
            return result
    return None


async def download_url_snippet(url: str, out_dir: str, start: float = 2.0) -> str | None:
    """
    Download a short audio snippet of the URL using yt-dlp.
    Returns the path to the downloaded snippet file.
    """
    import yt_dlp
    from yt_dlp.utils import download_range_func
    from utils.downloader import ydl_base_opts

    start = max(start, 0)
    opts = ydl_base_opts({
        "format": "bestaudio/best",
        "outtmpl": f"{out_dir}/snippet.%(ext)s",
        "download_ranges": download_range_func(None, [(start, start + SNIPPET_SECONDS)]),
        "force_keyframes_at_cuts": True,
        "overwrites": True,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "wav",
        }],
    }, url=url)

    try:
        loop = asyncio.get_event_loop()
        def _download():
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.extract_info(url, download=True)
                return str(Path(out_dir) / "snippet.wav")

        filepath = await loop.run_in_executor(None, _download)
        if filepath and Path(filepath).exists():
            return filepath
        return None
    except Exception as e:
        logger.error(f"Error downloading URL audio snippet: {e}")
        return None
