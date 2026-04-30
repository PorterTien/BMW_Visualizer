"""APScheduler background jobs — watchlist digest + stale company re-research.
NAATBatt refresh is manual-only via POST /api/sync/naatbatt."""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

log = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None

_JOB_ID_DIGEST = "watchlist_daily_digest"
_JOB_ID_STALE = "stale_company_research"

# Max companies to re-research per daily run — avoids flooding the Perplexity/Claude APIs.
_STALE_BATCH_SIZE = 20


def _run_watchlist_digest():
    from backend.database import SessionLocal
    from backend.watchlist_digest import run_full_digest

    log.info("Scheduled watchlist digest starting…")
    db = SessionLocal()
    try:
        result = run_full_digest(db)
        log.info("Watchlist digest complete: %s", result)
    except Exception as e:
        log.error("Watchlist digest failed: %s", e)
    finally:
        db.close()


def _run_stale_research():
    """Re-research companies whose last_researched is >30 days ago (or never)."""
    from datetime import datetime, timedelta, timezone

    from backend.ai_research import research_company, search_company_news
    from backend.database import SessionLocal
    from backend.models import Company, NewsHeadline
    import json

    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    db = SessionLocal()
    try:
        stale = (
            db.query(Company)
            .filter(
                (Company.last_researched == None) | (Company.last_researched < cutoff),  # noqa: E711
                Company.data_source != "pitchbook_investor",
            )
            .order_by(Company.last_researched.asc().nullsfirst())
            .limit(_STALE_BATCH_SIZE)
            .all()
        )
        log.info("Stale research job: %d companies to re-research", len(stale))
        for company in stale:
            try:
                result = research_company(company.company_name)
                news = search_company_news(company.company_name)
                ts = datetime.now(timezone.utc).isoformat()

                overrides = set(json.loads(company.manual_overrides or "[]"))
                for field, val in result.items():
                    if val is not None and field not in ("company_name", "error") and field not in overrides:
                        setattr(company, field, json.dumps(val) if isinstance(val, (list, dict)) else val)
                company.last_updated = ts
                company.last_researched = ts
                db.commit()

                existing_urls = {
                    n.url for n in db.query(NewsHeadline.url)
                    .filter(NewsHeadline.company_id == company.id).all()
                    if n.url
                }
                for article in news:
                    url = article.get("url", "")
                    if url and url in existing_urls:
                        continue
                    article["company_id"] = company.id
                    article["created_at"] = ts
                    for lf in ("partners", "topics"):
                        if isinstance(article.get(lf), list):
                            article[lf] = json.dumps(article[lf])
                    db.add(NewsHeadline(**{k: v for k, v in article.items()
                                          if k in NewsHeadline.__table__.columns.keys()}))
                db.commit()
                log.info("Re-researched %r", company.company_name)
            except Exception as e:
                log.error("Stale research failed for %r: %s", company.company_name, e)
                db.rollback()
    finally:
        db.close()


def start_scheduler():
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        _run_watchlist_digest,
        trigger=CronTrigger(hour=7, minute=0),
        id=_JOB_ID_DIGEST,
        replace_existing=True,
    )
    _scheduler.add_job(
        _run_stale_research,
        trigger=CronTrigger(hour=3, minute=0),
        id=_JOB_ID_STALE,
        replace_existing=True,
    )
    _scheduler.start()
    log.info("APScheduler started — watchlist digest 07:00 UTC, stale research 03:00 UTC.")


def stop_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def get_next_run_time() -> str | None:
    return None
