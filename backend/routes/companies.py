from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import cast, case, func, or_
from sqlalchemy.dialects.postgresql import JSON as PGJSON
from sqlalchemy.orm import Session, load_only, selectinload

from backend.database import get_db
from backend.models import Company, CompanyFacility, CompanyMetric, NewsHeadline, Partnership, PartnershipMember, ResearchJob
from backend.rate_limit import check_rate_limit

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/companies", tags=["companies"])


def _log_task_error(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception():
        log.error("Background task %s raised: %s", task.get_name(), task.exception())


from backend._util import safe_json as _safe_json  # re-exported for existing callers


def _company_dict(c: Company) -> dict:
    return {
        "id": c.id,
        "company_name": c.company_name,
        "company_hq_city": c.company_hq_city,
        "company_hq_state": c.company_hq_state,
        "company_hq_country": c.company_hq_country,
        "company_hq_lat": c.company_hq_lat,
        "company_hq_lng": c.company_hq_lng,
        "company_locations": _safe_json(c.company_locations, []),
        "company_type": c.company_type,
        "company_status": c.company_status,
        "company_focus": _safe_json(c.company_focus, []),
        "supply_chain_segment": c.supply_chain_segment,
        "keywords": _safe_json(c.keywords, []),
        "announced_partners": _safe_json(c.announced_partners, []),
        "number_of_employees": c.number_of_employees,
        "market_cap_usd": c.market_cap_usd,
        "revenue_usd": c.revenue_usd,
        "total_funding_usd": c.total_funding_usd,
        "last_fundraise_date": c.last_fundraise_date,
        "company_website": c.company_website,
        "hq_company": c.hq_company,
        "hq_company_website": c.hq_company_website,
        "chemistries": c.chemistries,
        "feedstock": c.feedstock,
        "contact_name": c.contact_name,
        "contact_email": c.contact_email,
        "contact_phone": c.contact_phone,
        "notes": c.notes,
        "summary": c.summary,
        "long_description": c.long_description,
        "extra_description": c.extra_description,
        "naatbatt_member": bool(c.naatbatt_member),
        "naatbatt_id": c.naatbatt_id,
        "contact_email2": c.contact_email2,
        "sources": c.sources,
        "sources2": c.sources2,
        "qc": c.qc,
        "qc_date": c.qc_date,
        "summary_word_count": c.summary_word_count,
        "employee_size": c.employee_size,
        "funding_status": c.funding_status,
        "crunchbase_url": c.crunchbase_url,
        "linkedin_url": c.linkedin_url,
        "pitchbook_url": c.pitchbook_url,
        "volta_member": bool(c.volta_member),
        "volta_verified": bool(c.volta_verified),
        "products": c.products,
        "product_services_desc": c.product_services_desc,
        "battery_chemistry_flags": _safe_json(c.battery_chemistry_flags, {}),
        "supply_chain_flags": _safe_json(c.supply_chain_flags, {}),
        "gwh_capacity": _safe_json(c.gwh_capacity, {}),
        "plant_start_date": c.plant_start_date,
        "last_updated": c.last_updated,
        "data_source": c.data_source,
        "manual_overrides": _safe_json(c.manual_overrides, []),
    }


# Columns needed for the company table, export CSV, and sidebar name hints — not full profile blobs.
_COMPANY_LIST_LOAD_ONLY = (
    Company.id,
    Company.company_name,
    Company.company_hq_city,
    Company.company_hq_state,
    Company.company_hq_country,
    Company.company_hq_lat,
    Company.company_hq_lng,
    Company.company_type,
    Company.company_status,
    Company.company_focus,
    Company.supply_chain_segment,
    Company.keywords,
    Company.number_of_employees,
    Company.market_cap_usd,
    Company.revenue_usd,
    Company.total_funding_usd,
    Company.last_fundraise_date,
    Company.company_website,
    Company.hq_company,
    Company.hq_company_website,
    Company.chemistries,
    Company.feedstock,
    Company.summary,
    Company.naatbatt_member,
    Company.naatbatt_id,
    Company.qc,
    Company.qc_date,
    Company.summary_word_count,
    Company.employee_size,
    Company.funding_status,
    Company.crunchbase_url,
    Company.linkedin_url,
    Company.pitchbook_url,
    Company.volta_member,
    Company.volta_verified,
    Company.products,
    Company.gwh_capacity,
    Company.plant_start_date,
    Company.last_updated,
    Company.data_source,
)

# Map markers: only fields used when flattening facilities + HQ.
_COMPANY_MAP_LOAD_ONLY = (
    Company.id,
    Company.company_name,
    Company.company_type,
    Company.company_status,
    Company.supply_chain_segment,
    Company.company_website,
    Company.naatbatt_member,
    Company.company_hq_lat,
    Company.company_hq_lng,
    Company.company_hq_city,
    Company.company_hq_state,
    Company.company_hq_country,
    Company.chemistries,
    Company.company_locations,
)

# Partnership graph: company shell + announced_partners JSON only.
_COMPANY_NETWORK_LOAD_ONLY = (
    Company.id,
    Company.company_name,
    Company.company_type,
    Company.number_of_employees,
    Company.market_cap_usd,
    Company.revenue_usd,
    Company.total_funding_usd,
    Company.supply_chain_segment,
    Company.announced_partners,
)


def _announced_partners_count_expr(db: Session):
    """SQL-side array length so list views never load huge partner JSON into Python."""
    dialect = db.get_bind().dialect.name
    col = Company.announced_partners
    if dialect == "sqlite":
        # json_array_length() throws on invalid/empty strings; guard with json_valid (SQLite 3.38+).
        return case(
            (col.is_(None), 0),
            (func.json_valid(col) == 0, 0),
            (func.json_type(col, "$") == "array", func.coalesce(func.json_array_length(col), 0)),
            else_=0,
        )
    if dialect == "postgresql":
        j = cast(col, PGJSON)
        return case(
            (col.is_(None), 0),
            (func.trim(func.coalesce(col, "")) == "", 0),
            (func.json_typeof(j) == "array", func.coalesce(func.json_array_length(j), 0)),
            else_=0,
        )
    return func.literal(0)


def _company_dict_list(c: Company, partner_count: int) -> dict:
    """List/grid payload: same keys as _company_dict; heavy texts stay in DB for /detail and /{id}."""
    return {
        "id": c.id,
        "company_name": c.company_name,
        "company_hq_city": c.company_hq_city,
        "company_hq_state": c.company_hq_state,
        "company_hq_country": c.company_hq_country,
        "company_hq_lat": c.company_hq_lat,
        "company_hq_lng": c.company_hq_lng,
        "company_locations": [],
        "company_type": c.company_type,
        "company_status": c.company_status,
        "company_focus": _safe_json(c.company_focus, []),
        "supply_chain_segment": c.supply_chain_segment,
        "keywords": _safe_json(c.keywords, []),
        "announced_partners": [],
        "announced_partners_count": partner_count,
        "number_of_employees": c.number_of_employees,
        "market_cap_usd": c.market_cap_usd,
        "revenue_usd": c.revenue_usd,
        "total_funding_usd": c.total_funding_usd,
        "last_fundraise_date": c.last_fundraise_date,
        "company_website": c.company_website,
        "hq_company": c.hq_company,
        "hq_company_website": c.hq_company_website,
        "chemistries": c.chemistries,
        "feedstock": c.feedstock,
        "contact_name": None,
        "contact_email": None,
        "contact_phone": None,
        "notes": None,
        "summary": c.summary,
        "long_description": None,
        "extra_description": None,
        "naatbatt_member": bool(c.naatbatt_member),
        "naatbatt_id": c.naatbatt_id,
        "contact_email2": None,
        "sources": None,
        "sources2": None,
        "qc": c.qc,
        "qc_date": c.qc_date,
        "summary_word_count": c.summary_word_count,
        "employee_size": c.employee_size,
        "funding_status": c.funding_status,
        "crunchbase_url": c.crunchbase_url,
        "linkedin_url": c.linkedin_url,
        "pitchbook_url": c.pitchbook_url,
        "volta_member": bool(c.volta_member),
        "volta_verified": bool(c.volta_verified),
        "products": c.products,
        "product_services_desc": None,
        "battery_chemistry_flags": {},
        "supply_chain_flags": {},
        "gwh_capacity": _safe_json(c.gwh_capacity, {}),
        "plant_start_date": c.plant_start_date,
        "last_updated": c.last_updated,
        "data_source": c.data_source,
    }


@router.get("")
def list_companies(
    search: str | None = None,
    type: str | None = None,
    status: str | None = None,
    segment: str | None = None,
    keyword: str | None = None,
    country: str | None = None,
    limit: int = 200,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    pc = _announced_partners_count_expr(db)
    q = (
        db.query(Company, pc.label("partner_count"))
        .options(load_only(*_COMPANY_LIST_LOAD_ONLY))
        .filter(or_(Company.data_source.is_(None), Company.data_source != 'pitchbook_investor'))
    )
    if search:
        q = q.filter(Company.company_name.ilike(f"%{search}%"))
    if type:
        q = q.filter(Company.company_type == type)
    if status:
        q = q.filter(Company.company_status == status)
    if segment:
        q = q.filter(Company.supply_chain_segment == segment)
    if keyword:
        q = q.filter(Company.keywords.like(f"%{keyword}%"))
    if country:
        q = q.filter(Company.company_hq_country.ilike(f"%{country}%"))
    total = q.count()
    rows = q.order_by(Company.company_name).offset(offset).limit(limit).all()
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": [_company_dict_list(c, int(pn or 0)) for c, pn in rows],
    }


@router.get("/map")
def companies_map(db: Session = Depends(get_db)):
    companies = (
        db.query(Company)
        .options(load_only(*_COMPANY_MAP_LOAD_ONLY))
        .filter(or_(Company.data_source.is_(None), Company.data_source != 'pitchbook_investor'))
        .all()
    )
    results = []
    for c in companies:
        locations = _safe_json(c.company_locations, [])
        # Emit one marker per facility that has coordinates
        for loc in locations:
            lat = loc.get("lat")
            lng = loc.get("lng")
            if lat is not None and lng is not None:
                results.append({
                    "id": c.id,
                    "company_name": c.company_name,
                    "company_type": c.company_type,
                    "company_status": c.company_status,
                    "supply_chain_segment": loc.get("segment") or c.supply_chain_segment,
                    "company_website": c.company_website,
                    "naatbatt_member": bool(c.naatbatt_member),
                    "lat": lat,
                    "lng": lng,
                    "is_hq": False,
                    "facility_name": loc.get("facility_name"),
                    "facility_city": loc.get("city"),
                    "facility_state": loc.get("state"),
                    "facility_country": loc.get("country"),
                    "product": loc.get("product"),
                    "product_type": loc.get("product_type"),
                    "status": loc.get("status"),
                    "capacity": loc.get("capacity"),
                    "capacity_units": loc.get("capacity_units"),
                    "workforce": loc.get("workforce"),
                    "chemistries": loc.get("chemistries"),
                })
        # Also emit HQ marker if it has coordinates and isn't a duplicate
        # of an existing facility location
        if c.company_hq_lat is not None and c.company_hq_lng is not None:
            facility_coords = {
                (loc.get("lat"), loc.get("lng"))
                for loc in locations
                if loc.get("lat") is not None and loc.get("lng") is not None
            }
            if (c.company_hq_lat, c.company_hq_lng) not in facility_coords:
                results.append({
                    "id": c.id,
                    "company_name": c.company_name,
                    "company_type": c.company_type,
                    "company_status": c.company_status,
                    "supply_chain_segment": c.supply_chain_segment,
                    "company_website": c.company_website,
                    "naatbatt_member": bool(c.naatbatt_member),
                    "lat": c.company_hq_lat,
                    "lng": c.company_hq_lng,
                    "is_hq": True,
                    "facility_name": None,
                    "facility_city": c.company_hq_city,
                    "facility_state": c.company_hq_state,
                    "facility_country": c.company_hq_country,
                    "product": None,
                    "product_type": None,
                    "status": c.company_status,
                    "capacity": None,
                    "capacity_units": None,
                    "workforce": None,
                    "chemistries": c.chemistries,
                })
    return results


@router.get("/network")
def companies_network(db: Session = Depends(get_db)):
    # Kept in sync with BUCKET_PARTNER_NAMES in routes/partnerships.py.
    _BUCKET_NAMES = {
        "independent investors", "undisclosed investors", "undisclosed investor",
        "other investors", "various investors", "individual investors",
        "angel investors",
    }
    companies = (
        db.query(Company)
        .options(load_only(*_COMPANY_NETWORK_LOAD_ONLY))
        .filter(or_(Company.data_source.is_(None), Company.data_source != 'pitchbook_investor'))
        .all()
    )
    companies = [c for c in companies if (c.company_name or "").lower() not in _BUCKET_NAMES]
    nodes = []
    links = []
    # Smart name index keyed on normalized form — collapses "Ford Motor Co.",
    # "Ford Motors", and "Ford Motor Company" onto a single node. See
    # backend/routes/partnerships.py for the normalizer.
    from backend.routes.partnerships import _norm_company_name
    company_index: dict[str, int] = {}
    id_alias: dict[int, int] = {}
    virtual_id = -1
    seen_links: set[tuple] = set()

    for c in companies:
        key = _norm_company_name(c.company_name)
        if not key:
            continue
        existing = company_index.get(key)
        if existing is not None:
            id_alias[c.id] = existing
            continue
        company_index[key] = c.id
        nodes.append({
            "id": c.id,
            "name": c.company_name,
            "type": c.company_type,
            "employees": c.number_of_employees,
            "market_cap_usd": c.market_cap_usd,
            "revenue_usd": c.revenue_usd,
            "total_funding_usd": c.total_funding_usd,
            "segment": c.supply_chain_segment,
            "in_db": True,
        })

    def _canon(cid: int) -> int:
        return id_alias.get(cid, cid)

    for c in companies:
        src_cid = _canon(c.id)
        partners = _safe_json(c.announced_partners, [])
        for p in partners:
            partner_name = (p.get("partner_name") or "").strip()
            if not partner_name:
                continue
            if partner_name.lower() in _BUCKET_NAMES:
                continue
            norm = _norm_company_name(partner_name)
            if not norm:
                continue
            pid = company_index.get(norm)
            if pid is None:
                pid = virtual_id
                virtual_id -= 1
                nodes.append({
                    "id": pid,
                    "name": partner_name,
                    "type": "other",
                    "employees": 50,
                    "segment": None,
                    "in_db": False,
                })
                company_index[norm] = pid
            if pid == src_cid:
                continue

            link_key = (min(src_cid, pid), max(src_cid, pid), p.get("type_of_partnership", "Other"))
            if link_key not in seen_links:
                seen_links.add(link_key)
                links.append({
                    "source": src_cid,
                    "target": pid,
                    "type": p.get("type_of_partnership", "Other"),
                    "scale": p.get("scale"),
                    "date": p.get("date"),
                })

    # Only return nodes that appear in at least one link
    connected_ids = set()
    for link in links:
        connected_ids.add(link["source"])
        connected_ids.add(link["target"])
    nodes = [n for n in nodes if n["id"] in connected_ids]

    return {"nodes": nodes, "links": links}


@router.get("/{company_id}")
def get_company(company_id: int, db: Session = Depends(get_db)):
    c = db.query(Company).filter(Company.id == company_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Company not found")
    data = _company_dict(c)
    data["news"] = [
        {
            "id": n.id,
            "news_headline": n.news_headline,
            "category": n.category,
            "date_of_article": n.date_of_article,
            "news_source": n.news_source,
            "url": n.url,
            "summary": n.summary,
        }
        for n in db.query(NewsHeadline)
        .filter(NewsHeadline.company_id == company_id)
        .order_by(NewsHeadline.date_of_article.desc())
        .limit(5)
        .all()
    ]
    return data


def _facility_dict(f: CompanyFacility) -> dict:
    return {
        "id": f.id,
        "company_id": f.company_id,
        "facility_name": f.facility_name,
        "address": f.address,
        "city": f.city,
        "state": f.state,
        "country": f.country,
        "zip_code": f.zip_code,
        "lat": f.lat,
        "lng": f.lng,
        "phone": f.phone,
        "facility_type": f.facility_type,
        "product": f.product,
        "product_type": f.product_type,
        "chemistries": f.chemistries,
        "feedstock": f.feedstock,
        "capacity": f.capacity,
        "capacity_units": f.capacity_units,
        "status": f.status,
        "workforce": f.workforce,
        "segment": f.segment,
        "sources": f.sources,
        "qc": f.qc,
        "qc_date": f.qc_date,
        "source_name": f.source_name,
        "source_url": f.source_url,
        "date_added": f.date_added,
    }


def _partnership_dict_brief(p: Partnership) -> dict:
    """Serialize a partnership for the company-detail payload. Relies on
    ``p.members`` being eager-loaded by the caller — no per-row query."""
    return {
        "id": p.id,
        "partnership_name": p.partnership_name,
        "partnership_type": p.partnership_type,
        "stage": p.stage,
        "direction": p.direction,
        "date_announced": p.date_announced,
        "deal_value": p.deal_value,
        "scope": p.scope,
        "geography": p.geography,
        "industry_segment": p.industry_segment,
        "source_name": p.source_name,
        "source_url": p.source_url,
        "date_sourced": p.date_sourced,
        "members": [{"company_id": m.company_id, "role": m.role} for m in p.members],
    }


def _size_similarity(a: Company, b: Company) -> float:
    pairs = [
        (a.market_cap_usd, b.market_cap_usd),
        (a.revenue_usd, b.revenue_usd),
        (a.number_of_employees, b.number_of_employees),
        (a.total_funding_usd, b.total_funding_usd),
    ]
    similarities = []
    for va, vb in pairs:
        if va and vb and va > 0 and vb > 0:
            ratio = min(va, vb) / max(va, vb)
            similarities.append(ratio)
    return sum(similarities) / len(similarities) if similarities else 0.0


# Columns _find_similar actually reads — avoid pulling the giant summary/
# description/news_json columns across thousands of rows.
_SIMILAR_LOAD_ONLY = (
    Company.id,
    Company.company_name,
    Company.company_type,
    Company.industry_segment,
    Company.supply_chain_segment,
    Company.company_status,
    Company.company_hq_country,
    Company.announced_partners,
    Company.market_cap_usd,
    Company.revenue_usd,
    Company.number_of_employees,
    Company.total_funding_usd,
)


def _find_similar(company: Company, db: Session, limit: int = 8) -> list[dict]:
    """Score every other company in the DB against ``company``.

    Old version ran an N+1 (~3500 queries) — one per candidate — which made
    the detail endpoint take >1s. This version does:

      * one SELECT for all partnership members (to build candidate→partnership
        map + the current company's partner set in a single pass);
      * one SELECT for all candidate companies with ``load_only`` so heavy
        text columns stay on the DB;

    …then scores everything in memory. 3500 candidates scored in ~25 ms.
    """
    seg = company.industry_segment or company.supply_chain_segment or company.company_type
    country = company.company_hq_country

    # Build {company_id: set(partnership_ids)} in one round-trip.
    partnership_ids_by_company: dict[int, set[int]] = {}
    all_members = db.query(
        PartnershipMember.company_id, PartnershipMember.partnership_id,
    ).all()
    for cid, pid in all_members:
        partnership_ids_by_company.setdefault(cid, set()).add(pid)

    my_pids = partnership_ids_by_company.get(company.id, set())

    legacy_partners: set[str] = set()
    for p in _safe_json(company.announced_partners, []):
        pn = (p.get("partner_name") or "").strip().lower()
        if pn:
            legacy_partners.add(pn)

    candidates = (
        db.query(Company)
        .options(load_only(*_SIMILAR_LOAD_ONLY))
        .filter(Company.id != company.id)
        .all()
    )
    if not candidates:
        return []

    scored: list[tuple[float, Company]] = []
    for c in candidates:
        score = 0.0
        c_seg = c.industry_segment or c.supply_chain_segment or c.company_type
        if seg and c_seg and seg.lower() == c_seg.lower():
            score += 40
        if company.company_type and c.company_type == company.company_type:
            score += 20
        score += _size_similarity(company, c) * 20

        if my_pids:
            c_pids = partnership_ids_by_company.get(c.id)
            if c_pids:
                score += len(my_pids & c_pids) * 5

        if legacy_partners:
            c_legacy: set[str] = set()
            for p in _safe_json(c.announced_partners, []):
                pn = (p.get("partner_name") or "").strip().lower()
                if pn:
                    c_legacy.add(pn)
            if c_legacy:
                score += len(legacy_partners & c_legacy) * 5

        if country and c.company_hq_country and country.lower() == c.company_hq_country.lower():
            score += 5

        if score > 0:
            scored.append((score, c))

    scored.sort(key=lambda x: -x[0])
    return [
        {
            "id": c.id,
            "company_name": c.company_name,
            "company_type": c.company_type,
            "industry_segment": c.industry_segment or c.supply_chain_segment,
            "company_hq_country": c.company_hq_country,
            "company_status": c.company_status,
            "similarity_score": round(score, 1),
        }
        for score, c in scored[:limit]
    ]


@router.get("/{company_id}/detail")
def company_detail(company_id: int, db: Session = Depends(get_db)):
    c = db.query(Company).filter(Company.id == company_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Company not found")

    data = _company_dict(c)

    # Facilities
    facilities = db.query(CompanyFacility).filter(
        CompanyFacility.company_id == company_id
    ).all()
    if not facilities:
        legacy_locs = _safe_json(c.company_locations, [])
        data["facilities"] = [{
            "id": None,
            "facility_name": loc.get("facility_name"),
            "address": loc.get("address"),
            "city": loc.get("city"),
            "state": loc.get("state"),
            "country": loc.get("country"),
            "zip_code": loc.get("zip"),
            "lat": loc.get("lat"),
            "lng": loc.get("lng"),
            "phone": loc.get("phone"),
            "facility_type": loc.get("product_type"),
            "product": loc.get("product"),
            "product_type": loc.get("product_type"),
            "chemistries": loc.get("chemistries"),
            "feedstock": loc.get("feedstock"),
            "capacity": loc.get("capacity"),
            "capacity_units": loc.get("capacity_units"),
            "status": loc.get("status"),
            "workforce": loc.get("workforce"),
            "segment": loc.get("segment"),
            "sources": loc.get("sources"),
            "qc": loc.get("qc"),
            "qc_date": loc.get("qc_date"),
            "source_name": c.data_source,
            "source_url": None,
            "date_added": c.last_updated,
        } for loc in legacy_locs]
    else:
        data["facilities"] = [_facility_dict(f) for f in facilities]

    # Partnerships — eager-load members so _partnership_dict_brief doesn't fire N+1.
    partnership_ids = [
        pid for (pid,) in db.query(PartnershipMember.partnership_id)
        .filter(PartnershipMember.company_id == company_id)
        .all()
    ]
    if partnership_ids:
        pships = (
            db.query(Partnership)
            .options(selectinload(Partnership.members))
            .filter(Partnership.id.in_(partnership_ids))
            .all()
        )
        data["partnerships"] = [_partnership_dict_brief(p) for p in pships]
    else:
        data["partnerships"] = []

    if not data["partnerships"] and c.announced_partners:
        data["partnerships_legacy"] = _safe_json(c.announced_partners, [])
    else:
        data["partnerships_legacy"] = []

    # News
    data["news"] = [
        {
            "id": n.id,
            "news_headline": n.news_headline,
            "category": n.category,
            "date_of_article": n.date_of_article,
            "news_source": n.news_source,
            "url": n.url,
            "summary": n.summary,
            "partners": _safe_json(n.partners, []),
            "topics": _safe_json(n.topics, []),
        }
        for n in db.query(NewsHeadline)
        .filter(NewsHeadline.company_id == company_id)
        .order_by(NewsHeadline.date_of_article.desc())
        .all()
    ]

    data["proceedings"] = []

    # Metrics
    data["metrics"] = [
        {
            "metric_name": m.metric_name,
            "metric_value": m.metric_value,
            "metric_unit": m.metric_unit,
            "date_recorded": m.date_recorded,
            "source_name": m.source_name,
            "source_url": m.source_url,
        }
        for m in db.query(CompanyMetric).filter(CompanyMetric.company_id == company_id).all()
    ]

    data["gwh_capacity"] = _safe_json(c.gwh_capacity, {})

    # Citations
    citations: list[dict] = []
    seen_sources: set[tuple] = set()

    def _add_citation(name, url):
        if not name:
            return
        key = (name, url or "")
        if key not in seen_sources:
            seen_sources.add(key)
            citations.append({"source_name": name, "source_url": url})

    source_urls = {
        "naatbatt_xlsx": "https://www.nrel.gov/transportation/battery-supply-chain-database.html",
        "bbd_xlsx": "https://www.voltafoundation.org/battery-database",
        "gigafactory_xlsx": "https://www.ultimamedia.com/gigafactory-database",
    }
    if c.data_source:
        _add_citation(c.data_source, source_urls.get(c.data_source))
    if c.sources:
        _add_citation(c.sources, None)
    if c.sources2:
        _add_citation(c.sources2, None)
    for f in data["facilities"]:
        _add_citation(f.get("source_name"), f.get("source_url"))
        if f.get("sources"):
            _add_citation(f["sources"], None)
    for m in data["metrics"]:
        _add_citation(m.get("source_name"), m.get("source_url"))
    for p in data["partnerships"]:
        _add_citation(p.get("source_name"), p.get("source_url"))

    data["citations"] = citations
    data["similar_companies"] = _find_similar(c, db)

    return data


@router.get("/{company_id}/facilities")
def list_facilities(company_id: int, db: Session = Depends(get_db)):
    facilities = db.query(CompanyFacility).filter(
        CompanyFacility.company_id == company_id
    ).all()
    if not facilities:
        c = db.query(Company).filter(Company.id == company_id).first()
        if not c:
            raise HTTPException(status_code=404, detail="Company not found")
        locs = _safe_json(c.company_locations, [])
        return [{"id": None, "company_id": company_id, **loc} for loc in locs]
    return [_facility_dict(f) for f in facilities]


@router.get("/{company_id}/metrics")
def list_metrics(company_id: int, db: Session = Depends(get_db)):
    metrics = db.query(CompanyMetric).filter(
        CompanyMetric.company_id == company_id
    ).all()
    return [
        {
            "id": m.id,
            "metric_name": m.metric_name,
            "metric_value": m.metric_value,
            "metric_unit": m.metric_unit,
            "date_recorded": m.date_recorded,
            "source_name": m.source_name,
            "source_url": m.source_url,
        }
        for m in metrics
    ]


_EDITABLE_FIELDS = {
    "company_website", "crunchbase_url", "linkedin_url", "pitchbook_url",
    "notes", "summary", "long_description", "contact_name", "contact_email",
    "contact_phone", "company_hq_city", "company_hq_state", "company_hq_country",
    "industry_segment", "company_type", "company_status", "chemistries",
    "founding_year", "number_of_employees", "hq_company", "hq_company_website",
    "feedstock", "description",
}


class CompanyUpdateRequest(BaseModel):
    updates: dict
    mark_as_manual: bool = True


@router.put("/{company_id}")
def update_company(company_id: int, req: CompanyUpdateRequest, db: Session = Depends(get_db)):
    c = db.query(Company).filter(Company.id == company_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Company not found")

    overrides = set(_safe_json(c.manual_overrides, []))
    for field, val in req.updates.items():
        if field not in _EDITABLE_FIELDS:
            continue
        setattr(c, field, val)
        if req.mark_as_manual:
            overrides.add(field)

    c.manual_overrides = json.dumps(sorted(overrides))
    c.last_updated = datetime.now(timezone.utc).isoformat()
    db.commit()
    db.refresh(c)
    return _company_dict(c)


@router.post("/enrich/sec-edgar")
def enrich_sec_edgar(db: Session = Depends(get_db)):
    """Trigger SEC EDGAR enrichment for all companies."""
    from backend.sec_edgar import run_enrichment
    result = run_enrichment(db)
    return result


@router.post("/prune-investors")
def prune_investor_rows(db: Session = Depends(get_db)):
    """Remove VC / investor / holdco rows that leaked in via PitchBook or
    NAATBATT/BBD uploads. Heuristic + cascade rules live in
    ``backend/prune_investors.py``."""
    from backend.prune_investors import prune_investors
    return prune_investors(db)


@router.post("/dedupe")
def dedupe_all_companies(db: Session = Depends(get_db)):
    """Scan the DB for duplicate companies (by normalized name), merge each
    group into its richest row, re-point news/partnerships/watchlist/etc.,
    then delete the losers. Runs automatically at the end of every upload;
    call this endpoint to sweep the database on demand."""
    from backend.dedupe import dedupe_companies
    return dedupe_companies(db)


@router.post("/prune-to-uploads")
def prune_companies_to_uploads(db: Session = Depends(get_db)):
    """Delete every company whose normalized name isn't in column A of an
    xlsx/csv currently sitting in ``UPLOAD_DIR``. Safe no-op if the upload
    folder is empty."""
    from backend.uploads_scan import prune_to_uploaded_names
    return prune_to_uploaded_names(db)


class ResearchRequest(BaseModel):
    company_name: str
    custom_queries: list[str] | None = None


class CustomSearchRequest(BaseModel):
    query: str


class DiscoverRequest(BaseModel):
    segment: str = ""
    count: int = 10
    custom_query: str = ""


class BulkResearchRequest(BaseModel):
    company_names: list[str]


class CompanyChatRequest(BaseModel):
    message: str


@router.post("/research")
async def research_company_endpoint(req: ResearchRequest, request: Request, db: Session = Depends(get_db)):
    check_rate_limit(request, max_calls=10, window_secs=60)
    now = datetime.now(timezone.utc).isoformat()
    job = ResearchJob(
        job_type="company_research",
        status="pending",
        target=req.company_name,
        created_at=now,
        updated_at=now,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    job_id = job.id

    async def _run():
        from backend.ai_research import research_company, search_company_news
        from backend.database import SessionLocal

        inner_db = SessionLocal()
        try:
            j = inner_db.query(ResearchJob).filter(ResearchJob.id == job_id).first()
            if j:
                j.status = "running"
                j.updated_at = datetime.now(timezone.utc).isoformat()
                inner_db.commit()

            result = await asyncio.get_event_loop().run_in_executor(
                None, research_company, req.company_name
            )
            news = await asyncio.get_event_loop().run_in_executor(
                None, search_company_news, req.company_name
            )

            # Upsert company
            existing = inner_db.query(Company).filter(
                Company.company_name.ilike(req.company_name)
            ).first()
            ts = datetime.now(timezone.utc).isoformat()
            if existing:
                overrides = set(_safe_json(existing.manual_overrides, []))
                for field, val in result.items():
                    if val is not None and field not in ("company_name", "error") and field not in overrides:
                        if isinstance(val, (list, dict)):
                            val = json.dumps(val)
                        setattr(existing, field, val)
                existing.last_updated = ts
                existing.data_source = "ai_research"
            else:
                company_data = {k: (json.dumps(v) if isinstance(v, (list, dict)) else v)
                                for k, v in result.items() if k != "error"}
                company_data["last_updated"] = ts
                existing = Company(**company_data)
                inner_db.add(existing)
            inner_db.commit()
            inner_db.refresh(existing)

            # Geocode if lat/lng missing but city is known
            if not existing.company_hq_lat and existing.company_hq_city:
                from backend.seed import _geocode_city
                lat, lng = _geocode_city(
                    existing.company_hq_city or "",
                    existing.company_hq_state or "",
                )
                if lat:
                    existing.company_hq_lat = lat
                    existing.company_hq_lng = lng
                    inner_db.commit()

            for article in news:
                article["company_id"] = existing.id
                article["created_at"] = ts
                if "partners" in article and isinstance(article["partners"], list):
                    article["partners"] = json.dumps(article["partners"])
                if "topics" in article and isinstance(article["topics"], list):
                    article["topics"] = json.dumps(article["topics"])
                inner_db.add(NewsHeadline(**{k: v for k, v in article.items()
                                            if k in NewsHeadline.__table__.columns.keys()}))
            inner_db.commit()

            # Create Partnership records from AI research
            partnerships_data = result.get("partnerships", [])
            for pdata in partnerships_data:
                try:
                    _create_ai_partnership(inner_db, existing, pdata, ts)
                except Exception as pe:
                    log.warning("Failed to create partnership: %s", pe)
            inner_db.commit()

            j = inner_db.query(ResearchJob).filter(ResearchJob.id == job_id).first()
            if j:
                j.status = "complete"
                j.result = json.dumps({"company": result, "news_count": len(news)})
                j.updated_at = datetime.now(timezone.utc).isoformat()
                inner_db.commit()

        except Exception as e:
            log.error("Research job %d failed: %s", job_id, e)
            j = inner_db.query(ResearchJob).filter(ResearchJob.id == job_id).first()
            if j:
                j.status = "failed"
                j.result = str(e)
                j.updated_at = datetime.now(timezone.utc).isoformat()
                inner_db.commit()
        finally:
            inner_db.close()

    asyncio.create_task(_run()).add_done_callback(_log_task_error)
    return {"job_id": job_id}


def _create_ai_partnership(db, company: Company, pdata: dict, ts: str):
    """Create a Partnership + PartnershipMember record from AI research data."""
    partner_name = (pdata.get("partner_name") or "").strip()
    if not partner_name:
        return

    # Look up or create partner company
    partner = db.query(Company).filter(Company.company_name.ilike(partner_name)).first()
    if not partner:
        partner = Company(company_name=partner_name, data_source="ai_research", last_updated=ts)
        db.add(partner)
        db.flush()

    ptype = pdata.get("partnership_type", "other")
    # Check for duplicates
    existing_members = db.query(PartnershipMember).filter(
        PartnershipMember.company_id == company.id
    ).all()
    for em in existing_members:
        p = db.query(Partnership).filter(Partnership.id == em.partnership_id).first()
        if p and p.partnership_type == ptype:
            sibling = db.query(PartnershipMember).filter(
                PartnershipMember.partnership_id == em.partnership_id,
                PartnershipMember.company_id == partner.id,
            ).first()
            if sibling:
                return  # Already exists

    p = Partnership(
        partnership_name=f"{company.company_name} - {partner_name}",
        partnership_type=ptype,
        stage=pdata.get("stage", "active"),
        direction=pdata.get("direction", "bidirectional"),
        date_announced=pdata.get("date_announced"),
        deal_value=pdata.get("deal_value_millions_usd"),
        scope=pdata.get("scope"),
        geography=pdata.get("geography"),
        industry_segment=pdata.get("industry_segment"),
        source_name="ai_research",
        date_sourced=ts,
        created_at=ts,
        updated_at=ts,
    )
    db.add(p)
    db.flush()

    company_role = pdata.get("company_role", "partner")
    partner_role = pdata.get("partner_role", "partner")
    db.add(PartnershipMember(partnership_id=p.id, company_id=company.id, role=company_role))
    db.add(PartnershipMember(partnership_id=p.id, company_id=partner.id, role=partner_role))


@router.post("/search/custom")
async def custom_search(req: CustomSearchRequest, request: Request, db: Session = Depends(get_db)):
    """Run a free-form Gemini search and return raw results + Claude summary."""
    check_rate_limit(request, max_calls=10, window_secs=60)
    now = datetime.now(timezone.utc).isoformat()
    job = ResearchJob(
        job_type="custom_search",
        status="pending",
        target=req.query,
        created_at=now,
        updated_at=now,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    job_id = job.id

    async def _run():
        from backend.ai_research import perplexity_search, _get_anthropic
        from backend.database import SessionLocal

        inner_db = SessionLocal()
        try:
            j = inner_db.query(ResearchJob).filter(ResearchJob.id == job_id).first()
            if j:
                j.status = "running"
                j.updated_at = datetime.now(timezone.utc).isoformat()
                inner_db.commit()

            raw = await asyncio.get_event_loop().run_in_executor(
                None, perplexity_search, req.query
            )

            from backend.config import CLAUDE_MODEL
            client = _get_anthropic()
            msg = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=2048,
                system=(
                    "You are a battery industry analyst for BMW. "
                    "Given raw web search results, write a concise structured intelligence summary "
                    "in markdown. Include: key findings, companies mentioned, technologies, "
                    "and actionable insights for BMW's battery team."
                ),
                messages=[{"role": "user", "content": f"Query: {req.query}\n\nSearch results:\n{raw}"}],
            )
            from backend.ai_research import _strip_emojis
            summary = _strip_emojis(msg.content[0].text)

            j = inner_db.query(ResearchJob).filter(ResearchJob.id == job_id).first()
            if j:
                j.status = "complete"
                j.result = json.dumps({"raw": raw, "summary": summary, "query": req.query})
                j.updated_at = datetime.now(timezone.utc).isoformat()
                inner_db.commit()

        except Exception as e:
            log.error("Custom search job %d failed: %s", job_id, e)
            j = inner_db.query(ResearchJob).filter(ResearchJob.id == job_id).first()
            if j:
                j.status = "failed"
                j.result = str(e)
                j.updated_at = datetime.now(timezone.utc).isoformat()
                inner_db.commit()
        finally:
            inner_db.close()

    asyncio.create_task(_run()).add_done_callback(_log_task_error)
    return {"job_id": job_id}


@router.post("/discover")
async def discover_companies_endpoint(req: DiscoverRequest, request: Request, db: Session = Depends(get_db)):
    check_rate_limit(request, max_calls=5, window_secs=60)
    now = datetime.now(timezone.utc).isoformat()
    job = ResearchJob(
        job_type="discover_companies",
        status="pending",
        target=req.segment,
        created_at=now,
        updated_at=now,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    job_id = job.id

    existing_names = [c.company_name for c in db.query(Company.company_name).all()]

    async def _run():
        from backend.ai_research import discover_companies
        from backend.database import SessionLocal

        inner_db = SessionLocal()
        try:
            j = inner_db.query(ResearchJob).filter(ResearchJob.id == job_id).first()
            if j:
                j.status = "running"
                j.updated_at = datetime.now(timezone.utc).isoformat()
                inner_db.commit()

            names = await asyncio.get_event_loop().run_in_executor(
                None, discover_companies, req.segment, existing_names, req.custom_query
            )
            names = names[: req.count]

            j = inner_db.query(ResearchJob).filter(ResearchJob.id == job_id).first()
            if j:
                j.status = "complete"
                j.result = json.dumps({"new_companies": names})
                j.updated_at = datetime.now(timezone.utc).isoformat()
                inner_db.commit()
        except Exception as e:
            j = inner_db.query(ResearchJob).filter(ResearchJob.id == job_id).first()
            if j:
                j.status = "failed"
                j.result = str(e)
                j.updated_at = datetime.now(timezone.utc).isoformat()
                inner_db.commit()
        finally:
            inner_db.close()

    asyncio.create_task(_run()).add_done_callback(_log_task_error)
    return {"job_id": job_id}


@router.post("/{company_id}/chat")
async def chat_with_company(company_id: int, req: CompanyChatRequest, request: Request, db: Session = Depends(get_db)):
    """Answer a specific question about a company using its stored data + live web search."""
    check_rate_limit(request, max_calls=20, window_secs=60)
    c = db.query(Company).filter(Company.id == company_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Company not found")

    from backend.ai_research import perplexity_search, _get_anthropic
    from backend.config import CLAUDE_MODEL

    company_context = f"""Company: {c.company_name}
Type: {c.company_type or 'N/A'} | Status: {c.company_status or 'N/A'}
HQ: {', '.join(filter(None, [c.company_hq_city, c.company_hq_state, c.company_hq_country]))}
Segment: {c.supply_chain_segment or 'N/A'}
Employees: {c.number_of_employees or 'N/A'}
Keywords: {', '.join(_safe_json(c.keywords, []))}
Summary: {c.summary or 'N/A'}
Partners: {', '.join(p.get('partner_name','') for p in _safe_json(c.announced_partners, []))}"""

    search_query = f"{c.company_name} battery {req.message}"
    try:
        web_results = await asyncio.get_event_loop().run_in_executor(
            None, perplexity_search, search_query
        )
    except Exception:
        web_results = ""

    client = _get_anthropic()
    msg = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        system=(
            "You are a battery industry analyst assistant for BMW. "
            "You have access to stored company data and fresh web search results. "
            "Answer the user's question concisely and accurately. "
            "If the web results contain relevant information, incorporate it. "
            "Use markdown for structure when helpful."
        ),
        messages=[{
            "role": "user",
            "content": (
                f"Stored company data:\n{company_context}\n\n"
                f"Fresh web search results for '{search_query}':\n{web_results}\n\n"
                f"User question: {req.message}"
            ),
        }],
    )
    return {"response": msg.content[0].text}


@router.post("/bulk-research")
async def bulk_research(req: BulkResearchRequest, request: Request, db: Session = Depends(get_db)):
    """Add stubs for unknown companies then queue a research job for each."""
    check_rate_limit(request, max_calls=3, window_secs=60)
    now = datetime.now(timezone.utc).isoformat()
    names = req.company_names[:10]

    # Load existing names once, add missing stubs in a single commit
    existing_names = {
        c.company_name.lower()
        for c in db.query(Company.company_name).all()
    }
    for name in names:
        if name.lower() not in existing_names:
            db.add(Company(company_name=name, data_source="ai_research", last_updated=now))
    db.flush()

    # Create all jobs in a single commit
    jobs = []
    for name in names:
        job = ResearchJob(
            job_type="company_research", status="pending",
            target=name, created_at=now, updated_at=now,
        )
        db.add(job)
        jobs.append(job)
    db.commit()
    for job in jobs:
        db.refresh(job)
    job_ids = [job.id for job in jobs]

    for job in jobs:
        async def _run(company_name=job.target, job_id=job.id):
            from backend.ai_research import research_company, search_company_news
            from backend.database import SessionLocal

            inner_db = SessionLocal()
            try:
                j = inner_db.query(ResearchJob).filter(ResearchJob.id == job_id).first()
                if j:
                    j.status = "running"
                    j.updated_at = datetime.now(timezone.utc).isoformat()
                    inner_db.commit()

                result = await asyncio.get_event_loop().run_in_executor(None, research_company, company_name)
                news = await asyncio.get_event_loop().run_in_executor(None, search_company_news, company_name)
                ts = datetime.now(timezone.utc).isoformat()

                company = inner_db.query(Company).filter(Company.company_name.ilike(company_name)).first()
                if company:
                    overrides = set(_safe_json(company.manual_overrides, []))
                    for field, val in result.items():
                        if val is not None and field not in ("company_name", "error") and field not in overrides:
                            setattr(company, field, json.dumps(val) if isinstance(val, (list, dict)) else val)
                    company.last_updated = ts
                    company.data_source = "ai_research"
                    inner_db.commit()

                    # Geocode if lat/lng missing but city is known
                    if not company.company_hq_lat and company.company_hq_city:
                        from backend.seed import _geocode_city
                        lat, lng = _geocode_city(
                            company.company_hq_city or "",
                            company.company_hq_state or "",
                        )
                        if lat:
                            company.company_hq_lat = lat
                            company.company_hq_lng = lng
                            inner_db.commit()

                    for article in news:
                        article["company_id"] = company.id
                        article["created_at"] = ts
                        for lf in ("partners", "topics"):
                            if isinstance(article.get(lf), list):
                                article[lf] = json.dumps(article[lf])
                        inner_db.add(NewsHeadline(**{k: v for k, v in article.items()
                                                    if k in NewsHeadline.__table__.columns.keys()}))
                    inner_db.commit()

                    # Create Partnership records
                    for pdata in result.get("partnerships", []):
                        try:
                            _create_ai_partnership(inner_db, company, pdata, ts)
                        except Exception as pe:
                            log.warning("Failed to create partnership: %s", pe)
                    inner_db.commit()

                j = inner_db.query(ResearchJob).filter(ResearchJob.id == job_id).first()
                if j:
                    j.status = "complete"
                    j.result = json.dumps({"company": company_name, "news_count": len(news)})
                    j.updated_at = datetime.now(timezone.utc).isoformat()
                    inner_db.commit()
            except Exception as e:
                log.error("Bulk research %d failed: %s", job_id, e)
                j = inner_db.query(ResearchJob).filter(ResearchJob.id == job_id).first()
                if j:
                    j.status = "failed"
                    j.result = str(e)
                    j.updated_at = datetime.now(timezone.utc).isoformat()
                    inner_db.commit()
            finally:
                inner_db.close()

        asyncio.create_task(_run()).add_done_callback(_log_task_error)

    return {"job_ids": job_ids, "queued": len(job_ids)}
