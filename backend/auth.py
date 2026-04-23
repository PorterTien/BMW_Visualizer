from __future__ import annotations

import os

import httpx
from fastapi import Header

SUPABASE_URL = os.getenv("VITE_SUPABASE_URL") or os.getenv("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")


def get_user_id(authorization: str | None) -> str | None:
    import logging
    log = logging.getLogger(__name__)
    log.info("AUTH: header present=%s", bool(authorization))
    if not authorization or not authorization.startswith("Bearer "):
        log.info("AUTH: no valid bearer header")
        return None
    token = authorization.removeprefix("Bearer ").strip()
    log.info("AUTH: token length=%d, url=%s, anon_key=%s", len(token), bool(SUPABASE_URL), bool(SUPABASE_ANON_KEY))
    if not token or not SUPABASE_URL or not SUPABASE_ANON_KEY:
        log.info("AUTH: missing token or supabase config")
        return None
    try:
        resp = httpx.get(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={"Authorization": f"Bearer {token}", "apikey": SUPABASE_ANON_KEY},
            timeout=5.0,
        )
        log.info("AUTH: supabase response status=%d", resp.status_code)
        if resp.status_code == 200:
            uid = resp.json().get("id")
            log.info("AUTH: user_id=%s", uid)
            return uid
    except Exception as e:
        log.info("AUTH: exception=%s", e)
    return None


def require_user(authorization: str | None = Header(default=None)) -> str | None:
    return get_user_id(authorization)
