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
    # Sheet names → use the NAATBatt category names directly
    "Raw Materials": "Raw Materials",
    "Battery Grade Materials": "Battery Grade Materials",
    "Other Battery Components & Mat.": "Other Battery Components & Mat.",
    "Electrode & Cell Manufacturing": "Electrode & Cell Manufacturing",
    "Module-Pack Manufacturing": "Module-Pack Manufacturing",
    "Recycling-Repurposing": "Recycling-Repurposing",
    "Equipment": "Equipment",
    "R&D": "R&D",
    "Services & Consulting": "Services & Consulting",
    "Modeling & Software": "Modeling & Software",
    "Distributors": "Distributors",
    "Professional Services (NB)": "Professional Services",
    # Supply Chain Segment column values (fallback for Append2-only companies)
    "Upstream": "Raw Materials",
    "Midstream": "Electrode & Cell Manufacturing",
    "Downstream": "Module-Pack Manufacturing",
    "Other - Equipment": "Equipment",
    "Other - Equipment ": "Equipment",
    "Other - Research": "R&D",
    "Other - Service & Repair": "Services & Consulting",
    "Other - Modeling and Software": "Modeling & Software",
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

    # Process specific category sheets first so company_type is set from the
    # sheet name. Append2 (aggregate sheet) is processed last to fill gaps
    # without overwriting the more specific types.
    SPECIFIC_SHEETS = {
        "Raw Materials", "Battery Grade Materials",
        "Other Battery Components & Mat.", "Electrode & Cell Manufacturing",
        "Module-Pack Manufacturing", "Recycling-Repurposing", "Equipment",
        "R&D", "Services & Consulting", "Modeling & Software",
        "Distributors", "Professional Services (NB)",
    }
    ordered = [s for s in available if s in SPECIFIC_SHEETS]
    ordered += [s for s in available if s not in SPECIFIC_SHEETS]

    # normalized_name -> {fields..., locations: [...]}
    companies: dict[str, dict] = {}

    for sheet in ordered:
        df = xl.parse(sheet, dtype=str)
        # Normalize column names: strip whitespace + collapse double spaces
        df.columns = [" ".join(str(c).split()) for c in df.columns]

        # Deduplicate column names — append _2, _3, etc. for repeats
        seen: dict[str, int] = {}
        new_cols = []
        for col in df.columns:
            if col in seen:
                seen[col] += 1
                new_cols.append(f"{col}_{seen[col]}")
            else:
                seen[col] = 1
                new_cols.append(col)
        df.columns = new_cols

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
            # Store the raw Supply Chain Segment column value
            segment = _safe_str(row.get("Supply Chain Segment")) or sheet
            # Always derive company_type from the sheet name — the sheet
            # categorisation IS the NAATBatt classification
            company_type = SEGMENT_TO_TYPE.get(sheet, SEGMENT_TO_TYPE.get(segment, "other"))

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
                "sources": _safe_str(row.get("Sources")),
                "sources2": _safe_str(row.get("Sources2")),
                "qc": _safe_str(row.get("QC")),
                "qc_date": _safe_str(row.get("QC Date")),
                "segment": segment,
            }

            # Handle column-name variations for contact email
            contact_email = _safe_str(
                row.get("Contact Email") or row.get("Contact email")
            )
            contact_email2 = _safe_str(row.get("Contact Email2"))
            # Handle long description variations
            long_desc = _safe_str(
                row.get("Long Description") or row.get("Long description3")
                or row.get("Long description")
            )
            row_sources = _safe_str(row.get("Sources"))
            row_sources2 = _safe_str(row.get("Sources2"))
            row_qc = _safe_str(row.get("QC"))
            row_qc_date = _safe_str(row.get("QC Date"))
            row_swc = _safe_str(row.get("Summary Word Count"))
            row_extra = _safe_str(row.get("Column1"))

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
                    "contact_email2": contact_email2,
                    "sources": row_sources,
                    "sources2": row_sources2,
                    "qc": row_qc,
                    "qc_date": row_qc_date,
                    "summary_word_count": int(row_swc) if row_swc and row_swc.isdigit() else None,
                    "extra_description": row_extra,
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
                # Aggregate sources — keep the longest/most complete value
                if row_sources and (not existing["sources"] or len(row_sources) > len(existing["sources"])):
                    existing["sources"] = row_sources
                if row_sources2 and (not existing["sources2"] or len(row_sources2) > len(existing["sources2"])):
                    existing["sources2"] = row_sources2
                if row_qc and not existing["qc"]:
                    existing["qc"] = row_qc
                if row_qc_date and not existing["qc_date"]:
                    existing["qc_date"] = row_qc_date
                if not existing.get("contact_email2") and contact_email2:
                    existing["contact_email2"] = contact_email2
                if row_swc and row_swc.isdigit() and not existing.get("summary_word_count"):
                    existing["summary_word_count"] = int(row_swc)
                if row_extra and not existing.get("extra_description"):
                    existing["extra_description"] = row_extra

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
                "summary", "long_description", "extra_description",
                "chemistries", "feedstock",
                "notes", "contact_name", "contact_email", "contact_phone",
                "contact_email2", "sources", "sources2",
                "qc", "qc_date", "summary_word_count",
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


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
BBD_LOCAL_PATH = str(_PROJECT_ROOT / "data" / "bbd_data.xlsx")
GIGAFACTORY_LOCAL_PATH = str(_PROJECT_ROOT / "data" / "gigafactory_db.xlsx")

SUPPLY_CHAIN_COLS = [
    "Raw Materials", "Battery Grade Materials",
    "Other Battery Components & Materials",
    "Electrode & Cell Manufacturing", "Module & Pack Manufacturing",
    "End-of-life Recycling", "Equipment Manufacturing", "R&D",
    "Modeling & Software", "Legal & Financial Services",
    "Technical Consulting Services", "Education", "Government",
    "Vehicle OEM", "Consumer Electronics",
]

CHEMISTRY_COLS = [
    "Lithium Cobalt Oxide (LCO)", "Lithium Iron Phosphate (LFP)",
    "Lithium Iron Manganese Phosphate (LMFP)",
    "Nickel Manganese Cobalt Oxide (NMC)", "Nickel Cobalt Aluminum Oxide",
    "Lithium Manganese Oxide (LMO)", "Lithium Sulfur", "Silicon Anode",
    "Synthetic Graphite", "Mined Graphite", "Anode Free",
    "Solid Electrolyte", "Solid State Battery", "Lead Acid",
    "Nickel Cadmium", "Nickel Metal Hydride", "Sodium Ion",
]


def import_bbd(db) -> dict:
    """Import BBD (Volta Foundation) battery company data from bbd_data.xlsx."""
    path = Path(BBD_LOCAL_PATH)
    if not path.exists():
        log.warning("BBD file not found at %s — skipping.", path)
        return {"status": "skipped", "rows_added": 0, "rows_updated": 0}

    log.info("Importing BBD data from %s …", path)
    df = pd.read_excel(path, sheet_name="Data", dtype=str)
    now = datetime.now(timezone.utc).isoformat()
    added = updated = 0

    for _, row in df.iterrows():
        name = _safe_str(row.get("company_name"))
        if not name:
            continue

        sc_flags = {col: _safe_str(row.get(col)) == "True" for col in SUPPLY_CHAIN_COLS}
        chem_flags = {col: _safe_str(row.get(col)) == "True" for col in CHEMISTRY_COLS}

        data = {
            "company_name": name,
            "company_website": _safe_str(row.get("company_website")),
            "crunchbase_url": _safe_str(row.get("crunchbase_url")),
            "linkedin_url": _safe_str(row.get("linkedIn_url")),
            "pitchbook_url": _safe_str(row.get("pitchbook_url")),
            "summary": _safe_str(row.get("company_description")),
            "volta_member": 1 if _safe_str(row.get("volta_foundation_member")) == "True" else 0,
            "volta_verified": 1 if _safe_str(row.get("volta_verified")) == "True" else 0,
            "funding_status": _safe_str(row.get("funding_status")),
            "employee_size": _safe_str(row.get("employee_size")),
            "company_hq_city": _safe_str(row.get("city")),
            "company_hq_state": _safe_str(row.get("state")),
            "company_hq_country": _safe_str(row.get("country")),
            "products": _safe_str(row.get("products")),
            "product_services_desc": _safe_str(row.get("product_services_description")),
            "supply_chain_segment": _safe_str(row.get("supply_chain_segment")),
            "chemistries": _safe_str(row.get("battery_chemistry")),
            "supply_chain_flags": json.dumps(sc_flags),
            "battery_chemistry_flags": json.dumps(chem_flags),
            "data_source": "bbd_xlsx",
            "last_updated": now,
        }

        existing = (
            db.query(Company)
            .filter(Company.company_name.ilike(name))
            .first()
        )
        if existing:
            # Fill BBD-specific fields without overwriting NAATBatt data
            for field in [
                "company_website", "crunchbase_url", "linkedin_url", "pitchbook_url",
                "summary", "funding_status", "employee_size",
                "company_hq_city", "company_hq_state", "company_hq_country",
                "products", "product_services_desc", "supply_chain_segment", "chemistries",
            ]:
                if not getattr(existing, field, None) and data.get(field):
                    setattr(existing, field, data[field])
            # Always set BBD-only fields
            existing.volta_member = data["volta_member"]
            existing.volta_verified = data["volta_verified"]
            existing.supply_chain_flags = data["supply_chain_flags"]
            existing.battery_chemistry_flags = data["battery_chemistry_flags"]
            updated += 1
        else:
            db.add(Company(**data))
            added += 1

    db.commit()
    log.info("BBD import complete: %d added, %d updated", added, updated)

    db.add(SyncLog(
        source="bbd_xlsx", status="success",
        rows_added=added, rows_updated=updated,
        run_at=now,
    ))
    db.commit()
    return {"status": "success", "rows_added": added, "rows_updated": updated}


GWH_YEARS = ["2022", "2023", "2024", "2025", "2026", "2027", "2028", "2029", "2030"]
GWH_COL_MAP = {"2022": "Current GWh capacity 2022"}  # first year has a different column name

SECTION_HEADERS = {"asia pacific", "europe", "north america"}


def import_gigafactory(db) -> dict:
    """Import gigafactory battery cell plant data from gigafactory_db.xlsx."""
    path = Path(GIGAFACTORY_LOCAL_PATH)
    if not path.exists():
        log.warning("Gigafactory file not found at %s — skipping.", path)
        return {"status": "skipped", "rows_added": 0, "rows_updated": 0}

    log.info("Importing gigafactory data from %s …", path)
    df = pd.read_excel(path, sheet_name="Global", dtype=str, header=1)
    df.columns = [" ".join(str(c).split()) for c in df.columns]
    now = datetime.now(timezone.utc).isoformat()
    added = updated = 0
    # Track companies added in this batch (autoflush=False means queries
    # won't see unflushed additions)
    batch_added: dict[str, Company] = {}

    for _, row in df.iterrows():
        name = _safe_str(row.get("Company"))
        if not name:
            continue
        # Skip section header rows like "Asia Pacific current plants"
        if any(name.lower().startswith(h) for h in SECTION_HEADERS):
            continue

        gwh: dict[str, float] = {}
        for year in GWH_YEARS:
            col = GWH_COL_MAP.get(year, year)
            val = _safe_float(row.get(col))
            if val is not None:
                gwh[year] = val

        existing = (
            db.query(Company)
            .filter(Company.company_name.ilike(name))
            .first()
        ) or batch_added.get(name.lower())

        if existing:
            # Merge GWh — sum across multiple plants for the same company
            old_gwh = json.loads(existing.gwh_capacity or "{}")
            for year, val in gwh.items():
                old_gwh[year] = old_gwh.get(year, 0) + val
            existing.gwh_capacity = json.dumps(old_gwh)
            if not existing.plant_start_date:
                existing.plant_start_date = _safe_str(row.get("Start Date"))
            if not existing.notes:
                existing.notes = _safe_str(row.get("Notes"))
            updated += 1
        else:
            company = Company(
                company_name=name,
                company_hq_city=_safe_str(row.get("City")),
                company_hq_country=_safe_str(row.get("Country")),
                gwh_capacity=json.dumps(gwh),
                plant_start_date=_safe_str(row.get("Start Date")),
                notes=_safe_str(row.get("Notes")),
                company_type="Electrode & Cell Manufacturing",
                data_source="gigafactory_xlsx",
                last_updated=now,
            )
            db.add(company)
            batch_added[name.lower()] = company
            added += 1

    db.commit()
    log.info("Gigafactory import complete: %d added, %d updated", added, updated)

    db.add(SyncLog(
        source="gigafactory_xlsx", status="success",
        rows_added=added, rows_updated=updated,
        run_at=now,
    ))
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
            log.info("NAATBatt seed result: %s", result)
            result = import_bbd(db)
            log.info("BBD seed result: %s", result)
            result = import_gigafactory(db)
            log.info("Gigafactory seed result: %s", result)
        else:
            log.info("DB already has %d companies — skipping seed.", count)
    finally:
        db.close()
