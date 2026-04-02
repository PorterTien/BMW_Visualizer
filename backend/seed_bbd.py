"""
Volta Foundation Battery Business Directory (BBD) importer.
Parses bbd-data.xlsx and merges into companies table.
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

BBD_PATH = "data/bbd_data.xlsx"

# Map BBD supply chain columns to our company_type values
BBD_SEGMENT_TO_TYPE = {
    "Raw Materials": "Raw Materials",
    "Battery Grade Materials": "Battery Grade Materials",
    "Other Battery Components & Materials": "Other Battery Components & Mat.",
    "Electrode & Cell Manufacturing": "Electrode & Cell Manufacturing",
    "Module & Pack Manufacturing": "Module-Pack Manufacturing",
    "End-of-life Recycling": "Recycling-Repurposing",
    "Equipment Manufacturing": "Equipment",
    "R&D": "R&D",
    "Modeling & Software": "Modeling & Software",
    "Legal & Financial Services": "Services & Consulting",
    "Technical Consulting Services": "Services & Consulting",
    "Education": "R&D",
    "Government": "Services & Consulting",
    "Vehicle OEM": "Module-Pack Manufacturing",
    "Consumer Electronics": "Module-Pack Manufacturing",
}

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


def _safe_str(val) -> str | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    return str(val).strip() or None


def _is_true(val) -> bool:
    if val is None:
        return False
    return str(val).strip().lower() in ("true", "1", "yes")


def parse_bbd() -> list[dict]:
    """Parse BBD XLSX. Returns list of company dicts."""
    df = pd.read_excel(BBD_PATH, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]
    log.info("BBD: %d rows, %d columns", len(df), len(df.columns))

    results = []
    for _, row in df.iterrows():
        name = _safe_str(row.get("company_name"))
        if not name:
            continue

        # Determine primary type from supply chain flags
        active_segments = []
        supply_chain_flags = {}
        for col in SUPPLY_CHAIN_COLS:
            flag = _is_true(row.get(col))
            supply_chain_flags[col] = flag
            if flag:
                active_segments.append(col)

        # Pick the first active segment as primary type
        company_type = None
        for seg in active_segments:
            mapped = BBD_SEGMENT_TO_TYPE.get(seg)
            if mapped:
                company_type = mapped
                break

        # Build chemistry flags
        chemistry_flags = {}
        active_chems = []
        for col in CHEMISTRY_COLS:
            flag = _is_true(row.get(col))
            chemistry_flags[col] = flag
            if flag:
                active_chems.append(col)

        results.append({
            "company_name": name,
            "company_website": _safe_str(row.get("company_website")),
            "summary": _safe_str(row.get("company_description")),
            "funding_status": _safe_str(row.get("funding_status")),
            "employee_size": _safe_str(row.get("employee_size")),
            "company_hq_city": _safe_str(row.get("city")),
            "company_hq_state": _safe_str(row.get("state")),
            "company_hq_country": _safe_str(row.get("country")),
            "crunchbase_url": _safe_str(row.get("crunchbase_url")),
            "linkedin_url": _safe_str(row.get("linkedIn_url")),
            "pitchbook_url": _safe_str(row.get("pitchbook_url")),
            "volta_member": 1 if _is_true(row.get("volta_foundation_member")) else 0,
            "volta_verified": 1 if _is_true(row.get("volta_verified")) else 0,
            "products": _safe_str(row.get("products")),
            "product_services_desc": _safe_str(row.get("product_services_description")),
            "company_type": company_type,
            "supply_chain_flags": json.dumps(supply_chain_flags),
            "battery_chemistry_flags": json.dumps(chemistry_flags),
            "chemistries": ", ".join(active_chems) if active_chems else None,
            "supply_chain_segment": _safe_str(row.get("supply_chain_segment")),
            "battery_chemistry": _safe_str(row.get("battery_chemistry")),
        })

    log.info("Parsed %d companies from BBD", len(results))
    return results


def import_bbd(db) -> dict:
    """Import BBD data, enriching existing companies or creating new ones."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        companies = parse_bbd()
    except Exception as e:
        log.error("BBD import failed: %s", e)
        db.add(SyncLog(source="bbd", status="failed", rows_added=0, rows_updated=0, error_message=str(e), run_at=now))
        db.commit()
        return {"status": "failed", "error": str(e)}

    added = updated = 0

    # BBD-only fields that enrich without overwriting NAATBatt data
    ENRICH_FIELDS = [
        "funding_status", "employee_size", "crunchbase_url", "linkedin_url",
        "pitchbook_url", "products", "product_services_desc",
        "supply_chain_flags", "battery_chemistry_flags",
    ]

    for data in companies:
        name = data.pop("company_name")
        battery_chemistry = data.pop("battery_chemistry", None)

        existing = db.query(Company).filter(Company.company_name.ilike(name)).first()

        if existing:
            # Enrich: only fill in empty fields, never overwrite NAATBatt data
            for field in ENRICH_FIELDS:
                val = data.get(field)
                if val and not getattr(existing, field, None):
                    setattr(existing, field, val)
            # Volta membership flags always update
            if data.get("volta_member"):
                existing.volta_member = 1
            if data.get("volta_verified"):
                existing.volta_verified = 1
            # Enrich summary if empty
            if not existing.summary and data.get("summary"):
                existing.summary = data["summary"]
            # Enrich website if empty
            if not existing.company_website and data.get("company_website"):
                existing.company_website = data["company_website"]
            # Enrich chemistries if empty
            if not existing.chemistries and data.get("chemistries"):
                existing.chemistries = data["chemistries"]
            existing.last_updated = now
            updated += 1
        else:
            company = Company(
                company_name=name,
                company_hq_city=data.get("company_hq_city"),
                company_hq_state=data.get("company_hq_state"),
                company_hq_country=data.get("company_hq_country"),
                company_website=data.get("company_website"),
                company_type=data.get("company_type"),
                supply_chain_segment=data.get("supply_chain_segment"),
                summary=data.get("summary"),
                chemistries=data.get("chemistries"),
                funding_status=data.get("funding_status"),
                employee_size=data.get("employee_size"),
                crunchbase_url=data.get("crunchbase_url"),
                linkedin_url=data.get("linkedin_url"),
                pitchbook_url=data.get("pitchbook_url"),
                volta_member=data.get("volta_member", 0),
                volta_verified=data.get("volta_verified", 0),
                products=data.get("products"),
                product_services_desc=data.get("product_services_desc"),
                supply_chain_flags=data.get("supply_chain_flags"),
                battery_chemistry_flags=data.get("battery_chemistry_flags"),
                data_source="bbd",
                last_updated=now,
            )
            db.add(company)
            added += 1

    db.commit()
    log.info("BBD import: %d added, %d updated", added, updated)

    db.add(SyncLog(source="bbd", status="success", rows_added=added, rows_updated=updated, run_at=now))
    db.commit()
    return {"status": "success", "rows_added": added, "rows_updated": updated}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
    init_db()
    db = SessionLocal()
    try:
        result = import_bbd(db)
        print(result)
    finally:
        db.close()
