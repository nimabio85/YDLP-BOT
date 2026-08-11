"""
Automatic dependency updater for yt-dlp, gallery-dl, spotdl, curl-cffi, etc.
"""
import sys
import subprocess
import asyncio
import logging

logger = logging.getLogger(__name__)

DEPS_TO_UPDATE = [
    "yt-dlp",
    "gallery-dl",
    "spotdl",
    "curl-cffi",
    "yt-dlp-ejs",
    "shazamio",
]


async def update_dependencies() -> tuple[bool, str]:
    """Upgrade core downloader packages via pip in an executor."""
    loop = asyncio.get_event_loop()

    def _run_pip_upgrade():
        cmd = [
            sys.executable, "-m", "pip", "install", "--upgrade", "--no-cache-dir",
            *DEPS_TO_UPDATE
        ]
        try:
            logger.info("Starting automatic dependency update...")
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if res.returncode == 0:
                output_tail = "\n".join(res.stdout.strip().splitlines()[-6:])
                logger.info(f"Dependency update succeeded:\n{output_tail}")
                return True, output_tail or "Dependencies updated successfully."
            else:
                err_tail = "\n".join((res.stderr or res.stdout).strip().splitlines()[-6:])
                logger.error(f"Dependency update failed:\n{err_tail}")
                return False, err_tail or "Pip upgrade failed."
        except Exception as e:
            logger.error(f"Dependency update exception: {e}")
            return False, str(e)

    return await loop.run_in_executor(None, _run_pip_upgrade)
