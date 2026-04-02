# BMW Battery Intelligence Dashboard — Documentation

## Overview

A full-stack web application for tracking and researching battery supply chain companies. Aggregates data from NAATBatt, Volta Foundation (BBD), Ultima Media Gigafactory DB, and SEC EDGAR filings. Provides interactive maps, data tables, partnership networks, AI-powered research, and news feeds.

**Stack:** FastAPI + SQLAlchemy + SQLite | React 18 + Vite + Tailwind CSS | Claude AI + Tavily Search

**URLs:** Backend `http://localhost:8000` | Frontend `http://localhost:5173`

---

## Quick Start

```bash
cp .env.example .env   # Add your ANTHROPIC_API_KEY and TAVILY_API_KEY
bash run.sh            # Installs deps, seeds DB, starts both servers
```

---

## Data Pipeline Workflow

### 1. Initial Seed (First Run)

```
run.sh
  └─> backend/seed.py
        ├─ Downloads NAATBatt XLSX from NREL → data/naatbatt_latest.xlsx
        ├─ Parses 12 category sheets (Raw Materials, Battery Grade Materials, etc.)
        ├─ Deduplicates ~2,500 facility rows → ~893 unique companies
        ├─ Geocodes missing lat/lng via Nominatim
        └─ Inserts into companies table with company_type from sheet name
```

**Sheet processing order matters:** Specific category sheets are processed first so `company_type` is set from the sheet name. The Append2 (aggregate) sheet is processed last to fill gaps without overwriting types.

### 2. Additional Data Sources (Run Manually)

```bash
python3 -m backend.seed_bbd           # Volta Foundation BBD — 3,038 companies
python3 -m backend.seed_gigafactory   # Ultima Media Gigafactory — 188 companies
python3 -m backend.sec_edgar          # SEC EDGAR financials — enriches public companies
```

**BBD importer** (`seed_bbd.py`):
- Reads `data/bbd_data.xlsx` (50 columns)
- Imports: employee_size, funding_status, chemistry flags, supply chain flags, Crunchbase/LinkedIn/Pitchbook URLs
- Enriches existing companies (fills empty fields only), creates new ones

**Gigafactory importer** (`seed_gigafactory.py`):
- Reads `data/gigafactory_db.xlsx` (Global sheet)
- Imports: GWh capacity projections 2022-2030, plant start dates, city/country
- Aggregates total capacity across multiple plants per company
- Adds plant facilities to `company_locations` JSON array

**SEC EDGAR enrichment** (`sec_edgar.py`):
- Downloads SEC `company_tickers.json` (8,000+ public companies)
- Matches battery companies by name → CIK number
- Pulls latest 10-K XBRL data: revenue, net income, total assets, equity
- Stores revenue in `revenue_usd` (millions), assets in `market_cap_usd` (millions)
- No API key needed — free public API, just requires User-Agent header

### 3. Merge Strategy

All importers follow the same pattern:
1. Look up existing company by name (case-insensitive)
2. If found → **enrich** empty fields only, never overwrite NAATBatt data
3. If not found → **create** new company record

This means NAATBatt is the source of truth. BBD/Gigafactory/SEC data fills in gaps.

### 4. Scheduled Refresh

```
APScheduler (backend/scheduler.py)
  └─ Every Sunday 2:00 AM UTC
       └─ Re-downloads NAATBatt XLSX
       └─ Updates all 893 NAATBatt companies
```

Triggered manually via `POST /api/sync/naatbatt` or the "Sync Now" button in the navbar.

---

## Database Schema

### companies (primary table — ~3,400 rows)

| Column | Source | Description |
|--------|--------|-------------|
| company_name | NAATBatt/BBD/Giga | Unique company name |
| company_type | NAATBatt sheet name | e.g. "Raw Materials", "Equipment", "R&D" |
| company_hq_city/state/country | NAATBatt/BBD | HQ location |
| company_hq_lat/lng | NAATBatt + geocoding | Map coordinates |
| company_locations | NAATBatt/Giga | JSON array of all facilities |
| company_status | NAATBatt | "Commercial", "Planned", "Under Construction", etc. |
| company_focus | NAATBatt | JSON array of supply chain segments |
| supply_chain_segment | NAATBatt/BBD | Primary segment |
| summary | NAATBatt/BBD | Brief company profile |
| long_description | NAATBatt | Extended description |
| chemistries | NAATBatt/BBD | Battery chemistries (comma-separated) |
| feedstock | NAATBatt | Raw material inputs |
| company_website | NAATBatt/BBD | URL |
| hq_company / hq_company_website | NAATBatt | Parent company info |
| contact_name/email/phone/email2 | NAATBatt | Contact info |
| naatbatt_member | NAATBatt | Boolean (0/1) |
| naatbatt_id | NAATBatt | NAATBatt database ID |
| sources / sources2 | NAATBatt | Data references |
| qc / qc_date | NAATBatt | Quality control info |
| employee_size | BBD | Range string e.g. "11-50" |
| funding_status | BBD/SEC | "Private", "Public", "Acquired" |
| crunchbase_url / linkedin_url / pitchbook_url | BBD | External profile links |
| volta_member / volta_verified | BBD | Boolean flags |
| battery_chemistry_flags | BBD | JSON object of 17 chemistry booleans |
| supply_chain_flags | BBD | JSON object of 15 segment booleans |
| gwh_capacity | Gigafactory | JSON: {"2022": 60, "2023": 65, ...} |
| plant_start_date | Gigafactory | Earliest plant start year |
| revenue_usd | SEC EDGAR | Latest 10-K revenue in millions |
| market_cap_usd | SEC EDGAR | Total assets in millions |
| number_of_employees | AI research | Integer |
| total_funding_usd | AI research | In millions |
| keywords | AI research | JSON array |
| announced_partners | AI research | JSON array of partner objects |
| data_source | System | "naatbatt_xlsx", "bbd", "gigafactory", "ai_research" |

### Supporting Tables

- **news_headlines** — Articles linked to companies (from AI search)
- **conference_proceedings** — Papers/presentations (from document uploads)
- **sync_log** — Import history with row counts and errors
- **research_jobs** — Async job queue (pending → running → complete/failed)

---

## API Endpoints

### Companies
| Method | Path | Description |
|--------|------|-------------|
| GET | /api/companies | List all (filters: search, type, status, segment, country) |
| GET | /api/companies/{id} | Full detail + news + proceedings |
| GET | /api/companies/map | All facility markers (HQ + locations, deduplicated) |
| GET | /api/companies/network | Partnership graph (nodes + links) |
| POST | /api/companies/research | Async AI research on one company |
| POST | /api/companies/bulk-research | Research multiple companies in parallel |
| POST | /api/companies/discover | AI-powered discovery in a segment |
| POST | /api/companies/search/custom | Free-form web search + Claude synthesis |
| POST | /api/companies/{id}/chat | Chat about a company with context |
| POST | /api/companies/enrich/sec-edgar | Trigger SEC EDGAR financial enrichment |

### News & Proceedings
| Method | Path | Description |
|--------|------|-------------|
| GET | /api/news | List news (filters: company_id, category, date range) |
| POST | /api/news/search | Search & import news for a company |
| GET | /api/proceedings | List proceedings (filters: company_id, technology) |

### Data Import
| Method | Path | Description |
|--------|------|-------------|
| POST | /api/upload/csv | Upload company CSV/XLSX |
| POST | /api/upload/document | Upload PDF/TXT → async AI extraction |
| POST | /api/upload/partnerships | Import PitchBook/Crunchbase exports |

### System
| Method | Path | Description |
|--------|------|-------------|
| GET | /api/health | Health check |
| GET | /api/seed/status | Check if DB has been seeded |
| POST | /api/seed | Trigger initial seed |
| GET | /api/sync/status | Last sync info + next scheduled run |
| POST | /api/sync/naatbatt | Force NAATBatt re-sync |
| GET | /api/jobs/{id} | Poll async job status |

---

## Frontend Components

### App.jsx — Root Layout
6-tab SPA: Company Map | Company Table | News Feed | Partnership Network | Research Panel | Conference Proceedings. Global state: filters, selected company, dark mode.

### CompanyMap.jsx — Interactive Map
- Leaflet map with CircleMarker for every facility with coordinates (~2,400 markers)
- HQ markers have a dashed outer ring to distinguish from facility markers
- Color-coded by company type (12 NAATBatt categories)
- Click marker → popup with facility details → "Company Details" button
- Light/dark tile layers

### CompanyTable.jsx — Data Table (VF-style)
- Category tab bar at top (12 NAATBatt types + "All Companies")
- Compact rows with row numbers, like Volta Foundation layout
- Columns: #, Company, Employees, Funding, Revenue, Total Funding, Status, Country, State, Parent, Website, NAATBatt
- Sortable, searchable, paginated (25/50/100/250 per page)
- CSV export
- Click row → CompanyDetail panel

### CompanyDetail.jsx — Slide-out Profile Panel
- Company logo (Clearbit), quick facts grid
- Sections: Description, Keywords, Partners, News, Proceedings
- "Re-research" button triggers async AI research job
- Chat interface: ask questions about the company (uses web search + Claude)

### PartnershipNetwork.jsx — Force Graph
- react-force-graph-2d rendering
- Node size scales by: Employees, Market Cap, Revenue, or Total Funding
- Link types: Joint Venture, Investment, MOU, Off-take, Supply Agreement
- Filter by link type, highlight by name
- Auto-fits all nodes on layout complete

### NewsFeed.jsx — News Aggregation
- Category sidebar (8 categories)
- Featured article + grid + sidebar picks
- Color-coded category badges

### ResearchPanel.jsx — AI Research Hub
- Custom Search (Tavily + Claude)
- Discover Companies (AI finds new companies in a segment)
- Research Company (populates all fields)
- Bulk Research (parallel jobs)
- CSV/Document/Partnership uploads
- Job queue monitor

### Sidebar.jsx — Filter Panel
- Search with autocomplete
- Dropdowns: Type, Status, Segment, Country

---

## AI Research Workflow

```
User clicks "Research Company" for "QuantumScape"
  │
  ├─ POST /api/companies/research {company_name: "QuantumScape"}
  │    └─ Creates ResearchJob (status: pending), returns job_id
  │
  ├─ Backend async task:
  │    ├─ Tavily search: 3 queries (company overview, funding, news)
  │    ├─ Claude synthesis: structured JSON extraction
  │    │    └─ Fields: employees, revenue, funding, chemistries, partners, keywords
  │    ├─ Upsert Company record with extracted data
  │    └─ Update ResearchJob (status: complete, result: JSON)
  │
  └─ Frontend polls GET /api/jobs/{job_id} every 3 seconds
       └─ On complete: refreshes company data, shows results
```

---

## File Structure

```
BMW_data_visualizer/
├── backend/
│   ├── main.py              # FastAPI app, startup/shutdown, CORS
│   ├── database.py          # SQLAlchemy engine, session, init/migrate
│   ├── models.py            # ORM models (Company, News, Proceedings, etc.)
│   ├── config.py            # Env vars, constants
│   ├── seed.py              # NAATBatt XLSX importer (primary)
│   ├── seed_bbd.py          # Volta Foundation BBD importer
│   ├── seed_gigafactory.py  # Gigafactory capacity importer
│   ├── sec_edgar.py         # SEC EDGAR financial enrichment
│   ├── ai_research.py       # Tavily search + Claude synthesis
│   ├── scheduler.py         # APScheduler weekly refresh
│   └── routes/
│       ├── companies.py     # Company CRUD + research + map + network
│       ├── news.py          # News endpoints
│       ├── proceedings.py   # Proceedings endpoints
│       ├── upload.py        # CSV/document/partnership imports
│       └── jobs.py          # Async job status
├── frontend/
│   ├── src/
│   │   ├── App.jsx          # Root layout, tab navigation
│   │   ├── api/client.js    # Axios API client
│   │   └── components/
│   │       ├── CompanyMap.jsx
│   │       ├── CompanyTable.jsx
│   │       ├── CompanyDetail.jsx
│   │       ├── PartnershipNetwork.jsx
│   │       ├── NewsFeed.jsx
│   │       ├── ResearchPanel.jsx
│   │       ├── Proceedings.jsx
│   │       ├── Navbar.jsx
│   │       └── Sidebar.jsx
│   └── package.json
├── data/
│   ├── naatbatt_latest.xlsx
│   ├── bbd_data.xlsx
│   └── gigafactory_db.xlsx
├── run.sh                   # Single-command startup
├── requirements.txt
├── .env.example
└── battery_intel.db         # SQLite database
```

---

## Environment Variables

```
ANTHROPIC_API_KEY=sk-ant-...    # Required for AI research
TAVILY_API_KEY=tvly-...         # Required for web search
DATABASE_URL=sqlite:///./battery_intel.db
UPLOAD_DIR=./uploads
```

SEC EDGAR requires no API key.
