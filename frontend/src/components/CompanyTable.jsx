import React, { useEffect, useState, useMemo } from 'react'
import { getCompanies } from '../api/client'
import CompanyDetail from './CompanyDetail'

const PAGE_SIZE = 50

function safeHostname(url) {
  try { return new URL(url).hostname.replace('www.', '') } catch { return url }
}

function fmtNum(val) {
  if (val == null || val === '') return ''
  const n = Number(val)
  if (isNaN(n)) return ''
  return n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function fmtPct(val) {
  if (val == null || val === '') return ''
  const n = Number(val)
  if (isNaN(n)) return ''
  return n.toFixed(2) + '%'
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
  'Electrode & Cell Manufacturing': '#4599FE',
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
  { key: '_row', label: '#', align: 'center', w: 'w-10' },
  { key: 'company_name', label: 'Companies', align: 'left', w: 'min-w-[220px]' },
  { key: 'employee_size', label: 'Employees', align: 'left', w: 'w-20' },
  { key: 'funding_status', label: 'Funding', align: 'left', w: 'w-20' },
  { key: 'revenue_usd', label: 'Revenue ($M)', align: 'right', w: 'w-24' },
  { key: 'total_funding_usd', label: 'Total Funding ($M)', align: 'right', w: 'w-28' },
  { key: 'company_status', label: 'Status', align: 'left', w: 'w-32' },
  { key: 'company_hq_country', label: 'Country', align: 'left', w: 'w-16' },
  { key: 'company_hq_state', label: 'State', align: 'left', w: 'w-12' },
  { key: 'hq_company', label: 'Parent', align: 'left', w: 'w-32' },
  { key: 'company_website', label: 'Website', align: 'left', w: 'w-32' },
  { key: 'naatbatt_member', label: 'NAATBatt', align: 'center', w: 'w-16' },
]

function exportCSV(companies) {
  const headers = [
    'Name', 'Type', 'Status', 'Revenue ($M)', 'Total Funding ($M)',
    'HQ City', 'HQ State', 'Country', 'Website',
    'Parent Company', 'Chemistries', 'Feedstock',
    'NAATBatt Member', 'Contact', 'Contact Email', 'Profile',
  ]
  const rows = companies.map((c) => [
    c.company_name, c.company_type, c.company_status,
    c.revenue_usd, c.total_funding_usd,
    c.company_hq_city, c.company_hq_state, c.company_hq_country, c.company_website,
    c.hq_company, c.chemistries, c.feedstock,
    c.naatbatt_member ? 'Yes' : 'No', c.contact_name, c.contact_email, c.summary,
  ])
  const csv = [headers, ...rows].map((r) => r.map((v) => `"${v ?? ''}"`).join(',')).join('\n')
  const blob = new Blob([csv], { type: 'text/csv' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = 'bmw_battery_companies.csv'
  a.click()
}

export default function CompanyTable({ filters }) {
  const [companies, setCompanies] = useState([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [sortKey, setSortKey] = useState('company_name')
  const [sortDir, setSortDir] = useState(1)
  const [page, setPage] = useState(1)
  const [selectedId, setSelectedId] = useState(null)
  const [activeCategory, setActiveCategory] = useState('all')
  const [pageSize, setPageSize] = useState(PAGE_SIZE)

  useEffect(() => {
    setLoading(true)
    getCompanies()
      .then(({ data }) => setCompanies(data))
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

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
    if (filters.types.length) rows = rows.filter((c) => filters.types.includes(c.company_type))
    if (filters.statuses.length) rows = rows.filter((c) => filters.statuses.includes(c.company_status))
    if (filters.segments.length) rows = rows.filter((c) => filters.segments.includes(c.supply_chain_segment))
    if (filters.countries.length)
      rows = rows.filter((c) => filters.countries.some((co) => c.company_hq_country?.includes(co)))

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
    if (key === '_row') return
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
      <div className="flex flex-wrap gap-1.5 px-4 pt-3 pb-2 bg-[#F0F4F8] border-b border-[#B8CAD1]">
        {CATEGORIES.map((cat) => {
          const isActive = activeCategory === cat.key
          const color = CATEGORY_COLORS[cat.key] || '#4599FE'
          const count = categoryCounts[cat.key] || 0
          return (
            <button
              key={cat.key}
              onClick={() => handleCategoryChange(cat.key)}
              className={`px-3 py-1.5 text-xs font-medium rounded-full transition-all ${
                isActive
                  ? 'text-white shadow-sm'
                  : 'bg-white text-gray-600 border border-[#B8CAD1] hover:bg-gray-50'
              }`}
              style={isActive ? { backgroundColor: cat.key === 'all' ? '#4599FE' : color } : {}}
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
      <div className="flex items-center gap-3 px-4 py-2 border-b border-[#B8CAD1] bg-white">
        <input
          type="text"
          placeholder="Search companies…"
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(1) }}
          className="flex-1 border border-[#B8CAD1] rounded px-3 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-[#4599FE]"
        />
        <span className="text-xs text-gray-500">{filtered.length} results</span>
        <button
          onClick={() => exportCSV(filtered)}
          className="bg-[#4599FE] hover:bg-[#3a88ee] text-white text-xs px-3 py-1.5 rounded"
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
                const rev = fmtNum(c.revenue_usd)
                const fund = fmtNum(c.total_funding_usd)
                return (
                  <tr
                    key={c.id}
                    onClick={() => setSelectedId(c.id)}
                    className={`cursor-pointer border-b border-[#EEF1F4] hover:bg-[#EDF3FF] transition-colors ${
                      i % 2 === 0 ? 'bg-white' : 'bg-[#FAFBFC]'
                    }`}
                    style={{ height: '32px' }}
                  >
                    {/* Row # */}
                    <td className="px-3 py-1.5 text-center text-[#8899A6] font-mono">{rowNum}</td>
                    {/* Company name */}
                    <td className="px-3 py-1.5 font-medium text-[#1A5FAD] whitespace-nowrap">{c.company_name}</td>
                    {/* Employees */}
                    <td className="px-3 py-1.5 text-gray-600 whitespace-nowrap">{c.employee_size || ''}</td>
                    {/* Funding Status */}
                    <td className="px-3 py-1.5 text-gray-600 whitespace-nowrap">{c.funding_status || ''}</td>
                    {/* Revenue */}
                    <td className="px-3 py-1.5 text-right text-gray-700 font-mono whitespace-nowrap">
                      {rev || ''}
                    </td>
                    {/* Total Funding */}
                    <td className="px-3 py-1.5 text-right text-gray-700 font-mono whitespace-nowrap">
                      {fund || ''}
                    </td>
                    {/* Status */}
                    <td className="px-3 py-1.5 whitespace-nowrap">
                      <StatusBadge status={c.company_status} />
                    </td>
                    {/* Country */}
                    <td className="px-3 py-1.5 text-gray-600 whitespace-nowrap">{c.company_hq_country || ''}</td>
                    {/* State */}
                    <td className="px-3 py-1.5 text-gray-600 whitespace-nowrap">{c.company_hq_state || ''}</td>
                    {/* Parent */}
                    <td className="px-3 py-1.5 text-gray-600 whitespace-nowrap max-w-[140px] truncate" title={c.hq_company || ''}>
                      {c.hq_company || ''}
                    </td>
                    {/* Website */}
                    <td className="px-3 py-1.5 whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
                      {c.company_website ? (
                        <a
                          href={c.company_website}
                          target="_blank"
                          rel="noreferrer"
                          className="text-[#1A5FAD] hover:underline"
                        >
                          {safeHostname(c.company_website)}
                        </a>
                      ) : ''}
                    </td>
                    {/* NAATBatt */}
                    <td className="px-3 py-1.5 text-center whitespace-nowrap">
                      {c.naatbatt_member ? (
                        <span className="text-green-600 font-medium">Yes</span>
                      ) : ''}
                    </td>
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
          className="border border-[#B8CAD1] rounded px-1.5 py-0.5 text-xs bg-white"
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
              page === p ? 'bg-[#4599FE] text-white font-bold' : 'hover:bg-gray-200'
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
              page === totalPages ? 'bg-[#4599FE] text-white font-bold' : 'hover:bg-gray-200'
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
          type="number"
          min={1}
          max={totalPages}
          className="w-12 border border-[#B8CAD1] rounded px-1.5 py-0.5 text-xs bg-white"
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              const v = Math.max(1, Math.min(totalPages, Number(e.target.value)))
              setPage(v)
            }
          }}
          placeholder="Page"
        />
      </div>

      {/* Detail panel */}
      {selectedId && (
        <CompanyDetail companyId={selectedId} onClose={() => setSelectedId(null)} />
      )}
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
  if (!status) return <span className="text-gray-400">—</span>
  return (
    <span className={`text-[11px] px-1.5 py-0.5 rounded ${MAP[status] || 'bg-gray-100 text-gray-700'}`}>
      {status}
    </span>
  )
}
