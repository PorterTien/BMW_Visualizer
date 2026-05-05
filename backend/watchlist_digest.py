"""Watchlist digest: fetch news for watched companies, score with Claude."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from backend.config import ANTHROPIC_API_KEY, CLAUDE_MODEL, TAVILY_API_KEY

log = logging.getLogger(__name__)


def _tavily_news(company_name: str) -> list[dict]:
    """Fetch top 10 recent news articles for a company via Tavily."""
    if not TAVILY_API_KEY:
        log.warning("No TAVILY_API_KEY — skipping news search for %s", company_name)
        return []
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=TAVILY_API_KEY)
        resp = client.search(
            query=f"{company_name} battery company latest news 2024 2025",
            search_depth="advanced",
            max_results=10,
            include_answer=False,
        )
        articles = []
        for r in resp.get("results", []):
            articles.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", "")[:400],
                "published_date": r.get("published_date", ""),
            })
        return articles
    except Exception as e:
        log.error("Tavily news search failed for %s: %s", company_name, e)
        return []


def _claude_score_articles(company_name: str, articles: list[dict]) -> list[dict]:
    """Use Claude to score importance of each article and flag breaking news."""
    if not ANTHROPIC_API_KEY or not articles:
        return articles

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        articles_text = "\n\n".join(
            f"Article {i+1}:\nTitle: {a['title']}\nURL: {a['url']}\nSnippet: {a['snippet']}"
            for i, a in enumerate(articles)
        )

        prompt = f"""You are analyzing news articles about {company_name}, a battery industry company.

For each article below, return a JSON array with one object per article containing:
- "index": article number (1-based)
- "importance": integer 1-10 (10 = critical industry-moving news)
- "why": one sentence explaining why this matters for battery industry investors/analysts
- "is_breaking": true if this is major breaking news (acquisition, bankruptcy, large funding round >$50M, major regulatory action, plant closure, breakthrough technology announcement), false otherwise
- "category": one of: funding, partnership, regulatory, technology, expansion, leadership, financial, other

IMPORTANT: Return ONLY valid JSON array, no other text.

Articles:
{articles_text}"""

        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = resp.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        scores = json.loads(raw.strip())

        # Merge scores back into articles
        score_map = {s["index"]: s for s in scores}
        enriched = []
        for i, article in enumerate(articles):
            s = score_map.get(i + 1, {})
            enriched.append({
                **article,
                "importance": s.get("importance", 5),
                "why": s.get("why", ""),
                "is_breaking": s.get("is_breaking", False),
                "category": s.get("category", "other"),
            })
        return enriched
    except Exception as e:
        log.error("Claude scoring failed for %s: %s", company_name, e)
        return articles


def run_digest_for_company(db, company_id: int, company_name: str) -> dict:
    """Fetch news + AI score for one company, save to watchlist_digest and news_headlines."""
    from backend.models import NewsHeadline, WatchlistDigest

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now = datetime.now(timezone.utc).isoformat()

    log.info("Running digest for %s (id=%d)", company_name, company_id)

    articles = _tavily_news(company_name)
    if articles:
        articles = _claude_score_articles(company_name, articles)

    has_breaking = any(a.get("is_breaking") for a in articles)

    # Upsert: delete today's existing entry for this company, then insert fresh
    existing = (
        db.query(WatchlistDigest)
        .filter_by(company_id=company_id, run_date=today)
        .first()
    )
    if existing:
        db.delete(existing)
        db.flush()

    digest = WatchlistDigest(
        company_id=company_id,
        company_name=company_name,
        run_date=today,
        articles_json=json.dumps(articles),
        has_breaking=1 if has_breaking else 0,
        created_at=now,
    )
    db.add(digest)
    db.flush()

    # Also persist articles to news_headlines so they appear in the News Feed tab
    existing_urls = {
        row[0] for row in
        db.query(NewsHeadline.url)
        .filter(NewsHeadline.company_id == company_id)
        .all()
        if row[0]
    }
    for article in articles:
        url = article.get("url", "")
        if url and url in existing_urls:
            continue  # skip duplicates
        db.add(NewsHeadline(
            company_id=company_id,
            company_name=company_name,
            news_headline=article.get("title", ""),
            category=article.get("category", "other"),
            url=url,
            summary=article.get("snippet") or article.get("why", ""),
            date_of_article=article.get("published_date", ""),
            created_at=now,
        ))

    db.commit()

    return {
        "company_id": company_id,
        "company_name": company_name,
        "articles_count": len(articles),
        "has_breaking": has_breaking,
    }


def run_full_digest(db) -> dict:
    """Run digest for all watched companies. Called by scheduler or manual trigger."""
    from backend.models import Company, WatchlistEntry

    entries = db.query(WatchlistEntry).all()
    if not entries:
        log.info("Watchlist is empty — nothing to digest.")
        return {"companies_processed": 0}

    results = []
    for entry in entries:
        company = db.query(Company).filter_by(id=entry.company_id).first()
        if not company:
            continue
        try:
            r = run_digest_for_company(db, company.id, company.company_name)
            results.append(r)
        except Exception as e:
            log.error("Digest failed for company_id=%d: %s", entry.company_id, e)

    breaking_count = sum(1 for r in results if r.get("has_breaking"))
    log.info(
        "Watchlist digest complete: %d companies, %d with breaking news",
        len(results), breaking_count,
    )
    return {
        "companies_processed": len(results),
        "breaking_count": breaking_count,
        "results": results,
    }
