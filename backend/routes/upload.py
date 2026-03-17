from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from backend.config import UPLOAD_DIR
from backend.database import get_db
from backend.models import Company, ConferenceProceeding, NewsHeadline, ResearchJob

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/upload", tags=["upload"])

os.makedirs(UPLOAD_DIR, exist_ok=True)


def _save_file(upload: UploadFile) -> str:
    dest = Path(UPLOAD_DIR) / upload.filename
    with open(dest, "wb") as f:
        f.write(upload.file.read())
    return str(dest)


@router.post("/csv")
async def upload_csv(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename.endswith((".csv", ".xlsx")):
        raise HTTPException(400, "Only CSV or XLSX files are supported.")
    path = _save_file(file)
    try:
        if file.filename.endswith(".csv"):
            df = pd.read_csv(path, dtype=str)
        else:
            df = pd.read_excel(path, dtype=str)
    except Exception as e:
        raise HTTPException(400, f"Failed to parse file: {e}")

    added = updated = 0
    ts = datetime.now(timezone.utc).isoformat()
    existing_map = {
        c.company_name.lower(): c
        for c in db.query(Company).all()
    }
    for _, row in df.iterrows():
        name = str(row.get("company_name", "")).strip()
        if not name:
            continue
        existing = existing_map.get(name.lower())
        data = {
            "company_name": name,
            "company_hq_city": row.get("company_hq_city") or None,
            "company_hq_state": row.get("company_hq_state") or None,
            "company_hq_country": row.get("company_hq_country") or None,
            "company_type": row.get("company_type") or None,
            "company_status": row.get("company_status") or None,
            "summary": row.get("summary") or None,
            "company_website": row.get("company_website") or None,
            "data_source": "file_upload",
            "last_updated": ts,
        }
        if existing:
            for k, v in data.items():
                if v is not None:
                    setattr(existing, k, v)
            updated += 1
        else:
            db.add(Company(**data))
            added += 1
    db.commit()
    return {"added": added, "updated": updated, "filename": file.filename}


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
            companies_added = news_added = procs_added = 0

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
                    file_path=path if hasattr(NewsHeadline, "file_path") else None,
                    created_at=ts,
                )
                inner_db.add(n)
                news_added += 1

            for proc in result.get("proceedings", []):
                name = proc.get("company_name", "")
                company = inner_db.query(Company).filter(
                    Company.company_name.ilike(name)
                ).first() if name else None
                p = ConferenceProceeding(
                    company_id=company.id if company else None,
                    company_name=name,
                    title=proc.get("title", filename),
                    event_name=proc.get("event_name"),
                    event_date=proc.get("event_date"),
                    location=proc.get("location"),
                    authors=json.dumps(proc.get("authors", [])),
                    technologies=json.dumps(proc.get("technologies", [])),
                    partners_mentioned=json.dumps(proc.get("partners_mentioned", [])),
                    results_summary=proc.get("results_summary"),
                    source_type=proc.get("source_type", "conference_paper"),
                    file_path=path,
                    topics=json.dumps(proc.get("topics", [])),
                    created_at=ts,
                )
                inner_db.add(p)
                procs_added += 1

            inner_db.commit()

            j = inner_db.query(ResearchJob).filter(ResearchJob.id == job_id).first()
            if j:
                j.status = "complete"
                j.result = json.dumps({
                    "companies_added": companies_added,
                    "news_added": news_added,
                    "proceedings_added": procs_added,
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

    asyncio.create_task(_run())
    return {"job_id": job_id, "filename": filename}


# ─── PitchBook / Crunchbase partnership import ────────────────────────────────

def _parse_money_millions(val) -> float | None:
    if not val:
        return None
    s = str(val).strip().replace(',', '').replace('$', '').replace(' ', '')
    if s in ('', '-', 'N/A', 'nan', 'NaN', 'None', 'n/a'):
        return None
    mult = 1.0
    if s.upper().endswith('B'):
        mult = 1000.0
        s = s[:-1]
    elif s.upper().endswith('M'):
        mult = 1.0
        s = s[:-1]
    elif s.upper().endswith('K'):
        mult = 0.001
        s = s[:-1]
    try:
        raw = float(s)
        if mult == 1.0 and raw > 1_000_000:
            raw /= 1_000_000
        return round(raw * mult, 2)
    except (ValueError, TypeError):
        return None


def _parse_employees(val) -> int | None:
    if not val:
        return None
    s = str(val).strip().replace(',', '').replace('+', '')
    if s in ('', '-', 'N/A', 'nan'):
        return None
    # Handle ranges like "100-250" or "100 to 250"
    m = re.match(r'(\d+)\s*(?:-|to)\s*(\d+)', s)
    if m:
        return int((int(m.group(1)) + int(m.group(2))) / 2)
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None


def _parse_hq(loc: str) -> tuple:
    if not loc or str(loc).strip() in ('', 'nan', 'None'):
        return None, None, None
    parts = [p.strip() for p in str(loc).split(',') if p.strip()]
    if len(parts) >= 3:
        return parts[0], parts[1], parts[-1]
    elif len(parts) == 2:
        return parts[0], None, parts[1]
    elif len(parts) == 1:
        return None, None, parts[0]
    return None, None, None


def _col(row, *names) -> str | None:
    for name in names:
        val = row.get(name)
        if val and str(val).strip() not in ('', 'nan', 'None', 'NaN', '-', 'n/a', 'N/A'):
            return str(val).strip()
    return None


def _upsert_company(db, name: str, data: dict, ts: str) -> Company:
    company = db.query(Company).filter(Company.company_name.ilike(name)).first()
    data['last_updated'] = ts
    valid_cols = set(Company.__table__.columns.keys())
    if company:
        for k, v in data.items():
            if v is not None and k in valid_cols:
                setattr(company, k, v)
    else:
        safe = {k: v for k, v in data.items() if k in valid_cols and v is not None}
        company = Company(company_name=name, **safe)
        db.add(company)
        db.flush()
    return company


def _add_partner(company: Company, partner_name: str, ptype: str, scale: str | None, date: str | None):
    existing = []
    if company.announced_partners:
        try:
            existing = json.loads(company.announced_partners)
        except Exception:
            existing = []
    key = (partner_name.lower(), ptype.lower())
    for e in existing:
        if (e.get('partner_name', '').lower(), e.get('type_of_partnership', '').lower()) == key:
            return
    existing.append({
        'partner_name': partner_name,
        'type_of_partnership': ptype,
        'scale': scale or '',
        'date': date or '',
    })
    company.announced_partners = json.dumps(existing)


def _has_col(cols: set, *keywords) -> bool:
    cols_lower = {c.lower() for c in cols}
    return any(any(kw in c for c in cols_lower) for kw in keywords)


DEAL_TYPE_MAP = {
    'joint venture': 'Joint Venture',
    'off-take': 'Off-take',
    'offtake': 'Off-take',
    'supply': 'Supply Agreement',
    'mou': 'MOU',
    'strategic': 'MOU',
    'partnership': 'MOU',
    'merger': 'Other',
    'acquisition': 'Other',
    'buyout': 'Other',
}


def _map_deal_type(raw: str | None) -> str:
    if not raw:
        return 'Investment'
    lower = raw.lower()
    for key, val in DEAL_TYPE_MAP.items():
        if key in lower:
            return val
    return 'Investment'


def _scale_label(val_millions: float | None) -> str | None:
    if not val_millions:
        return None
    if val_millions >= 1000:
        return f"${val_millions / 1000:.1f}B"
    return f"${val_millions:,.0f}M"


def _split_investors(raw: str) -> list[str]:
    sep = ';' if ';' in raw else ','
    return [i.strip() for i in raw.split(sep) if i.strip()]


# ── Format detection ──────────────────────────────────────────────────────────

def _detect_format(cols: set) -> str | None:
    lc = {c.lower() for c in cols}
    has = lambda *kw: any(any(k in c for c in lc) for k in kw)
    has_exact = lambda *kw: any(k in lc for k in kw)

    if has_exact('organization name') and has('money raised', 'announced date') and has('funding type'):
        return 'crunchbase_rounds'
    if has_exact('organization name') and has('total funding', 'last funding', 'last financing'):
        return 'crunchbase_orgs'
    if has('deal date', 'deal type') and has('investors', 'deal size'):
        return 'pitchbook_deals'
    if has('total raised', 'post-money valuation', 'last financing', 'total capital raised'):
        return 'pitchbook_companies'
    return None


# ── PitchBook company list ────────────────────────────────────────────────────

def _import_pitchbook_companies(df: pd.DataFrame, db, ts: str) -> dict:
    added = updated = 0
    for _, row in df.iterrows():
        name = _col(row, 'Company Name', 'Company')
        if not name:
            continue
        hq_raw = _col(row, 'HQ Location', 'Headquarters Location', 'Location', 'HQ')
        city, state, country = _parse_hq(hq_raw) if hq_raw else (None, None, None)
        city = _col(row, 'HQ City', 'City') or city
        state = _col(row, 'HQ State', 'State', 'Region') or state
        country = _col(row, 'HQ Country', 'Country') or country

        existed = db.query(Company).filter(Company.company_name.ilike(name)).first() is not None
        _upsert_company(db, name, {
            'company_hq_city': city,
            'company_hq_state': state,
            'company_hq_country': country,
            'summary': _col(row, 'Business Description', 'Description', 'Company Description'),
            'company_website': _col(row, 'Website', 'Company Website', 'URL'),
            'last_fundraise_date': _col(row, 'Last Financing Date', 'Last Funding Date'),
            'total_funding_usd': _parse_money_millions(_col(row, 'Total Raised (USD)', 'Total Capital Raised (USD)', 'Total Raised', 'Total Funding')),
            'market_cap_usd': _parse_money_millions(_col(row, 'Post-Money Valuation (USD)', 'Post Money Valuation', 'Valuation')),
            'number_of_employees': _parse_employees(_col(row, 'Number of Employees', 'Employees', 'Employee Count')),
            'data_source': 'pitchbook',
        }, ts)
        if existed:
            updated += 1
        else:
            added += 1
    return {'companies_added': added, 'companies_updated': updated, 'partnerships_added': 0}


# ── PitchBook deals ───────────────────────────────────────────────────────────

def _import_pitchbook_deals(df: pd.DataFrame, db, ts: str) -> dict:
    companies_added = partnerships = 0
    for _, row in df.iterrows():
        name = _col(row, 'Company Name', 'Company')
        if not name:
            continue
        ptype = _map_deal_type(_col(row, 'Deal Type', 'Round'))
        date = _col(row, 'Deal Date', 'Close Date', 'Announced Date')
        scale = _scale_label(_parse_money_millions(_col(row, 'Deal Size (USD)', 'Deal Size', 'Amount (USD)', 'Amount')))

        existed = db.query(Company).filter(Company.company_name.ilike(name)).first() is not None
        company = _upsert_company(db, name, {'data_source': 'pitchbook'}, ts)
        if not existed:
            companies_added += 1

        if date and not company.last_fundraise_date:
            company.last_fundraise_date = date

        investors_raw = _col(row, 'Investors', 'Lead Investors', 'Investor(s)', 'All Investors')
        if investors_raw:
            for investor in _split_investors(investors_raw):
                _add_partner(company, investor, ptype, scale, date)
                partnerships += 1
    return {'companies_added': companies_added, 'companies_updated': 0, 'partnerships_added': partnerships}


# ── Crunchbase organizations ──────────────────────────────────────────────────

def _import_crunchbase_orgs(df: pd.DataFrame, db, ts: str) -> dict:
    added = updated = 0
    for _, row in df.iterrows():
        name = _col(row, 'Organization Name', 'Name')
        if not name:
            continue
        hq = _col(row, 'Headquarters Location', 'HQ Location', 'Location')
        city, state, country = _parse_hq(hq) if hq else (None, None, None)
        city = _col(row, 'City') or city
        state = _col(row, 'State', 'Region') or state
        country = _col(row, 'Country', 'Country Code') or country

        existed = db.query(Company).filter(Company.company_name.ilike(name)).first() is not None
        _upsert_company(db, name, {
            'company_hq_city': city,
            'company_hq_state': state,
            'company_hq_country': country,
            'summary': _col(row, 'Short Description', 'Description'),
            'company_website': _col(row, 'Website', 'Homepage URL'),
            'last_fundraise_date': _col(row, 'Last Funding Date', 'Last Funding Round Date'),
            'total_funding_usd': _parse_money_millions(_col(row, 'Total Funding Amount (in USD)', 'Total Funding Amount Currency (in USD)', 'Total Funding Amount', 'Total Raised')),
            'number_of_employees': _parse_employees(_col(row, 'Number of Employees', 'Employees')),
            'data_source': 'crunchbase',
        }, ts)
        if existed:
            updated += 1
        else:
            added += 1
    return {'companies_added': added, 'companies_updated': updated, 'partnerships_added': 0}


# ── Crunchbase funding rounds ─────────────────────────────────────────────────

def _import_crunchbase_rounds(df: pd.DataFrame, db, ts: str) -> dict:
    companies_added = partnerships = 0
    for _, row in df.iterrows():
        name = _col(row, 'Organization Name', 'Company')
        if not name:
            continue
        ptype = _map_deal_type(_col(row, 'Funding Type', 'Round'))
        date = _col(row, 'Announced Date', 'Close Date', 'Date')
        scale = _scale_label(_parse_money_millions(_col(row, 'Money Raised (in USD)', 'Money Raised Currency (in USD)', 'Money Raised', 'Amount (in USD)', 'Amount')))

        existed = db.query(Company).filter(Company.company_name.ilike(name)).first() is not None
        company = _upsert_company(db, name, {'data_source': 'crunchbase'}, ts)
        if not existed:
            companies_added += 1

        investors: set[str] = set()
        for col_name in ('Lead Investors', 'Investors', 'Investor Names'):
            raw = _col(row, col_name)
            if raw:
                investors.update(_split_investors(raw))
        for investor in investors:
            _add_partner(company, investor, ptype, scale, date)
            partnerships += 1
    return {'companies_added': companies_added, 'companies_updated': 0, 'partnerships_added': partnerships}


@router.post("/partnerships")
async def upload_partnerships(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Import company + partnership data from PitchBook or Crunchbase CSV/XLSX exports."""
    if not file.filename.endswith((".csv", ".xlsx")):
        raise HTTPException(400, "Only CSV or XLSX files are supported.")
    path = _save_file(file)
    try:
        df = pd.read_csv(path, dtype=str) if file.filename.endswith(".csv") else pd.read_excel(path, dtype=str)
    except Exception as e:
        raise HTTPException(400, f"Failed to parse file: {e}")

    df.columns = [str(c).strip() for c in df.columns]
    fmt = _detect_format(set(df.columns))
    if not fmt:
        raise HTTPException(
            400,
            "Format not recognized. Supported exports: "
            "PitchBook company list, PitchBook deals, "
            "Crunchbase organizations, Crunchbase funding rounds."
        )

    ts = datetime.now(timezone.utc).isoformat()
    IMPORTERS = {
        'pitchbook_companies': _import_pitchbook_companies,
        'pitchbook_deals': _import_pitchbook_deals,
        'crunchbase_orgs': _import_crunchbase_orgs,
        'crunchbase_rounds': _import_crunchbase_rounds,
    }
    result = IMPORTERS[fmt](df, db, ts)
    db.commit()

    SOURCE_LABELS = {
        'pitchbook_companies': 'PitchBook — Company List',
        'pitchbook_deals': 'PitchBook — Deals',
        'crunchbase_orgs': 'Crunchbase — Organizations',
        'crunchbase_rounds': 'Crunchbase — Funding Rounds',
    }
    log.info("Partnership import (%s): %s", fmt, result)
    return {"source": SOURCE_LABELS[fmt], "format": fmt, **result, "filename": file.filename}
