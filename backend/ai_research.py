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

For partnerships, provide detailed structured partnership data.
Each partnership object must have:
- partner_name: string
- partnership_type: one of [jv, supply_agreement, licensing, equity_stake, r_and_d_collab, government_grant, other]
- stage: one of [announced, signed, active, dissolved]
- direction: one of [supplier_to_buyer, investor_to_investee, bidirectional]
- company_role: one of [supplier, buyer, investor, investee, partner]
- partner_role: one of [supplier, buyer, investor, investee, partner]
- deal_value_millions_usd: number or null
- date_announced: string (YYYY or YYYY-MM or YYYY-MM-DD) or null
- scope: string (description of what the partnership covers)
- geography: string or null
- industry_segment: one of [cell_manufacturing, materials_mining, recycling, ev_oem, energy_storage, other] or null

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
  "partnerships": [{"partner_name": string, "partnership_type": string, "stage": string, "direction": string, "company_role": string, "partner_role": string, "deal_value_millions_usd": number, "date_announced": string, "scope": string, "geography": string, "industry_segment": string}],
  "number_of_employees": integer or null,
  "market_cap_usd": number or null (in millions USD, e.g. 1200.0 means $1.2B),
  "revenue_usd": number or null (in millions USD, annual, most recent),
  "total_funding_usd": number or null (in millions USD, cumulative VC/PE/grants raised),
  "last_fundraise_date": string or null,
  "founding_year": integer or null,
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


CLASSIFY_PARTNERSHIPS_PROMPT = """You are a battery/energy industry analyst. For each partnership below, infer the type and direction from the company names and any available context.

partnership_type — choose ONE:
- jv              : Joint venture (new shared entity)
- supply_agreement: One company supplies materials/products to the other
- licensing       : Technology or IP licensing
- equity_stake    : Investment / equity stake
- r_and_d_collab  : R&D or technology collaboration
- government_grant: Government funding, grant, or loan
- other           : Cannot be determined

direction — choose ONE:
- supplier_to_buyer      : clear supply relationship
- investor_to_investee   : clear investment relationship
- bidirectional          : JV, R&D collab, or symmetric deal

Return ONLY a JSON object keyed by the integer partnership ID provided.
Example: {"12": {"type": "supply_agreement", "direction": "supplier_to_buyer"}, "7": {"type": "equity_stake", "direction": "investor_to_investee"}}"""


CLASSIFY_BATCH_PROMPT = """You are a battery/energy industry analyst. Classify each company into our taxonomy based on its description and industry info.

For company_type choose EXACTLY ONE from: start-up, cell supplier, materials supplier, EV OEM, testing partner, prototyping partner, recycler, equipment supplier, R&D, services, modeling/software, other.

Return ONLY a JSON object mapping company name to company_type. No other text.
Example: {"Tesla": "EV OEM", "CATL": "cell supplier", "Li-Cycle": "recycler", "McKinsey": "services"}"""


def classify_companies_batch(companies_info: list[dict]) -> dict[str, str]:
    """Classify company_type for a batch of companies using Claude.

    Each dict should have keys: 'name', 'description' (optional), 'industry' (optional).
    Returns {company_name: company_type}.
    """
    if not companies_info:
        return {}

    lines = []
    for c in companies_info:
        parts = [f"- {c['name']}"]
        if c.get('description'):
            parts.append(f"  Description: {c['description'][:300]}")
        if c.get('industry'):
            parts.append(f"  Industry: {c['industry']}")
        lines.append("\n".join(parts))

    user_msg = "Classify these companies:\n\n" + "\n\n".join(lines)

    try:
        result = _claude_json(CLASSIFY_BATCH_PROMPT, user_msg)
        if isinstance(result, dict):
            log.info("Batch classified %d companies", len(result))
            return result
    except Exception as e:
        log.error("Batch classification failed: %s", e)
    return {}


def classify_partnerships_batch(partnerships_info: list[dict]) -> dict[str, dict]:
    """Classify partnership_type and direction for a batch of partnerships.

    Each dict should have keys: 'id', 'company_a', 'company_b', 'scope' (optional).
    Returns {str(id): {type, direction}}.
    """
    if not partnerships_info:
        return {}

    lines = []
    for p in partnerships_info:
        parts = [f"- ID {p['id']}: {p['company_a']} <-> {p['company_b']}"]
        if p.get('scope'):
            parts.append(f"  Context: {p['scope'][:150]}")
        lines.append("\n".join(parts))

    user_msg = "Classify these partnerships:\n\n" + "\n\n".join(lines)

    try:
        result = _claude_json(CLASSIFY_PARTNERSHIPS_PROMPT, user_msg)
        if isinstance(result, dict):
            log.info("Batch classified %d partnerships", len(result))
            return result
    except Exception as e:
        log.error("Partnership batch classification failed: %s", e)
    return {}


_EMPLOYEE_SYSTEM_PROMPT = """You extract the current total employee headcount for a company from web-search results.
Return ONLY valid JSON with the shape:
{"number_of_employees": integer or null, "employee_size": string or null, "as_of": string or null, "source_url": string or null, "confidence": "high"|"medium"|"low"}

Rules:
- number_of_employees is a single integer for total worldwide full-time-equivalent employees (or the best public approximation). Prefer the company's latest 10-K / annual report / LinkedIn headcount / Crunchbase.
- If only a range is available (e.g. LinkedIn "201-500"), set number_of_employees to the midpoint (rounded) AND set employee_size to the original range string.
- If the snippets mention multiple companies, pick the one that clearly matches the target name; if you can't disambiguate, return nulls with confidence "low".
- as_of: the year or YYYY-MM the figure applies to, if stated. Otherwise null.
- source_url: a single best URL from the search results (must be one of the URLs actually present in the snippets). Otherwise null.
- Never fabricate numbers. When in doubt, return nulls."""


def research_employee_count(company_name: str) -> dict:
    """Targeted lookup of a single company's headcount.

    Uses one focused web search + one Claude JSON synthesis, which is ~10x
    cheaper than the full :func:`research_company` pipeline. Returns a dict
    with at least ``number_of_employees`` (int|None). Safe to call on
    failure — never raises."""
    query = (
        f'"{company_name}" total number of employees headcount '
        f"(site:linkedin.com OR annual report OR 10-K OR crunchbase) 2024 2025"
    )
    try:
        snippets = perplexity_search(query)
    except Exception as e:
        log.warning("Employee search failed for %r: %s", company_name, e)
        return {"number_of_employees": None, "error": str(e)}

    if not snippets or snippets.startswith("Search failed"):
        return {"number_of_employees": None, "error": "no_results"}

    # Fast path: if snippets already contain an explicit range/count near
    # employee-related words, parse directly and skip Claude synthesis.
    # This removes the second model call for many companies.
    text = snippets.lower()
    m_range = re.search(
        r"(?:employees?|headcount|workforce)[^0-9]{0,40}(\d{1,3}(?:,\d{3})?)\s*[-–]\s*(\d{1,3}(?:,\d{3})?)",
        text,
    )
    if m_range:
        lo = int(m_range.group(1).replace(",", ""))
        hi = int(m_range.group(2).replace(",", ""))
        if 0 < lo <= hi:
            return {
                "number_of_employees": int(round((lo + hi) / 2)),
                "employee_size": f"{lo}-{hi}",
                "confidence": "medium",
            }

    m_single = re.search(
        r"(?:employees?|headcount|workforce)[^0-9]{0,25}(\d{2,3}(?:,\d{3}){0,2})\b",
        text,
    )
    if m_single:
        n = int(m_single.group(1).replace(",", ""))
        if 10 <= n <= 2_000_000:
            return {
                "number_of_employees": n,
                "employee_size": None,
                "confidence": "medium",
            }

    user_msg = (
        f"Target company: {company_name}\n\n"
        f"Search results:\n{snippets[:4500]}"
    )
    try:
        data = _claude_json(_EMPLOYEE_SYSTEM_PROMPT, user_msg)
        if not isinstance(data, dict):
            return {"number_of_employees": None, "error": "bad_shape"}
        n = data.get("number_of_employees")
        if isinstance(n, (int, float)) and n > 0:
            data["number_of_employees"] = int(n)
        else:
            data["number_of_employees"] = None
        return data
    except Exception as e:
        log.warning("Claude employee parse failed for %r: %s", company_name, e)
        return {"number_of_employees": None, "error": str(e)}


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
