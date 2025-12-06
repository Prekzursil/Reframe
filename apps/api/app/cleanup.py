from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


def _remove_old_files(directory: Path, older_than: timedelta) -> None:
    if not directory.exists() or not directory.is_dir():
        return
    cutoff = datetime.utcnow() - older_than
    for entry in directory.iterdir():
        try:
            if entry.is_file():
                mtime = datetime.utcfromtimestamp(entry.stat().st_mtime)
                if mtime < cutoff:
                    entry.unlink(missing_ok=True)
        except Exception:
            # best-effort cleanup
            continue


def start_cleanup_loop(root: str, interval_seconds: int = 3600, ttl_hours: int = 24) -> Optional[threading.Thread]:
    target_dir = Path(root) / "tmp"
    target_dir.mkdir(parents=True, exist_ok=True)

    def _loop() -> None:
        while True:
            _remove_old_files(target_dir, timedelta(hours=ttl_hours))
            time.sleep(interval_seconds)

    thread = threading.Thread(target=_loop, daemon=True)
    thread.start()
    return thread
