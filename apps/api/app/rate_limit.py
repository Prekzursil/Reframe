from __future__ import annotations

import time
from collections import deque
from typing import Deque, Dict

from fastapi import Request

from app.config import get_settings
from app.errors import rate_limited


class RateLimiter:
    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = max(1, limit)
        self.window_seconds = max(1, window_seconds)
        self._hits: Dict[str, Deque[float]] = {}

    def allow(self, key: str) -> bool:
        now = time.time()
        window_start = now - self.window_seconds
        bucket = self._hits.setdefault(key, deque())

        while bucket and bucket[0] < window_start:
            bucket.popleft()

        if len(bucket) >= self.limit:
            return False

        bucket.append(now)
        return True


settings = get_settings()
rate_limiter = RateLimiter(limit=settings.rate_limit_requests, window_seconds=settings.rate_limit_window_seconds)


async def enforce_rate_limit(request: Request) -> None:
    client_ip = request.client.host if request.client else "anonymous"
    if not rate_limiter.allow(client_ip):
        raise rate_limited(
            details={
                "limit": rate_limiter.limit,
                "window_seconds": rate_limiter.window_seconds,
                "client": client_ip,
            }
        )
