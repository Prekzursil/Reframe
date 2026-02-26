from __future__ import annotations

import time
from collections import deque
from typing import Deque, Dict

from fastapi import Request

from app.config import get_settings
from app.errors import rate_limited


class RateLimiter:
    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = max(1, int(limit))
        self.window_seconds = max(1, int(window_seconds))
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


def _build_policy_limiters() -> dict[str, RateLimiter]:
    settings = get_settings()
    return {
        "default": RateLimiter(limit=settings.rate_limit_requests, window_seconds=settings.rate_limit_window_seconds),
        "heavy_jobs": RateLimiter(limit=settings.rate_limit_heavy_requests, window_seconds=settings.rate_limit_heavy_window_seconds),
        "uploads": RateLimiter(limit=settings.rate_limit_upload_requests, window_seconds=settings.rate_limit_upload_window_seconds),
    }


policy_limiters: dict[str, RateLimiter] = _build_policy_limiters()


async def _enforce_policy(request: Request, policy: str) -> None:
    limiter = policy_limiters.get(policy) or policy_limiters["default"]
    client_ip = request.client.host if request.client else "anonymous"
    # Per-path keys avoid one noisy endpoint starving all others under the same policy bucket.
    bucket_key = f"{client_ip}:{request.url.path}"
    if not limiter.allow(bucket_key):
        raise rate_limited(
            details={
                "policy": policy,
                "limit": limiter.limit,
                "window_seconds": limiter.window_seconds,
                "client": client_ip,
                "path": request.url.path,
            }
        )


def enforce_rate_limit(policy: str = "default"):
    async def _dependency(request: Request) -> None:
        await _enforce_policy(request, policy)

    return _dependency


async def enforce_default_rate_limit(request: Request) -> None:
    await _enforce_policy(request, "default")
