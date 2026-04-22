"""Partnership routes — CRUD, graph data, import helpers."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db, SessionLocal
from backend.models import (
    Company,
    CompanyFacility,
    CompanyMetric,
    Partnership,
    PartnershipMember,
    NewsHeadline,
    ResearchJob,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["partnerships"])


# ── Pydantic schemas ─────────────────────��──────────────────────────────────

class PartnershipMemberIn(BaseModel):
    company_id: int
    role: str = "partner"


class PartnershipCreate(BaseModel):
    partnership_name: str | None = None
    partnership_type: str = "other"
    stage: str = "announced"
    direction: str = "bidirectional"
    date_announced: str | None = None
    date_effective: str | None = None
    date_expiration: str | None = None
    deal_value: float | None = None
    deal_currency: str = "USD"
    scope: str | None = None
    geography: str | None = None
    industry_segment: str | None = None
    source_name: str | None = None
    source_url: str | None = None
    members: list[PartnershipMemberIn] = []


# ── Helpers ────────────────────────────────────────────────────��────────────

def _partnership_dict(p: Partnership, db: Session) -> dict:
    members = []
    for m in p.members:
        company = db.query(Company).filter(Company.id == m.company_id).first()
        members.append({
            "company_id": m.company_id,
            "company_name": company.company_name if company else "Unknown",
            "role": m.role,
        })
    return {
        "id": p.id,
        "partnership_name": p.partnership_name,
        "partnership_type": p.partnership_type,
        "stage": p.stage,
        "direction": p.direction,
        "date_announced": p.date_announced,
        "date_effective": p.date_effective,
        "date_expiration": p.date_expiration,
        "deal_value": p.deal_value,
        "deal_currency": p.deal_currency,
        "scope": p.scope,
        "geography": p.geography,
        "industry_segment": p.industry_segment,
        "source_name": p.source_name,
        "source_url": p.source_url,
        "date_sourced": p.date_sourced,
        "members": members,
    }


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


# ── Partnership CRUD ────────────────────────────────────────────────────────

@router.get("/partnerships")
def list_partnerships(
    partnership_type: str | None = None,
    stage: str | None = None,
    industry_segment: str | None = None,
    company_id: int | None = None,
    geography: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    db: Session = Depends(get_db),
):
    q = db.query(Partnership)
    if partnership_type:
        q = q.filter(Partnership.partnership_type == partnership_type)
    if stage:
        q = q.filter(Partnership.stage == stage)
    if industry_segment:
        q = q.filter(Partnership.industry_segment == industry_segment)
    if geography:
        q = q.filter(Partnership.geography.ilike(f"%{geography}%"))
    if date_from:
        q = q.filter(Partnership.date_announced >= date_from)
    if date_to:
        q = q.filter(Partnership.date_announced <= date_to)
    if company_id:
        q = q.join(PartnershipMember).filter(PartnershipMember.company_id == company_id)
    partnerships = q.order_by(Partnership.date_announced.desc()).all()
    return [_partnership_dict(p, db) for p in partnerships]


# NOTE: /graph must be defined BEFORE /{partnership_id} to avoid "graph" being matched as an ID
@router.get("/partnerships/graph")
def partnership_graph(db: Session = Depends(get_db)):
    """Return nodes + links for the enhanced bubble graph."""
    return _build_partnership_graph(db)


@router.post("/partnerships/enrich")
async def enrich_network(db: Session = Depends(get_db)):
    """Background job: AI-classify all unclassified company types and partnership types."""
    ts = datetime.now(timezone.utc).isoformat()
    job = ResearchJob(job_type="network_enrich", status="pending", target="network", created_at=ts, updated_at=ts)
    db.add(job)
    db.commit()
    db.refresh(job)
    job_id = job.id
    asyncio.create_task(_enrich_network_bg(job_id, ts))
    return {"job_id": job_id}


async def _enrich_network_bg(job_id: int, ts: str):
    """Classify untyped companies and unclassified partnerships."""
    from backend.ai_research import classify_companies_batch, classify_partnerships_batch

    BATCH = 20
    db = SessionLocal()
    try:
        job = db.query(ResearchJob).filter(ResearchJob.id == job_id).first()
        if job:
            job.status = "running"; job.updated_at = datetime.now(timezone.utc).isoformat(); db.commit()

        # ── 1. Classify companies missing company_type ──────────────────
        untyped = (
            db.query(Company)
            .filter((Company.company_type == None) | (Company.company_type == ''))  # noqa: E711
            .filter(Company.company_name != 'Independent Investors')
            .all()
        )
        companies_classified = 0
        for i in range(0, len(untyped), BATCH):
            batch = untyped[i:i + BATCH]
            info = [{'name': c.company_name,
                     'description': (c.summary or c.long_description or c.description or '')[:300],
                     'industry': c.notes or ''} for c in batch]
            try:
                results = await asyncio.get_event_loop().run_in_executor(None, classify_companies_batch, info)
                for c in batch:
                    ct = results.get(c.company_name)
                    if ct:
                        c.company_type = ct
                        companies_classified += 1
                db.commit()
            except Exception as e:
                log.error("Company classify batch %d failed: %s", i, e)

        # ── 2. Classify partnerships with null or 'other' type ──────────
        untyped_ps = (
            db.query(Partnership)
            .filter((Partnership.partnership_type == None) | (Partnership.partnership_type == 'other'))  # noqa: E711
            .all()
        )
        partnerships_classified = 0
        for i in range(0, len(untyped_ps), BATCH):
            batch = untyped_ps[i:i + BATCH]
            # Build context from member company names
            info = []
            for p in batch:
                names = [m.company.company_name for m in p.members if m.company] if p.members else []
                if len(names) < 2:
                    continue
                info.append({'id': p.id, 'company_a': names[0], 'company_b': names[1],
                             'scope': p.scope or ''})
            if not info:
                continue
            try:
                results = await asyncio.get_event_loop().run_in_executor(None, classify_partnerships_batch, info)
                for p in batch:
                    r = results.get(str(p.id))
                    if r:
                        new_type = r.get('type')
                        new_dir = r.get('direction')
                        if new_type and new_type != 'other':
                            p.partnership_type = new_type
                            partnerships_classified += 1
                        if new_dir:
                            p.direction = new_dir
                db.commit()
            except Exception as e:
                log.error("Partnership classify batch %d failed: %s", i, e)

        result = {'companies_classified': companies_classified, 'partnerships_classified': partnerships_classified,
                  'companies_total': len(untyped), 'partnerships_total': len(untyped_ps)}
        job = db.query(ResearchJob).filter(ResearchJob.id == job_id).first()
        if job:
            job.status = "complete"; job.result = json.dumps(result)
            job.updated_at = datetime.now(timezone.utc).isoformat(); db.commit()
        log.info("Network enrich job %d complete: %s", job_id, result)

    except Exception as e:
        log.error("Network enrich job %d failed: %s", job_id, e)
        job = db.query(ResearchJob).filter(ResearchJob.id == job_id).first()
        if job:
            job.status = "failed"; job.result = str(e)
            job.updated_at = datetime.now(timezone.utc).isoformat(); db.commit()
    finally:
        db.close()


@router.get("/partnerships/{partnership_id}")
def get_partnership(partnership_id: int, db: Session = Depends(get_db)):
    p = db.query(Partnership).filter(Partnership.id == partnership_id).first()
    if not p:
        raise HTTPException(404, "Partnership not found")
    return _partnership_dict(p, db)


@router.post("/partnerships")
def create_partnership(data: PartnershipCreate, db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc).isoformat()
    p = Partnership(
        partnership_name=data.partnership_name,
        partnership_type=data.partnership_type,
        stage=data.stage,
        direction=data.direction,
        date_announced=data.date_announced,
        date_effective=data.date_effective,
        date_expiration=data.date_expiration,
        deal_value=data.deal_value,
        deal_currency=data.deal_currency,
        scope=data.scope,
        geography=data.geography,
        industry_segment=data.industry_segment,
        source_name=data.source_name,
        source_url=data.source_url,
        date_sourced=now,
        created_at=now,
        updated_at=now,
    )
    db.add(p)
    db.flush()
    for m in data.members:
        db.add(PartnershipMember(
            partnership_id=p.id,
            company_id=m.company_id,
            role=m.role,
        ))
    db.commit()
    db.refresh(p)
    return _partnership_dict(p, db)


# ── Enhanced network graph data ─────────────────────────────────────────────

PARTNERSHIP_TYPE_DIRECTIONS = {
    "supply_agreement": "supplier_to_buyer",
    "equity_stake": "investor_to_investee",
    "licensing": "bidirectional",
    "jv": "bidirectional",
    "r_and_d_collab": "bidirectional",
    "government_grant": "bidirectional",
    "other": "bidirectional",
}


def _build_partnership_graph(db: Session) -> dict:
    """Return nodes + links for the enhanced bubble graph, using both
    the new partnerships table AND legacy announced_partners JSON."""

    companies = db.query(Company).all()
    partnerships = db.query(Partnership).all()

    # Build company lookup
    company_map: dict[int, Company] = {c.id: c for c in companies}
    company_name_map: dict[str, int] = {c.company_name.lower(): c.id for c in companies}

    # Gather all metrics for percentile estimation
    metrics_by_company: dict[int, dict] = {}
    for c in companies:
        metrics_by_company[c.id] = {
            "market_cap_usd": c.market_cap_usd,
            "revenue_usd": c.revenue_usd,
            "employee_count": c.number_of_employees,
            "total_funding_usd": c.total_funding_usd,
            "manufacturing_capacity_gwh": _parse_max_gwh(c.gwh_capacity),
        }

    # Also pull from company_metrics table
    all_metrics = db.query(CompanyMetric).all()
    for m in all_metrics:
        if m.company_id in metrics_by_company:
            metrics_by_company[m.company_id][m.metric_name] = m.metric_value

    # Compute percentiles for approximation
    metric_ranks = _compute_percentiles(metrics_by_company)

    # Build nodes
    nodes = []
    for c in companies:
        m = metrics_by_company.get(c.id, {})
        nodes.append({
            "id": c.id,
            "name": c.company_name,
            "type": c.company_type,
            "industry_segment": c.industry_segment or c.supply_chain_segment,
            "market_cap_usd": m.get("market_cap_usd"),
            "revenue_usd": m.get("revenue_usd"),
            "employee_count": m.get("employee_count"),
            "total_funding_usd": m.get("total_funding_usd"),
            "manufacturing_capacity_gwh": m.get("manufacturing_capacity_gwh"),
            "patent_count": m.get("patent_count"),
            "funding_raised": m.get("funding_raised"),
            "production_volume": m.get("production_volume"),
            "partnership_investment_total": m.get("partnership_investment_total"),
            "percentile": metric_ranks.get(c.id, 50),
            "in_db": True,
        })

    # Build links from partnerships table
    links = []
    seen_links: set[tuple] = set()
    for p in partnerships:
        member_ids = [(m.company_id, m.role) for m in p.members]
        if len(member_ids) < 2:
            continue
        for i, (cid1, role1) in enumerate(member_ids):
            for cid2, role2 in member_ids[i + 1:]:
                direction = p.direction or PARTNERSHIP_TYPE_DIRECTIONS.get(p.partnership_type, "bidirectional")
                # Determine source/target based on roles
                source_id, target_id = cid1, cid2
                if direction == "supplier_to_buyer":
                    if role1 == "buyer":
                        source_id, target_id = cid2, cid1
                elif direction == "investor_to_investee":
                    if role1 == "investee":
                        source_id, target_id = cid2, cid1

                link_key = (min(source_id, target_id), max(source_id, target_id), p.partnership_type)
                if link_key not in seen_links:
                    seen_links.add(link_key)
                    links.append({
                        "partnership_id": p.id,
                        "source": source_id,
                        "target": target_id,
                        "type": p.partnership_type,
                        "direction": direction,
                        "stage": p.stage,
                        "deal_value": p.deal_value,
                        "date": p.date_announced,
                        "scope": p.scope,
                    })

    # Also include legacy announced_partners links
    virtual_id = -1
    virtual_nodes: dict[str, int] = {}
    for c in companies:
        partners = json.loads(c.announced_partners or "[]")
        for p in partners:
            partner_name = (p.get("partner_name") or "").strip()
            if not partner_name:
                continue
            pid = company_name_map.get(partner_name.lower())
            if pid is None:
                if partner_name.lower() in virtual_nodes:
                    pid = virtual_nodes[partner_name.lower()]
                else:
                    pid = virtual_id
                    virtual_id -= 1
                    virtual_nodes[partner_name.lower()] = pid
                    nodes.append({
                        "id": pid,
                        "name": partner_name,
                        "type": "other",
                        "industry_segment": None,
                        "market_cap_usd": None,
                        "revenue_usd": None,
                        "employee_count": None,
                        "total_funding_usd": None,
                        "manufacturing_capacity_gwh": None,
                        "patent_count": None,
                        "funding_raised": None,
                        "production_volume": None,
                        "partnership_investment_total": None,
                        "percentile": 10,
                        "in_db": False,
                    })

            ptype = _map_legacy_type(p.get("type_of_partnership", "Other"))
            link_key = (min(c.id, pid), max(c.id, pid), ptype)
            if link_key not in seen_links:
                seen_links.add(link_key)
                links.append({
                    "partnership_id": None,
                    "source": c.id,
                    "target": pid,
                    "type": ptype,
                    "direction": "bidirectional",
                    "stage": "active",
                    "deal_value": None,
                    "date": p.get("date"),
                    "scope": p.get("scale"),
                })

    # Filter to only connected nodes
    connected_ids = set()
    for link in links:
        connected_ids.add(link["source"])
        connected_ids.add(link["target"])
    nodes = [n for n in nodes if n["id"] in connected_ids]

    return {"nodes": nodes, "links": links}


def _map_legacy_type(legacy: str) -> str:
    mapping = {
        "Joint Venture": "jv",
        "Investment": "equity_stake",
        "MOU": "r_and_d_collab",
        "Off-take": "supply_agreement",
        "Supply Agreement": "supply_agreement",
        "Other": "other",
    }
    return mapping.get(legacy, "other")


def _parse_max_gwh(gwh_json: str | None) -> float | None:
    if not gwh_json:
        return None
    try:
        data = json.loads(gwh_json)
        vals = [float(v) for v in data.values() if v]
        return max(vals) if vals else None
    except Exception:
        return None


def _compute_percentiles(metrics_by_company: dict[int, dict]) -> dict[int, float]:
    """Compute a composite percentile for each company based on available metrics."""
    metric_keys = ["market_cap_usd", "revenue_usd", "employee_count",
                   "total_funding_usd", "manufacturing_capacity_gwh"]

    # For each metric, rank companies that have it
    per_metric_rank: dict[str, dict[int, float]] = {}
    for mk in metric_keys:
        vals = [(cid, m.get(mk)) for cid, m in metrics_by_company.items() if m.get(mk)]
        if not vals:
            continue
        vals.sort(key=lambda x: x[1])
        n = len(vals)
        per_metric_rank[mk] = {cid: (i / n) * 100 for i, (cid, _) in enumerate(vals)}

    # Composite: weighted average of available percentiles
    weights = {
        "market_cap_usd": 1.0,
        "revenue_usd": 1.0,
        "employee_count": 0.7,
        "total_funding_usd": 0.8,
        "manufacturing_capacity_gwh": 0.9,
    }
    result: dict[int, float] = {}
    for cid in metrics_by_company:
        total_w = 0
        total_v = 0
        for mk in metric_keys:
            ranks = per_metric_rank.get(mk, {})
            if cid in ranks:
                w = weights.get(mk, 1.0)
                total_w += w
                total_v += ranks[cid] * w
        result[cid] = (total_v / total_w) if total_w > 0 else 20  # default low for no-data companies
    return result


# ── Company detail (full page) ──────────────────────────────────────────────

@router.get("/companies/{company_id}/detail")
def company_detail(company_id: int, db: Session = Depends(get_db)):
    """Full company detail page data: overview, facilities, partnerships,
    news, proceedings, metrics, sources/citations, similar companies."""

    c = db.query(Company).filter(Company.id == company_id).first()
    if not c:
        raise HTTPException(404, "Company not found")

    # Base company data
    from backend.routes.companies import _company_dict
    data = _company_dict(c)

    # Facilities
    facilities = db.query(CompanyFacility).filter(
        CompanyFacility.company_id == company_id
    ).all()

    # Fall back to legacy company_locations if no facility records exist
    if not facilities:
        legacy_locs = json.loads(c.company_locations or "[]")
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

    # Partnerships — from new table
    member_rows = db.query(PartnershipMember).filter(
        PartnershipMember.company_id == company_id
    ).all()
    partnership_ids = [m.partnership_id for m in member_rows]
    if partnership_ids:
        pships = db.query(Partnership).filter(Partnership.id.in_(partnership_ids)).all()
        data["partnerships"] = [_partnership_dict(p, db) for p in pships]
    else:
        data["partnerships"] = []

    # Legacy announced_partners (if no new-table partnerships yet)
    if not data["partnerships"] and c.announced_partners:
        legacy = json.loads(c.announced_partners or "[]")
        data["partnerships_legacy"] = legacy
    else:
        data["partnerships_legacy"] = []

    # All news
    data["news"] = [
        {
            "id": n.id,
            "news_headline": n.news_headline,
            "category": n.category,
            "date_of_article": n.date_of_article,
            "news_source": n.news_source,
            "url": n.url,
            "summary": n.summary,
            "partners": json.loads(n.partners or "[]"),
            "topics": json.loads(n.topics or "[]"),
        }
        for n in db.query(NewsHeadline)
        .filter(NewsHeadline.company_id == company_id)
        .order_by(NewsHeadline.date_of_article.desc())
        .all()
    ]

    data["proceedings"] = []

    # Metrics
    metrics = db.query(CompanyMetric).filter(
        CompanyMetric.company_id == company_id
    ).all()
    data["metrics"] = [
        {
            "metric_name": m.metric_name,
            "metric_value": m.metric_value,
            "metric_unit": m.metric_unit,
            "date_recorded": m.date_recorded,
            "source_name": m.source_name,
            "source_url": m.source_url,
        }
        for m in metrics
    ]

    # GWh capacity (already on company)
    data["gwh_capacity"] = json.loads(c.gwh_capacity or "{}")

    # Citations — aggregate all sources
    citations = []
    seen_sources = set()

    def _add_citation(name, url):
        if not name:
            return
        key = (name, url or "")
        if key not in seen_sources:
            seen_sources.add(key)
            citations.append({"source_name": name, "source_url": url})

    # From data_source
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
    for f in data.get("facilities", []):
        _add_citation(f.get("source_name"), f.get("source_url"))
        if f.get("sources"):
            _add_citation(f["sources"], None)
    for m in data.get("metrics", []):
        _add_citation(m.get("source_name"), m.get("source_url"))
    for p in data.get("partnerships", []):
        _add_citation(p.get("source_name"), p.get("source_url"))

    data["citations"] = citations

    # Similar companies
    data["similar_companies"] = _find_similar(c, db)

    return data


def _find_similar(company: Company, db: Session, limit: int = 8) -> list[dict]:
    """Find similar companies by industry segment + size, then shared partners + geography."""
    candidates = db.query(Company).filter(Company.id != company.id).all()
    if not candidates:
        return []

    seg = company.industry_segment or company.supply_chain_segment or company.company_type
    country = company.company_hq_country

    # Gather this company's partner IDs
    my_partner_ids = set()
    members = db.query(PartnershipMember).filter(
        PartnershipMember.company_id == company.id
    ).all()
    for m in members:
        siblings = db.query(PartnershipMember).filter(
            PartnershipMember.partnership_id == m.partnership_id,
            PartnershipMember.company_id != company.id,
        ).all()
        for s in siblings:
            my_partner_ids.add(s.company_id)

    # Also gather from legacy
    legacy_partners = set()
    for p in json.loads(company.announced_partners or "[]"):
        pn = (p.get("partner_name") or "").strip().lower()
        if pn:
            legacy_partners.add(pn)

    scored = []
    for c in candidates:
        score = 0.0
        c_seg = c.industry_segment or c.supply_chain_segment or c.company_type

        # Industry segment match (highest weight)
        if seg and c_seg and seg.lower() == c_seg.lower():
            score += 40

        # Same company_type
        if company.company_type and c.company_type == company.company_type:
            score += 20

        # Size similarity (compare available metrics)
        score += _size_similarity(company, c) * 20

        # Shared partners
        c_partner_ids = set()
        c_members = db.query(PartnershipMember).filter(
            PartnershipMember.company_id == c.id
        ).all()
        for m in c_members:
            c_partner_ids.add(m.partnership_id)
        shared = len(my_partner_ids & c_partner_ids) if my_partner_ids else 0
        # Also check legacy
        c_legacy = set()
        for p in json.loads(c.announced_partners or "[]"):
            pn = (p.get("partner_name") or "").strip().lower()
            if pn:
                c_legacy.add(pn)
        shared_legacy = len(legacy_partners & c_legacy)
        score += (shared + shared_legacy) * 5

        # Geography
        if country and c.company_hq_country and country.lower() == c.company_hq_country.lower():
            score += 5

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
        if score > 0
    ]


def _size_similarity(a: Company, b: Company) -> float:
    """Return 0-1 similarity based on comparable metrics."""
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


# ── Facilities endpoint ─────────────────────────────────────────────────────

@router.get("/companies/{company_id}/facilities")
def list_facilities(company_id: int, db: Session = Depends(get_db)):
    facilities = db.query(CompanyFacility).filter(
        CompanyFacility.company_id == company_id
    ).all()
    if not facilities:
        # Fall back to legacy
        c = db.query(Company).filter(Company.id == company_id).first()
        if not c:
            raise HTTPException(404, "Company not found")
        locs = json.loads(c.company_locations or "[]")
        return [{"id": None, "company_id": company_id, **loc} for loc in locs]
    return [_facility_dict(f) for f in facilities]


# ── Metrics endpoint ────────────────────────────────────────────────────────

@router.get("/companies/{company_id}/metrics")
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
