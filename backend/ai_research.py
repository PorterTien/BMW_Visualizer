"""AI Research module: Claude web search + Claude synthesis."""
from __future__ import annotations

import json
import logging
import re
import time

import anthropic

from backend.config import (
    ANTHROPIC_API_KEY,
    CLAUDE_MODEL,
    TAVILY_API_KEY,
)

log = logging.getLogger(__name__)

_anthropic_client = None


def _get_anthropic():
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _anthropic_client


def perplexity_search(query: str, max_retries: int = 3) -> str:
    """Search the web using Tavily (preferred) or Claude web search (fallback)."""
    if TAVILY_API_KEY:
        return _tavily_search(query, max_retries)
    return _claude_web_search(query, max_retries)


def _tavily_search(query: str, max_retries: int = 3) -> str:
    """Search via Tavily API — fast, cheap, purpose-built for AI agents."""
    from tavily import TavilyClient
    client = TavilyClient(api_key=TAVILY_API_KEY)

    for attempt in range(max_retries):
        try:
            response = client.search(
                query=query,
                search_depth="advanced",
                max_results=8,
                include_answer=True,
            )
            parts = []
            if response.get("answer"):
                parts.append(response["answer"])
            for r in response.get("results", []):
                title = r.get("title", "")
                url = r.get("url", "")
                content = r.get("content", "")
                if content:
                    parts.append(f"[{title}] ({url})\n{content}")
            result = "\n\n".join(parts).strip()
            log.debug("Tavily search for %r returned %d chars", query, len(result))
            return result or f"No results for: {query}"
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(5)
                continue
            log.error("Tavily search failed: %s", e)
            return f"Search failed: {query}"


def _claude_web_search(query: str, max_retries: int = 3) -> str:
    """Fallback: search via Claude's built-in web search tool."""
    client = _get_anthropic()

    for attempt in range(max_retries):
        try:
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=4096,
                tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
                messages=[{
                    "role": "user",
                    "content": (
                        f"Search for detailed, factual information about: {query}. "
                        "Return all relevant facts, figures, partnerships, funding amounts, "
                        "employee counts, technologies, and recent news you find."
                    ),
                }],
            )
            text_parts = [b.text for b in response.content if hasattr(b, "text") and b.text]
            result = "\n\n".join(text_parts).strip()
            log.debug("Claude web search for %r returned %d chars", query, len(result))
            return result or f"No results found for: {query}"
        except Exception as e:
            err_str = str(e)
            if ("529" in err_str or "overloaded" in err_str.lower() or "rate_limit" in err_str.lower()) and attempt < max_retries - 1:
                wait = 30 * (attempt + 1)
                log.warning("Claude web search throttled — waiting %ds (attempt %d/%d)", wait, attempt + 1, max_retries)
                time.sleep(wait)
                continue
            raise

    return f"Search failed after {max_retries} retries: {query}"


COMPANY_SYSTEM_PROMPT = """You are a senior battery industry analyst for BMW's technology scouting team.
Given web search results about a battery company, extract structured intelligence and return ONLY valid JSON.
Use null for unknown fields. Be thorough — this data drives investment and partnership decisions.
Do NOT use emojis anywhere in your output.

For company_type choose from: start-up, cell supplier, materials supplier, EV OEM, testing partner, prototyping partner, recycler, equipment supplier, R&D, services, modeling/software, other.

For company_status choose from: Commercial, Pre-commercial/startup, Planned, Under Construction, Pilot Plant, Operational, Closed, Paused.

For keywords pick ALL that apply from: solid-state, sodium-ion, lithium metal, anode, cathode, electrolyte, silicon, prelithiation, LLZO, lithium-sulfur, AI, simulation, LFP, anode-free, polymer, current collector, separator, sulfidic electrolyte, NMC, NCA, NCMA, dry electrode, formation, recycling, second-life.

For announced_partners include every partnership, JV, investment, supply agreement, or MOU you can find.
Each partner object must have: partner_name, type_of_partnership (Joint Venture / Investment / MOU / Off-take / Supply Agreement / Other), scale (dollar amount, capacity, or description), date (YYYY or YYYY-MM).

For summary write 3-5 sentences covering: what the company does, their core technology, stage of commercialization, and why they matter to BMW.

Return a JSON object with EXACTLY these fields:
{
  "company_type": string,
  "company_hq_city": string,
  "company_hq_state": string,
  "company_hq_country": string,
  "company_status": string,
  "company_focus": [string],
  "keywords": [string],
  "announced_partners": [{"partner_name": string, "type_of_partnership": string, "scale": string, "date": string}],
  "number_of_employees": integer or null,
  "market_cap_usd": number or null (in millions USD, e.g. 1200.0 means $1.2B),
  "revenue_usd": number or null (in millions USD, annual, most recent),
  "total_funding_usd": number or null (in millions USD, cumulative VC/PE/grants raised),
  "last_fundraise_date": string or null,
  "company_website": string or null,
  "summary": string
}"""

NEWS_SYSTEM_PROMPT = """You are a battery industry analyst for BMW. Do NOT use emojis.
Given web search results, extract up to 10 distinct news articles/events from 2023-2025.
Return ONLY a JSON array — no other text, no markdown.

Each element must have:
{
  "news_headline": string (clear, factual headline),
  "category": one of [funding, partnership, product launch, facility, regulatory, market, research, other],
  "partners": [string] (other companies mentioned),
  "news_source": string (publication name),
  "date_of_article": string (YYYY-MM-DD or YYYY-MM or YYYY),
  "location": string or null,
  "topics": [string] (2-5 relevant topic tags),
  "url": string or null,
  "summary": string (2-3 sentences explaining what happened and why it matters)
}"""

DISCOVER_SYSTEM_PROMPT = """You are a battery industry analyst for BMW tasked with finding companies NOT already tracked.
Given web search results, extract every distinct company name you can find.
Return ONLY a JSON array of company name strings — as many as you can find (aim for 15-25).
Include small, niche, or less well-known companies — not just the famous ones.
Do NOT filter by the existing list — that filtering is done separately.
Example: ["Lyten", "Addionics", "Echion Technologies", "Group14 Technologies"]
Return ONLY the JSON array, no other text."""

EXTRACT_SYSTEM_PROMPT = """You are a battery industry analyst for BMW.
Analyze the provided document text and extract all relevant information.
Return ONLY valid JSON with this structure:
{
  "companies": [{
    "company_name": string,
    "company_type": string,
    "company_hq_city": string or null,
    "company_hq_state": string or null,
    "summary": string or null,
    "keywords": [string],
    "announced_partners": []
  }],
  "news": [{
    "company_name": string,
    "news_headline": string,
    "category": string,
    "date_of_article": string or null,
    "summary": string,
    "partners": [],
    "topics": []
  }],
  "proceedings": [{
    "company_name": string or null,
    "title": string,
    "event_name": string or null,
    "event_date": string or null,
    "location": string or null,
    "authors": [string],
    "technologies": [string],
    "partners_mentioned": [string],
    "results_summary": string or null,
    "source_type": string,
    "topics": [string]
  }]
}"""


def _strip_emojis(text: str) -> str:
    return re.sub(r'[\U0001F000-\U0001FFFF\u2600-\u27BF\U0001FA00-\U0001FFFF]', '', text)


def _claude_json(system: str, user: str) -> dict | list:
    client = _get_anthropic()
    msg = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = msg.content[0].text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1])
    return json.loads(text)


def research_company(company_name: str) -> dict:
    """Run targeted Gemini searches then synthesize with Claude."""
    queries = [
        f"{company_name} battery company overview technology funding partnerships employees 2024 2025",
        f"{company_name} battery OEM deals joint ventures supply agreements customers announcements",
    ]
    results = []
    for q in queries:
        try:
            text = perplexity_search(q)
            results.append(f"Search: {q}\n\n{text}")
            log.info("Search OK for %r (%d chars)", q[:60], len(text))
        except Exception as e:
            log.warning("Gemini search error for %r: %s", q, e)
        time.sleep(1)

    if not results:
        return {"company_name": company_name, "data_source": "ai_research", "error": "all searches failed"}

    combined = "\n\n---\n\n".join(results)
    user_msg = f"Company: {company_name}\n\nSearch results:\n{combined}"

    try:
        data = _claude_json(COMPANY_SYSTEM_PROMPT, user_msg)
        if isinstance(data, dict):
            data["company_name"] = company_name
            data["data_source"] = "ai_research"
            log.info("Research complete for %r: %d partners, %d keywords",
                     company_name,
                     len(data.get("announced_partners") or []),
                     len(data.get("keywords") or []))
            return data
    except Exception as e:
        log.error("Claude synthesis failed for %r: %s", company_name, e)

    return {"company_name": company_name, "data_source": "ai_research", "error": "Claude synthesis failed"}


def search_company_news(company_name: str) -> list[dict]:
    """Search for recent news about a company."""
    queries = [
        f"{company_name} battery news funding partnership announcement milestone 2023 2024 2025",
    ]
    results = []
    for q in queries:
        try:
            results.append(perplexity_search(q))
        except Exception as e:
            log.error("Gemini news search failed for %r: %s", q, e)
        time.sleep(2)

    if not results:
        return []

    combined = "\n\n---\n\n".join(results)
    user_msg = f"Company: {company_name}\n\nSearch results:\n{combined}"
    try:
        articles = _claude_json(NEWS_SYSTEM_PROMPT, user_msg)
        if isinstance(articles, list):
            for a in articles:
                a["company_name"] = company_name
            log.info("Found %d news articles for %r", len(articles), company_name)
            return articles
    except Exception as e:
        log.error("Claude news extraction failed: %s", e)
    return []


def discover_companies(segment: str, existing_names: list[str], custom_query: str = "") -> list[str]:
    """Discover new battery companies by segment or custom query."""
    existing_lower = {n.lower().strip() for n in existing_names}

    if custom_query:
        queries = [custom_query]
    else:
        queries = [
            f"battery {segment} companies startups US emerging lesser-known 2024 2025",
            f"new battery {segment} manufacturers investors funding seed series 2024 2025 site:crunchbase.com OR site:pitchbook.com OR site:techcrunch.com",
        ]

    all_text = []
    for q in queries:
        try:
            text = perplexity_search(q)
            all_text.append(text)
            log.info("Discover search OK (%d chars) for %r", len(text), q[:60])
        except Exception as e:
            log.error("Gemini discover failed for %r: %s", q, e)
        time.sleep(2)

    if not all_text:
        return []

    combined = "\n\n---\n\n".join(all_text)
    user_msg = f"Search context: {queries[0]}\n\nSearch results:\n{combined}"

    try:
        names = _claude_json(DISCOVER_SYSTEM_PROMPT, user_msg)
        if isinstance(names, list):
            # Full deduplication in Python against all existing names
            new = [
                n for n in names
                if isinstance(n, str) and n.strip() and n.strip().lower() not in existing_lower
            ]
            log.info("Discovered %d new companies (filtered from %d raw) for %r",
                     len(new), len(names), queries[0][:60])
            return new
    except Exception as e:
        log.error("Claude discover failed: %s", e)
    return []


def extract_from_document(text: str, filename: str) -> dict:
    """Extract companies, news, and proceedings from document text."""
    user_msg = f"Filename: {filename}\n\nDocument text:\n{text[:40000]}"
    try:
        result = _claude_json(EXTRACT_SYSTEM_PROMPT, user_msg)
        if isinstance(result, dict):
            return result
    except Exception as e:
        log.error("Claude document extraction failed: %s", e)
    return {"companies": [], "news": [], "proceedings": []}
