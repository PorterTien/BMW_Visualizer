"""Simple in-memory per-IP rate limiter for expensive AI endpoints."""
from __future__ import annotations

import time
from collections import defaultdict

from fastapi import HTTPException, Request

_calls: dict[str, list[float]] = defaultdict(list)


def check_rate_limit(request: Request, *, max_calls: int = 10, window_secs: int = 60) -> None:
    ip = (request.client.host if request.client else None) or "unknown"
    key = f"{ip}:{request.url.path}"
    now = time.monotonic()
    calls = _calls[key]
    calls[:] = [t for t in calls if now - t < window_secs]
    if len(calls) >= max_calls:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: max {max_calls} requests per {window_secs}s. Try again later.",
        )
    calls.append(now)
