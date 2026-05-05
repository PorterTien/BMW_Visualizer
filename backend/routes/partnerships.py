"""Partnership routes — CRUD, graph data, import helpers."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, load_only, selectinload

from backend._util import safe_json as _safe_json, safe_float as _safe_float
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

# Generic bucket labels that occasionally appear as partner_name in legacy
# announced_partners JSON or as synthetic seed rows. They're categories, not
# companies, so they must NEVER render as network nodes. See also the
# "Independent Investors" sentinel in routes/upload.py.
BUCKET_PARTNER_NAMES = frozenset({
    "independent investors",
    "undisclosed investors",
    "undisclosed investor",
    "other investors",
    "various investors",
    "individual investors",
    "angel investors",
})


# ── Name normalization ──────────────────────────────────────────────────────
# Legal entity suffixes + generic qualifiers that should be stripped when
# comparing company names. The goal is to collapse "Ford Motor Company",
# "Ford Motor Co.", and "Ford Motors, Inc." down to the same bucket so the
# partnership network doesn't render them as three separate investor nodes.
_LEGAL_SUFFIX_TOKENS = frozenset({
    "inc", "incorporated", "corp", "corporation",
    "co", "company", "companies", "cos",
    "llc", "lp", "llp", "ltd", "limited",
    "plc", "gmbh", "ag", "sa", "nv", "bv", "oy", "ab", "as", "spa",
    "holdings", "holding", "group", "grp",
})

_LEADING_ARTICLES = frozenset({"the", "a", "an"})

_PUNCT_RE = re.compile(r"[^\w\s&]+")
_WS_RE = re.compile(r"\s+")


def _norm_company_name(name: str | None) -> str:
    """Return a canonical form of ``name`` for equality comparison.

    Strips punctuation, lowercases, removes legal-suffix tokens and leading
    articles, and normalizes whitespace. Two raw names with identical
    normalized output are treated as the same company.
    """
    if not name:
        return ""
    s = _PUNCT_RE.sub(" ", name.lower())
    tokens = [t for t in _WS_RE.split(s) if t]
    while tokens and tokens[0] in _LEADING_ARTICLES:
        tokens.pop(0)
    while tokens and tokens[-1] in _LEGAL_SUFFIX_TOKENS:
        tokens.pop()
    if not tokens:
        # The name was *entirely* a suffix/article (e.g. "The Company"); fall
        # back to the original so we don't collapse it into every other empty
        # normalized name.
        return name.strip().lower()
    # Collapse trailing pluralization on the last token so "ford motors" and
    # "ford motor" coalesce. Only applies when the singular form is >= 3
    # chars to avoid mangling short tokens ("sas" → "sa").
    last = tokens[-1]
    if last.endswith("s") and len(last) > 3 and not last.endswith("ss"):
        tokens[-1] = last[:-1]
    return " ".join(tokens)


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


@router.post("/partnerships/enrich-employees")
async def enrich_network_employees(request: Request, db: Session = Depends(get_db)):
    """Background job: look up `number_of_employees` for every company that
    participates in the partnership network (PartnershipMember OR legacy
    announced_partners JSON) and is currently missing that value. Results are
    written back to `companies.number_of_employees` and `employee_size`, and
    progress is reported via a ResearchJob row whose `result` field is a live
    JSON object shaped like {processed, total, updated, failed}."""
    check_rate_limit(request, max_calls=2, window_secs=60)
    ts = datetime.now(timezone.utc).isoformat()
    job = ResearchJob(
        job_type="employee_enrichment",
        status="pending",
        target="partnership_network",
        created_at=ts,
        updated_at=ts,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    asyncio.create_task(_enrich_employees_bg(job.id)).add_done_callback(_log_task_error)
    return {"job_id": job.id}


async def _enrich_employees_bg(job_id: int):
    """Fill in missing employee counts for every company in the partnership
    network. Respects `manual_overrides` (never stomps a human edit)."""
    from backend.ai_research import research_employee_count

    CONCURRENCY = 16

    def _parse_employee_size_midpoint(raw: str | None) -> int | None:
        if not raw:
            return None
        s = str(raw).strip().lower().replace("employees", "").replace("employee", "")
        m = re.search(r"(\d{1,3}(?:,\d{3})?)\s*[-–]\s*(\d{1,3}(?:,\d{3})?)", s)
        if not m:
            return None
        lo = int(m.group(1).replace(",", ""))
        hi = int(m.group(2).replace(",", ""))
        if lo <= 0 or hi < lo:
            return None
        return int(round((lo + hi) / 2))

    def _parse_headcount_from_text(*chunks: str | None) -> int | None:
        blob = " ".join((c or "") for c in chunks).lower()
        if not blob.strip():
            return None
        # Prefer explicit employee/headcount references in local company text.
        m_range = re.search(
            r"(?:employees?|headcount|workforce)[^0-9]{0,35}(\d{1,3}(?:,\d{3})?)\s*[-–]\s*(\d{1,3}(?:,\d{3})?)",
            blob,
        )
        if m_range:
            lo = int(m_range.group(1).replace(",", ""))
            hi = int(m_range.group(2).replace(",", ""))
            if 1 <= lo <= hi <= 2_000_000:
                return int(round((lo + hi) / 2))

        m_single = re.search(
            r"(?:employees?|headcount|workforce)[^0-9]{0,20}(\d{2,3}(?:,\d{3}){0,2})\b",
            blob,
        )
        if m_single:
            n = int(m_single.group(1).replace(",", ""))
            if 10 <= n <= 2_000_000:
                return n
        return None

    def _mark(db, status: str, payload: dict) -> None:
        j = db.query(ResearchJob).filter(ResearchJob.id == job_id).first()
        if not j:
            return
        j.status = status
        j.result = json.dumps(payload)
        j.updated_at = datetime.now(timezone.utc).isoformat()
        db.commit()

    db = SessionLocal()
    try:
        _mark(db, "running", {"processed": 0, "total": 0, "updated": 0, "failed": 0})

        # IDs that participate in the network (same rule as _build_partnership_graph)
        member_ids = {
            row[0] for row in db.query(PartnershipMember.company_id).distinct().all()
        }
        legacy_ids = {
            row[0] for row in db.query(Company.id).filter(
                Company.announced_partners.isnot(None),
                func.trim(Company.announced_partners) != "",
                func.trim(Company.announced_partners) != "[]",
            ).all()
        }
        network_ids = member_ids | legacy_ids

        # Only companies missing a real employee count.
        targets = (
            db.query(
                Company.id,
                Company.company_name,
                Company.manual_overrides,
                Company.employee_size,
                Company.summary,
                Company.long_description,
                Company.description,
                Company.notes,
                Company.extra_description,
            )
            .filter(Company.id.in_(network_ids))
            .filter(
                (Company.number_of_employees.is_(None))
                | (Company.number_of_employees == 0)
            )
            .all()
        )

        # Stage 1 (instant): fill from existing employee_size ranges, no web calls.
        updated = 0
        prefetched_ids: set[int] = set()
        for cid, _name, overrides_json, employee_size, *_txt in targets:
            if "number_of_employees" in set(_safe_json(overrides_json, [])):
                continue
            midpoint = _parse_employee_size_midpoint(employee_size)
            if midpoint:
                c = db.query(Company).filter(Company.id == cid).first()
                if c and not c.number_of_employees:
                    c.number_of_employees = midpoint
                    c.last_updated = datetime.now(timezone.utc).isoformat()
                    prefetched_ids.add(cid)
                    updated += 1
        if prefetched_ids:
            db.commit()

        # Stage 1b (instant): extract from existing local text fields, no web calls.
        for cid, _name, overrides_json, _employee_size, summary, long_desc, desc, notes, extra_desc in targets:
            if cid in prefetched_ids:
                continue
            if "number_of_employees" in set(_safe_json(overrides_json, [])):
                continue
            local_n = _parse_headcount_from_text(summary, long_desc, desc, notes, extra_desc)
            if local_n:
                c = db.query(Company).filter(Company.id == cid).first()
                if c and not c.number_of_employees:
                    c.number_of_employees = local_n
                    c.last_updated = datetime.now(timezone.utc).isoformat()
                    prefetched_ids.add(cid)
                    updated += 1
        if prefetched_ids:
            db.commit()

        unresolved = [(cid, name, ov, es) for cid, name, ov, es, *_ in targets if cid not in prefetched_ids]

        # Stage 2 (network): dedupe by normalized company name so aliases like
        # "24 M Technologies" + "24M Technologies" share one lookup.
        by_key: dict[str, list[tuple[int, str, str | None, str | None]]] = {}
        for row in unresolved:
            cid, name, ov, es = row
            key = _norm_company_name(name) or name.strip().lower()
            by_key.setdefault(key, []).append((cid, name, ov, es))
        dedup_targets = list(by_key.values())

        total = len(targets)
        if total == 0:
            _mark(db, "complete", {"processed": 0, "total": 0, "updated": 0, "failed": 0})
            return

        processed = len(prefetched_ids)
        failed = 0
        no_results = 0
        timed_out = 0
        crashed = 0
        sem = asyncio.Semaphore(CONCURRENCY)
        loop = asyncio.get_event_loop()

        async def _one(group_rows: list[tuple[int, str, str | None, str | None]]):
            nonlocal processed, updated, failed, no_results, timed_out, crashed
            cid0, name0, _ov0, _es0 = group_rows[0]
            async with sem:
                try:
                    data = await asyncio.wait_for(
                        loop.run_in_executor(None, research_employee_count, name0),
                        timeout=12,
                    )
                except asyncio.TimeoutError:
                    timed_out += len(group_rows)
                    data = {"number_of_employees": None, "error": "timeout"}
                except Exception as e:
                    log.warning("employee lookup crashed for %r: %s", name0, e)
                    crashed += len(group_rows)
                    data = {"number_of_employees": None, "error": str(e)}

            # Each worker gets its own session — SQLAlchemy sessions aren't
            # safe to share across concurrent tasks.
            inner = SessionLocal()
            try:
                n = data.get("number_of_employees")
                if isinstance(n, int) and n > 0:
                    group_updates = 0
                    for cid, _name, _ov, _es in group_rows:
                        c = inner.query(Company).filter(Company.id == cid).first()
                        if c and "number_of_employees" not in set(_safe_json(c.manual_overrides, [])):
                            if not c.number_of_employees:
                                c.number_of_employees = n
                                group_updates += 1
                            if data.get("employee_size") and not c.employee_size:
                                c.employee_size = data["employee_size"]
                            c.last_updated = datetime.now(timezone.utc).isoformat()
                    inner.commit()
                    updated += group_updates
                else:
                    if data.get("error") == "no_results":
                        no_results += len(group_rows)
                    failed += len(group_rows)
            except Exception as e:
                log.warning("commit failed for company %s: %s", cid0, e)
                failed += len(group_rows)
            finally:
                inner.close()

            processed += len(group_rows)
            # Heartbeat every 20 rows (and always on the last one) to reduce
            # DB write pressure while still keeping useful progress feedback.
            if processed % 20 == 0 or processed == total:
                hb = SessionLocal()
                try:
                    _mark(hb, "running", {
                        "processed": processed, "total": total,
                        "updated": updated, "failed": failed,
                        "no_results": no_results,
                        "timed_out": timed_out,
                        "crashed": crashed,
                    })
                finally:
                    hb.close()

        await asyncio.gather(*(_one(group) for group in dedup_targets))

        _mark(db, "complete", {
            "processed": processed, "total": total,
            "updated": updated, "failed": failed,
            "no_results": no_results,
            "timed_out": timed_out,
            "crashed": crashed,
        })
    except Exception as e:
        log.error("employee enrichment job %d crashed: %s", job_id, e)
        try:
            _mark(db, "failed", {"error": str(e)})
        except Exception:
            pass
    finally:
        db.close()


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
            .options(selectinload(Partnership.members).selectinload(PartnershipMember.company))
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
    Company.company_hq_lat,
    Company.data_source,
)

_BATTERY_SOURCES = frozenset({
    'naatbatt_xlsx', 'bbd_xlsx', 'gigafactory_xlsx', 'bbd', 'gigafactory', 'file_upload'
})


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

    # Smart name lookup — keyed on the normalized form so "Ford Motor Company"
    # and "Ford Motor Co." collapse onto the same id. The first id we see for
    # a given normalized name becomes the canonical id; any subsequent DB row
    # with the same normalized name aliases back to it via ``id_alias``.
    company_name_map: dict[str, int] = {}
    id_alias: dict[int, int] = {}   # duplicate DB row id → canonical id
    for c in companies:
        key = _norm_company_name(c.company_name)
        if not key:
            continue
        existing = company_name_map.get(key)
        if existing is None:
            company_name_map[key] = c.id
        elif existing != c.id:
            id_alias[c.id] = existing

    def _canon(cid: int) -> int:
        return id_alias.get(cid, cid)

    # We also need a name→id map for ALL companies (so legacy JSON partners
    # that happen to exist in DB but aren't yet "relevant" resolve to real IDs
    # instead of getting a virtual node). One lightweight SELECT of two cols.
    full_name_map_rows = (
        db.query(Company.id, Company.company_name)
        .filter(Company.id.notin_(relevant_ids))
        .all()
    )
    for cid, cname in full_name_map_rows:
        key = _norm_company_name(cname)
        if key:
            company_name_map.setdefault(key, cid)

    _f = _safe_float

    # Gather metrics for percentile estimation — relevant companies only.
    metrics_by_company: dict[int, dict] = {}
    for c in companies:
        metrics_by_company[c.id] = {
            "market_cap_usd": _f(c.market_cap_usd),
            "revenue_usd": _f(c.revenue_usd),
            "employee_count": int(c.number_of_employees) if c.number_of_employees is not None else None,
            "total_funding_usd": _f(c.total_funding_usd),
            "manufacturing_capacity_gwh": _f(_parse_max_gwh(c.gwh_capacity)),
        }

    # Pull company_metrics only for relevant companies.
    all_metrics = (
        db.query(CompanyMetric)
        .filter(CompanyMetric.company_id.in_(relevant_ids))
        .all()
    )
    for m in all_metrics:
        if m.company_id in metrics_by_company:
            metrics_by_company[m.company_id][m.metric_name] = _f(m.metric_value)

    # Compute percentiles for approximation
    metric_ranks = _compute_percentiles(metrics_by_company)

    # Strip bucket-label companies from the graph entirely (defensive — the
    # prune in backend/prune_investors.py should have deleted them already).
    bucket_ids = {c.id for c in companies if (c.company_name or "").lower() in BUCKET_PARTNER_NAMES}

    nodes = []
    for c in companies:
        if c.id in bucket_ids:
            continue
        if c.id in id_alias:
            # Duplicate DB row that normalizes onto another company — skip so
            # we emit exactly one node per canonical entity.
            continue
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
        # Resolve each member to its canonical id and drop buckets + self-loops
        # created by duplicate DB rows collapsing onto the same canonical.
        raw_members = [(_canon(m.company_id), m.role) for m in p.members if m.company_id not in bucket_ids]
        seen_member_ids = set()
        member_ids: list[tuple[int, str]] = []
        for cid, role in raw_members:
            if cid in seen_member_ids:
                continue
            seen_member_ids.add(cid)
            member_ids.append((cid, role))
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
                        "deal_value": _f(p.deal_value),
                        "date": p.date_announced,
                        "scope": p.scope,
                    })

    # Also include legacy announced_partners links
    virtual_id = -1
    virtual_nodes: dict[str, int] = {}   # keyed by normalized name
    for c in companies:
        if c.id in id_alias:
            # Aliased company's JSON partners will be covered by the canonical
            # row; processing them here would create duplicate links.
            continue
        partners = _safe_json(c.announced_partners, [])
        for p in partners:
            partner_name = (p.get("partner_name") or "").strip()
            if not partner_name:
                continue
            if partner_name.lower() in BUCKET_PARTNER_NAMES:
                continue
            norm = _norm_company_name(partner_name)
            if not norm:
                continue
            # Prefer a real DB company (normalized match) over a virtual node
            # so "Ford Motor Company" in the DB absorbs "Ford Motors" from
            # someone else's announced_partners JSON.
            pid = company_name_map.get(norm)
            if pid is None:
                if norm in virtual_nodes:
                    pid = virtual_nodes[norm]
                else:
                    pid = virtual_id
                    virtual_id -= 1
                    virtual_nodes[norm] = pid
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
            src_cid = _canon(c.id)
            if src_cid == pid:
                continue  # self-loop after canonicalization
            link_key = (min(src_cid, pid), max(src_cid, pid), ptype)
            if link_key not in seen_links:
                seen_links.add(link_key)
                links.append({
                    "partnership_id": None,
                    "source": src_cid,
                    "target": pid,
                    "type": ptype,
                    "direction": "bidirectional",
                    "stage": "active",
                    "deal_value": None,
                    "date": p.get("date"),
                    "scope": p.get("scale"),
                })

    # Only keep nodes that appear in at least one link.
    connected_ids = set()
    for link in links:
        connected_ids.add(link["source"])
        connected_ids.add(link["target"])

    node_ids = {n["id"] for n in nodes}
    links = [lnk for lnk in links if lnk["source"] in node_ids and lnk["target"] in node_ids]
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
        vals = [_safe_float(v) for v in data.values() if v]
        vals = [v for v in vals if v is not None]
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


