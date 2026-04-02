"""
Ultima Media Gigafactory Database importer.
Parses GWh capacity projections (2022-2030) per plant and merges into companies table.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.database import SessionLocal, init_db
from backend.models import Company, SyncLog

log = logging.getLogger(__name__)

GIGAFACTORY_PATH = "data/gigafactory_db.xlsx"

# Section headers / non-data rows to skip
SKIP_PATTERNS = [
    "current plants", "planned plants", "north america", "europe",
    "asia pacific", "total", "sum", "sources", "grand total",
]

CAPACITY_YEARS = ["2022", "2023", "2024", "2025", "2026", "2027", "2028", "2029", "2030"]


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


def parse_gigafactory() -> dict[str, dict]:
    """Parse the Global sheet. Returns dict keyed by normalized company name."""
    xl = pd.ExcelFile(GIGAFACTORY_PATH)
    df = xl.parse("Global", dtype=str, header=None)

    # Row 1 is the header
    headers = [
        "Company", "Start Date", "GWh_2022", "2023", "2024", "2025",
        "2026", "2027", "2028", "2029", "2030", "City", "Country", "Region", "Notes",
    ]
    df = df.iloc[2:]  # skip title + header rows
    df.columns = headers

    companies: dict[str, dict] = {}

    for _, row in df.iterrows():
        name = _safe_str(row.get("Company"))
        if not name:
            continue
        # Skip section headers
        if any(p in name.lower() for p in SKIP_PATTERNS):
            continue

        key = name.strip().lower()
        city = _safe_str(row.get("City"))
        country = _safe_str(row.get("Country"))
        region = _safe_str(row.get("Region"))
        start_date = _safe_str(row.get("Start Date"))
        notes = _safe_str(row.get("Notes"))

        # Build capacity dict
        capacity = {}
        for yr in CAPACITY_YEARS:
            col = yr if yr != "2022" else "GWh_2022"
            val = _safe_float(row.get(col))
            if val is not None:
                capacity[yr] = val

        plant = {
            "city": city,
            "country": country,
            "region": region,
            "start_date": start_date,
            "notes": notes,
            "gwh_capacity": capacity,
        }

        if key not in companies:
            companies[key] = {
                "company_name": name,
                "company_hq_country": country,
                "plant_start_date": start_date,
                "gwh_capacity": capacity,
                "plants": [plant],
            }
        else:
            existing = companies[key]
            existing["plants"].append(plant)
            # Aggregate capacity across all plants
            for yr, val in capacity.items():
                existing["gwh_capacity"][yr] = existing["gwh_capacity"].get(yr, 0) + val
            # Keep earliest start date
            if start_date and (not existing["plant_start_date"] or start_date < existing["plant_start_date"]):
                existing["plant_start_date"] = start_date

    log.info("Parsed %d unique companies from gigafactory DB", len(companies))
    return companies


def import_gigafactory(db) -> dict:
    """Import gigafactory data, merging with existing companies."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        companies = parse_gigafactory()
    except Exception as e:
        log.error("Gigafactory import failed: %s", e)
        db.add(SyncLog(source="gigafactory", status="failed", rows_added=0, rows_updated=0, error_message=str(e), run_at=now))
        db.commit()
        return {"status": "failed", "error": str(e)}

    added = updated = 0

    for key, data in companies.items():
        plants = data.pop("plants")
        gwh = data.pop("gwh_capacity")

        existing = db.query(Company).filter(Company.company_name.ilike(data["company_name"])).first()

        if existing:
            # Enrich: add gigafactory data without overwriting NAATBatt fields
            existing.gwh_capacity = json.dumps(gwh)
            if data["plant_start_date"] and not existing.plant_start_date:
                existing.plant_start_date = data["plant_start_date"]
            # Merge plants into existing locations
            locs = json.loads(existing.company_locations or "[]")
            for p in plants:
                locs.append({
                    "facility_name": f"{data['company_name']} - Gigafactory",
                    "city": p["city"],
                    "country": p["country"],
                    "status": f"Start: {p['start_date']}" if p["start_date"] else None,
                    "capacity": str(max(p["gwh_capacity"].values())) + " GWh" if p["gwh_capacity"] else None,
                    "notes": p["notes"],
                    "sources": "Ultima Media Gigafactory Database (July 2022)",
                    "segment": "Electrode & Cell Manufacturing",
                })
            existing.company_locations = json.dumps(locs)
            existing.last_updated = now
            updated += 1
        else:
            locs = []
            for p in plants:
                locs.append({
                    "facility_name": f"{data['company_name']} - Gigafactory",
                    "city": p["city"],
                    "country": p["country"],
                    "status": f"Start: {p['start_date']}" if p["start_date"] else None,
                    "capacity": str(max(p["gwh_capacity"].values())) + " GWh" if p["gwh_capacity"] else None,
                    "notes": p["notes"],
                    "sources": "Ultima Media Gigafactory Database (July 2022)",
                    "segment": "Electrode & Cell Manufacturing",
                })
            company = Company(
                company_name=data["company_name"],
                company_hq_country=data["company_hq_country"],
                company_type="Electrode & Cell Manufacturing",
                company_locations=json.dumps(locs),
                gwh_capacity=json.dumps(gwh),
                plant_start_date=data["plant_start_date"],
                data_source="gigafactory",
                last_updated=now,
            )
            db.add(company)
            added += 1

    db.commit()
    log.info("Gigafactory import: %d added, %d updated", added, updated)

    db.add(SyncLog(source="gigafactory", status="success", rows_added=added, rows_updated=updated, run_at=now))
    db.commit()
    return {"status": "success", "rows_added": added, "rows_updated": updated}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
    init_db()
    db = SessionLocal()
    try:
        result = import_gigafactory(db)
        print(result)
    finally:
        db.close()
