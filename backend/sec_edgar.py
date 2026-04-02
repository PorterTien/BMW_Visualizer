"""
SEC EDGAR enrichment module.
Looks up public battery companies and pulls revenue, net income, total assets
from XBRL filings. No API key needed — just a User-Agent header.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

import httpx

from backend.database import SessionLocal, init_db
from backend.models import Company, SyncLog

log = logging.getLogger(__name__)

HEADERS = {"User-Agent": "BMW-Battery-Intel/1.0 (portertien@example.com)"}
RATE_LIMIT = 0.12  # ~8 req/sec to stay under 10/sec limit

# Company search (by name → CIK)
SEARCH_URL = "https://efts.sec.gov/LATEST/search-index?q={query}&dateRange=custom&startdt=2020-01-01&forms=10-K"
COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

# XBRL company facts
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

# XBRL tags to try for each metric (in priority order)
REVENUE_TAGS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
]
NET_INCOME_TAGS = ["NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"]
TOTAL_ASSETS_TAGS = ["Assets"]
EQUITY_TAGS = ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"]


def _get_json(url: str, client: httpx.Client, timeout: int = 15) -> dict | None:
    """GET request with rate limiting and error handling."""
    time.sleep(RATE_LIMIT)
    try:
        r = client.get(url, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        log.debug("HTTP %d for %s", r.status_code, url)
    except Exception as e:
        log.debug("Request failed for %s: %s", url, e)
    return None


def load_ticker_map(client: httpx.Client) -> dict[str, dict]:
    """
    Download SEC company_tickers.json and return a lookup dict
    keyed by lowercase company name → {cik, ticker, title}.
    """
    data = _get_json(COMPANY_TICKERS_URL, client, timeout=30)
    if not data:
        log.warning("Failed to load SEC ticker map — retrying...")
        time.sleep(2)
        data = _get_json(COMPANY_TICKERS_URL, client, timeout=30)
    if not data:
        log.error("Failed to load SEC ticker map after retry")
        return {}

    lookup = {}
    for entry in data.values():
        name = entry.get("title", "").strip().lower()
        if name:
            lookup[name] = {
                "cik": str(entry["cik_str"]).zfill(10),
                "ticker": entry.get("ticker", ""),
                "title": entry.get("title", ""),
            }
    log.info("Loaded %d SEC tickers", len(lookup))
    return lookup


# Common name aliases → SEC filing name
COMPANY_ALIASES = {
    "general motors": "general motors co",
    "general motors (gm)": "general motors co",
    "gm": "general motors co",
    "john deere": "deere & co",
    "magna": "magna international inc",
    "nikola": "nikola corp",
    "proterra": "proterra inc",
    "caterpillar": "caterpillar inc",
    "wabtec": "westinghouse air brake technologies corp",
    "wabtec corp.": "westinghouse air brake technologies corp",
    "innophos": "innophos holdings inc",
    "piedmont lithium": "piedmont lithium inc",
    "piedmont lithium limited": "piedmont lithium inc",
    "flux power, inc.": "flux power holdings inc",
    "accelera by cummins": "cummins inc",
    "arkema": "arkema sa",
    "quantumscape": "quantumscape corp",
    "stardust power": "stardust power inc",
    "graphite one": "graphite one inc",
    "bmw": "bayerische motoren werke ag",
    "volkswagen": "volkswagen ag",
    "toyota": "toyota motor corp",
    "lg energy solution": "lg energy solution ltd",
    "samsung sdi": "samsung sdi co ltd",
    "panasonic": "panasonic holdings corp",
    "sk innovation": "sk innovation co ltd",
    "hyundai": "hyundai motor co",
    "stellantis": "stellantis nv",
    "rivian": "rivian automotive inc",
    "lucid": "lucid group inc",
    "lucid motors": "lucid group inc",
    "fisker": "fisker inc",
    "li-cycle": "li-cycle holdings corp",
    "freyr": "freyr battery",
    "eos energy": "eos energy enterprises inc",
    "romeo power": "romeo power inc",
}


def _normalize_for_match(name: str) -> str:
    """Strip common suffixes and parentheticals for matching."""
    import re
    name = name.strip().lower()
    # Remove parenthetical stock tickers: "Company (NYSE: ABC)" → "company"
    name = re.sub(r'\s*\([^)]*\)\s*', ' ', name).strip()
    # Remove trailing suffixes
    for suffix in [" inc", " inc.", " corp", " corp.", " co", " co.",
                   " ltd", " ltd.", " llc", " plc", " se", " sa",
                   " ag", " nv", " gmbh", " company", " corporation",
                   " limited", " holdings", " group", " international"]:
        if name.endswith(suffix):
            name = name[:-len(suffix)].strip()
            break
    return name.strip(" ,.")


def _find_cik(company_name: str, ticker_map: dict) -> dict | None:
    """
    Try to match a company name to a CIK.
    Strategy: alias lookup, exact match, normalized match, substring match.
    """
    name_lower = company_name.strip().lower()

    # Check aliases first
    alias_key = COMPANY_ALIASES.get(name_lower)
    if alias_key and alias_key in ticker_map:
        return ticker_map[alias_key]

    # Exact match
    if name_lower in ticker_map:
        return ticker_map[name_lower]

    # Normalized match — strip suffixes from both sides
    norm = _normalize_for_match(name_lower)
    if len(norm) >= 4:  # Avoid matching very short strings
        for key, val in ticker_map.items():
            key_norm = _normalize_for_match(key)
            if norm == key_norm:
                return val

    # Strip common suffixes and try prefix/substring
    for suffix in [" inc", " inc.", " corp", " corp.", " co", " co.",
                   " ltd", " ltd.", " llc", " plc", " se", " sa",
                   " ag", " nv", " gmbh"]:
        stripped = name_lower.rstrip(".").removesuffix(suffix.rstrip("."))
        if stripped != name_lower and len(stripped) >= 5:
            for key, val in ticker_map.items():
                if key.startswith(stripped) or stripped in key:
                    return val

    # Substring match — but only for longer names to avoid false positives
    if len(name_lower) >= 6:
        for key, val in ticker_map.items():
            if name_lower in key or key in name_lower:
                return val

    return None


def _extract_latest_annual(facts: dict, tags: list[str]) -> tuple[float | None, str | None]:
    """
    From XBRL facts, find the most recent 10-K value for any of the given tags.
    Returns (value_in_millions, fiscal_year_end_date).
    """
    us_gaap = facts.get("facts", {}).get("us-gaap", {})

    for tag in tags:
        tag_data = us_gaap.get(tag)
        if not tag_data:
            continue

        units = tag_data.get("units", {})
        usd_entries = units.get("USD", [])
        if not usd_entries:
            continue

        # Filter to 10-K filings (annual) with a fiscal period of FY
        annual = [
            e for e in usd_entries
            if e.get("form") == "10-K" and e.get("fp") == "FY"
        ]
        if not annual:
            # Fallback: any 10-K entry
            annual = [e for e in usd_entries if e.get("form") == "10-K"]
        if not annual:
            continue

        # Sort by end date descending
        annual.sort(key=lambda e: e.get("end", ""), reverse=True)
        latest = annual[0]
        val = latest.get("val")
        if val is not None:
            return val / 1_000_000, latest.get("end")  # Convert to millions

    return None, None


def enrich_company(company_name: str, ticker_map: dict, client: httpx.Client) -> dict | None:
    """
    Look up a company in SEC EDGAR and return financial data.
    Returns dict with revenue_usd, net_income, total_assets, etc. or None.
    """
    match = _find_cik(company_name, ticker_map)
    if not match:
        return None

    cik = match["cik"]
    ticker = match["ticker"]

    facts = _get_json(FACTS_URL.format(cik=cik), client)
    if not facts:
        return None

    revenue, rev_date = _extract_latest_annual(facts, REVENUE_TAGS)
    net_income, ni_date = _extract_latest_annual(facts, NET_INCOME_TAGS)
    total_assets, _ = _extract_latest_annual(facts, TOTAL_ASSETS_TAGS)
    equity, _ = _extract_latest_annual(facts, EQUITY_TAGS)

    if revenue is None and net_income is None and total_assets is None:
        return None

    return {
        "ticker": ticker,
        "cik": cik,
        "entity_name": match["title"],
        "revenue_usd": revenue,
        "net_income_usd": net_income,
        "total_assets_usd": total_assets,
        "equity_usd": equity,
        "fiscal_year_end": rev_date or ni_date,
    }


def run_enrichment(db, limit: int | None = None) -> dict:
    """
    Scan all companies and enrich public ones with SEC EDGAR data.
    Only targets companies with funding_status containing 'Public' or
    companies that are well-known public battery firms.
    """
    now = datetime.now(timezone.utc).isoformat()

    query = db.query(Company)
    # Prioritize companies likely to be public
    companies = query.all()

    with httpx.Client(follow_redirects=True, headers=HEADERS) as client:
        ticker_map = load_ticker_map(client)
        if not ticker_map:
            return {"status": "failed", "error": "Could not load SEC ticker map"}

        enriched = 0
        checked = 0

        for c in companies:
            if limit and enriched >= limit:
                break

            result = enrich_company(c.company_name, ticker_map, client)
            if result:
                if result["revenue_usd"] is not None:
                    c.revenue_usd = round(result["revenue_usd"], 2)
                if result.get("total_assets_usd") is not None:
                    c.market_cap_usd = round(result["total_assets_usd"], 2)
                if not c.funding_status:
                    c.funding_status = "Public"
                c.last_updated = now
                enriched += 1
                log.info(
                    "Enriched %s (ticker: %s) — revenue: $%.1fM",
                    c.company_name, result["ticker"],
                    result["revenue_usd"] or 0,
                )

            checked += 1
            if checked % 100 == 0:
                log.info("Checked %d / %d companies (%d enriched)", checked, len(companies), enriched)

        db.commit()

    log.info("SEC EDGAR enrichment: %d enriched out of %d checked", enriched, checked)

    db.add(SyncLog(
        source="sec_edgar",
        status="success",
        rows_added=0,
        rows_updated=enriched,
        run_at=now,
    ))
    db.commit()

    return {"status": "success", "checked": checked, "enriched": enriched}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
    init_db()
    db = SessionLocal()
    try:
        result = run_enrichment(db)
        print(result)
    finally:
        db.close()
