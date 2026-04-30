"""APScheduler background jobs — watchlist digest only.
NAATBatt sync is manual via the UI Sync Now button."""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

log = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None
_JOB_ID_DIGEST = "watchlist_daily_digest"


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


def start_scheduler():
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        _run_watchlist_digest,
        trigger=CronTrigger(hour=7, minute=0),  # every day at 7am UTC
        id=_JOB_ID_DIGEST,
        replace_existing=True,
    )
    _scheduler.start()
    log.info("APScheduler started — watchlist digest 07:00 UTC. NAATBatt sync is manual.")


def stop_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
