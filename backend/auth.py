from __future__ import annotations

import logging
import os

import httpx
import jwt
from fastapi import Header

log = logging.getLogger(__name__)

SUPABASE_URL = (os.getenv("VITE_SUPABASE_URL") or os.getenv("SUPABASE_URL", "")).strip()
SUPABASE_ANON_KEY = (os.getenv("SUPABASE_ANON_KEY") or os.getenv("VITE_SUPABASE_ANON_KEY", "")).strip()
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "").strip()
WATCHLIST_REQUIRES_AUTH = os.getenv("WATCHLIST_REQUIRES_AUTH", "").strip().lower() in {
    "1", "true", "yes", "on",
}
SHARED_WATCHLIST_USER = os.getenv("SHARED_WATCHLIST_USER", "shared").strip() or "shared"

log.info("AUTH INIT: url=%s anon_key=%s jwt_secret=%s",
         bool(SUPABASE_URL), bool(SUPABASE_ANON_KEY), bool(SUPABASE_JWT_SECRET))


def get_user_id(authorization: str | None) -> str | None:
    if not authorization or not authorization.startswith("Bearer "):
        log.info("AUTH: no bearer header")
        return None

    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        return None

    # Method 1: verify via Supabase REST API (no secret needed locally)
    if SUPABASE_URL and SUPABASE_ANON_KEY:
        try:
            resp = httpx.get(
                f"{SUPABASE_URL}/auth/v1/user",
                headers={"Authorization": f"Bearer {token}", "apikey": SUPABASE_ANON_KEY},
                timeout=5.0,
            )
            log.info("AUTH: supabase api status=%d", resp.status_code)
            if resp.status_code == 200:
                uid = resp.json().get("id")
                log.info("AUTH: verified via api, uid=%s", uid)
                return uid
        except Exception as exc:
            log.info("AUTH: supabase api error: %s", exc)

    # Method 2: verify JWT locally with the project secret
    if SUPABASE_JWT_SECRET:
        try:
            payload = jwt.decode(
                token,
                SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                options={"verify_aud": False},
            )
            uid = payload.get("sub")
            log.info("AUTH: verified via jwt, uid=%s", uid)
            return uid
        except Exception as exc:
            log.info("AUTH: jwt error: %s", exc)

    log.info("AUTH: all methods failed — no supabase config or invalid token")
    return None


def require_user(authorization: str | None = Header(default=None)) -> str | None:
    uid = get_user_id(authorization)
    if uid:
        return uid
    if WATCHLIST_REQUIRES_AUTH:
        return None
    return SHARED_WATCHLIST_USER
