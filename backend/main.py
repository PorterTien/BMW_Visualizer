"""FastAPI application entry point."""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from backend.database import get_db, init_db, migrate_db
from backend.models import Company, SyncLog
from backend.routes import companies, jobs, news, proceedings, upload
from backend.scheduler import get_next_run_time, start_scheduler, stop_scheduler

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

app = FastAPI(title="BMW Battery Intelligence API", version="1.0.0")

_default_cors = "http://localhost:5173,http://127.0.0.1:5173"
_cors_raw = os.getenv("CORS_ORIGINS", _default_cors).strip()
if _cors_raw == "*":
    _cors_origins = ["*"]
else:
    _cors_origins = [o.strip() for o in _cors_raw.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(companies.router)
app.include_router(news.router)
app.include_router(proceedings.router)
app.include_router(upload.router)
app.include_router(jobs.router)


@app.on_event("startup")
async def startup():
    init_db()
    migrate_db()
    start_scheduler()
    # Auto-seed if DB is empty
    from backend.database import SessionLocal

    db = SessionLocal()
    try:
        count = db.query(Company).count()
        if count == 0:
            log.info("DB is empty — auto-triggering NAATBatt seed in background.")
            asyncio.create_task(_auto_seed())
    finally:
        db.close()


async def _run_seed(force: bool):
    from backend.database import SessionLocal
    from backend.seed import import_bbd, import_gigafactory, import_naatbatt

    db = SessionLocal()
    try:
        await asyncio.get_event_loop().run_in_executor(None, import_naatbatt, db, force)
        await asyncio.get_event_loop().run_in_executor(None, import_bbd, db)
        await asyncio.get_event_loop().run_in_executor(None, import_gigafactory, db)
    finally:
        db.close()


async def _auto_seed():
    await _run_seed(False)


@app.on_event("shutdown")
async def shutdown():
    stop_scheduler()


# Sync endpoints
@app.get("/api/sync/status")
def sync_status(db: Session = Depends(get_db)):
    last = db.query(SyncLog).order_by(SyncLog.run_at.desc()).first()
    return {
        "last_sync": {
            "id": last.id,
            "source": last.source,
            "status": last.status,
            "rows_added": last.rows_added,
            "rows_updated": last.rows_updated,
            "run_at": last.run_at,
        }
        if last
        else None,
        "next_scheduled_run": get_next_run_time(),
    }


@app.post("/api/sync/naatbatt")
def trigger_naatbatt_sync():
    asyncio.create_task(_run_seed(True))
    return {"status": "sync_started"}


# Seed endpoints
@app.post("/api/seed")
def trigger_seed():
    asyncio.create_task(_run_seed(False))
    return {"status": "seed_started"}


@app.get("/api/seed/status")
def seed_status(db: Session = Depends(get_db)):
    count = db.query(Company).count()
    return {"seeded": count > 0, "company_count": count}


@app.get("/api/health")
def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


# Production: serve Vite build from the same origin as /api (register after API routes)
_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="spa")
