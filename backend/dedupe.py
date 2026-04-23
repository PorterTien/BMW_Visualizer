"""Company deduplication.

After any import, two rows may exist for what is really the same company — e.g.
"Tesla" and "Tesla, Inc.", "LG Chem" and "LG Chem Ltd.", "QuantumScape" and
"QuantumScape Corp". This module normalizes names, merges the rows (filling the
survivor's empty fields from the loser, respecting manual_overrides), re-points
all dependent FKs, then deletes the loser.

Surviving-row choice: the row that looks the richest (most populated columns,
most recently updated). Ties break on the lower id so results are deterministic.
"""
from __future__ import annotations

import json
import logging
import re
from collections import defaultdict

from sqlalchemy.orm import Session

from backend.models import (
    Company,
    CompanyFacility,
    CompanyMetric,
    NewsHeadline,
    Partnership,
    PartnershipMember,
    WatchlistDigest,
    WatchlistEntry,
)

log = logging.getLogger(__name__)


# Corporate suffixes we'll strip for matching only. Conservative list — we skip
# words like "technologies", "holdings", "group" because they can legitimately
# distinguish companies ("Tesla" vs "Tesla Energy" are not the same org).
_SUFFIX_TOKENS = (
    "inc", "incorporated", "llc", "l.l.c", "corp", "corporation",
    "ltd", "limited", "plc", "sa", "s.a", "ag", "gmbh", "co",
    "bv", "b.v", "nv", "n.v", "srl", "spa", "s.p.a", "pte",
)
_SUFFIX_RE = re.compile(
    r"[\s,\.]+(?:" + "|".join(re.escape(s) for s in _SUFFIX_TOKENS) + r")\.?\s*$",
    re.IGNORECASE,
)
_PARENS_RE = re.compile(r"\([^)]*\)")
_PUNCT_RE = re.compile(r"[.,\-–—&/\\'\"“”‘’]+")
_WS_RE = re.compile(r"\s+")


def normalize_name(name: str | None) -> str:
    """Canonical key for duplicate matching. Empty string for unusable input.

    "Tesla, Inc." → "tesla"
    "LG Chem Ltd." → "lg chem"
    "QuantumScape Corp." → "quantumscape"
    "Acme (NAS: ACME)" → "acme"
    """
    if not name:
        return ""
    s = str(name).strip().lower()
    s = _PARENS_RE.sub(" ", s)
    # Strip chained suffixes: "Foo Holdings Co Ltd." → "foo holdings"
    for _ in range(3):
        new = _SUFFIX_RE.sub("", s).strip()
        if new == s:
            break
        s = new
    s = _PUNCT_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s


def _safe_json_list(val: str | None) -> list:
    if not val:
        return []
    try:
        parsed = json.loads(val)
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


# Columns we never copy during a merge.
_SKIP_MERGE_COLS = frozenset({"id", "company_name", "manual_overrides"})

# Fields that store 0/1 flags — treat 0 as "no info" and let a 1 from the loser win.
_FLAG_COLS = frozenset({"naatbatt_member", "volta_member", "volta_verified"})


def _retarget_foreign_keys(db: Session, winner_id: int, loser_id: int) -> None:
    """Move every child row from loser → winner, dropping rows that would
    violate an implicit uniqueness constraint on (parent, company_id)."""
    # NewsHeadline — no unique constraint, bulk update
    db.query(NewsHeadline).filter(NewsHeadline.company_id == loser_id).update(
        {NewsHeadline.company_id: winner_id}, synchronize_session=False
    )
    # CompanyFacility — no unique constraint, bulk update
    db.query(CompanyFacility).filter(CompanyFacility.company_id == loser_id).update(
        {CompanyFacility.company_id: winner_id}, synchronize_session=False
    )
    # CompanyMetric — no unique constraint, bulk update
    db.query(CompanyMetric).filter(CompanyMetric.company_id == loser_id).update(
        {CompanyMetric.company_id: winner_id}, synchronize_session=False
    )

    # WatchlistEntry — logically unique on (user_id, company_id); skip collisions
    winner_users = {
        e.user_id
        for e in db.query(WatchlistEntry).filter_by(company_id=winner_id).all()
    }
    for e in db.query(WatchlistEntry).filter_by(company_id=loser_id).all():
        if e.user_id in winner_users:
            db.delete(e)
        else:
            e.company_id = winner_id
            winner_users.add(e.user_id)

    # WatchlistDigest — logically unique on (company_id, run_date)
    winner_dates = {
        d.run_date
        for d in db.query(WatchlistDigest).filter_by(company_id=winner_id).all()
    }
    for d in db.query(WatchlistDigest).filter_by(company_id=loser_id).all():
        if d.run_date in winner_dates:
            db.delete(d)
        else:
            d.company_id = winner_id
            winner_dates.add(d.run_date)

    # PartnershipMember — logically unique on (partnership_id, company_id).
    # A partnership that had BOTH winner and loser as members loses a slot after
    # this; prune_degenerate_partnerships() below drops partnerships left with <2.
    winner_pships = {
        m.partnership_id
        for m in db.query(PartnershipMember).filter_by(company_id=winner_id).all()
    }
    for m in db.query(PartnershipMember).filter_by(company_id=loser_id).all():
        if m.partnership_id in winner_pships:
            db.delete(m)
        else:
            m.company_id = winner_id
            winner_pships.add(m.partnership_id)


def _non_null_score(c: Company) -> int:
    n = 0
    for col in Company.__table__.columns:
        if col.name in _SKIP_MERGE_COLS:
            continue
        v = getattr(c, col.name, None)
        if v is None or (isinstance(v, str) and not v.strip()):
            continue
        n += 1
    return n


def _pick_winner(group: list[Company]) -> Company:
    """Richest row wins; ties break on most recent last_updated, then lowest id."""
    return max(
        group,
        key=lambda c: (
            _non_null_score(c),
            c.last_updated or "",
            -c.id,
        ),
    )


def merge_companies(db: Session, winner: Company, loser: Company) -> None:
    """Fold `loser` into `winner` and delete it. No commit; caller commits."""
    if winner.id == loser.id:
        return

    winner_overrides = set(_safe_json_list(winner.manual_overrides))
    loser_overrides = set(_safe_json_list(loser.manual_overrides))

    for col in Company.__table__.columns:
        name = col.name
        if name in _SKIP_MERGE_COLS:
            continue
        # User explicitly set this on the winner — never clobber.
        if name in winner_overrides:
            continue

        wv = getattr(winner, name, None)
        lv = getattr(loser, name, None)

        if name in _FLAG_COLS:
            # 0/1 flag — take loser's 1 if winner is 0/None.
            if not wv and lv:
                setattr(winner, name, lv)
            continue

        w_empty = wv is None or (isinstance(wv, str) and not wv.strip())
        l_has = lv is not None and (not isinstance(lv, str) or lv.strip() != "")
        if w_empty and l_has:
            setattr(winner, name, lv)

    merged_overrides = sorted(winner_overrides | loser_overrides)
    winner.manual_overrides = json.dumps(merged_overrides) if merged_overrides else None

    _retarget_foreign_keys(db, winner_id=winner.id, loser_id=loser.id)

    db.flush()
    db.delete(loser)
    db.flush()


def prune_degenerate_partnerships(db: Session) -> int:
    """Delete partnerships left with fewer than 2 unique member companies after
    merges. Returns the count removed.

    Old version ran O(#partnerships) queries to fetch members; this pulls every
    (partnership_id, company_id) pair in a single SELECT, groups in memory, and
    deletes by id in two bulk statements."""
    pairs = db.query(
        PartnershipMember.partnership_id, PartnershipMember.company_id,
    ).all()
    members_by_pship: dict[int, set[int]] = {}
    for pid, cid in pairs:
        members_by_pship.setdefault(pid, set()).add(cid)

    # Partnerships with zero members don't appear in the pair list; include all.
    all_ids = {p_id for (p_id,) in db.query(Partnership.id).all()}
    degenerate_ids = [
        pid for pid in all_ids if len(members_by_pship.get(pid, set())) < 2
    ]
    if not degenerate_ids:
        return 0

    db.query(PartnershipMember).filter(
        PartnershipMember.partnership_id.in_(degenerate_ids),
    ).delete(synchronize_session=False)
    db.query(Partnership).filter(Partnership.id.in_(degenerate_ids)).delete(
        synchronize_session=False,
    )
    db.flush()
    return len(degenerate_ids)


def dedupe_companies(db: Session, commit: bool = True) -> dict:
    """Full-DB duplicate sweep. Returns a summary with counts.

    Safe to call repeatedly; a no-op on a clean DB.
    """
    all_companies = db.query(Company).all()
    groups: dict[str, list[Company]] = defaultdict(list)
    for c in all_companies:
        key = normalize_name(c.company_name)
        if key:
            groups[key].append(c)

    merged = 0
    groups_with_dupes = 0
    for key, group in groups.items():
        if len(group) < 2:
            continue
        groups_with_dupes += 1
        winner = _pick_winner(group)
        for loser in group:
            if loser.id == winner.id:
                continue
            log.info(
                "Dedupe: merging %r (id=%d) into %r (id=%d) [key=%r]",
                loser.company_name, loser.id, winner.company_name, winner.id, key,
            )
            merge_companies(db, winner, loser)
            merged += 1

    orphan_partnerships = prune_degenerate_partnerships(db) if merged else 0

    if commit:
        db.commit()

    return {
        "companies_scanned": len(all_companies),
        "duplicate_groups": groups_with_dupes,
        "companies_merged": merged,
        "orphan_partnerships_removed": orphan_partnerships,
    }
