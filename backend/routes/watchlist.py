"""Watchlist CRUD + digest endpoints — per-user, requires Supabase JWT."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend._util import safe_json
from backend.auth import require_user
from backend.database import get_db
from backend.models import Company, WatchlistDigest, WatchlistEntry, WatchlistList

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_or_create_default_list(db: Session, user_id: str) -> WatchlistList:
    lst = db.query(WatchlistList).filter_by(user_id=user_id, name="My Watchlist").first()
    if not lst:
        lst = WatchlistList(user_id=user_id, name="My Watchlist", created_at=_now())
        db.add(lst)
        db.commit()
        db.refresh(lst)
    return lst


# ── List CRUD ────────────────────────────────────────────────────────────────

@router.get("/lists")
def get_lists(
    user_id: str | None = Depends(require_user),
    db: Session = Depends(get_db),
):
    if not user_id:
        return []
    lists = db.query(WatchlistList).filter_by(user_id=user_id).order_by(WatchlistList.created_at).all()
    result = []
    for lst in lists:
        count = db.query(WatchlistEntry).filter_by(list_id=lst.id).count()
        result.append({"id": lst.id, "name": lst.name, "created_at": lst.created_at, "company_count": count})
    return result


@router.post("/lists")
def create_list(
    name: str = Body(..., embed=True),
    user_id: str | None = Depends(require_user),
    db: Session = Depends(get_db),
):
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="List name cannot be empty")
    lst = WatchlistList(user_id=user_id, name=name, created_at=_now())
    db.add(lst)
    db.commit()
    db.refresh(lst)
    return {"id": lst.id, "name": lst.name, "created_at": lst.created_at, "company_count": 0}


@router.patch("/lists/{list_id}")
def rename_list(
    list_id: int,
    name: str = Body(..., embed=True),
    user_id: str | None = Depends(require_user),
    db: Session = Depends(get_db),
):
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    lst = db.query(WatchlistList).filter_by(id=list_id, user_id=user_id).first()
    if not lst:
        raise HTTPException(status_code=404, detail="List not found")
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="List name cannot be empty")
    lst.name = name
    db.commit()
    return {"id": lst.id, "name": lst.name}


@router.delete("/lists/{list_id}")
def delete_list(
    list_id: int,
    user_id: str | None = Depends(require_user),
    db: Session = Depends(get_db),
):
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    lst = db.query(WatchlistList).filter_by(id=list_id, user_id=user_id).first()
    if not lst:
        raise HTTPException(status_code=404, detail="List not found")
    db.delete(lst)
    db.commit()
    return {"status": "deleted", "list_id": list_id}


# ── Watchlist CRUD ──────────────────────────────────────────────────────────

@router.get("")
def list_watchlist(
    list_id: Optional[int] = Query(None),
    user_id: str | None = Depends(require_user),
    db: Session = Depends(get_db),
):
    if not user_id:
        return []
    query = db.query(WatchlistEntry).filter_by(user_id=user_id)
    if list_id is not None:
        query = query.filter_by(list_id=list_id)
    entries = query.all()
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
                "list_id": e.list_id,
            })
    return result


@router.post("/{company_id}")
def add_to_watchlist(
    company_id: int,
    list_id: Optional[int] = Body(None, embed=True),
    user_id: str | None = Depends(require_user),
    db: Session = Depends(get_db),
):
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    company = db.query(Company).filter_by(id=company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    # Resolve target list
    if list_id is not None:
        lst = db.query(WatchlistList).filter_by(id=list_id, user_id=user_id).first()
        if not lst:
            raise HTTPException(status_code=404, detail="List not found")
    else:
        lst = _get_or_create_default_list(db, user_id)

    existing = db.query(WatchlistEntry).filter_by(
        company_id=company_id, user_id=user_id, list_id=lst.id
    ).first()
    if existing:
        return {"status": "already_watching", "company_id": company_id, "list_id": lst.id}

    entry = WatchlistEntry(
        company_id=company_id,
        user_id=user_id,
        list_id=lst.id,
        added_at=_now(),
    )
    db.add(entry)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return {"status": "already_watching", "company_id": company_id, "list_id": lst.id}
    return {"status": "added", "company_id": company_id, "list_id": lst.id}


@router.delete("/{company_id}")
def remove_from_watchlist(
    company_id: int,
    list_id: Optional[int] = Query(None),
    user_id: str | None = Depends(require_user),
    db: Session = Depends(get_db),
):
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    query = db.query(WatchlistEntry).filter_by(company_id=company_id, user_id=user_id)
    if list_id is not None:
        query = query.filter_by(list_id=list_id)
    entries = query.all()
    if not entries:
        raise HTTPException(status_code=404, detail="Not in watchlist")
    for e in entries:
        db.delete(e)
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
