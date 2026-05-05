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

# Warn if JWT secret looks like a JWT token itself (common misconfiguration —
# the env var should be the raw secret from Supabase Settings > API > JWT Secret,
# not the anon key or service role key which start with "eyJ").
if SUPABASE_JWT_SECRET.startswith("eyJ"):
    log.warning(
        "AUTH: SUPABASE_JWT_SECRET looks like a JWT token (starts with 'eyJ'). "
        "Set it to the raw JWT secret from Supabase Settings → API → JWT Secret, "
        "not the anon or service role key. Falling back to Supabase API auth."
    )
    SUPABASE_JWT_SECRET = ""

log.info("AUTH INIT: url=%s anon_key=%s jwt_secret=%s",
         bool(SUPABASE_URL), bool(SUPABASE_ANON_KEY), bool(SUPABASE_JWT_SECRET))


def get_user_id(authorization: str | None) -> str | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None

    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        return None

    # Method 1: local JWT verification (instant, no network call)
    if SUPABASE_JWT_SECRET:
        try:
            payload = jwt.decode(
                token,
                SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                options={"verify_aud": False},
            )
            uid = payload.get("sub")
            log.debug("AUTH: verified via jwt, uid=%s", uid)
            return uid
        except Exception as exc:
            log.debug("AUTH: jwt error: %s", exc)

    # Method 2: fallback to Supabase REST API (slower, ~100-500ms network round-trip)
    if SUPABASE_URL and SUPABASE_ANON_KEY:
        try:
            resp = httpx.get(
                f"{SUPABASE_URL}/auth/v1/user",
                headers={"Authorization": f"Bearer {token}", "apikey": SUPABASE_ANON_KEY},
                timeout=5.0,
            )
            log.debug("AUTH: supabase api status=%d", resp.status_code)
            if resp.status_code == 200:
                uid = resp.json().get("id")
                log.debug("AUTH: verified via api, uid=%s", uid)
                return uid
        except Exception as exc:
            log.debug("AUTH: supabase api error: %s", exc)

    return None


def require_user(authorization: str | None = Header(default=None)) -> str | None:
    uid = get_user_id(authorization)
    if uid:
        return uid
    if WATCHLIST_REQUIRES_AUTH:
        return None
    return SHARED_WATCHLIST_USER
