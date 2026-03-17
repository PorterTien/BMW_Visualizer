import React, { useState, useEffect, useRef } from 'react'
import { getCompanies } from '../api/client'

const TYPES = [
  'start-up', 'cell supplier', 'materials supplier', 'EV OEM',
  'testing partner', 'prototyping partner', 'recycler', 'equipment supplier',
  'R&D', 'services', 'modeling/software', 'other',
]

const STATUSES = [
  'Commercial', 'Pre-commercial/startup', 'Planned', 'Under Construction',
  'Pilot Plant', 'Closed', 'Operational', 'Paused',
]

const SEGMENTS = [
  'Raw Materials', 'Battery Grade Materials', 'Other Battery Components & Mat.',
  'Electrode & Cell Manufacturing', 'Module-Pack Manufacturing',
  'Recycling-Repurposing', 'Equipment', 'R&D', 'Services & Consulting', 'Modeling & Software',
]

const COUNTRIES = ['US', 'USA', 'Canada']

function DropdownFilter({ label, options, selected, onChange }) {
  const [open, setOpen] = useState(false)
  const activeCount = selected.length

  return (
    <div className="border-b border-[#B8CAD1]">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-3 py-2 text-xs font-semibold text-[#031E49] hover:bg-[#F0F4F8] transition-colors"
      >
        <span>{label}{activeCount > 0 ? <span className="ml-1 text-[#4599FE]">({activeCount})</span> : ''}</span>
        <svg
          className={`flex-shrink-0 w-3 h-3 transition-transform text-gray-400 ${open ? 'rotate-180' : ''}`}
          viewBox="0 0 10 6" fill="none" stroke="currentColor" strokeWidth="1.5"
        >
          <path d="M1 1l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {open && (
        <div>
          {options.map((opt) => (
            <label
              key={opt}
              className="flex items-center gap-2 px-3 py-0.5 cursor-pointer hover:bg-[#F0F4F8]"
            >
              <input
                type="checkbox"
                checked={selected.includes(opt)}
                onChange={() => {
                  const next = selected.includes(opt)
                    ? selected.filter((x) => x !== opt)
                    : [...selected, opt]
                  onChange(next)
                }}
                className="accent-[#4599FE] flex-shrink-0"
              />
              <span className="text-xs text-gray-700">{opt}</span>
            </label>
          ))}
          <button
            onClick={() => onChange([])}
            className={`w-full text-left px-3 py-1.5 text-xs border-t border-[#B8CAD1] ${activeCount > 0 ? 'text-[#4599FE] hover:bg-[#F0F4F8] cursor-pointer' : 'invisible pointer-events-none'}`}
          >
            Clear
          </button>
        </div>
      )}
    </div>
  )
}

export default function Sidebar({ filters, setFilters, collapsed, setCollapsed, onHighlightCompany }) {
  const [companyNames, setCompanyNames] = useState([])
  const [suggestions, setSuggestions] = useState([])
  const [showSuggestions, setShowSuggestions] = useState(false)
  const searchRef = useRef(null)

  const lowerNamesRef = useRef([])

  useEffect(() => {
    getCompanies()
      .then(({ data }) => {
        const names = data.map((c) => c.company_name).filter(Boolean)
        setCompanyNames(names)
        lowerNamesRef.current = names.map((n) => n.toLowerCase())
      })
      .catch(() => {})
  }, [])

  function handleSearchChange(val) {
    setFilters((f) => ({ ...f, search: val }))
    if (val.trim().length > 0) {
      const q = val.toLowerCase()
      const lower = lowerNamesRef.current
      const starts = companyNames.filter((_, i) => lower[i].startsWith(q))
      const contains = companyNames.filter((_, i) => !lower[i].startsWith(q) && lower[i].includes(q))
      setSuggestions([...starts, ...contains].slice(0, 16))
      setShowSuggestions(true)
    } else {
      setSuggestions([])
      setShowSuggestions(false)
    }
  }

  function selectSuggestion(name) {
    setFilters((f) => ({ ...f, search: name }))
    setSuggestions([])
    setShowSuggestions(false)
  }

  return (
    <aside
      className={`bg-white border-r border-[#B8CAD1] transition-all duration-200 flex-shrink-0 flex flex-col ${
        collapsed ? 'w-10' : 'w-64'
      }`}
    >
      <div className="flex items-center justify-between px-2 py-2 border-b border-[#B8CAD1] flex-shrink-0">
        {!collapsed && (
          <span className="text-xs font-semibold text-[#031E49] uppercase tracking-wider">Filters</span>
        )}
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="text-gray-500 hover:text-gray-800 text-lg leading-none"
          title={collapsed ? 'Expand filters' : 'Collapse filters'}
        >
          {collapsed ? '›' : '‹'}
        </button>
      </div>

      {!collapsed && (
        <div
          className="overflow-y-auto flex-1 min-h-0"
          onWheel={(e) => {
            e.preventDefault()
            e.currentTarget.scrollTop += e.deltaY * 0.3
          }}
        >
          {/* Search */}
          <div className="px-3 py-2 border-b border-[#B8CAD1] relative" ref={searchRef}>
            <input
              type="text"
              placeholder="Search companies…"
              value={filters.search}
              onChange={(e) => handleSearchChange(e.target.value)}
              onFocus={() => filters.search && setShowSuggestions(suggestions.length > 0)}
              onBlur={() => setTimeout(() => setShowSuggestions(false), 150)}
              className="w-full border border-[#B8CAD1] rounded px-2 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-[#4599FE]"
            />
            {showSuggestions && suggestions.length > 0 && (
              <div className="absolute left-3 right-3 top-full mt-0 bg-white border border-[#B8CAD1] rounded shadow-lg z-50 overflow-hidden">
                {suggestions.map((name) => (
                  <button
                    key={name}
                    onMouseDown={() => selectSuggestion(name)}
                    onMouseEnter={() => onHighlightCompany?.(name)}
                    onMouseLeave={() => onHighlightCompany?.(null)}
                    className="w-full text-left px-3 py-1.5 text-xs text-gray-700 hover:bg-[#E8F1FF] hover:text-[#031E49] border-b border-[#B8CAD1] last:border-b-0 truncate"
                  >
                    {name}
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="px-3 py-2 border-b border-[#B8CAD1] flex items-center justify-between">
            <span className="text-xs text-gray-400">Filter companies</span>
            <button
              onClick={() => setFilters({ search: '', types: [], statuses: [], segments: [], countries: [] })}
              className="text-xs text-[#4599FE] hover:underline"
            >
              Clear all
            </button>
          </div>

          <DropdownFilter
            label="Type"
            options={TYPES}
            selected={filters.types}
            onChange={(v) => setFilters((f) => ({ ...f, types: v }))}
          />
          <DropdownFilter
            label="Status"
            options={STATUSES}
            selected={filters.statuses}
            onChange={(v) => setFilters((f) => ({ ...f, statuses: v }))}
          />
          <DropdownFilter
            label="Segment"
            options={SEGMENTS}
            selected={filters.segments}
            onChange={(v) => setFilters((f) => ({ ...f, segments: v }))}
          />
          <DropdownFilter
            label="Country"
            options={COUNTRIES}
            selected={filters.countries}
            onChange={(v) => setFilters((f) => ({ ...f, countries: v }))}
          />
        </div>
      )}
    </aside>
  )
}
