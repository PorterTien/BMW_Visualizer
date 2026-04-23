"""Watchlist CRUD + digest endpoints — per-user, requires Supabase JWT."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend._util import safe_json
from backend.auth import require_user
from backend.database import get_db
from backend.models import Company, WatchlistDigest, WatchlistEntry

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])

# ── Watchlist CRUD ──────────────────────────────────────────────────────────

@router.get("")
def list_watchlist(
    user_id: str | None = Depends(require_user),
    db: Session = Depends(get_db),
):
    if not user_id:
        return []
    entries = db.query(WatchlistEntry).filter_by(user_id=user_id).all()
    company_ids = [e.company_id for e in entries]
    companies = db.query(Company).filter(Company.id.in_(company_ids)).all() if company_ids else []
    company_map = {c.id: c for c in companies}

    result = []
    for e in entries:
        c = company_map.get(e.company_id)
        if c:
            result.append({
                "company_id": c.id,
                "company_name": c.company_name,
                "company_type": c.company_type,
                "company_status": c.company_status,
                "company_hq_country": c.company_hq_country,
                "funding_status": c.funding_status,
                "company_website": c.company_website,
                "added_at": e.added_at,
            })
    return result


@router.post("/{company_id}")
def add_to_watchlist(
    company_id: int,
    user_id: str | None = Depends(require_user),
    db: Session = Depends(get_db),
):
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    company = db.query(Company).filter_by(id=company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    existing = db.query(WatchlistEntry).filter_by(company_id=company_id, user_id=user_id).first()
    if existing:
        return {"status": "already_watching", "company_id": company_id}
    entry = WatchlistEntry(
        company_id=company_id,
        user_id=user_id,
        added_at=datetime.now(timezone.utc).isoformat(),
    )
    db.add(entry)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return {"status": "already_watching", "company_id": company_id}
    return {"status": "added", "company_id": company_id}


@router.delete("/{company_id}")
def remove_from_watchlist(
    company_id: int,
    user_id: str | None = Depends(require_user),
    db: Session = Depends(get_db),
):
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    entry = db.query(WatchlistEntry).filter_by(company_id=company_id, user_id=user_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Not in watchlist")
    db.delete(entry)
    db.commit()
    return {"status": "removed", "company_id": company_id}


# ── Digest endpoints ─────────────────────────────────────────────────────────

@router.get("/digest/latest")
def get_latest_digest(
    user_id: str | None = Depends(require_user),
    db: Session = Depends(get_db),
):
    if not user_id:
        return []
    company_ids = [
        cid for (cid,) in db.query(WatchlistEntry.company_id)
        .filter(WatchlistEntry.user_id == user_id).all()
    ]
    if not company_ids:
        return []

    digests = (
        db.query(WatchlistDigest)
        .filter(WatchlistDigest.company_id.in_(company_ids))
        .order_by(WatchlistDigest.company_id, WatchlistDigest.run_date.desc())
        .all()
    )
    seen: set[int] = set()
    results = []
    for d in digests:
        if d.company_id in seen:
            continue
        seen.add(d.company_id)
        results.append({
            "company_id": d.company_id,
            "company_name": d.company_name,
            "run_date": d.run_date,
            "has_breaking": bool(d.has_breaking),
            "articles": safe_json(d.articles_json, []),
            "created_at": d.created_at,
        })
    return results


@router.post("/digest/run")
def trigger_digest(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    from backend.watchlist_digest import run_full_digest

    def _run():
        from backend.database import SessionLocal
        d = SessionLocal()
        try:
            run_full_digest(d)
        finally:
            d.close()

    background_tasks.add_task(_run)
    return {"status": "digest_started"}


@router.post("/digest/run/{company_id}")
def trigger_digest_one(
    company_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    company = db.query(Company).filter_by(id=company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    name = company.company_name

    def _run():
        from backend.database import SessionLocal
        from backend.watchlist_digest import run_digest_for_company
        d = SessionLocal()
        try:
            run_digest_for_company(d, company_id, name)
        finally:
            d.close()

    background_tasks.add_task(_run)
    return {"status": "digest_started", "company_id": company_id, "company_name": name}
