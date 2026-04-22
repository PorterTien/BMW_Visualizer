from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone

import requests as req_lib
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import NewsHeadline, ResearchJob
from backend.rate_limit import check_rate_limit

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/news", tags=["news"])


def _log_task_error(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception():
        log.error("Background task %s raised: %s", task.get_name(), task.exception())


def _safe_json(val: str | None, default):
    if not val:
        return default
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return default

# In-process cache: at most 500 entries (LRU-eviction via insertion-order dict)
_THUMB_CACHE_MAX = 500
_thumb_cache: dict[str, str | None] = {}


def _thumb_cache_put(url: str, value: str | None) -> None:
    if len(_thumb_cache) >= _THUMB_CACHE_MAX:
        _thumb_cache.pop(next(iter(_thumb_cache)))
    _thumb_cache[url] = value


def _news_dict(n: NewsHeadline) -> dict:
    return {
        "id": n.id,
        "company_id": n.company_id,
        "company_name": n.company_name,
        "news_headline": n.news_headline,
        "category": n.category,
        "partners": _safe_json(n.partners, []),
        "news_source": n.news_source,
        "date_of_article": n.date_of_article,
        "location": n.location,
        "topics": _safe_json(n.topics, []),
        "url": n.url,
        "summary": n.summary,
        "created_at": n.created_at,
    }


def _fetch_og_image(url: str) -> str | None:
    """Extract og:image / twitter:image from a URL. Returns None on any failure."""
    try:
        r = req_lib.get(url, timeout=6, headers={
            "User-Agent": "Mozilla/5.0 (compatible; BMWDataBot/1.0)",
            "Accept": "text/html",
        }, allow_redirects=True, stream=True)
        # Read only the first 60 KB — the <head> section is always near the top
        html = b""
        for chunk in r.iter_content(chunk_size=8192):
            html += chunk
            if len(html) >= 61440:
                break
        text = html.decode("utf-8", errors="replace")
    except Exception:
        return None

    patterns = [
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']{5,})["\']',
        r'<meta[^>]+content=["\']([^"\']{5,})["\'][^>]+property=["\']og:image["\']',
        r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']{5,})["\']',
        r'<meta[^>]+content=["\']([^"\']{5,})["\'][^>]+name=["\']twitter:image["\']',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            img = m.group(1).strip()
            # Skip data URIs and tiny tracking pixels
            if img.startswith("data:") or len(img) < 10:
                continue
            # Make relative URLs absolute
            if img.startswith("//"):
                img = "https:" + img
            elif img.startswith("/"):
                try:
                    from urllib.parse import urlparse
                    base = urlparse(url)
                    img = f"{base.scheme}://{base.netloc}{img}"
                except Exception:
                    pass
            return img
    return None


@router.get("/thumbnail")
async def get_thumbnail(url: str):
    """Return the og:image for an article URL (cached in memory)."""
    if url in _thumb_cache:
        return {"thumbnail_url": _thumb_cache[url]}
    img = await asyncio.get_event_loop().run_in_executor(None, _fetch_og_image, url)
    _thumb_cache_put(url, img)
    return {"thumbnail_url": img}


@router.get("")
def list_news(
    company_id: int | None = None,
    category: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    search: str | None = None,
    db: Session = Depends(get_db),
):
    q = db.query(NewsHeadline)
    if company_id:
        q = q.filter(NewsHeadline.company_id == company_id)
    if category:
        q = q.filter(NewsHeadline.category == category)
    if from_date:
        q = q.filter(NewsHeadline.date_of_article >= from_date)
    if to_date:
        q = q.filter(NewsHeadline.date_of_article <= to_date)
    if search:
        q = q.filter(
            NewsHeadline.news_headline.ilike(f"%{search}%")
            | NewsHeadline.summary.ilike(f"%{search}%")
            | NewsHeadline.company_name.ilike(f"%{search}%")
        )
    return [_news_dict(n) for n in q.order_by(NewsHeadline.date_of_article.desc()).all()]


class NewsSearchRequest(BaseModel):
    company_name: str


@router.post("/search")
async def search_news(req: NewsSearchRequest, request: Request, db: Session = Depends(get_db)):
    check_rate_limit(request, max_calls=10, window_secs=60)
    now = datetime.now(timezone.utc).isoformat()
    job = ResearchJob(
        job_type="news_search",
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
        from backend.ai_research import search_company_news
        from backend.database import SessionLocal
        from backend.models import Company

        inner_db = SessionLocal()
        try:
            j = inner_db.query(ResearchJob).filter(ResearchJob.id == job_id).first()
            if j:
                j.status = "running"
                j.updated_at = datetime.now(timezone.utc).isoformat()
                inner_db.commit()

            articles = await asyncio.get_event_loop().run_in_executor(
                None, search_company_news, req.company_name
            )

            company = inner_db.query(Company).filter(
                Company.company_name.ilike(req.company_name)
            ).first()

            ts = datetime.now(timezone.utc).isoformat()
            for article in articles:
                article["company_id"] = company.id if company else None
                article["created_at"] = ts
                for list_field in ("partners", "topics"):
                    if isinstance(article.get(list_field), list):
                        article[list_field] = json.dumps(article[list_field])
                valid = {k: v for k, v in article.items()
                         if k in NewsHeadline.__table__.columns.keys()}
                inner_db.add(NewsHeadline(**valid))
            inner_db.commit()

            j = inner_db.query(ResearchJob).filter(ResearchJob.id == job_id).first()
            if j:
                j.status = "complete"
                j.result = json.dumps({"news_count": len(articles)})
                j.updated_at = datetime.now(timezone.utc).isoformat()
                inner_db.commit()
        except Exception as e:
            log.error("News search job %d failed: %s", job_id, e)
            j = inner_db.query(ResearchJob).filter(ResearchJob.id == job_id).first()
            if j:
                j.status = "failed"
                j.result = str(e)
                j.updated_at = datetime.now(timezone.utc).isoformat()
                inner_db.commit()
        finally:
            inner_db.close()

    asyncio.create_task(_run()).add_done_callback(_log_task_error)
    return {"job_id": job_id}
