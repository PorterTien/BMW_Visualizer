import React, { useEffect, useState, useMemo } from 'react'
import { MapContainer, TileLayer, CircleMarker, Popup, useMap } from 'react-leaflet'
import { getCompaniesMap } from '../api/client'

const LIGHT_TILES = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'
const DARK_TILES = 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
const LIGHT_ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
const DARK_ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>'

const TYPE_COLORS = {
  'start-up': '#8B5CF6',
  'cell supplier': '#4599FE',
  'materials supplier': '#F59E0B',
  'EV OEM': '#10B981',
  'testing partner': '#EC4899',
  'prototyping partner': '#F97316',
  'recycler': '#6B7280',
  'equipment supplier': '#06B6D4',
  'R&D': '#3B82F6',
  'services': '#84CC16',
  'modeling/software': '#A855F7',
  'other': '#9CA3AF',
}

function Legend() {
  const [collapsed, setCollapsed] = React.useState(false)
  return (
    <div className="absolute bottom-8 right-4 z-[1000] bg-white rounded-lg shadow-lg text-xs border border-[#B8CAD1] overflow-hidden">
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="flex items-center justify-between w-full px-3 py-2 font-semibold text-[#031E49] hover:bg-[#F0F4F8]"
      >
        <span>Company Type</span>
        <span className="ml-4 text-gray-400">{collapsed ? '▲' : '▼'}</span>
      </button>
      {!collapsed && (
        <div className="px-3 pb-3 max-h-56 overflow-y-auto space-y-1">
          {Object.entries(TYPE_COLORS).map(([type, color]) => (
            <div key={type} className="flex items-center gap-2">
              <span
                className="inline-block w-3 h-3 rounded-full flex-shrink-0"
                style={{ backgroundColor: color }}
              />
              <span className="text-gray-700 capitalize">{type}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function CompanyMap({ filters, onSelectCompany, highlightName, darkMode }) {
  const [companies, setCompanies] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getCompaniesMap()
      .then(({ data }) => setCompanies(data))
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  const filtered = useMemo(() => companies.filter((c) => {
    if (filters.search) {
      const q = filters.search.toLowerCase()
      if (!c.company_name?.toLowerCase().includes(q)) return false
    }
    if (filters.types.length && !filters.types.includes(c.company_type)) return false
    if (filters.statuses.length && !filters.statuses.includes(c.company_status)) return false
    if (filters.segments.length && !filters.segments.includes(c.supply_chain_segment)) return false
    if (filters.countries.length && !filters.countries.some((co) => c.company_hq_country?.includes(co))) return false
    return true
  }), [companies, filters])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500">
        Loading map data…
      </div>
    )
  }

  return (
    <div className="relative flex-1 min-h-0">
      <MapContainer
        center={[39.5, -98.35]}
        zoom={4}
        style={{ height: '100%', width: '100%' }}
        zoomAnimation={true}
        zoomAnimationThreshold={4}
        wheelPxPerZoomLevel={120}
        wheelDebounceTime={80}
      >
        <TileLayer
          key={darkMode ? 'dark' : 'light'}
          attribution={darkMode ? DARK_ATTR : LIGHT_ATTR}
          url={darkMode ? DARK_TILES : LIGHT_TILES}
        />
        {filtered.map((c) => {
          const isHighlighted = highlightName && c.company_name === highlightName
          return (
          <CircleMarker
            key={c.id}
            center={[c.lat, c.lng]}
            radius={isHighlighted ? 12 : 7}
            pathOptions={{
              color: isHighlighted ? '#EE0405' : (TYPE_COLORS[c.company_type] || '#9CA3AF'),
              fillColor: isHighlighted ? '#EE0405' : (TYPE_COLORS[c.company_type] || '#9CA3AF'),
              fillOpacity: isHighlighted ? 1 : 0.8,
              weight: isHighlighted ? 3 : 1.5,
            }}
          >
            <Popup>
              <div className="min-w-[180px]">
                <div className="font-bold text-[#031E49] text-sm mb-1">{c.company_name}</div>
                <div className="text-xs text-gray-600 space-y-0.5">
                  <div>
                    <span className="font-medium">Type:</span>{' '}
                    <span style={{ color: TYPE_COLORS[c.company_type] }}>
                      {c.company_type || 'Unknown'}
                    </span>
                  </div>
                  <div>
                    <span className="font-medium">Status:</span> {c.company_status || '—'}
                  </div>
                  <div>
                    <span className="font-medium">HQ:</span>{' '}
                    {[c.company_hq_city, c.company_hq_state].filter(Boolean).join(', ') || '—'}
                  </div>
                  {c.company_website && (
                    <div>
                      <a
                        href={c.company_website}
                        target="_blank"
                        rel="noreferrer"
                        className="text-[#4599FE] hover:underline"
                      >
                        Website
                      </a>
                    </div>
                  )}
                </div>
                <button
                  onClick={() => onSelectCompany(c.id)}
                  className="mt-2 w-full bg-[#4599FE] text-white text-xs py-1 rounded hover:bg-[#4599FE]"
                >
                  Details
                </button>
              </div>
            </Popup>
          </CircleMarker>
          )
        })}
      </MapContainer>
      <Legend />
      <div className="absolute top-3 left-14 z-[1000] bg-white rounded shadow px-3 py-1.5 text-xs text-gray-600 border border-[#B8CAD1]">
        Showing <strong>{filtered.length}</strong> of <strong>{companies.length}</strong> companies
      </div>
    </div>
  )
}
