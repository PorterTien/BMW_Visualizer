#!/usr/bin/env python3
"""
fix_location_names.py — Reverse-geocode company HQ coordinates to correct
city/state/country text fields that don't match the actual pin location.

Uses the Nominatim API (OpenStreetMap, free, no key needed).
Rate-limited to 1 request/second per Nominatim's usage policy.

Usage (run from project root):
    python -m backend.fix_location_names            # apply fixes
    python -m backend.fix_location_names --dry-run  # preview without writing
    python -m backend.fix_location_names --all      # update all, not just mismatches
"""

import argparse
import logging
import sys
import time

import requests

from backend.database import SessionLocal
from backend.models import Company

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
_HEADERS = {"User-Agent": "BMW-Visualizer/1.0 (yson630@berkeley.edu)"}
_RATE_LIMIT = 1.1  # seconds between requests


def _reverse_geocode(lat: float, lng: float) -> dict | None:
    try:
        r = requests.get(
            _NOMINATIM_URL,
            params={"lat": lat, "lon": lng, "format": "json", "addressdetails": 1},
            headers=_HEADERS,
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            return None
        addr = data.get("address", {})
        city = (
            addr.get("city")
            or addr.get("town")
            or addr.get("village")
            or addr.get("county")
            or addr.get("municipality")
        )
        state = addr.get("state") or addr.get("province")
        country = addr.get("country")
        return {"city": city, "state": state, "country": country}
    except Exception as exc:
        log.warning("Nominatim error for (%.4f, %.4f): %s", lat, lng, exc)
        return None


def _region(lat: float, lng: float) -> str:
    if 15 <= lat <= 84 and -180 <= lng <= -52:
        return "north_america"
    if 35 <= lat <= 72 and -15 <= lng <= 45:
        return "europe"
    if 1 <= lat <= 55 and 100 <= lng <= 145:
        return "east_asia"
    if 8 <= lat <= 35 and 68 <= lng <= 97:
        return "south_asia"
    if -55 <= lat <= 15 and -82 <= lng <= -34:
        return "south_america"
    if -35 <= lat <= 37 and -20 <= lng <= 55:
        return "africa"
    if -45 <= lat <= -10 and 110 <= lng <= 155:
        return "australia"
    return "other"


_REGION_COUNTRIES = {
    "north_america": {"united states", "usa", "u.s.", "us", "u.s.a.", "canada", "mexico"},
    "europe": {
        "germany", "france", "italy", "spain", "uk", "united kingdom", "great britain",
        "sweden", "norway", "finland", "denmark", "netherlands", "belgium", "austria",
        "switzerland", "poland", "czech republic", "czechia", "portugal", "ireland",
        "luxembourg", "hungary", "romania", "bulgaria", "greece", "croatia", "slovakia",
        "slovenia", "estonia", "latvia", "lithuania", "malta", "cyprus",
    },
    "east_asia": {
        "china", "japan", "korea", "south korea", "republic of korea", "taiwan",
        "singapore", "malaysia", "indonesia", "vietnam", "thailand", "philippines",
        "hong kong", "macao",
    },
    "south_asia": {"india", "pakistan", "bangladesh", "sri lanka", "nepal"},
    "south_america": {
        "brazil", "argentina", "chile", "colombia", "peru", "venezuela", "bolivia",
        "ecuador", "paraguay", "uruguay",
    },
    "africa": {
        "south africa", "nigeria", "kenya", "ghana", "ethiopia", "tanzania",
        "morocco", "egypt", "algeria", "tunisia", "democratic republic of the congo",
        "mozambique", "zambia", "zimbabwe",
    },
    "australia": {"australia", "new zealand"},
}


def _is_mismatch(lat: float, lng: float, country: str | None) -> bool:
    """Return True if the country text clearly doesn't match the coordinate region."""
    if not country:
        return False
    region = _region(lat, lng)
    expected = _REGION_COUNTRIES.get(region, set())
    if not expected:
        return False
    c = country.strip().lower()
    # If country text matches any expected country for this region → no mismatch
    return not any(c == exp or exp in c or c in exp for exp in expected)


def run(dry_run: bool = False, update_all: bool = False) -> None:
    db = SessionLocal()
    try:
        companies = (
            db.query(Company)
            .filter(Company.company_hq_lat.isnot(None), Company.company_hq_lng.isnot(None))
            .all()
        )

        candidates = []
        for co in companies:
            if update_all or _is_mismatch(co.company_hq_lat, co.company_hq_lng, co.company_hq_country):
                candidates.append(co)

        log.info("Companies to reverse-geocode: %d", len(candidates))
        fixed = 0

        for i, co in enumerate(candidates):
            result = _reverse_geocode(co.company_hq_lat, co.company_hq_lng)
            if result is None:
                log.warning("SKIP  %s — no result", co.company_name)
                time.sleep(_RATE_LIMIT)
                continue

            new_city = result["city"]
            new_state = result["state"]
            new_country = result["country"]

            changed = []
            if new_city and new_city != co.company_hq_city:
                changed.append(f"city {co.company_hq_city!r} → {new_city!r}")
            if new_state and new_state != co.company_hq_state:
                changed.append(f"state {co.company_hq_state!r} → {new_state!r}")
            if new_country and new_country != co.company_hq_country:
                changed.append(f"country {co.company_hq_country!r} → {new_country!r}")

            if changed:
                log.info(
                    "[%d/%d] %-45s  %s",
                    i + 1, len(candidates), co.company_name[:45], "  ".join(changed),
                )
                if not dry_run:
                    if new_city:
                        co.company_hq_city = new_city
                    if new_state:
                        co.company_hq_state = new_state
                    if new_country:
                        co.company_hq_country = new_country
                fixed += 1
            else:
                log.debug("[%d/%d] %-45s  no change", i + 1, len(candidates), co.company_name[:45])

            time.sleep(_RATE_LIMIT)

        if not dry_run:
            db.commit()

        mode = "[DRY RUN] " if dry_run else ""
        log.info("%sFixed %d / %d companies", mode, fixed, len(candidates))
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--all", dest="update_all", action="store_true",
                        help="Re-geocode all companies, not just mismatches")
    args = parser.parse_args()
    run(dry_run=args.dry_run, update_all=args.update_all)
    sys.exit(0)
