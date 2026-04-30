"""Tiny shared utilities used by multiple routes.

Kept in its own file so imports in ``backend/routes/*`` don't circle back
through ``models`` or ``database``.
"""
from __future__ import annotations

import json
import math


def safe_float(val) -> float | None:
    """Return None for NaN/Inf floats that json.dumps would reject."""
    if val is None:
        return None
    try:
        f = float(val)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return None


def safe_json(val: str | None, default):
    """Parse JSON stored in a DB column; return ``default`` on missing/corrupt data.

    Many of our TEXT columns hold JSON blobs (``announced_partners``,
    ``articles_json`` …). A corrupt row should never 500 an endpoint, so
    every caller routes through here instead of raw ``json.loads``.
    """
    if not val:
        return default
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError, ValueError):
        return default
