"""Remove venture/investor rows from the `companies` table.

Rationale
---------
Uploads from PitchBook and BBD/NAATBATT lists occasionally leak in
VC firms, banks, asset-management holdcos, and spreadsheet header rows
(e.g. "Global total", "Year"). Those are not battery companies and
pollute the map, network, and table views.

Usage
-----
Programmatic:
    from backend.prune_investors import prune_investors, is_investor_row
    n = prune_investors(db)            # delete + cascade, returns count

CLI (dry run):
    python -m backend.prune_investors

CLI (delete):
    python -m backend.prune_investors --apply

Heuristics
----------
A row is treated as an investor if ANY of these hold AND it has no
positive battery signal (naatbatt_member / gwh_capacity / chemistries
/ linked facilities / a battery-industry `company_type`):
  1. data_source == 'pitchbook_investor'
  2. Name matches a VC/finance token (Ventures, Capital, Partners,
     Holdings, Advisors, Fund, Equity, Investments, VC, Asset
     Management, Private Equity, Angel Fund)
  3. The row appears in `partnership_members` exclusively as
     role='investor'.
  4. Spreadsheet header-row junk ("Global total", "Year").
"""
from __future__ import annotations

import re
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.models import (
    Company, CompanyFacility, CompanyMetric, NewsHeadline,
    Partnership, PartnershipMember, WatchlistEntry,
)

VC_TOKENS = re.compile(
    r'\b(ventures?|capital|partners|holdings?|advisors?|equity|'
    r'angel(s| fund)?|investments?|investors?|fund|vc|'
    r'asset management|private equity)\b',
    re.I,
)

# Battery-industry company_type values that *keep* a row regardless of name.
BATTERY_KEEP_TYPES = {
    'Battery Grade Materials', 'Distributors', 'EV OEM',
    'Electrode & Cell Manufacturing', 'Equipment', 'Modeling & Software',
    'Module-Pack Manufacturing', 'Other Battery Components & Mat.',
    'R&D', 'Raw Materials', 'Recycling-Repurposing',
    'cell supplier', 'equipment supplier', 'materials supplier',
    'modeling/software', 'prototyping partner', 'recycler', 'start-up',
    'testing partner',
}

HEADER_JUNK_NAMES = {'Global total', 'Year'}


def is_investor_name(name: str) -> bool:
    return bool(name and VC_TOKENS.search(name))


def _candidate_rows(db: Session):
    return db.execute(text("""
        SELECT c.id, c.company_name, c.company_type, c.data_source,
               c.naatbatt_member, c.gwh_capacity, c.chemistries,
               (SELECT COUNT(*) FROM partnership_members pm
                  WHERE pm.company_id=c.id) AS pm_count,
               (SELECT COUNT(*) FROM partnership_members pm
                  WHERE pm.company_id=c.id AND pm.role='investor') AS inv_count,
               (SELECT COUNT(*) FROM company_facilities f
                  WHERE f.company_id=c.id) AS fac_count
        FROM companies c
    """)).fetchall()


def find_investor_ids(db: Session) -> list[int]:
    """Return company IDs that the heuristics classify as investor/VC rows."""
    ids = []
    for r in _candidate_rows(db):
        battery_type = r.company_type in BATTERY_KEEP_TYPES
        has_battery_signal = bool(
            r.naatbatt_member or r.gwh_capacity
            or (r.chemistries and str(r.chemistries).strip())
            or r.fac_count
        )
        all_roles_investor = r.pm_count > 0 and r.pm_count == r.inv_count
        name_vc = is_investor_name(r.company_name)

        if (r.data_source == 'pitchbook_investor'
            or (name_vc and not battery_type and not has_battery_signal)
            or (all_roles_investor and not battery_type and not has_battery_signal)
            or r.company_name in HEADER_JUNK_NAMES):
            ids.append(r.id)
    return ids


def prune_investors(db: Session) -> dict:
    """Delete investor rows plus their dependent rows; commit.

    Also removes partnerships that end up with fewer than 2 members
    after their investor side is stripped out.
    """
    ids = find_investor_ids(db)
    if not ids:
        return {'deleted': 0, 'partnerships_pruned': 0}

    pm_q = db.query(PartnershipMember).filter(PartnershipMember.company_id.in_(ids))
    affected_partnerships = {pm.partnership_id for pm in pm_q.all()}
    pm_q.delete(synchronize_session=False)

    pruned = 0
    for pid in affected_partnerships:
        remaining = db.query(PartnershipMember).filter(
            PartnershipMember.partnership_id == pid).count()
        if remaining < 2:
            db.query(PartnershipMember).filter(
                PartnershipMember.partnership_id == pid).delete(synchronize_session=False)
            db.query(Partnership).filter(
                Partnership.id == pid).delete(synchronize_session=False)
            pruned += 1

    db.query(NewsHeadline).filter(NewsHeadline.company_id.in_(ids)).delete(synchronize_session=False)
    db.query(WatchlistEntry).filter(WatchlistEntry.company_id.in_(ids)).delete(synchronize_session=False)
    db.query(CompanyMetric).filter(CompanyMetric.company_id.in_(ids)).delete(synchronize_session=False)
    db.query(CompanyFacility).filter(CompanyFacility.company_id.in_(ids)).delete(synchronize_session=False)
    deleted = db.query(Company).filter(Company.id.in_(ids)).delete(synchronize_session=False)
    db.commit()
    return {'deleted': deleted, 'partnerships_pruned': pruned}


if __name__ == '__main__':
    import sys
    from backend.database import SessionLocal
    apply = '--apply' in sys.argv
    db = SessionLocal()
    try:
        if apply:
            result = prune_investors(db)
            print(f"Deleted {result['deleted']} investor companies; "
                  f"pruned {result['partnerships_pruned']} degenerate partnerships.")
        else:
            ids = find_investor_ids(db)
            print(f"DRY RUN: {len(ids)} companies would be deleted.")
            for cid in ids[:50]:
                c = db.query(Company).get(cid)
                print(f"  {cid:>5}  {c.company_name}  [{c.company_type} / {c.data_source}]")
            if len(ids) > 50:
                print(f"  ... {len(ids)-50} more")
            print("\nPass --apply to delete.")
    finally:
        db.close()
