"""
NAATBatt XLSX importer.
Run directly: python backend/seed.py
Or call import_naatbatt(db, force=True) from routes.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pandas as pd

# Allow running as a script from repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.config import NAATBATT_LOCAL_PATH, NAATBATT_URL, VALID_COUNTRIES
from backend.database import SessionLocal, init_db
from backend.models import Company, SyncLog

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

SEGMENT_TO_TYPE = {
    "Raw Materials": "materials supplier",
    "Battery Grade Materials": "materials supplier",
    "Other Battery Components & Mat.": "materials supplier",
    "Electrode & Cell Manufacturing": "cell supplier",
    "Module-Pack Manufacturing": "cell supplier",
    "Recycling-Repurposing": "recycler",
    "Equipment": "equipment supplier",
    "R&D": "R&D",
    "Services & Consulting": "services",
    "Modeling & Software": "modeling/software",
    "Distributors": "services",
    "Professional Services (NB)": "services",
}


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def download_xlsx(force: bool = False) -> bool:
    """Download XLSX; returns True if file was (re)downloaded."""
    path = Path(NAATBATT_LOCAL_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)

    old_hash = _sha256(str(path)) if path.exists() else None

    if path.exists() and not force:
        log.info("XLSX already cached at %s — skipping download.", path)
        return False

    log.info("Downloading NAATBatt XLSX from %s …", NAATBATT_URL)
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        r = client.get(NAATBATT_URL)
        r.raise_for_status()
    path.write_bytes(r.content)
    new_hash = _sha256(str(path))
    if old_hash == new_hash:
        log.info("Downloaded file is identical to cached version — no change.")
        return False
    log.info("Downloaded %d bytes → %s", len(r.content), path)
    return True


def _safe_str(val) -> str | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    return str(val).strip() or None


def _safe_float(val) -> float | None:
    try:
        v = float(val)
        return None if pd.isna(v) else v
    except (TypeError, ValueError):
        return None


def _normalize_name(name: str) -> str:
    return name.strip().lower()


def _geocode_city(city: str, state: str) -> tuple[float | None, float | None]:
    """Nominatim geocode with rate limiting."""
    try:
        query = f"{city},{state}"
        url = f"https://nominatim.openstreetmap.org/search?q={query}&format=json&limit=1"
        with httpx.Client(timeout=10, headers={"User-Agent": "BMW-Battery-Intel/1.0"}) as c:
            r = c.get(url)
            data = r.json()
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception:
        pass
    return None, None


def parse_xlsx() -> dict[str, dict]:
    """
    Returns a dict keyed by normalized company name.
    Each value contains the merged company record + locations list.
    Auto-detects all sheets with a 'Company' column.
    """
    path = NAATBATT_LOCAL_PATH
    xl = pd.ExcelFile(path)
    available = xl.sheet_names
    log.info("Sheets in file: %s", available)

    # normalized_name -> {fields..., locations: [...]}
    companies: dict[str, dict] = {}

    for sheet in available:
        df = xl.parse(sheet, dtype=str)
        # Normalize column names: strip whitespace + collapse double spaces
        df.columns = [" ".join(str(c).split()) for c in df.columns]

        # Only parse sheets that have a "Company" column
        if "Company" not in df.columns:
            log.debug("Sheet %r: no 'Company' column — skipping.", sheet)
            continue

        log.info("Sheet %r: %d rows", sheet, len(df))

        for _, row in df.iterrows():
            country = _safe_str(row.get("Facility Country", "")) or ""
            hq_country = _safe_str(row.get("HQ Country", "")) or ""
            # If VALID_COUNTRIES is non-empty, filter; otherwise accept all
            if VALID_COUNTRIES:
                country_ok = (
                    not country
                    or country.upper() in {c.upper() for c in VALID_COUNTRIES}
                    or not hq_country
                    or hq_country.upper() in {c.upper() for c in VALID_COUNTRIES}
                )
                if not country_ok:
                    continue

            raw_name = _safe_str(row.get("Company", ""))
            if not raw_name:
                continue
            key = _normalize_name(raw_name)

            lat = _safe_float(row.get("Latitude"))
            lng = _safe_float(row.get("Longitude"))
            # Support column naming variations across sheets
            capacity = _safe_str(
                row.get("Capacity") or row.get("Production Capacity")
            )
            capacity_units = _safe_str(
                row.get("Capacity Units") or row.get("Production Units")
            )
            # Use segment from data column when available; fall back to sheet name
            segment = _safe_str(row.get("Supply Chain Segment")) or sheet
            company_type = SEGMENT_TO_TYPE.get(segment, "other")

            location = {
                "facility_name": _safe_str(row.get("Facility Name")),
                "address": _safe_str(row.get("Facility Address")),
                "city": _safe_str(row.get("Facility City")),
                "state": _safe_str(row.get("Facility State or Province")),
                "country": country,
                "zip": _safe_str(row.get("Facility Zip")),
                "phone": _safe_str(row.get("Facility Phone")),
                "lat": lat,
                "lng": lng,
                "product": _safe_str(row.get("Product")),
                "product_type": _safe_str(row.get("Product/Facility Type")),
                "chemistries": _safe_str(row.get("Chemistries")),
                "feedstock": _safe_str(row.get("Feedstock")),
                "status": _safe_str(row.get("Status")),
                "workforce": _safe_str(row.get("Facility Workforce")),
                "capacity": capacity,
                "capacity_units": capacity_units,
            }

            # Handle column-name variations for contact email
            contact_email = _safe_str(
                row.get("Contact Email") or row.get("Contact email")
            )
            # Handle long description variations
            long_desc = _safe_str(
                row.get("Long Description") or row.get("Long description3")
            )

            if key not in companies:
                companies[key] = {
                    "company_name": raw_name,
                    "company_hq_city": _safe_str(row.get("HQ City")),
                    "company_hq_state": _safe_str(row.get("HQ State or Province")),
                    "company_hq_country": _safe_str(row.get("HQ Country")),
                    "company_hq_lat": lat,
                    "company_hq_lng": lng,
                    "company_website": _safe_str(row.get("Company Website")),
                    "hq_company": _safe_str(row.get("HQ Company")),
                    "hq_company_website": _safe_str(row.get("HQ Company Website")),
                    "supply_chain_segment": segment,
                    "company_type": company_type,
                    "company_status": _safe_str(row.get("Status")),
                    "summary": _safe_str(row.get("Brief Company Profile")),
                    "long_description": long_desc,
                    "chemistries": _safe_str(row.get("Chemistries")),
                    "feedstock": _safe_str(row.get("Feedstock")),
                    "notes": _safe_str(row.get("Notes")),
                    "contact_name": _safe_str(row.get("Contact")),
                    "contact_email": contact_email,
                    "contact_phone": _safe_str(row.get("Contact Phone")),
                    "naatbatt_member": 1 if _safe_str(row.get("NAATBatt Member", "")) == "Yes" else 0,
                    "naatbatt_id": _safe_str(row.get("ID")),
                    "company_focus": json.dumps([segment]),
                    "data_source": "naatbatt_xlsx",
                    "locations": [location],
                }
            else:
                # Merge: add location + extend focus areas
                existing = companies[key]
                existing["locations"].append(location)
                focus = json.loads(existing["company_focus"])
                if segment not in focus:
                    focus.append(segment)
                existing["company_focus"] = json.dumps(focus)
                # Fill in missing fields from subsequent rows
                if not existing["company_hq_lat"] and lat:
                    existing["company_hq_lat"] = lat
                    existing["company_hq_lng"] = lng
                if not existing["company_hq_city"]:
                    existing["company_hq_city"] = _safe_str(row.get("HQ City"))
                    existing["company_hq_state"] = _safe_str(row.get("HQ State or Province"))
                if not existing["summary"]:
                    existing["summary"] = _safe_str(row.get("Brief Company Profile"))
                if not existing["long_description"]:
                    existing["long_description"] = long_desc
                if not existing["chemistries"]:
                    existing["chemistries"] = _safe_str(row.get("Chemistries"))
                if not existing["feedstock"]:
                    existing["feedstock"] = _safe_str(row.get("Feedstock"))
                if not existing["notes"]:
                    existing["notes"] = _safe_str(row.get("Notes"))
                if not existing["contact_name"]:
                    existing["contact_name"] = _safe_str(row.get("Contact"))
                    existing["contact_email"] = contact_email
                    existing["contact_phone"] = _safe_str(row.get("Contact Phone"))
                if not existing["hq_company"]:
                    existing["hq_company"] = _safe_str(row.get("HQ Company"))
                    existing["hq_company_website"] = _safe_str(row.get("HQ Company Website"))

    # Geocode companies missing lat/lng
    geocoded = 0
    for data in companies.values():
        if not data["company_hq_lat"] and data["company_hq_city"]:
            lat, lng = _geocode_city(
                data["company_hq_city"] or "",
                data["company_hq_state"] or "",
            )
            if lat:
                data["company_hq_lat"] = lat
                data["company_hq_lng"] = lng
                geocoded += 1
            time.sleep(1)  # Nominatim rate limit

    log.info("Parsed %d unique companies (%d geocoded)", len(companies), geocoded)
    return companies


def import_naatbatt(db, force_download: bool = False) -> dict:
    """
    Download (if needed) and import NAATBatt data.
    Returns {rows_added, rows_updated, status}.
    """
    now = datetime.now(timezone.utc).isoformat()
    try:
        download_xlsx(force=force_download)
        companies = parse_xlsx()
    except Exception as e:
        log.error("Import failed: %s", e)
        log_entry = SyncLog(
            source="naatbatt_xlsx",
            status="failed",
            rows_added=0,
            rows_updated=0,
            error_message=str(e),
            run_at=now,
        )
        db.add(log_entry)
        db.commit()
        return {"status": "failed", "error": str(e), "rows_added": 0, "rows_updated": 0}

    added = updated = 0

    for key, data in companies.items():
        locations = data.pop("locations", [])
        data["company_locations"] = json.dumps(locations)
        data["last_updated"] = now

        existing = (
            db.query(Company)
            .filter(Company.company_name.ilike(data["company_name"]))
            .first()
        )
        if existing:
            # Only update NAATBatt-sourced fields; preserve AI-enriched ones
            for field in [
                "company_hq_city", "company_hq_state", "company_hq_country",
                "company_hq_lat", "company_hq_lng", "company_locations",
                "company_website", "hq_company", "hq_company_website",
                "supply_chain_segment", "company_type", "company_status",
                "summary", "long_description", "chemistries", "feedstock",
                "notes", "contact_name", "contact_email", "contact_phone",
                "naatbatt_member", "naatbatt_id", "company_focus",
                "last_updated",
            ]:
                val = data.get(field)
                if val is not None:
                    setattr(existing, field, val)
            updated += 1
        else:
            company = Company(**data)
            db.add(company)
            added += 1

    db.commit()
    log.info("Import complete: %d added, %d updated", added, updated)

    log_entry = SyncLog(
        source="naatbatt_xlsx",
        status="success",
        rows_added=added,
        rows_updated=updated,
        run_at=now,
    )
    db.add(log_entry)
    db.commit()

    return {"status": "success", "rows_added": added, "rows_updated": updated}


if __name__ == "__main__":
    init_db()
    db = SessionLocal()
    try:
        count = db.query(Company).count()
        if count == 0:
            log.info("Empty DB — running initial seed import…")
            result = import_naatbatt(db, force_download=False)
            log.info("Seed result: %s", result)
        else:
            log.info("DB already has %d companies — skipping seed.", count)
    finally:
        db.close()
