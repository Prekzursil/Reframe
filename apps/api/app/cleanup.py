"""Background cleanup of stale temporary files."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


def _remove_old_files(directory: Path, older_than: timedelta) -> None:
    if not directory.exists() or not directory.is_dir():
        return
    cutoff = datetime.now(timezone.utc) - older_than
    for entry in directory.iterdir():
        try:
            if entry.is_file():
                mtime = datetime.fromtimestamp(entry.stat().st_mtime, tz=timezone.utc)
                if mtime < cutoff:
                    entry.unlink(missing_ok=True)
        except OSError:
            # best-effort cleanup
            continue


def start_cleanup_loop(
    root: str, interval_seconds: int = 3600, ttl_hours: int = 24
) -> Optional[threading.Thread]:
    """Start a daemon thread that periodically removes stale temp files."""
    target_dir = Path(root) / "tmp"
    target_dir.mkdir(parents=True, exist_ok=True)

    def _loop() -> None:
        while True:
            _remove_old_files(target_dir, timedelta(hours=ttl_hours))
            time.sleep(interval_seconds)

    thread = threading.Thread(target=_loop, daemon=True)
    thread.start()
    return thread
