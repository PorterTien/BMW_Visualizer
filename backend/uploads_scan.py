"""First-column-only ingest + DB pruning.

The user's contract: every CSV/XLSX upload is a flat list of company names
(column A only). The set of names ever accepted by an upload is persisted in
a manifest (``uploads/.uploaded_company_names.json``). Pruning uses the
manifest to delete any Company row whose normalized name isn't in it — so
the table mirrors the union of column A from every file the user has
uploaded through the new endpoints.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy.orm import Session, load_only

from backend.config import UPLOAD_DIR
from backend.dedupe import normalize_name, prune_degenerate_partnerships
from backend.models import Company
from backend.prune_investors import is_investor_name

log = logging.getLogger(__name__)

_MANIFEST_PATH = Path(UPLOAD_DIR) / ".uploaded_company_names.json"

# Column-A cells that look like headers, not companies. Normalized form.
_HEADER_TOKENS = frozenset({
    "company", "companies", "company name", "organization", "organization name",
    "name", "firm", "firms", "issuer", "issuer name", "target", "target name",
    "account", "account name", "deal id",
})


def read_first_column(path: str | Path) -> list[str]:
    """Return the trimmed, non-empty cell values of column A in ``path``.

    Filters out obvious non-company cells: empty strings, nan/null sentinels,
    headers, and strings longer than 120 chars (export metadata blurbs).
    """
    import pandas as pd

    p = Path(path)
    if p.suffix.lower() == ".csv":
        df = pd.read_csv(p, header=None, dtype=str, usecols=[0])
    else:
        df = pd.read_excel(p, header=None, dtype=str, usecols=[0])

    out: list[str] = []
    for val in df.iloc[:, 0].tolist():
        if val is None:
            continue
        s = str(val).strip()
        if not s or s.lower() in ("nan", "none", "null", "-", "n/a"):
            continue
        if len(s) > 120 or s.lower() in _HEADER_TOKENS:
            continue
        # Skip VC / investor / holdco rows — they pollute the battery-company
        # table. See backend/prune_investors.py for the matching heuristic
        # and the rerunnable cleanup.
        if is_investor_name(s):
            continue
        out.append(s)
    return out


# ── Manifest of accepted names ───────────────────────────────────────────────

def _load_manifest() -> set[str]:
    if not _MANIFEST_PATH.exists():
        return set()
    try:
        raw = json.loads(_MANIFEST_PATH.read_text())
        if isinstance(raw, list):
            return {str(k) for k in raw}
    except (json.JSONDecodeError, OSError) as e:
        log.warning("uploads_scan: manifest unreadable (%s), treating as empty", e)
    return set()


def _save_manifest(keys: set[str]) -> None:
    _MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    _MANIFEST_PATH.write_text(json.dumps(sorted(keys), indent=2))


def record_uploaded_names(names: list[str]) -> int:
    """Add every normalized name in ``names`` to the manifest. Returns the
    number of newly-added keys (ignores duplicates)."""
    existing = _load_manifest()
    before = len(existing)
    for raw in names:
        k = normalize_name(raw)
        if k:
            existing.add(k)
    _save_manifest(existing)
    return len(existing) - before


# ── Upload helpers ───────────────────────────────────────────────────────────

def upsert_names(db: Session, names: list[str], ts: str) -> dict:
    """Insert a Company row for every new entry in ``names``; touch
    ``last_updated`` on rows that already exist. Only ``company_name`` is
    written — no other columns."""
    if not names:
        return {"added": 0, "updated": 0}

    # Only pull id + company_name + last_updated — the other 50+ text columns
    # aren't used by this path and would balloon memory on large DBs.
    rows = (
        db.query(Company)
        .options(load_only(Company.id, Company.company_name, Company.last_updated))
        .all()
    )
    existing_by_key: dict[str, Company] = {normalize_name(c.company_name): c for c in rows}

    added = updated = 0
    seen_this_batch: set[str] = set()
    for raw in names:
        key = normalize_name(raw)
        if not key or key in seen_this_batch:
            continue
        seen_this_batch.add(key)
        existing = existing_by_key.get(key)
        if existing:
            existing.last_updated = ts
            updated += 1
        else:
            row = Company(
                company_name=str(raw).strip(),
                data_source="file_upload",
                last_updated=ts,
            )
            db.add(row)
            existing_by_key[key] = row
            added += 1
    db.flush()
    return {"added": added, "updated": updated}


# ── Pruning ──────────────────────────────────────────────────────────────────

def prune_to_uploaded_names(db: Session, commit: bool = True) -> dict:
    """Delete every Company whose normalized name isn't in the uploaded-names
    manifest. No-op (returns zeros) if the manifest is empty — we never wipe
    the table just because nothing's been uploaded yet through the new flow.
    """
    allowed = _load_manifest()
    if not allowed:
        return {
            "allowed_names": 0,
            "scanned_companies": 0,
            "deleted_companies": 0,
            "orphan_partnerships_removed": 0,
            "skipped": "manifest empty; upload a file first",
        }

    # id + name only — we delete by id, no need to hydrate full rows.
    rows = (
        db.query(Company.id, Company.company_name).all()
    )
    to_delete_ids = [cid for cid, cname in rows if normalize_name(cname) not in allowed]

    for cid in to_delete_ids:
        _drop_dependents(db, cid)
    if to_delete_ids:
        db.query(Company).filter(Company.id.in_(to_delete_ids)).delete(
            synchronize_session=False,
        )
        db.flush()

    orphan_partnerships = prune_degenerate_partnerships(db) if to_delete_ids else 0

    if commit:
        db.commit()

    return {
        "allowed_names": len(allowed),
        "scanned_companies": len(rows),
        "deleted_companies": len(to_delete_ids),
        "orphan_partnerships_removed": orphan_partnerships,
    }


def _drop_dependents(db: Session, company_id: int) -> None:
    """Remove rows that FK to ``company_id`` so the parent can be deleted."""
    from backend.models import (
        CompanyFacility,
        CompanyMetric,
        NewsHeadline,
        PartnershipMember,
        WatchlistDigest,
        WatchlistEntry,
    )

    for model in (
        NewsHeadline,
        CompanyFacility,
        CompanyMetric,
        WatchlistEntry,
        WatchlistDigest,
        PartnershipMember,
    ):
        db.query(model).filter(model.company_id == company_id).delete(
            synchronize_session=False,
        )
