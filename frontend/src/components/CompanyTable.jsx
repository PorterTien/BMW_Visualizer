import React, { useEffect, useState, useMemo, useCallback } from 'react'
import { getCompanies, addToWatchlist, removeFromWatchlist, getWatchlist } from '../api/client'

const PAGE_SIZE = 50

const COUNTRY_ALIASES = {
  'United States': ['united states', 'us'],
  'United Kingdom': ['united kingdom', 'uk'],
  'South Korea': ['south korea', 'republic of korea'],
}

function safeHostname(url) {
  try { return new URL(url).hostname.replace('www.', '') } catch { return url }
}

function getFaviconUrl(website) {
  try {
    const domain = new URL(website).hostname.replace(/^www\./, '')
    return `https://www.google.com/s2/favicons?sz=64&domain=${domain}`
  } catch { return null }
}

// Deterministic pastel color from company name
function nameColor(name) {
  let h = 0
  for (let i = 0; i < name.length; i++) h = (Math.imul(31, h) + name.charCodeAt(i)) | 0
  const hue = ((h >>> 0) % 12) * 30
  return `hsl(${hue}, 55%, 55%)`
}

function CompanyLogo({ name, website }) {
  const [failed, setFailed] = React.useState(false)
  const src = website ? getFaviconUrl(website) : null
  const initials = name ? name.replace(/[^A-Za-z0-9]/g, '').slice(0, 2).toUpperCase() : '?'
  const bg = nameColor(name || '')

  if (src && !failed) {
    return (
      <div className="w-5 h-5 rounded overflow-hidden flex items-center justify-center bg-gray-50 flex-shrink-0 border border-gray-100">
        <img
          src={src}
          alt=""
          className="w-4 h-4 object-contain"
          onError={() => setFailed(true)}
        />
      </div>
    )
  }
  return (
    <div
      className="w-5 h-5 rounded flex items-center justify-center flex-shrink-0 text-white font-bold select-none"
      style={{ fontSize: '8px', backgroundColor: bg }}
    >
      {initials}
    </div>
  )
}

function fmtMoney(val) {
  if (val == null || val === '') return ''
  const n = Number(val)
  if (isNaN(n) || n === 0) return ''
  if (n >= 1000) return `$${(n / 1000).toFixed(1)}B`
  if (n >= 1) return `$${Math.round(n)}M`
  return `$${(n * 1000).toFixed(0)}K`
}

function fmtInt(val) {
  if (val == null || val === '') return ''
  const n = Number(val)
  if (isNaN(n) || n === 0) return ''
  return n.toLocaleString('en-US')
}

function fmtDate(val) {
  if (!val) return ''
  // Accept YYYY-MM-DD or ISO strings
  const d = new Date(val)
  if (isNaN(d.getTime())) return val
  return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short' })
}

const CATEGORIES = [
  { key: 'all', label: 'All Companies' },
  { key: 'Raw Materials', label: 'Raw Materials' },
  { key: 'Battery Grade Materials', label: 'Battery Grade Materials' },
  { key: 'Other Battery Components & Mat.', label: 'Other Battery Components' },
  { key: 'Electrode & Cell Manufacturing', label: 'Electrode & Cell Mfg.' },
  { key: 'Module-Pack Manufacturing', label: 'Module-Pack Mfg.' },
  { key: 'Recycling-Repurposing', label: 'Recycling-Repurposing' },
  { key: 'Equipment', label: 'Equipment' },
  { key: 'R&D', label: 'R&D' },
  { key: 'Services & Consulting', label: 'Services & Consulting' },
  { key: 'Modeling & Software', label: 'Modeling & Software' },
  { key: 'Distributors', label: 'Distributors' },
  { key: 'Professional Services', label: 'Professional Services' },
]

const CATEGORY_COLORS = {
  'Raw Materials': '#F59E0B',
  'Battery Grade Materials': '#EAB308',
  'Other Battery Components & Mat.': '#D97706',
  'Electrode & Cell Manufacturing': '#1C69D4',
  'Module-Pack Manufacturing': '#2563EB',
  'Recycling-Repurposing': '#10B981',
  'Equipment': '#06B6D4',
  'R&D': '#8B5CF6',
  'Services & Consulting': '#84CC16',
  'Modeling & Software': '#A855F7',
  'Distributors': '#F97316',
  'Professional Services': '#EC4899',
}

const COLS = [
  // Identity
  { key: '_row',             label: '#',               align: 'center', w: 'w-8' },
  { key: '_watch',           label: '',                align: 'center', w: 'w-8' },
  { key: 'company_name',     label: 'Company',         align: 'left',   w: 'min-w-[200px]' },
  // Classification
  { key: 'company_type',     label: 'Type',            align: 'left',   w: 'min-w-[160px]' },
  { key: 'supply_chain_segment', label: 'Segment',     align: 'left',   w: 'w-32' },
  { key: 'company_status',   label: 'Status',          align: 'left',   w: 'w-36' },
  // Geography
  { key: 'company_hq_city',  label: 'City',            align: 'left',   w: 'w-28' },
  { key: 'company_hq_state', label: 'State',           align: 'left',   w: 'w-14' },
  { key: 'company_hq_country', label: 'Country',       align: 'left',   w: 'w-20' },
  // Financials
  { key: 'market_cap_usd',   label: 'Mkt Cap',         align: 'right',  w: 'w-20' },
  { key: 'revenue_usd',      label: 'Revenue',         align: 'right',  w: 'w-20' },
  { key: 'total_funding_usd',label: 'Total Funding',   align: 'right',  w: 'w-24' },
  { key: 'funding_status',   label: 'Funding Stage',   align: 'left',   w: 'w-24' },
  { key: 'last_fundraise_date', label: 'Last Raise',   align: 'left',   w: 'w-24' },
  // People
  { key: 'number_of_employees', label: 'Headcount',    align: 'right',  w: 'w-20' },
  { key: 'employee_size',    label: 'Size Range',      align: 'left',   w: 'w-20' },
  // Operations
  { key: '_partner_count',   label: 'Partners',        align: 'center', w: 'w-16' },
  { key: 'chemistries',      label: 'Chemistries',     align: 'left',   w: 'w-36' },
  { key: 'feedstock',        label: 'Feedstock',       align: 'left',   w: 'w-28' },
  { key: 'products',         label: 'Products',        align: 'left',   w: 'min-w-[160px]' },
  { key: '_gwh',             label: 'GWh Cap.',        align: 'right',  w: 'w-20' },
  { key: 'plant_start_date', label: 'Plant Start',     align: 'left',   w: 'w-24' },
  // Relationships
  { key: 'hq_company',       label: 'Parent Co.',      align: 'left',   w: 'w-32' },
  // Links
  { key: 'company_website',  label: 'Website',         align: 'left',   w: 'w-32' },
  { key: '_links',           label: 'Profiles',        align: 'center', w: 'w-20' },
  // Meta
  { key: 'data_source',      label: 'Source',          align: 'left',   w: 'w-24' },
  { key: 'last_updated',     label: 'Updated',         align: 'left',   w: 'w-24' },
]

function exportCSV(companies) {
  const headers = [
    'Name', 'Type', 'Segment', 'Status',
    'City', 'State', 'Country',
    'Market Cap ($M)', 'Revenue ($M)', 'Total Funding ($M)', 'Funding Stage', 'Last Fundraise',
    'Headcount', 'Size Range', 'Partners',
    'Chemistries', 'Feedstock', 'Products', 'GWh Capacity', 'Plant Start',
    'Parent Company', 'Website', 'LinkedIn', 'Crunchbase', 'PitchBook',
    'Data Source', 'Last Updated',
    'Summary',
  ]
  const rows = companies.map((c) => {
    let maxGwh = ''
    try {
      const obj = typeof c.gwh_capacity === 'string' ? JSON.parse(c.gwh_capacity) : c.gwh_capacity
      if (obj) { const vals = Object.values(obj).map(Number).filter((v) => !isNaN(v) && v > 0); if (vals.length) maxGwh = Math.max(...vals) }
    } catch {}
    return [
      c.company_name, c.company_type, c.supply_chain_segment, c.company_status,
      c.company_hq_city, c.company_hq_state, c.company_hq_country,
      c.market_cap_usd, c.revenue_usd, c.total_funding_usd, c.funding_status, c.last_fundraise_date,
      c.number_of_employees, c.employee_size, (c.announced_partners || []).length,
      c.chemistries, c.feedstock, c.products, maxGwh, c.plant_start_date,
      c.hq_company, c.company_website, c.linkedin_url, c.crunchbase_url, c.pitchbook_url,
      c.data_source, c.last_updated,
      c.summary,
    ]
  })
  const csv = [headers, ...rows].map((r) => r.map((v) => `"${(v ?? '').toString().replace(/"/g, '""')}"`).join(',')).join('\n')
  const blob = new Blob([csv], { type: 'text/csv' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = 'bmw_battery_companies.csv'
  a.click()
}

export default function CompanyTable({ filters, onOpenCompany }) {
  const [companies, setCompanies] = useState([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [sortKey, setSortKey] = useState('company_name')
  const [sortDir, setSortDir] = useState(1)
  const [page, setPage] = useState(1)
  const [activeCategory, setActiveCategory] = useState('all')
  const [pageSize, setPageSize] = useState(PAGE_SIZE)
  const [watchedIds, setWatchedIds] = useState(new Set())
  const [watchTogglingId, setWatchTogglingId] = useState(null)

  useEffect(() => {
    setLoading(true)
    Promise.all([getCompanies({ limit: 2000 }), getWatchlist()])
      .then(([{ data: res }, { data: wl }]) => {
        // API returns { items, total, ... } paginated shape
        setCompanies(Array.isArray(res) ? res : res.items ?? [])
        setWatchedIds(new Set(wl.map((e) => e.company_id)))
      })
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  const handleWatchToggle = useCallback(async (e, companyId) => {
    e.stopPropagation()
    setWatchTogglingId(companyId)
    try {
      if (watchedIds.has(companyId)) {
        await removeFromWatchlist(companyId)
        setWatchedIds((prev) => { const s = new Set(prev); s.delete(companyId); return s })
      } else {
        await addToWatchlist(companyId)
        setWatchedIds((prev) => new Set([...prev, companyId]))
      }
    } catch (err) {
      console.error(err)
    }
    setWatchTogglingId(null)
  }, [watchedIds])

  const categoryCounts = useMemo(() => {
    const counts = { all: companies.length }
    for (const cat of CATEGORIES) {
      if (cat.key !== 'all') {
        counts[cat.key] = companies.filter((c) => c.company_type === cat.key).length
      }
    }
    return counts
  }, [companies])

  const filtered = useMemo(() => {
    let rows = companies
    if (activeCategory !== 'all') {
      rows = rows.filter((c) => c.company_type === activeCategory)
    }
    const q = (search || filters.search || '').toLowerCase()
    if (q) {
      rows = rows.filter(
        (c) =>
          c.company_name?.toLowerCase().includes(q) ||
          c.company_type?.toLowerCase().includes(q) ||
          c.summary?.toLowerCase().includes(q)
      )
    }
    if (filters.statuses.length) rows = rows.filter((c) => filters.statuses.includes(c.company_status))
    if (filters.segments.length) {
      rows = rows.filter((c) => {
        const segs = (c.supply_chain_segment || '').split(' | ')
        return filters.segments.some((seg) => segs.includes(seg))
      })
    }
    if (filters.countries.length) {
      rows = rows.filter((c) => {
        const hq = (c.company_hq_country || '').trim().toLowerCase()
        return filters.countries.some((co) => {
          const aliases = COUNTRY_ALIASES[co] || [co.toLowerCase()]
          return aliases.includes(hq)
        })
      })
    }

    rows = [...rows].sort((a, b) => {
      const av = a[sortKey] ?? ''
      const bv = b[sortKey] ?? ''
      if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * sortDir
      return av < bv ? -sortDir : av > bv ? sortDir : 0
    })
    return rows
  }, [companies, search, filters, sortKey, sortDir, activeCategory])

  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize))
  const paginated = filtered.slice((page - 1) * pageSize, page * pageSize)
  const startIdx = (page - 1) * pageSize

  function handleSort(key) {
    if (key === '_row' || key === '_watch') return
    if (sortKey === key) setSortDir((d) => -d)
    else { setSortKey(key); setSortDir(1) }
    setPage(1)
  }

  function handleCategoryChange(key) {
    setActiveCategory(key)
    setPage(1)
  }

  return (
    <div className="flex flex-col flex-1 min-h-0">
      {/* Category tabs */}
      <div className="flex flex-wrap gap-1.5 px-4 pt-3 pb-2 bg-bmw-gray-light border-b border-bmw-border">
        {CATEGORIES.map((cat) => {
          const isActive = activeCategory === cat.key
          const color = CATEGORY_COLORS[cat.key] || '#1C69D4'
          const count = categoryCounts[cat.key] || 0
          return (
            <button
              key={cat.key}
              onClick={() => handleCategoryChange(cat.key)}
              className={`px-3 py-1.5 text-xs font-medium rounded-full transition-all ${
                isActive
                  ? 'text-white shadow-sm font-semibold'
                  : 'bg-white text-gray-600 border border-bmw-border hover:bg-gray-50'
              }`}
              style={isActive ? { backgroundColor: color } : {}}
            >
              {cat.label}
              <span className={`ml-1.5 ${isActive ? 'text-white/80' : 'text-gray-400'}`}>
                {count}
              </span>
            </button>
          )
        })}
      </div>

      {/* Toolbar */}
      <div className="flex items-center gap-3 px-4 py-2 border-b border-bmw-border bg-white">
        <input
          type="text"
          placeholder="Search companies…"
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(1) }}
          className="flex-1 border border-bmw-border rounded px-3 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-bmw-blue"
        />
        <span className="text-xs text-gray-500">{filtered.length} results</span>
        <button
          onClick={() => exportCSV(filtered)}
          className="bg-bmw-blue hover:bg-[#3a88ee] text-white text-xs px-3 py-1.5 rounded"
        >
          Export CSV
        </button>
      </div>

      {/* Table */}
      <div className="flex-1 overflow-x-auto overflow-y-auto">
        {loading ? (
          <div className="flex items-center justify-center h-full text-gray-500 text-sm">Loading…</div>
        ) : (
          <table className="w-full text-xs border-collapse">
            <thead className="bg-[#F7F9FB] sticky top-0 z-10">
              <tr>
                {COLS.map((col) => (
                  <th
                    key={col.key}
                    onClick={() => handleSort(col.key)}
                    className={`px-3 py-2 font-semibold text-[#3B5068] cursor-pointer hover:text-gray-900 border-b border-[#DDE4EA] whitespace-nowrap ${
                      col.align === 'right' ? 'text-right' : col.align === 'center' ? 'text-center' : 'text-left'
                    } ${col.w || ''}`}
                  >
                    {col.label}
                    {col.key !== '_row' && (
                      <span className="ml-0.5 text-[10px]">
                        {sortKey === col.key ? (sortDir === 1 ? '↑' : '↓') : ''}
                      </span>
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {paginated.map((c, i) => {
                const rowNum = startIdx + i + 1
                const partnerCount = (c.announced_partners || []).length
                // Parse max GWh from JSON capacity object
                let maxGwh = null
                try {
                  const gwhObj = typeof c.gwh_capacity === 'string' ? JSON.parse(c.gwh_capacity) : c.gwh_capacity
                  if (gwhObj && typeof gwhObj === 'object') {
                    const vals = Object.values(gwhObj).map(Number).filter((v) => !isNaN(v) && v > 0)
                    if (vals.length) maxGwh = Math.max(...vals)
                  }
                } catch {}

                return (
                  <tr
                    key={c.id}
                    onClick={() => onOpenCompany ? onOpenCompany(c.id) : null}
                    className={`cursor-pointer border-b border-[#EEF1F4] hover:bg-[#EDF3FF] transition-colors ${
                      i % 2 === 0 ? 'bg-white' : 'bg-[#FAFBFC]'
                    }`}
                    style={{ height: '34px' }}
                  >
                    {/* # */}
                    <td className="px-2 py-1.5 text-center text-[#8899A6] font-mono text-[11px]">{rowNum}</td>
                    {/* Watch */}
                    <td className="px-1 py-1.5 text-center" onClick={(e) => handleWatchToggle(e, c.id)}>
                      <button className={`transition-colors ${watchTogglingId === c.id ? 'opacity-40' : 'hover:scale-110'}`} title={watchedIds.has(c.id) ? 'Remove' : 'Add to watchlist'}>
                        <svg className={`w-4 h-4 ${watchedIds.has(c.id) ? 'fill-amber-400 text-amber-400' : 'fill-none text-gray-300 hover:text-amber-300'}`} viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.5">
                          <path strokeLinecap="round" strokeLinejoin="round" d="M11.48 3.499a.562.562 0 0 1 1.04 0l2.125 5.111a.563.563 0 0 0 .475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 0 0-.182.557l1.285 5.385a.562.562 0 0 1-.84.61l-4.725-2.885a.562.562 0 0 0-.586 0L6.982 20.54a.562.562 0 0 1-.84-.61l1.285-5.386a.562.562 0 0 0-.182-.557l-4.204-3.602a.562.562 0 0 1 .321-.988l5.518-.442a.563.563 0 0 0 .475-.345L11.48 3.5Z" />
                        </svg>
                      </button>
                    </td>
                    {/* Company name + logo */}
                    <td className="px-3 py-1.5 font-medium text-[#1A5FAD] whitespace-nowrap">
                      <div className="flex items-center gap-2">
                        <CompanyLogo name={c.company_name} website={c.company_website} />
                        {c.company_name}
                      </div>
                    </td>
                    {/* Type */}
                    <td className="px-3 py-1.5 whitespace-nowrap">
                      {c.company_type ? (
                        <TypeBadge type={c.company_type} />
                      ) : <span className="text-gray-300">—</span>}
                    </td>
                    {/* Segment */}
                    <td className="px-3 py-1.5 text-gray-600 whitespace-nowrap text-xs">{c.supply_chain_segment || ''}</td>
                    {/* Status */}
                    <td className="px-3 py-1.5 whitespace-nowrap"><StatusBadge status={c.company_status} /></td>
                    {/* City */}
                    <td className="px-3 py-1.5 text-gray-600 whitespace-nowrap">{c.company_hq_city || ''}</td>
                    {/* State */}
                    <td className="px-3 py-1.5 text-gray-600 whitespace-nowrap">{c.company_hq_state || ''}</td>
                    {/* Country */}
                    <td className="px-3 py-1.5 text-gray-600 whitespace-nowrap">{c.company_hq_country || ''}</td>
                    {/* Market Cap */}
                    <td className="px-3 py-1.5 text-right text-gray-700 font-mono whitespace-nowrap text-xs">{fmtMoney(c.market_cap_usd)}</td>
                    {/* Revenue */}
                    <td className="px-3 py-1.5 text-right text-gray-700 font-mono whitespace-nowrap text-xs">{fmtMoney(c.revenue_usd)}</td>
                    {/* Total Funding */}
                    <td className="px-3 py-1.5 text-right text-gray-700 font-mono whitespace-nowrap text-xs">{fmtMoney(c.total_funding_usd)}</td>
                    {/* Funding Stage */}
                    <td className="px-3 py-1.5 text-gray-600 whitespace-nowrap text-xs">{c.funding_status || ''}</td>
                    {/* Last Fundraise */}
                    <td className="px-3 py-1.5 text-gray-600 whitespace-nowrap text-xs">{fmtDate(c.last_fundraise_date)}</td>
                    {/* Headcount */}
                    <td className="px-3 py-1.5 text-right text-gray-700 font-mono whitespace-nowrap text-xs">{fmtInt(c.number_of_employees)}</td>
                    {/* Size Range */}
                    <td className="px-3 py-1.5 text-gray-600 whitespace-nowrap text-xs">{c.employee_size || ''}</td>
                    {/* Partners */}
                    <td className="px-3 py-1.5 text-center whitespace-nowrap">
                      {partnerCount > 0 ? <span className="bg-blue-50 text-blue-700 text-[11px] px-1.5 py-0.5 rounded-full">{partnerCount}</span> : ''}
                    </td>
                    {/* Chemistries */}
                    <td className="px-3 py-1.5 whitespace-nowrap max-w-[160px]">
                      <ChemBadges value={c.chemistries} />
                    </td>
                    {/* Feedstock */}
                    <td className="px-3 py-1.5 text-gray-600 whitespace-nowrap text-xs max-w-[120px] truncate" title={c.feedstock || ''}>{c.feedstock || ''}</td>
                    {/* Products */}
                    <td className="px-3 py-1.5 text-gray-600 text-xs max-w-[180px] truncate" title={c.products || ''}>
                      {c.products || ''}
                    </td>
                    {/* GWh Capacity */}
                    <td className="px-3 py-1.5 text-right text-gray-700 font-mono whitespace-nowrap text-xs">
                      {maxGwh != null ? `${maxGwh} GWh` : ''}
                    </td>
                    {/* Plant Start */}
                    <td className="px-3 py-1.5 text-gray-600 whitespace-nowrap text-xs">{fmtDate(c.plant_start_date)}</td>
                    {/* Parent */}
                    <td className="px-3 py-1.5 text-gray-600 whitespace-nowrap text-xs max-w-[140px] truncate" title={c.hq_company || ''}>{c.hq_company || ''}</td>
                    {/* Website */}
                    <td className="px-3 py-1.5 whitespace-nowrap text-xs" onClick={(e) => e.stopPropagation()}>
                      {c.company_website ? (
                        <a href={c.company_website} target="_blank" rel="noreferrer" className="text-[#1A5FAD] hover:underline">
                          {safeHostname(c.company_website)}
                        </a>
                      ) : ''}
                    </td>
                    {/* Profile Links */}
                    <td className="px-3 py-1.5 whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
                      <div className="flex items-center gap-2">
                        {c.linkedin_url && (
                          <a href={c.linkedin_url} target="_blank" rel="noreferrer" title="LinkedIn" className="text-[#0A66C2] hover:opacity-70">
                            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor"><path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 0 1-2.063-2.065 2.064 2.064 0 1 1 2.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/></svg>
                          </a>
                        )}
                        {c.crunchbase_url && (
                          <a href={c.crunchbase_url} target="_blank" rel="noreferrer" title="Crunchbase" className="text-[#0288D1] hover:opacity-70">
                            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor"><path d="M21.6 0H2.4A2.4 2.4 0 0 0 0 2.4v19.2A2.4 2.4 0 0 0 2.4 24h19.2a2.4 2.4 0 0 0 2.4-2.4V2.4A2.4 2.4 0 0 0 21.6 0zm-8.4 17.04a4.56 4.56 0 0 1-3.24-1.32l-1.2 1.2a.6.6 0 0 1-.84-.84l1.2-1.2A4.56 4.56 0 1 1 13.2 17.04zm0-7.92a3.36 3.36 0 1 0 0 6.72 3.36 3.36 0 0 0 0-6.72zm-6 1.44H5.4a.6.6 0 0 1 0-1.2h1.8a.6.6 0 0 1 0 1.2zm0 2.4H5.4a.6.6 0 0 1 0-1.2h1.8a.6.6 0 1 1 0 1.2zm0 2.4H5.4a.6.6 0 0 1 0-1.2h1.8a.6.6 0 1 1 0 1.2z"/></svg>
                          </a>
                        )}
                        {c.pitchbook_url && (
                          <a href={c.pitchbook_url} target="_blank" rel="noreferrer" title="PitchBook" className="text-gray-500 hover:opacity-70 font-bold text-[10px] leading-none">PB</a>
                        )}
                      </div>
                    </td>
                    {/* Source */}
                    <td className="px-3 py-1.5 text-gray-400 whitespace-nowrap text-[11px]">{c.data_source || ''}</td>
                    {/* Updated */}
                    <td className="px-3 py-1.5 text-gray-400 whitespace-nowrap text-[11px]">{fmtDate(c.last_updated)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Pagination — VF-style */}
      <div className="flex items-center gap-3 px-4 py-2 border-t border-[#DDE4EA] bg-[#FAFBFC] text-xs text-gray-600">
        <span>Show</span>
        <select
          value={pageSize}
          onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1) }}
          className="border border-bmw-border rounded px-1.5 py-0.5 text-xs bg-white"
        >
          {[25, 50, 100, 250].map((n) => (
            <option key={n} value={n}>{n}</option>
          ))}
        </select>

        <span className="mx-1 text-gray-400">|</span>

        <button
          onClick={() => setPage((p) => Math.max(1, p - 1))}
          disabled={page === 1}
          className="px-1.5 disabled:opacity-30 hover:text-gray-900"
        >
          Prev
        </button>

        {Array.from({ length: Math.min(4, totalPages) }, (_, i) => i + 1).map((p) => (
          <button
            key={p}
            onClick={() => setPage(p)}
            className={`w-6 h-6 rounded text-center ${
              page === p ? 'bg-bmw-blue text-white font-bold' : 'hover:bg-gray-200'
            }`}
          >
            {p}
          </button>
        ))}
        {totalPages > 4 && <span>…</span>}
        {totalPages > 4 && (
          <button
            onClick={() => setPage(totalPages)}
            className={`w-6 h-6 rounded text-center ${
              page === totalPages ? 'bg-bmw-blue text-white font-bold' : 'hover:bg-gray-200'
            }`}
          >
            {totalPages}
          </button>
        )}

        <button
          onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
          disabled={page === totalPages}
          className="px-1.5 disabled:opacity-30 hover:text-gray-900"
        >
          Next
        </button>

        <span className="mx-1 text-gray-400">|</span>
        <span>Go To</span>
        <input
          type="text"
          inputMode="numeric"
          pattern="[0-9]*"
          className="w-20 border border-bmw-border rounded px-1.5 py-0.5 text-xs bg-white"
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              const v = Math.max(1, Math.min(totalPages, Number(e.target.value)))
              setPage(v)
            }
          }}
          placeholder="Page"
        />
      </div>

    </div>
  )
}

function StatusBadge({ status }) {
  const MAP = {
    'Commercial': 'bg-green-100 text-green-700',
    'Operational': 'bg-green-100 text-green-700',
    'Pre-commercial/startup': 'bg-blue-100 text-blue-700',
    'Pre-commercial/ startup': 'bg-blue-100 text-blue-700',
    'Planned': 'bg-yellow-100 text-yellow-700',
    'Under Construction': 'bg-orange-100 text-orange-700',
    'Pilot Plant': 'bg-purple-100 text-purple-700',
    'Closed': 'bg-red-100 text-red-700',
    'Paused': 'bg-gray-100 text-gray-700',
  }
  if (!status) return <span className="text-gray-300">—</span>
  return (
    <span className={`text-[11px] px-1.5 py-0.5 rounded ${MAP[status] || 'bg-gray-100 text-gray-700'}`}>
      {status}
    </span>
  )
}

function TypeBadge({ type }) {
  const COLOR_MAP = {
    'Raw Materials':                   'bg-amber-100 text-amber-800',
    'Battery Grade Materials':         'bg-yellow-100 text-yellow-800',
    'Other Battery Components & Mat.': 'bg-orange-100 text-orange-800',
    'Electrode & Cell Manufacturing':  'bg-blue-100 text-blue-800',
    'Module-Pack Manufacturing':       'bg-indigo-100 text-indigo-800',
    'Recycling-Repurposing':           'bg-emerald-100 text-emerald-800',
    'Equipment':                       'bg-cyan-100 text-cyan-800',
    'R&D':                             'bg-violet-100 text-violet-800',
    'Services & Consulting':           'bg-lime-100 text-lime-800',
    'Modeling & Software':             'bg-purple-100 text-purple-800',
    'Distributors':                    'bg-rose-100 text-rose-800',
    'Professional Services':           'bg-pink-100 text-pink-800',
  }
  return (
    <span className={`text-[11px] px-1.5 py-0.5 rounded whitespace-nowrap ${COLOR_MAP[type] || 'bg-gray-100 text-gray-700'}`}>
      {type}
    </span>
  )
}

function ChemBadges({ value }) {
  if (!value) return null
  const chems = value.split(/[,;/]+/).map((s) => s.trim()).filter(Boolean).slice(0, 4)
  return (
    <div className="flex gap-1 flex-wrap">
      {chems.map((ch) => (
        <span key={ch} className="text-[10px] px-1 py-0.5 bg-slate-100 text-slate-600 rounded">
          {ch}
        </span>
      ))}
    </div>
  )
}
