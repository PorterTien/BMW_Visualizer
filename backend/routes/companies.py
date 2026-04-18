from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import cast, case, func
from sqlalchemy.dialects.postgresql import JSON as PGJSON
from sqlalchemy.orm import Session, load_only

from backend.database import get_db
from backend.models import Company, NewsHeadline, Partnership, PartnershipMember, ResearchJob

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/companies", tags=["companies"])


def _company_dict(c: Company) -> dict:
    return {
        "id": c.id,
        "company_name": c.company_name,
        "company_hq_city": c.company_hq_city,
        "company_hq_state": c.company_hq_state,
        "company_hq_country": c.company_hq_country,
        "company_hq_lat": c.company_hq_lat,
        "company_hq_lng": c.company_hq_lng,
        "company_locations": json.loads(c.company_locations or "[]"),
        "company_type": c.company_type,
        "company_status": c.company_status,
        "company_focus": json.loads(c.company_focus or "[]"),
        "supply_chain_segment": c.supply_chain_segment,
        "keywords": json.loads(c.keywords or "[]"),
        "announced_partners": json.loads(c.announced_partners or "[]"),
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
        "battery_chemistry_flags": json.loads(c.battery_chemistry_flags or "{}"),
        "supply_chain_flags": json.loads(c.supply_chain_flags or "{}"),
        "gwh_capacity": json.loads(c.gwh_capacity or "{}"),
        "plant_start_date": c.plant_start_date,
        "last_updated": c.last_updated,
        "data_source": c.data_source,
        "manual_overrides": json.loads(c.manual_overrides or "[]"),
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
        "company_focus": json.loads(c.company_focus or "[]"),
        "supply_chain_segment": c.supply_chain_segment,
        "keywords": json.loads(c.keywords or "[]"),
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
        "gwh_capacity": json.loads(c.gwh_capacity or "{}"),
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
    db: Session = Depends(get_db),
):
    pc = _announced_partners_count_expr(db)
    q = (
        db.query(Company, pc.label("partner_count"))
        .options(load_only(*_COMPANY_LIST_LOAD_ONLY))
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
    rows = q.order_by(Company.company_name).all()
    return [_company_dict_list(c, int(pn or 0)) for c, pn in rows]


@router.get("/map")
def companies_map(db: Session = Depends(get_db)):
    companies = (
        db.query(Company)
        .options(load_only(*_COMPANY_MAP_LOAD_ONLY))
        .all()
    )
    results = []
    for c in companies:
        locations = json.loads(c.company_locations or "[]")
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
    companies = (
        db.query(Company)
        .options(load_only(*_COMPANY_NETWORK_LOAD_ONLY))
        .all()
    )
    nodes = []
    links = []
    company_index: dict[str, int] = {}  # name_lower -> node id
    virtual_id = -1
    seen_links: set[tuple] = set()

    for c in companies:
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
        company_index[c.company_name.lower()] = c.id

    # Build links; create virtual nodes for external partners not in DB
    for c in companies:
        partners = json.loads(c.announced_partners or "[]")
        for p in partners:
            partner_name = (p.get("partner_name") or "").strip()
            if not partner_name:
                continue
            pid = company_index.get(partner_name.lower())
            if pid is None:
                # Create a virtual node for this external partner
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
                company_index[partner_name.lower()] = pid

            link_key = (min(c.id, pid), max(c.id, pid), p.get("type_of_partnership", "Other"))
            if link_key not in seen_links:
                seen_links.add(link_key)
                links.append({
                    "source": c.id,
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

    overrides = set(json.loads(c.manual_overrides or "[]"))
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
async def research_company_endpoint(req: ResearchRequest, db: Session = Depends(get_db)):
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
                overrides = set(json.loads(existing.manual_overrides or "[]"))
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

    asyncio.create_task(_run())
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
async def custom_search(req: CustomSearchRequest, db: Session = Depends(get_db)):
    """Run a free-form Gemini search and return raw results + Claude summary."""
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

    asyncio.create_task(_run())
    return {"job_id": job_id}


@router.post("/discover")
async def discover_companies_endpoint(req: DiscoverRequest, db: Session = Depends(get_db)):
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

    asyncio.create_task(_run())
    return {"job_id": job_id}


@router.post("/{company_id}/chat")
async def chat_with_company(company_id: int, req: CompanyChatRequest, db: Session = Depends(get_db)):
    """Answer a specific question about a company using its stored data + live web search."""
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
Keywords: {', '.join(json.loads(c.keywords or '[]'))}
Summary: {c.summary or 'N/A'}
Partners: {', '.join(p.get('partner_name','') for p in json.loads(c.announced_partners or '[]'))}"""

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
async def bulk_research(req: BulkResearchRequest, db: Session = Depends(get_db)):
    """Add stubs for unknown companies then queue a research job for each."""
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
                    overrides = set(json.loads(company.manual_overrides or "[]"))
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

        asyncio.create_task(_run())

    return {"job_ids": job_ids, "queued": len(job_ids)}
