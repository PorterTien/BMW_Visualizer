from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from backend.config import UPLOAD_DIR
from backend.database import get_db
from backend.dedupe import dedupe_companies
from backend.models import Company, NewsHeadline, ResearchJob
from backend.uploads_scan import (
    prune_to_uploaded_names,
    read_first_column,
    record_uploaded_names,
    upsert_names,
)

# Kept as a no-op filter sentinel — the enrichment job skips rows with this
# exact name so legacy seeded "Independent Investors" placeholder doesn't get
# classified.
INDEPENDENT_INVESTORS_NAME = "Independent Investors"

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/upload", tags=["upload"])


def _log_task_error(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception():
        log.error("Background task %s raised: %s", task.get_name(), task.exception())

os.makedirs(UPLOAD_DIR, exist_ok=True)


def _save_file(upload: UploadFile) -> str:
    # Strip directory components to prevent path traversal
    safe_name = Path(upload.filename or "upload").name
    if not safe_name or safe_name in (".", ".."):
        raise HTTPException(400, "Invalid filename.")
    dest = (Path(UPLOAD_DIR) / safe_name).resolve()
    upload_root = Path(UPLOAD_DIR).resolve()
    if not str(dest).startswith(str(upload_root)):
        raise HTTPException(400, "Invalid filename.")
    with open(dest, "wb") as f:
        f.write(upload.file.read())
    return str(dest)


@router.post("/csv")
async def upload_csv(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Ingest **only the first column** of a CSV/XLSX as a list of company
    names. Every other column is ignored. The accepted names are recorded in
    the upload manifest; we then prune the Company table down to just the
    union of names that manifest has ever seen, so the table mirrors what
    the user has uploaded."""
    if not file.filename.endswith((".csv", ".xlsx")):
        raise HTTPException(400, "Only CSV or XLSX files are supported.")
    path = _save_file(file)
    try:
        names = read_first_column(path)
    except Exception as e:
        raise HTTPException(400, f"Failed to parse file: {e}")

    ts = datetime.now(timezone.utc).isoformat()
    ins = upsert_names(db, names, ts)
    db.commit()

    record_uploaded_names(names)

    dedupe_summary = dedupe_companies(db)
    prune_summary = prune_to_uploaded_names(db)

    return {
        "added": ins["added"],
        "updated": ins["updated"],
        "names_in_file": len(names),
        "filename": file.filename,
        "dedupe": dedupe_summary,
        "prune": prune_summary,
    }


@router.post("/document")
async def upload_document(file: UploadFile = File(...), db: Session = Depends(get_db)):
    allowed = (".pdf", ".txt", ".md")
    if not any(file.filename.endswith(ext) for ext in allowed):
        raise HTTPException(400, "Supported formats: PDF, TXT, MD.")
    path = _save_file(file)

    now = datetime.now(timezone.utc).isoformat()
    job = ResearchJob(
        job_type="document_extract",
        status="pending",
        target=file.filename,
        created_at=now,
        updated_at=now,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    job_id = job.id
    filename = file.filename

    async def _run():
        from backend.ai_research import extract_from_document
        from backend.database import SessionLocal

        inner_db = SessionLocal()
        try:
            j = inner_db.query(ResearchJob).filter(ResearchJob.id == job_id).first()
            if j:
                j.status = "running"
                j.updated_at = datetime.now(timezone.utc).isoformat()
                inner_db.commit()

            # Extract text
            text = ""
            if filename.endswith(".pdf"):
                import pdfplumber

                with pdfplumber.open(path) as pdf:
                    for page in pdf.pages:
                        text += (page.extract_text() or "") + "\n"
            else:
                with open(path, "r", errors="ignore") as f:
                    text = f.read()

            result = await asyncio.get_event_loop().run_in_executor(
                None, extract_from_document, text, filename
            )

            ts = datetime.now(timezone.utc).isoformat()
            companies_added = news_added = 0

            for comp_data in result.get("companies", []):
                name = comp_data.get("company_name", "").strip()
                if not name:
                    continue
                existing = inner_db.query(Company).filter(
                    Company.company_name.ilike(name)
                ).first()
                safe = {k: (json.dumps(v) if isinstance(v, (list, dict)) else v)
                        for k, v in comp_data.items()
                        if k in Company.__table__.columns.keys()}
                safe["last_updated"] = ts
                safe["data_source"] = "file_upload"
                if existing:
                    for k, v in safe.items():
                        if v is not None:
                            setattr(existing, k, v)
                else:
                    inner_db.add(Company(**safe))
                    companies_added += 1
            inner_db.commit()

            for news in result.get("news", []):
                name = news.get("company_name", "")
                company = inner_db.query(Company).filter(
                    Company.company_name.ilike(name)
                ).first() if name else None
                n = NewsHeadline(
                    company_id=company.id if company else None,
                    company_name=name,
                    news_headline=news.get("news_headline", ""),
                    category=news.get("category"),
                    partners=json.dumps(news.get("partners", [])),
                    date_of_article=news.get("date_of_article"),
                    summary=news.get("summary"),
                    topics=json.dumps(news.get("topics", [])),
                    created_at=ts,
                )
                inner_db.add(n)
                news_added += 1

            inner_db.commit()

            dedupe_summary = dedupe_companies(inner_db)

            j = inner_db.query(ResearchJob).filter(ResearchJob.id == job_id).first()
            if j:
                j.status = "complete"
                j.result = json.dumps({
                    "companies_added": companies_added,
                    "news_added": news_added,
                    "dedupe": dedupe_summary,
                })
                j.updated_at = datetime.now(timezone.utc).isoformat()
                inner_db.commit()
        except Exception as e:
            log.error("Document extract job %d failed: %s", job_id, e)
            j = inner_db.query(ResearchJob).filter(ResearchJob.id == job_id).first()
            if j:
                j.status = "failed"
                j.result = str(e)
                j.updated_at = datetime.now(timezone.utc).isoformat()
                inner_db.commit()
        finally:
            inner_db.close()

    asyncio.create_task(_run()).add_done_callback(_log_task_error)
    return {"job_id": job_id, "filename": filename}



@router.post("/partnerships")
async def upload_partnerships(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Legacy PitchBook/Crunchbase endpoint — now first-column-only, same as
    ``/csv``. Kept so existing frontend buttons still work."""
    if not file.filename.endswith((".csv", ".xlsx")):
        raise HTTPException(400, "Only CSV or XLSX files are supported.")
    path = _save_file(file)
    try:
        names = read_first_column(path)
    except Exception as e:
        raise HTTPException(400, f"Failed to parse file: {e}")

    ts = datetime.now(timezone.utc).isoformat()
    ins = upsert_names(db, names, ts)
    db.commit()

    record_uploaded_names(names)

    dedupe_summary = dedupe_companies(db)
    prune_summary = prune_to_uploaded_names(db)

    # Kick off background AI enrichment for companies missing company_type.
    enrich_job = ResearchJob(
        job_type="pitchbook_enrich",
        status="pending",
        target=file.filename,
        created_at=ts,
        updated_at=ts,
    )
    db.add(enrich_job)
    db.commit()
    db.refresh(enrich_job)
    enrich_job_id = enrich_job.id
    asyncio.create_task(_enrich_companies_bg(enrich_job_id, ts)).add_done_callback(_log_task_error)

    return {
        "source": "First Column Ingest",
        "format": "first_column",
        "companies_added": ins["added"],
        "companies_updated": ins["updated"],
        "partnerships_added": 0,
        "names_in_file": len(names),
        "filename": file.filename,
        "enrich_job_id": enrich_job_id,
        "dedupe": dedupe_summary,
        "prune": prune_summary,
    }


# ── Background AI enrichment ────────────────────────────────────────────────

BATCH_SIZE = 20  # companies per Claude call


async def _enrich_companies_bg(job_id: int, ts: str):
    """Background task: classify company_type for companies missing it."""
    from backend.ai_research import classify_companies_batch
    from backend.database import SessionLocal

    db = SessionLocal()
    try:
        job = db.query(ResearchJob).filter(ResearchJob.id == job_id).first()
        if job:
            job.status = "running"
            job.updated_at = datetime.now(timezone.utc).isoformat()
            db.commit()

        # Find ALL companies that lack a company_type (any source)
        candidates = (
            db.query(Company)
            .filter(
                (Company.company_type == None) | (Company.company_type == ''),  # noqa: E711
                Company.company_name != INDEPENDENT_INVESTORS_NAME,
            )
            .all()
        )

        if not candidates:
            log.info("Enrich job %d: no companies need classification", job_id)
            job = db.query(ResearchJob).filter(ResearchJob.id == job_id).first()
            if job:
                job.status = "complete"
                job.result = json.dumps({"classified": 0})
                job.updated_at = datetime.now(timezone.utc).isoformat()
                db.commit()
            return

        log.info("Enrich job %d: classifying %d companies", job_id, len(candidates))
        classified_total = 0

        # Process in batches
        for i in range(0, len(candidates), BATCH_SIZE):
            batch = candidates[i:i + BATCH_SIZE]
            info = []
            for c in batch:
                entry = {'name': c.company_name}
                # Use summary or description for context
                desc = c.summary or c.long_description or c.description or ''
                if desc:
                    entry['description'] = desc
                # Use notes field where we stashed PitchBook industry info
                if c.notes:
                    entry['industry'] = c.notes
                info.append(entry)

            try:
                results = await asyncio.get_event_loop().run_in_executor(
                    None, classify_companies_batch, info,
                )
            except Exception as e:
                log.error("Enrich batch %d failed: %s", i, e)
                continue

            for c in batch:
                ctype = results.get(c.company_name)
                if ctype:
                    c.company_type = ctype
                    classified_total += 1

            db.commit()
            log.info("Enrich job %d: classified batch %d-%d (%d hits)",
                     job_id, i, i + len(batch), sum(1 for c in batch if results.get(c.company_name)))

        job = db.query(ResearchJob).filter(ResearchJob.id == job_id).first()
        if job:
            job.status = "complete"
            job.result = json.dumps({"classified": classified_total, "total_candidates": len(candidates)})
            job.updated_at = datetime.now(timezone.utc).isoformat()
            db.commit()

        log.info("Enrich job %d complete: classified %d / %d companies", job_id, classified_total, len(candidates))

    except Exception as e:
        log.error("Enrich job %d failed: %s", job_id, e)
        job = db.query(ResearchJob).filter(ResearchJob.id == job_id).first()
        if job:
            job.status = "failed"
            job.result = str(e)
            job.updated_at = datetime.now(timezone.utc).isoformat()
            db.commit()
    finally:
        db.close()
