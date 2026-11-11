"""Per-user sliding-window rate limit (in-process; use a shared store when scaling out)."""

from __future__ import annotations

import time
from collections import defaultdict, deque

from typing import Annotated

from fastapi import Depends, HTTPException, Request

from app.core.config import Settings, get_settings
from app.core.security import UserDep


class SlidingWindowLimiter:
    def __init__(self, window_seconds: float = 60.0):
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, limit: int, now: float | None = None) -> bool:
        now = now or time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] >= self.window:
            hits.popleft()
        if len(hits) >= limit:
            return False
        hits.append(now)
        return True


def chat_rate_limit(request: Request, user: UserDep, settings: Annotated[Settings, Depends(get_settings)]) -> None:
    limiter: SlidingWindowLimiter = request.app.state.chat_limiter
    if not limiter.allow(user.id, settings.chat_rate_limit_per_minute):
        raise HTTPException(429, "Too many requests. Please wait a minute.", headers={"Retry-After": "60"})
