"""Supabase JWT verification for FastAPI."""
from __future__ import annotations

import os
import jwt
from fastapi import Header, HTTPException

SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")


def get_user_id(authorization: str = Header(default=None)) -> str | None:
    """Extract user_id from Supabase Bearer token. Returns None if no token."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.removeprefix("Bearer ").strip()
    if not token or not SUPABASE_JWT_SECRET:
        return None
    try:
        payload = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
        return payload.get("sub")
    except Exception:
        return None


def require_user(authorization: str = Header(default=None)) -> str:
    """Like get_user_id but raises 401 if not authenticated."""
    uid = get_user_id(authorization)
    if not uid:
        raise HTTPException(status_code=401, detail="Authentication required")
    return uid
