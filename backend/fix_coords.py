#!/usr/bin/env python3
"""
fix_coords.py — Fix wrong-sign coordinates for US companies in the database.

The NAATBatt dataset occasionally has US facility/HQ coordinates with the
wrong sign on longitude (positive instead of negative) or latitude (negative
instead of positive), causing pins to appear in Asia or the southern hemisphere.

This script detects those cases by checking whether a location's country/state
field identifies it as US-based, then verifying whether flipping a sign lands
the point inside a loose US bounding box.

For the rare cases where the coordinates are simply wrong values (not a sign
issue), add the company to data/coord_overrides.json with the correct lat/lng.
Those overrides are applied after the automated sign-flip pass.

Usage (run from project root):
    python -m backend.fix_coords            # apply fixes
    python -m backend.fix_coords --dry-run  # preview without writing
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from backend.database import SessionLocal
from backend.models import Company, CompanyFacility

_OVERRIDES_PATH = Path(__file__).resolve().parent.parent / "data" / "coord_overrides.json"

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# ── North America detection ───────────────────────────────────────────────────
# Both the US and Canada are in the western hemisphere (negative longitude) and
# northern hemisphere (positive latitude), so the same sign-flip logic applies.

_US_COUNTRY_NAMES = {
    "united states", "usa", "us", "u.s.", "u.s.a.", "united states of america",
}
_CA_COUNTRY_NAMES = {"canada", "ca"}

_US_STATE_ABBREVS = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC", "PR", "VI", "GU", "AS", "MP",
}
_CA_PROVINCE_ABBREVS = {
    "AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT",
}

# Loose bounding box covering CONUS + Alaska + Hawaii + Canada + territories
_NA_LAT_MIN, _NA_LAT_MAX = 15.0, 84.0
_NA_LNG_MIN, _NA_LNG_MAX = -180.0, -52.0


def _is_north_america(country: str | None, state: str | None) -> bool:
    if country:
        c = country.strip().lower()
        if c in _US_COUNTRY_NAMES or c in _CA_COUNTRY_NAMES:
            return True
    if state:
        s = state.strip().upper()
        if s in _US_STATE_ABBREVS or s in _CA_PROVINCE_ABBREVS:
            return True
    return False


def _in_na_box(lat: float, lng: float) -> bool:
    return _NA_LAT_MIN <= lat <= _NA_LAT_MAX and _NA_LNG_MIN <= lng <= _NA_LNG_MAX


def fix_us_coords(
    lat: float | None,
    lng: float | None,
) -> tuple[float | None, float | None, list[str]]:
    """
    Return (fixed_lat, fixed_lng, change_descriptions).
    Only flips a sign when:
      - the flipped value lands in the North America bounding box AND
      - the original value doesn't already sit in the NA box
    Returns originals unchanged if no fix applies.
    """
    if lat is None or lng is None:
        return lat, lng, []

    # Already correct
    if _in_na_box(lat, lng):
        return lat, lng, []

    changes: list[str] = []
    new_lat = lat
    new_lng = lng

    # North America is northern hemisphere: latitude should be positive
    if new_lat < 0 and _NA_LAT_MIN <= abs(new_lat) <= _NA_LAT_MAX:
        new_lat = abs(new_lat)
        changes.append(f"lat {lat:.4f} → {new_lat:.4f}")

    # North America is western hemisphere: longitude should be negative (52–180° W)
    if new_lng > 0 and 52.0 <= new_lng <= 180.0:
        new_lng = -new_lng
        changes.append(f"lng {lng:.4f} → {new_lng:.4f}")

    # Sanity-check: does the corrected point land in the North America bounding box?
    if not _in_na_box(new_lat, new_lng):
        return lat, lng, []

    return new_lat, new_lng, changes


# ── Manual overrides ─────────────────────────────────────────────────────────

def _load_overrides() -> dict[str, dict]:
    """Load data/coord_overrides.json, ignoring keys that start with '_'."""
    if not _OVERRIDES_PATH.exists():
        return {}
    try:
        raw = json.loads(_OVERRIDES_PATH.read_text())
        return {k: v for k, v in raw.items() if not k.startswith("_")}
    except Exception as exc:
        log.warning("Could not load coord_overrides.json: %s", exc)
        return {}


def _apply_overrides(db, dry_run: bool) -> int:
    """Set HQ coords for companies listed in coord_overrides.json."""
    overrides = _load_overrides()
    if not overrides:
        return 0
    fixed = 0
    for name, coords in overrides.items():
        co = db.query(Company).filter(Company.company_name == name).first()
        if not co:
            log.warning("OVERRIDE  company not found: %r", name)
            continue
        new_lat, new_lng = coords["lat"], coords["lng"]
        if co.company_hq_lat == new_lat and co.company_hq_lng == new_lng:
            continue
        log.info(
            "OVERRIDE  %-45s  lat %s → %.4f  lng %s → %.4f",
            name[:45],
            co.company_hq_lat, new_lat,
            co.company_hq_lng, new_lng,
        )
        if not dry_run:
            co.company_hq_lat = new_lat
            co.company_hq_lng = new_lng
        fixed += 1
    return fixed


# ── Main fix logic ────────────────────────────────────────────────────────────

def run(dry_run: bool = False) -> None:
    db = SessionLocal()
    try:
        hq_fixed = _fix_company_hq(db, dry_run)
        loc_fixed = _fix_company_locations_json(db, dry_run)
        fac_fixed = _fix_company_facilities(db, dry_run)
        override_fixed = _apply_overrides(db, dry_run)

        if not dry_run:
            db.commit()

        total = hq_fixed + loc_fixed + fac_fixed + override_fixed
        mode = "[DRY RUN] " if dry_run else ""
        log.info(
            "%sTotal fixes: %d HQ coords, %d location-JSON entries, %d facility rows, %d overrides",
            mode, hq_fixed, loc_fixed, fac_fixed, override_fixed,
        )
        if total == 0:
            log.info("No coordinate fixes needed.")
    finally:
        db.close()


def _fix_company_hq(db, dry_run: bool) -> int:
    """Fix company_hq_lat / company_hq_lng on Company rows."""
    fixed = 0
    companies = (
        db.query(Company)
        .filter(Company.company_hq_lat.isnot(None), Company.company_hq_lng.isnot(None))
        .all()
    )
    for co in companies:
        if not _is_north_america(co.company_hq_country, co.company_hq_state):
            continue
        new_lat, new_lng, changes = fix_us_coords(co.company_hq_lat, co.company_hq_lng)
        if not changes:
            continue
        log.info("HQ  %-45s  %s", co.company_name[:45], "  ".join(changes))
        if not dry_run:
            co.company_hq_lat = new_lat
            co.company_hq_lng = new_lng
        fixed += 1
    return fixed


def _fix_company_locations_json(db, dry_run: bool) -> int:
    """Fix lat/lng inside the company_locations JSON blob on each Company row."""
    fixed_entries = 0
    companies = (
        db.query(Company)
        .filter(Company.company_locations.isnot(None))
        .all()
    )
    for co in companies:
        try:
            locations = json.loads(co.company_locations)
        except (TypeError, ValueError):
            continue
        if not isinstance(locations, list):
            continue

        row_changed = False
        for loc in locations:
            lat = loc.get("lat")
            lng = loc.get("lng")
            if lat is None or lng is None:
                continue

            country = loc.get("country") or co.company_hq_country
            state = loc.get("state") or co.company_hq_state
            if not _is_north_america(country, state):
                continue

            new_lat, new_lng, changes = fix_us_coords(lat, lng)
            if not changes:
                continue

            facility = loc.get("facility_name") or loc.get("city") or "?"
            log.info(
                "LOC %-45s  facility=%-20s  %s",
                co.company_name[:45], str(facility)[:20], "  ".join(changes),
            )
            if not dry_run:
                loc["lat"] = new_lat
                loc["lng"] = new_lng
            fixed_entries += 1
            row_changed = True

        if row_changed and not dry_run:
            co.company_locations = json.dumps(locations)

    return fixed_entries


def _fix_company_facilities(db, dry_run: bool) -> int:
    """Fix lat/lng on CompanyFacility rows."""
    fixed = 0
    facilities = (
        db.query(CompanyFacility)
        .filter(CompanyFacility.lat.isnot(None), CompanyFacility.lng.isnot(None))
        .all()
    )
    for fac in facilities:
        if not _is_north_america(fac.country, fac.state):
            continue
        new_lat, new_lng, changes = fix_us_coords(fac.lat, fac.lng)
        if not changes:
            continue
        log.info(
            "FAC id=%-6s  %-40s  %s",
            fac.id, str(fac.facility_name or fac.city or "?")[:40], "  ".join(changes),
        )
        if not dry_run:
            fac.lat = new_lat
            fac.lng = new_lng
        fixed += 1
    return fixed


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would change without writing to the database.",
    )
    args = parser.parse_args()
    run(dry_run=args.dry_run)
    sys.exit(0)
