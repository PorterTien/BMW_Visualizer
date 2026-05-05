"""Sector-level AI research: discover top companies + news in a battery category."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.ai_research import perplexity_search
from backend.config import TAVILY_API_KEY
from backend.database import SessionLocal, get_db
from backend.models import Company, NewsHeadline, ResearchJob

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sector-research", tags=["sector-research"])

# ── Category definitions ──────────────────────────────────────────────────────

CATEGORIES = {
    "Cell Manufacturing": {
        "company_queries": [
            "top battery cell manufacturing companies US Canada 2025 2026 lithium-ion gigafactory startup",
            "battery cell manufacturers emerging startups US Canada EV solid-state sodium-ion 2026 funding",
        ],
        "news_queries": [
            "battery cell manufacturing US news 2025 2026 gigafactory opening partnership announcement",
            "lithium-ion cell manufacturer announcement investment acquisition US Canada 2025 2026",
        ],
    },
    "Solid-State Battery": {
        "company_queries": [
            "solid-state battery companies US Canada 2025 2026 startup OEM sulfide oxide polymer",
            "solid-state electrolyte battery manufacturer US Canada research startup funding 2026",
        ],
        "news_queries": [
            "solid-state battery news 2025 2026 US breakthrough milestone partnership announcement",
            "solid-state battery company funding acquisition research milestone US 2026",
        ],
    },
    "Battery Grade Materials": {
        "company_queries": [
            "battery grade materials supplier US Canada 2025 2026 cathode anode electrolyte precursor",
            "lithium battery materials manufacturer US Canada NMC LFP NCA NCMA supplier 2026",
        ],
        "news_queries": [
            "battery materials supplier news US Canada 2025 2026 supply agreement partnership funding",
            "battery grade cathode anode electrolyte materials announcement US 2025 2026",
        ],
    },
    "EV OEM": {
        "company_queries": [
            "electric vehicle OEM manufacturers US Canada 2025 2026 battery cell partnership gigafactory",
            "EV automaker US Canada battery supply chain investment 2026",
        ],
        "news_queries": [
            "EV OEM battery cell partnership announcement US Canada 2025 2026",
            "electric vehicle manufacturer battery supply chain news US 2025 2026",
        ],
    },
    "Battery Recycling": {
        "company_queries": [
            "battery recycling companies US Canada 2025 2026 lithium-ion hydrometallurgy pyrometallurgy",
            "EV battery recycling startup US Canada funding partnership 2026",
        ],
        "news_queries": [
            "battery recycling news US Canada 2025 2026 facility opening funding announcement",
            "lithium-ion battery recycling plant US Canada 2025 2026",
        ],
    },
    "Testing & Prototyping": {
        "company_queries": [
            "battery testing prototyping services companies US Canada 2025 2026 cell characterization",
            "battery cell testing lab prototyping partner US Canada startup 2026",
        ],
        "news_queries": [
            "battery testing prototyping service provider news US Canada 2025 2026",
            "battery cell characterization testing facility announcement US 2025 2026",
        ],
    },
    "Equipment Supplier": {
        "company_queries": [
            "battery manufacturing equipment supplier US Canada 2025 2026 electrode coating formation",
            "battery production equipment maker US Canada startup OEM 2026",
        ],
        "news_queries": [
            "battery manufacturing equipment supplier news US Canada 2025 2026",
            "battery equipment supplier partnership announcement US 2025 2026",
        ],
    },
    "R&D / University": {
        "company_queries": [
            "battery R&D company university research institute US Canada 2025 2026 DOE ARPA-E",
            "battery technology research lab US Canada startup spinout 2026",
        ],
        "news_queries": [
            "battery research discovery milestone US university 2025 2026 announcement",
            "battery R&D breakthrough US Canada DOE university 2025 2026",
        ],
    },
    "Modeling & Software": {
        "company_queries": [
            "battery modeling simulation software company US Canada 2025 2026 AI digital twin",
            "battery AI simulation startup US Canada 2026 funding",
        ],
        "news_queries": [
            "battery modeling software AI announcement US Canada 2025 2026",
            "battery simulation digital twin software company news US 2025 2026",
        ],
    },
    "Anode Materials": {
        "company_queries": [
            "battery anode material company US Canada 2025 2026 silicon graphite lithium metal",
            "anode material supplier startup US Canada silicon prelithiation 2026 funding",
        ],
        "news_queries": [
            "battery anode material news US Canada 2025 2026 silicon graphite lithium metal",
            "anode material supplier announcement US Canada 2025 2026",
        ],
    },
    "Cathode Materials": {
        "company_queries": [
            "battery cathode material company US Canada 2025 2026 NMC LFP NCA NCMA supplier",
            "cathode active material startup US Canada 2026 funding partnership",
        ],
        "news_queries": [
            "battery cathode material news US Canada 2025 2026 NMC LFP supply agreement",
            "cathode material supplier announcement US Canada 2025 2026",
        ],
    },
    "Electrolyte": {
        "company_queries": [
            "battery electrolyte company US Canada 2025 2026 liquid solid polymer startup",
            "electrolyte supplier US Canada 2026 ionic liquid solid-state funding",
        ],
        "news_queries": [
            "battery electrolyte news US Canada 2025 2026 announcement funding partnership",
            "electrolyte supplier milestone discovery US Canada 2025 2026",
        ],
    },
    "Raw Materials & Mining": {
        "company_queries": [
            "battery raw materials mining company US Canada 2025 2026 lithium cobalt nickel manganese",
            "critical mineral mining US Canada battery supply chain 2026",
        ],
        "news_queries": [
            "battery raw materials mining news US Canada 2025 2026 lithium nickel cobalt",
            "critical mineral supply chain announcement US Canada 2025 2026",
        ],
    },
}

# ── AI prompts ─────────────────────────────────────────────────────────────────

SECTOR_COMPANY_PROMPT = """You are a battery industry analyst. Given web search results, list the top 10-15 companies in the specified battery sector in North America (US and Canada).

Return ONLY a JSON array — no markdown, no explanation. Each item:
{"company_name": string, "company_hq_city": string or null, "company_hq_state": string or null, "company_type": string, "company_status": string, "company_website": string or null, "summary": string}

company_type: start-up | cell supplier | materials supplier | EV OEM | testing partner | recycler | equipment supplier | R&D | modeling/software | other
company_status: Commercial | Pre-commercial/startup | Pilot Plant | Operational | Closed | Paused

Include large incumbents AND emerging startups. Return ONLY the JSON array."""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _update_job(db: Session, job_id: int, status: str, result: Any = None):
    job = db.query(ResearchJob).filter(ResearchJob.id == job_id).first()
    if job:
        job.status = status
        if result is not None:
            job.result = json.dumps(result)
        job.updated_at = _now()
        db.commit()


def _extract_list(text: str, label: str) -> list:
    """Robustly pull a JSON array out of Claude's response even with surrounding prose."""
    text = text.strip()

    # Strategy 1: code fence with optional language tag (```json ... ``` or ``` ... ```)
    fence = re.search(r'```(?:json)?\s*\n([\s\S]*?)\n```', text)
    if fence:
        try:
            result = json.loads(fence.group(1).strip())
            if isinstance(result, list):
                log.info("%s: extracted %d items via code fence", label, len(result))
                return result
        except json.JSONDecodeError:
            pass

    # Strategy 2: direct parse of the whole response
    try:
        result = json.loads(text)
        if isinstance(result, list):
            log.info("%s: extracted %d items via direct parse", label, len(result))
            return result
    except json.JSONDecodeError:
        pass

    # Strategy 3: find any [...] block spanning the whole array (greedy, handles nested)
    match = re.search(r'\[[\s\S]*\]', text)
    if match:
        try:
            result = json.loads(match.group())
            if isinstance(result, list):
                log.info("%s: extracted %d items via regex", label, len(result))
                return result
        except json.JSONDecodeError:
            pass

    log.warning("%s: could not extract JSON list; raw response head: %r", label, text[:300])
    return []


def _sector_search(query: str) -> str:
    """Tavily search with fewer results to stay under the 10k TPM rate limit."""
    if TAVILY_API_KEY:
        from tavily import TavilyClient
        client = TavilyClient(api_key=TAVILY_API_KEY)
        resp = client.search(query=query, search_depth="basic", max_results=4, include_answer=False)
        parts = []
        for r in resp.get("results", []):
            title = r.get("title", "")
            url = r.get("url", "")
            content = (r.get("content") or "")[:600]
            if content:
                parts.append(f"[{title}] ({url})\n{content}")
        return "\n\n".join(parts) or f"No results for: {query}"
    return perplexity_search(query)


def _claude_list(system: str, user_msg: str, label: str) -> list:
    """Call Claude and robustly extract a JSON array from its response. Retries on 429."""
    import anthropic
    from backend.config import ANTHROPIC_API_KEY, CLAUDE_MODEL
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    for attempt in range(3):
        try:
            msg = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=4096,
                system=system,
                messages=[{"role": "user", "content": user_msg}],
            )
            raw = msg.content[0].text
            log.info("%s: Claude responded with %d chars", label, len(raw))
            return _extract_list(raw, label)
        except anthropic.RateLimitError:
            if attempt < 2:
                wait = 35 * (attempt + 1)
                log.warning("%s: rate limited — waiting %ds (attempt %d/3)", label, wait, attempt + 1)
                time.sleep(wait)
            else:
                log.error("%s: rate limit exceeded after 3 attempts", label)
                return []
        except Exception as e:
            log.error("%s: Claude call failed: %s", label, e)
            return []


# ── Background research task ──────────────────────────────────────────────────

def _run_sector_research(job_id: int, category: str):
    db = SessionLocal()
    try:
        _update_job(db, job_id, "running")
        config = CATEGORIES.get(category, {})

        # ── Companies ──
        company_texts = []
        for q in config.get("company_queries", []):
            try:
                text = _sector_search(q)
                company_texts.append(f"Query: {q}\n\n{text}")
                log.info("Company search OK: %r (%d chars)", q[:60], len(text))
            except Exception as e:
                log.warning("Company search failed for %r: %s", q, e)
            time.sleep(1)

        companies = []
        if company_texts:
            combined = "\n\n---\n\n".join(company_texts)
            user_msg = f"Sector: {category}\n\nSearch results:\n{combined}"
            companies = _claude_list(SECTOR_COMPANY_PROMPT, user_msg, f"companies/{category}")
            log.info("Sector %r: %d companies extracted", category, len(companies))

        _update_job(db, job_id, "complete", {"companies": companies, "news": []})

    except Exception as e:
        log.error("Sector research job %d failed: %s", job_id, e)
        _update_job(db, job_id, "failed", {"error": str(e)})
    finally:
        db.close()


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/categories")
def get_categories():
    return {"categories": list(CATEGORIES.keys())}


class RunRequest(BaseModel):
    category: str


@router.post("/run")
def run_sector_research(req: RunRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    if req.category not in CATEGORIES:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Unknown category: {req.category}")

    job = ResearchJob(
        job_type="sector_research",
        status="pending",
        target=req.category,
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    background_tasks.add_task(_run_sector_research, job.id, req.category)
    return {"job_id": job.id, "status": "pending"}


@router.get("/jobs/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db)):
    from fastapi import HTTPException
    job = db.query(ResearchJob).filter(ResearchJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    result = None
    if job.result:
        try:
            result = json.loads(job.result)
        except Exception:
            pass
    return {
        "id": job.id,
        "status": job.status,
        "target": job.target,
        "result": result,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


class VerifyRequest(BaseModel):
    urls: list[str]


@router.post("/verify-urls")
async def verify_urls(req: VerifyRequest):
    results: dict[str, dict] = {}
    timeout = httpx.Timeout(10.0)

    async def check(url: str):
        if not url or not url.startswith("http"):
            results[url] = {"valid": False, "status_code": None, "error": "invalid url"}
            return
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                try:
                    r = await client.head(url, headers={"User-Agent": "Mozilla/5.0"})
                    # Some servers return 405 on HEAD — fall back to GET
                    if r.status_code == 405:
                        r = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                except httpx.HTTPStatusError as e:
                    results[url] = {"valid": False, "status_code": e.response.status_code, "error": str(e)}
                    return
            valid = r.status_code < 400
            results[url] = {"valid": valid, "status_code": r.status_code, "error": None}
        except Exception as e:
            results[url] = {"valid": False, "status_code": None, "error": str(e)[:120]}

    await asyncio.gather(*[check(u) for u in req.urls])
    return results


class ApproveRequest(BaseModel):
    companies: list[dict] = []


def _run_company_research(company_name: str):
    """Full research + upsert for one company (blocking, run in thread)."""
    from backend.ai_research import research_company, search_company_news

    db = SessionLocal()
    try:
        now = _now()
        result = research_company(company_name)

        existing = db.query(Company).filter(
            Company.company_name.ilike(company_name)
        ).first()

        valid_columns = {c.key for c in Company.__table__.columns}
        if existing:
            for field, val in result.items():
                if val is not None and field not in ("company_name", "error") and field in valid_columns:
                    if isinstance(val, (list, dict)):
                        val = json.dumps(val)
                    setattr(existing, field, val)
            existing.last_updated = now[:10]
            existing.data_source = "ai_research"
        else:
            company_data = {
                k: (json.dumps(v) if isinstance(v, (list, dict)) else v)
                for k, v in result.items()
                if k != "error" and k in valid_columns
            }
            company_data["last_updated"] = now[:10]
            existing = Company(**company_data)
            db.add(existing)

        db.commit()
        db.refresh(existing)

        # Geocode if lat/lng missing
        if not existing.company_hq_lat and existing.company_hq_city:
            try:
                from backend.seed import _geocode_city
                lat, lng = _geocode_city(
                    existing.company_hq_city or "",
                    existing.company_hq_state or "",
                )
                if lat:
                    existing.company_hq_lat = lat
                    existing.company_hq_lng = lng
                    db.commit()
            except Exception:
                pass

        # Save linked news articles
        news = search_company_news(company_name)
        for article in news:
            article["company_id"] = existing.id
            article["created_at"] = now
            if isinstance(article.get("partners"), list):
                article["partners"] = json.dumps(article["partners"])
            if isinstance(article.get("topics"), list):
                article["topics"] = json.dumps(article["topics"])
            db.add(NewsHeadline(**{
                k: v for k, v in article.items()
                if k in NewsHeadline.__table__.columns.keys()
            }))
        db.commit()

        log.info("Enrichment complete for %r: %d news articles", company_name, len(news))
    except Exception as e:
        log.error("Enrichment failed for %r: %s", company_name, e)
    finally:
        db.close()


@router.post("/approve")
def approve_research(req: ApproveRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    now = _now()
    names = [c.get("company_name", "").strip() for c in req.companies if c.get("company_name", "").strip()]
    company_by_name = {c.get("company_name", "").strip(): c for c in req.companies if c.get("company_name", "").strip()}

    for name in names:
        stub_data = company_by_name[name]
        existing = db.query(Company).filter(Company.company_name.ilike(name)).first()
        if existing:
            existing.company_type = stub_data.get("company_type") or existing.company_type
            existing.company_status = stub_data.get("company_status") or existing.company_status
            existing.company_hq_city = stub_data.get("company_hq_city") or existing.company_hq_city
            existing.company_hq_state = stub_data.get("company_hq_state") or existing.company_hq_state
            existing.company_website = stub_data.get("company_website") or existing.company_website
            existing.summary = stub_data.get("summary") or existing.summary
            existing.data_source = "ai_research"
            existing.last_updated = now[:10]
        else:
            db.add(Company(
                company_name=name,
                company_type=stub_data.get("company_type"),
                company_status=stub_data.get("company_status"),
                company_hq_city=stub_data.get("company_hq_city"),
                company_hq_state=stub_data.get("company_hq_state"),
                company_website=stub_data.get("company_website"),
                summary=stub_data.get("summary"),
                data_source="ai_research",
                last_updated=now[:10],
            ))
        try:
            db.commit()
        except Exception as e:
            db.rollback()
            log.error("Failed to upsert stub for %r: %s", name, e)

        background_tasks.add_task(_run_company_research, name)

    return {"queued": len(names), "company_names": names}


class SectorChatRequest(BaseModel):
    message: str
    category: str = ""
    companies: list = []
    news: list = []


@router.post("/chat")
async def chat_sector(req: SectorChatRequest):
    from backend.ai_research import _get_anthropic
    from backend.config import CLAUDE_MODEL

    company_lines = "\n".join(
        f"- {c.get('company_name', '?')} ({c.get('company_type', '?')}, {c.get('company_hq_city') or c.get('company_hq_state') or 'unknown location'}): {c.get('summary', '')}"
        for c in req.companies[:20]
    )
    context = f"Category: {req.category or 'Battery supply chain'}\n\nDiscovered companies:\n{company_lines or 'None yet'}"

    search_query = f"battery {req.category} {req.message}"
    try:
        web_results = await asyncio.get_event_loop().run_in_executor(
            None, perplexity_search, search_query
        )
    except Exception:
        web_results = ""

    client = _get_anthropic()
    msg = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        system=(
            "You are a battery industry analyst assistant for BMW. "
            "Answer questions about battery supply chain sectors, companies, and trends. "
            "Use the research context and web results provided. "
            "Use markdown for structure when helpful."
        ),
        messages=[{
            "role": "user",
            "content": (
                f"Research context:\n{context}\n\n"
                f"Fresh web search results:\n{web_results}\n\n"
                f"User question: {req.message}"
            ),
        }],
    )
    return {"response": msg.content[0].text}
