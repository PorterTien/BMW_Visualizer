from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from backend.config import UPLOAD_DIR
from backend.database import get_db
from backend.models import Company, NewsHeadline, Partnership, PartnershipMember, ResearchJob

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
    if not file.filename.endswith((".csv", ".xlsx")):
        raise HTTPException(400, "Only CSV or XLSX files are supported.")
    path = _save_file(file)
    try:
        import pandas as pd

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

            j = inner_db.query(ResearchJob).filter(ResearchJob.id == job_id).first()
            if j:
                j.status = "complete"
                j.result = json.dumps({
                    "companies_added": companies_added,
                    "news_added": news_added,
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


LEGACY_TO_NEW_TYPE = {
    'Joint Venture': 'jv',
    'Investment': 'equity_stake',
    'MOU': 'r_and_d_collab',
    'Off-take': 'supply_agreement',
    'Supply Agreement': 'supply_agreement',
    'Other': 'other',
}

DIRECTION_FOR_TYPE = {
    'equity_stake': 'investor_to_investee',
    'supply_agreement': 'supplier_to_buyer',
    'jv': 'bidirectional',
    'r_and_d_collab': 'bidirectional',
    'other': 'bidirectional',
}


def _create_partnership_record(
    db, company: Company, partner_name: str, legacy_type: str,
    scale: str | None, date: str | None, source: str, ts: str,
):
    """Create a Partnership + PartnershipMember record in the new normalized tables."""
    new_type = LEGACY_TO_NEW_TYPE.get(legacy_type, 'other')
    direction = DIRECTION_FOR_TYPE.get(new_type, 'bidirectional')

    # Look up or create the partner company
    partner = db.query(Company).filter(Company.company_name.ilike(partner_name)).first()
    if not partner:
        partner = Company(company_name=partner_name, data_source=source, last_updated=ts)
        db.add(partner)
        db.flush()

    # Check for duplicate partnership
    existing = (
        db.query(Partnership)
        .join(PartnershipMember)
        .filter(
            Partnership.partnership_type == new_type,
            PartnershipMember.company_id.in_([company.id, partner.id]),
        )
        .all()
    )
    for ep in existing:
        member_ids = {m.company_id for m in ep.members}
        if company.id in member_ids and partner.id in member_ids:
            return  # Already exists

    deal_value = None
    if scale:
        try:
            cleaned = scale.replace('$', '').replace(',', '').strip()
            if cleaned.upper().endswith('B'):
                deal_value = float(cleaned[:-1]) * 1000
            elif cleaned.upper().endswith('M'):
                deal_value = float(cleaned[:-1])
        except (ValueError, TypeError):
            pass

    p = Partnership(
        partnership_name=f"{company.company_name} - {partner_name}",
        partnership_type=new_type,
        stage="active",
        direction=direction,
        date_announced=date,
        deal_value=deal_value,
        scope=scale,
        source_name=source,
        date_sourced=ts,
        created_at=ts,
        updated_at=ts,
    )
    db.add(p)
    db.flush()

    # Determine roles
    if direction == 'investor_to_investee':
        db.add(PartnershipMember(partnership_id=p.id, company_id=partner.id, role='investor'))
        db.add(PartnershipMember(partnership_id=p.id, company_id=company.id, role='investee'))
    elif direction == 'supplier_to_buyer':
        db.add(PartnershipMember(partnership_id=p.id, company_id=partner.id, role='supplier'))
        db.add(PartnershipMember(partnership_id=p.id, company_id=company.id, role='buyer'))
    else:
        db.add(PartnershipMember(partnership_id=p.id, company_id=company.id, role='partner'))
        db.add(PartnershipMember(partnership_id=p.id, company_id=partner.id, role='partner'))


def _has_col(cols: set, *keywords) -> bool:
    cols_lower = {c.lower() for c in cols}
    return any(any(kw in c for c in cols_lower) for kw in keywords)


def _clean_company_name(name: str) -> str:
    """Strip stock ticker suffixes like '(NAS: TSLA)' from PitchBook company names."""
    if not name:
        return name
    return re.sub(r'\s*\([A-Z]{2,5}:\s*[A-Z0-9.]+\)\s*$', '', name).strip()


def _clean_hyperlink(val: str) -> str:
    """Extract URL from Excel =HYPERLINK() formula."""
    if not val:
        return val
    m = re.match(r'=HYPERLINK\("([^"]+)"', str(val))
    return m.group(1) if m else str(val)


INDEPENDENT_INVESTORS_NAME = 'Independent Investors'

COMPANY_WORDS = frozenset({
    'inc', 'llc', 'corp', 'corporation', 'ltd', 'plc', 'sa', 'ag', 'gmbh', 'co',
    'capital', 'ventures', 'partners', 'group', 'holdings', 'management',
    'fund', 'advisors', 'investments', 'associates', 'bank', 'financial',
    'energy', 'technologies', 'technology', 'motors', 'industries',
    'enterprises', 'commission', 'platform', 'cloud', 'solutions',
    'services', 'systems', 'labs', 'laboratories', 'institute',
    'university', 'foundation', 'company', 'global', 'network',
})


def _is_individual_investor(raw_name: str) -> tuple[bool, str]:
    """Detect individual (person) investors. Returns (is_individual, clean_name).

    Conservative — only catches clear cases to avoid grouping real companies.
    """
    stripped = raw_name.strip()

    # Definite: "Bill Lee(Bill Lee)" — person name repeated in parens
    m = re.match(r'^(.+?)\(\1\)$', stripped)
    if m:
        return True, m.group(1).strip()

    # Has stock ticker → definitely a company
    if re.search(r'\([A-Z]{2,5}:\s*[A-Z0-9.]+\)', stripped):
        return False, stripped

    # Has parenthetical (like "Firm(Person)") → treat as company
    if '(' in stripped:
        return False, stripped

    # Simple 2-word name with no company indicators → likely a person
    words = stripped.split()
    if len(words) != 2:
        return False, stripped

    if {w.lower() for w in words} & COMPANY_WORDS:
        return False, stripped

    if all(w[0].isupper() and w.isalpha() for w in words):
        return True, stripped

    return False, stripped


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
    # Reject if any column name is suspiciously long — that means we're reading
    # a metadata/search-criteria row, not a real header row.
    if any(len(str(c)) > 80 for c in cols):
        return None

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
        name = _col(row, 'Company Name', 'Company', 'Companies')
        if not name:
            continue
        name = _clean_company_name(name)
        hq_raw = _col(row, 'HQ Location', 'Headquarters Location', 'Location', 'HQ')
        city, state, country = _parse_hq(hq_raw) if hq_raw else (None, None, None)
        city = _col(row, 'Company City', 'HQ City', 'City') or city
        state = _col(row, 'Company State/Province', 'HQ State', 'State', 'Region') or state
        country = _col(row, 'Company Country/Territory/Region', 'HQ Country', 'Country') or country

        website = _col(row, 'Company Website', 'Website', 'URL')
        if website:
            website = _clean_hyperlink(website)

        existed = db.query(Company).filter(Company.company_name.ilike(name)).first() is not None
        _upsert_company(db, name, {
            'company_hq_city': city,
            'company_hq_state': state,
            'company_hq_country': country,
            'summary': _col(row, 'Description', 'Business Description', 'Company Description'),
            'company_website': website,
            'last_fundraise_date': _col(row, 'Last Financing Date', 'Last Funding Date'),
            'total_funding_usd': _parse_money_millions(_col(row, 'Total Raised (USD)', 'Total Capital Raised (USD)', 'Total Raised', 'Total Funding', 'Raised to Date')),
            'market_cap_usd': _parse_money_millions(_col(row, 'Post-Money Valuation (USD)', 'Post Money Valuation', 'Post Valuation', 'Valuation')),
            'number_of_employees': _parse_employees(_col(row, 'Current Employees', 'Number of Employees', 'Employees', 'Employee Count')),
            'data_source': 'pitchbook',
        }, ts)
        if existed:
            updated += 1
        else:
            added += 1
    return {'companies_added': added, 'companies_updated': updated, 'partnerships_added': 0}


# ── PitchBook deals ───────────────────────────────────────────────────────────

def _extract_jv_partners(raw_name: str) -> list[str]:
    """Extract partner names from 'Joint Venture (A / B)' or 'Company (A / B)' patterns."""
    m = re.search(r'\(([^)]+)\)', raw_name)
    if not m:
        return []
    inner = m.group(1)
    if '/' not in inner:
        return []
    parts = [p.strip() for p in inner.split('/') if p.strip()]
    return parts if len(parts) >= 2 else []


def _import_pitchbook_deals(df: pd.DataFrame, db, ts: str) -> dict:
    """
    3-flush bulk import strategy:
      1. Parse entire file → collect all company data + partnership edges in memory
      2. Flush 1: bulk-add all new Company rows → get their IDs
      3. Flush 2: bulk-add all Partnership rows → get their IDs
      4. Flush 3: bulk-add all PartnershipMember rows
    Network round-trips: 2 preload SELECTs + 3 flushes, regardless of file size.
    """
    valid_company_cols = set(Company.__table__.columns.keys())

    # ── Pass 1: preload existing data ──────────────────────────────────────────
    company_cache: dict[str, Company] = {
        c.company_name.lower(): c for c in db.query(Company).all()
    }
    existing_pairs: set[tuple] = set()
    for p in db.query(Partnership).all():
        ids = tuple(sorted(m.company_id for m in p.members))
        existing_pairs.add((ids, p.partnership_type))

    companies_added_before = len(company_cache)

    # ── Pass 2: parse the entire file in Python, no DB calls ──────────────────
    # pending_companies: name → best-known data dict (merges across rows)
    pending_companies: dict[str, dict] = {}
    # pending_updates: existing companies that need field updates
    pending_updates: list[tuple[Company, dict]] = []
    # edges: list of (name_a, name_b, legacy_type, scale, date, deal_val)
    edges: list[tuple] = []
    individuals_grouped = 0

    def touch_company(name: str, data: dict):
        key = name.lower()
        if key in company_cache:
            pending_updates.append((company_cache[key], data))
        else:
            existing = pending_companies.get(key, {})
            # Merge: only fill in fields not yet seen
            merged = {k: v for k, v in data.items() if v is not None}
            existing.update({k: v for k, v in merged.items() if k not in existing})
            pending_companies[key] = existing

    for _, row in df.iterrows():
        raw_company_col = _col(row, 'Company Name', 'Company', 'Companies')
        if not raw_company_col:
            continue
        name = _clean_company_name(raw_company_col)

        deal_type_raw = _col(row, 'Deal Type', 'Deal Type 2', 'Round') or ''
        ptype = _map_deal_type(deal_type_raw)
        date = _col(row, 'Deal Date', 'Close Date', 'Announced Date')
        deal_val = _parse_money_millions(_col(row, 'Deal Size (USD)', 'Deal Size', 'Amount (USD)', 'Amount'))
        scale = _scale_label(deal_val)

        hq_raw = _col(row, 'HQ Location', 'Headquarters Location')
        city, state, country = _parse_hq(hq_raw) if hq_raw else (None, None, None)
        city    = _col(row, 'Company City', 'HQ City', 'City') or city
        state   = _col(row, 'Company State/Province', 'HQ State', 'State') or state
        country = _col(row, 'Company Country/Territory/Region', 'HQ Country', 'Country') or country
        website = _col(row, 'Company Website', 'Website', 'URL')
        if website:
            website = _clean_hyperlink(website)
        pb_industry = ' / '.join(filter(None, [
            _col(row, 'Primary PitchBook Industry Sector'),
            _col(row, 'Primary PitchBook Industry Group'),
            _col(row, 'Primary PitchBook Industry Code'),
        ]))

        touch_company(name, {
            'company_hq_city': city, 'company_hq_state': state,
            'company_hq_country': country,
            'summary': _col(row, 'Description', 'Business Description', 'Company Description'),
            'company_website': website,
            'number_of_employees': _parse_employees(
                _col(row, 'Current Employees', 'Employees', 'Number of Employees')),
            'last_fundraise_date': date,
            'data_source': 'pitchbook',
            'notes': pb_industry or None,
        })

        investors_raw = _col(row, 'Investors', 'Lead/Sole Investors', 'Lead Investors',
                             'Investor(s)', 'All Investors')
        if investors_raw:
            for raw_investor in _split_investors(investors_raw):
                is_individual, person_name = _is_individual_investor(raw_investor)
                inv_name = INDEPENDENT_INVESTORS_NAME if is_individual else _clean_company_name(raw_investor)
                inv_scale = (f"{person_name}" + (f" — {scale}" if scale else "")) if is_individual else scale
                if is_individual:
                    individuals_grouped += 1
                touch_company(inv_name, {'data_source': 'pitchbook'})
                edges.append((name, inv_name, ptype, inv_scale, date, deal_val))

        if 'joint venture' in deal_type_raw.lower():
            jv = _extract_jv_partners(raw_company_col)
            for i, pa in enumerate(jv):
                pa_clean = _clean_company_name(pa)
                touch_company(pa_clean, {'data_source': 'pitchbook'})
                for pb in jv[i + 1:]:
                    pb_clean = _clean_company_name(pb)
                    touch_company(pb_clean, {'data_source': 'pitchbook'})
                    edges.append((pa_clean, pb_clean, 'Joint Venture', scale, date, deal_val))

    # ── Flush 1: insert all new companies at once ──────────────────────────────
    for key, data in pending_companies.items():
        safe = {k: v for k, v in data.items() if v is not None and k in valid_company_cols}
        co = Company(company_name=safe.pop('company_name', key), last_updated=ts, **safe)
        db.add(co)
        company_cache[key] = co

    # Apply updates to existing companies
    for co, data in pending_updates:
        for k, v in data.items():
            if v is not None and k in valid_company_cols and not getattr(co, k, None):
                setattr(co, k, v)
        co.last_updated = ts

    db.flush()  # ← Flush 1: assigns IDs to all new Company rows

    # ── Flush 2: insert all Partnership rows ───────────────────────────────────
    partnership_objs: list[tuple[Partnership, str, str, str]] = []  # (p, id_a, id_b, direction)
    partnerships = 0

    for name_a, name_b, legacy_type, scale, date, deal_val in edges:
        co_a = company_cache.get(name_a.lower())
        co_b = company_cache.get(name_b.lower())
        if not co_a or not co_b:
            continue
        new_type = LEGACY_TO_NEW_TYPE.get(legacy_type, 'other')
        ids = tuple(sorted([co_a.id, co_b.id]))
        if (ids, new_type) in existing_pairs:
            continue
        existing_pairs.add((ids, new_type))

        # Update announced_partners on both companies
        _add_partner(co_a, name_b, legacy_type, scale, date)
        _add_partner(co_b, name_a, legacy_type, scale, date)

        direction = DIRECTION_FOR_TYPE.get(new_type, 'bidirectional')
        deal_value_f = None
        if deal_val:
            deal_value_f = float(deal_val)

        p = Partnership(
            partnership_name=f"{co_a.company_name} — {co_b.company_name}",
            partnership_type=new_type,
            stage="active",
            direction=direction,
            date_announced=date,
            deal_value=deal_value_f,
            scope=scale,
            source_name='pitchbook',
            date_sourced=ts,
            created_at=ts,
            updated_at=ts,
        )
        db.add(p)
        partnership_objs.append((p, co_a.id, co_b.id, direction))
        partnerships += 1

    db.flush()  # ← Flush 2: assigns IDs to all new Partnership rows

    # ── Flush 3: insert all PartnershipMember rows ─────────────────────────────
    for p, id_a, id_b, direction in partnership_objs:
        if direction == 'investor_to_investee':
            db.add(PartnershipMember(partnership_id=p.id, company_id=id_b, role='investor'))
            db.add(PartnershipMember(partnership_id=p.id, company_id=id_a, role='investee'))
        elif direction == 'supplier_to_buyer':
            db.add(PartnershipMember(partnership_id=p.id, company_id=id_b, role='supplier'))
            db.add(PartnershipMember(partnership_id=p.id, company_id=id_a, role='buyer'))
        else:
            db.add(PartnershipMember(partnership_id=p.id, company_id=id_a, role='partner'))
            db.add(PartnershipMember(partnership_id=p.id, company_id=id_b, role='partner'))

    db.flush()  # ← Flush 3: insert all members

    companies_added = len(company_cache) - companies_added_before
    log.info("PitchBook deals: %d individuals grouped under '%s'", individuals_grouped, INDEPENDENT_INVESTORS_NAME)
    return {
        'companies_added': companies_added, 'companies_updated': len(pending_updates),
        'partnerships_added': partnerships, 'individuals_grouped': individuals_grouped,
    }


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
            _create_partnership_record(db, company, investor, ptype, scale, date, 'crunchbase', ts)
            partnerships += 1
    return {'companies_added': companies_added, 'companies_updated': 0, 'partnerships_added': partnerships}


@router.post("/partnerships")
async def upload_partnerships(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Import company + partnership data from PitchBook or Crunchbase CSV/XLSX exports."""
    if not file.filename.endswith((".csv", ".xlsx")):
        raise HTTPException(400, "Only CSV or XLSX files are supported.")
    path = _save_file(file)
    try:
        import pandas as pd

        if file.filename.endswith(".csv"):
            df = pd.read_csv(path, dtype=str)
            df.columns = [str(c).strip() for c in df.columns]
            fmt = _detect_format(set(df.columns))
        else:
            # Read once into memory as raw (no header), then find the real header
            # row by scanning in-memory — avoids re-reading the file up to 15 times.
            raw = pd.read_excel(path, header=None, dtype=str)
            df, fmt = None, None
            for hr in range(min(15, len(raw))):
                candidate_cols = [str(v).strip() for v in raw.iloc[hr].values]
                candidate_fmt = _detect_format(set(candidate_cols))
                if candidate_fmt:
                    df = raw.iloc[hr + 1:].copy()
                    df.columns = candidate_cols
                    df = df.reset_index(drop=True)
                    fmt = candidate_fmt
                    log.info("Detected header at row %d (format: %s)", hr, fmt)
                    break
            if df is None:
                df = raw
                df.columns = [str(c).strip() for c in df.columns]
    except Exception as e:
        raise HTTPException(400, f"Failed to parse file: {e}")

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

    # Kick off background AI enrichment for companies missing company_type
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

    SOURCE_LABELS = {
        'pitchbook_companies': 'PitchBook — Company List',
        'pitchbook_deals': 'PitchBook — Deals',
        'crunchbase_orgs': 'Crunchbase — Organizations',
        'crunchbase_rounds': 'Crunchbase — Funding Rounds',
    }
    log.info("Partnership import (%s): %s", fmt, result)
    return {
        "source": SOURCE_LABELS[fmt], "format": fmt,
        **result, "filename": file.filename,
        "enrich_job_id": enrich_job_id,
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
