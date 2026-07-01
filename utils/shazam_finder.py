import asyncio
import logging
import subprocess
from pathlib import Path
from shazamio import Shazam

logger = logging.getLogger(__name__)

async def extract_audio_snippet(input_path: str, output_path: str, duration: int = 12) -> bool:
    """
    Extract a 12-second mono WAV snippet from input media using FFmpeg.
    This limits bandwidth and memory requirements, ensuring extremely fast recognition.
    """
    # -y: Overwrite output file
    # -ss 2: Start 2 seconds in to bypass initial silence/static/ads
    # -i input_path: Input file path
    # -t duration: Snippet duration in seconds
    # -vn: Disable video stream
    # -acodec pcm_s16le: 16-bit PCM WAV encoding
    # -ar 44100: Standard CD-quality sample rate
    # -ac 1: Mono audio channel
    cmd = [
        "ffmpeg", "-y",
        "-ss", "00:00:02",
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
            
            # Fallback: if input is too short and fails to start at 2s, try starting at 0s
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
