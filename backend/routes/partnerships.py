"""Partnership routes — CRUD, graph data, import helpers."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, load_only, selectinload

from backend.database import get_db, SessionLocal
from backend.rate_limit import check_rate_limit
from backend.models import (
    Company,
    CompanyMetric,
    Partnership,
    PartnershipMember,
    ResearchJob,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["partnerships"])


def _log_task_error(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception():
        log.error("Background task %s raised: %s", task.get_name(), task.exception())


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

def _partnership_dict(p: Partnership, db: Session, company_map: dict[int, Company] | None = None) -> dict:
    if company_map is None:
        ids = [m.company_id for m in p.members]
        company_map = {c.id: c for c in db.query(Company).filter(Company.id.in_(ids)).all()} if ids else {}
    members = [
        {
            "company_id": m.company_id,
            "company_name": company_map[m.company_id].company_name if m.company_id in company_map else "Unknown",
            "role": m.role,
        }
        for m in p.members
    ]
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


# ── Partnership CRUD ────────────────────────────────────────────────────────

@router.post("/partnerships/import-pitchbook")
def import_pitchbook_endpoint(db: Session = Depends(get_db)):
    """One-shot: load PitchBook Excel from the local /data directory into the DB."""
    from backend.seed import import_pitchbook
    result = import_pitchbook(db)
    return result


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
    partnerships = (
        q.options(selectinload(Partnership.members))
        .order_by(Partnership.date_announced.desc())
        .all()
    )
    all_member_ids = {m.company_id for p in partnerships for m in p.members}
    company_map = {c.id: c for c in db.query(Company).filter(Company.id.in_(all_member_ids)).all()} if all_member_ids else {}
    return [_partnership_dict(p, db, company_map) for p in partnerships]


# NOTE: /graph must be defined BEFORE /{partnership_id} to avoid "graph" being matched as an ID
@router.get("/partnerships/graph")
def partnership_graph(db: Session = Depends(get_db)):
    """Return nodes + links for the enhanced bubble graph."""
    return _build_partnership_graph(db)


@router.post("/partnerships/enrich")
async def enrich_network(request: Request, db: Session = Depends(get_db)):
    """Background job: AI-classify all unclassified company types and partnership types."""
    check_rate_limit(request, max_calls=3, window_secs=60)
    ts = datetime.now(timezone.utc).isoformat()
    job = ResearchJob(job_type="network_enrich", status="pending", target="network", created_at=ts, updated_at=ts)
    db.add(job)
    db.commit()
    db.refresh(job)
    job_id = job.id
    asyncio.create_task(_enrich_network_bg(job_id, ts)).add_done_callback(_log_task_error)
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


_GRAPH_COMPANY_COLS = (
    Company.id,
    Company.company_name,
    Company.company_type,
    Company.industry_segment,
    Company.supply_chain_segment,
    Company.market_cap_usd,
    Company.revenue_usd,
    Company.number_of_employees,
    Company.total_funding_usd,
    Company.gwh_capacity,
    Company.announced_partners,
)


def _build_partnership_graph(db: Session) -> dict:
    """Return nodes + links for the enhanced bubble graph, using both
    the new partnerships table AND legacy announced_partners JSON.

    Only companies that actually participate in the graph (i.e. are a
    PartnershipMember, appear in another company's announced_partners JSON,
    or have a non-empty announced_partners of their own) are loaded. Heavy
    TEXT columns (summary, long_description, notes, keywords, …) never leave
    the DB. Partnership.members is eager-loaded to avoid the N+1 lazy-load."""

    # Eager-load members so we don't fire 1 SELECT per partnership.
    partnerships = (
        db.query(Partnership)
        .options(selectinload(Partnership.members))
        .all()
    )

    # IDs that matter: anyone who is a partnership member, or has legacy JSON.
    member_ids: set[int] = {m.company_id for p in partnerships for m in p.members}
    legacy_ids_q = db.query(Company.id).filter(
        Company.announced_partners.isnot(None),
        func.trim(Company.announced_partners) != "",
        func.trim(Company.announced_partners) != "[]",
    )
    legacy_ids: set[int] = {row[0] for row in legacy_ids_q.all()}
    relevant_ids = member_ids | legacy_ids

    if not relevant_ids:
        return {"nodes": [], "links": []}

    companies = (
        db.query(Company)
        .options(load_only(*_GRAPH_COMPANY_COLS))
        .filter(Company.id.in_(relevant_ids))
        .all()
    )

    company_map: dict[int, Company] = {c.id: c for c in companies}
    company_name_map: dict[str, int] = {c.company_name.lower(): c.id for c in companies}

    # We also need a name→id map for ALL companies (so legacy JSON partners
    # that happen to exist in DB but aren't yet "relevant" resolve to real IDs
    # instead of getting a virtual node). One lightweight SELECT of two cols.
    full_name_map_rows = (
        db.query(Company.id, Company.company_name)
        .filter(Company.id.notin_(relevant_ids))
        .all()
    )
    for cid, cname in full_name_map_rows:
        company_name_map.setdefault(cname.lower(), cid)

    # Gather metrics for percentile estimation — relevant companies only.
    metrics_by_company: dict[int, dict] = {}
    for c in companies:
        metrics_by_company[c.id] = {
            "market_cap_usd": c.market_cap_usd,
            "revenue_usd": c.revenue_usd,
            "employee_count": c.number_of_employees,
            "total_funding_usd": c.total_funding_usd,
            "manufacturing_capacity_gwh": _parse_max_gwh(c.gwh_capacity),
        }

    # Pull company_metrics only for relevant companies.
    all_metrics = (
        db.query(CompanyMetric)
        .filter(CompanyMetric.company_id.in_(relevant_ids))
        .all()
    )
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


