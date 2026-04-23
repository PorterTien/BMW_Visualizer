"""APScheduler background jobs for daily NAATBatt refresh + watchlist digest."""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

log = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None

# Job ids — shared between add_job and get_next_run_time so they never drift.
_JOB_ID_REFRESH = "naatbatt_daily_refresh"
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


def _run_refresh():
    from backend.database import SessionLocal
    from backend.seed import import_naatbatt

    log.info("Scheduled NAATBatt refresh starting…")
    db = SessionLocal()
    try:
        result = import_naatbatt(db, force_download=True)
        log.info("Scheduled refresh complete: %s", result)
    except Exception as e:
        log.error("Scheduled refresh failed: %s", e)
    finally:
        db.close()


def start_scheduler():
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        _run_refresh,
        trigger=CronTrigger(hour=3, minute=0),  # every day at 03:00 UTC
        id=_JOB_ID_REFRESH,
        replace_existing=True,
    )
    _scheduler.add_job(
        _run_watchlist_digest,
        trigger=CronTrigger(hour=7, minute=0),  # every day at 7am UTC
        id=_JOB_ID_DIGEST,
        replace_existing=True,
    )
    _scheduler.start()
    log.info("APScheduler started — daily NAATBatt refresh 03:00 UTC, watchlist digest 07:00 UTC.")


def stop_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def get_next_run_time() -> str | None:
    if _scheduler is None:
        return None
    job = _scheduler.get_job(_JOB_ID_REFRESH)
    if job and job.next_run_time:
        return job.next_run_time.isoformat()
    return None
