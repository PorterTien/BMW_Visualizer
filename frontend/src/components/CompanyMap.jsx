import React, { useEffect, useState, useMemo, useCallback } from 'react'
import { MapContainer, TileLayer, CircleMarker, Marker, Popup } from 'react-leaflet'
import MarkerClusterGroup from 'react-leaflet-cluster'
import L from 'leaflet'
import { getCompaniesMap, getWatchlist, addToWatchlist, removeFromWatchlist } from '../api/client'
import { COUNTRY_ALIASES } from '../utils/countries'

const LIGHT_TILES = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'
const DARK_TILES = 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
const LIGHT_ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
const DARK_ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>'

const SPLIT_ZOOM = 8

const TYPE_COLORS = {
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
  'other': '#9CA3AF',
}

/* ── Heat-style bubble cluster icon ── */

function getHeatStyle(count) {
  if (count >= 50) return { color: '#EF4444', bg: 'rgba(239, 68, 68, 0.55)', glow: 'rgba(239, 68, 68, 0.25)' }
  if (count >= 30) return { color: '#F97316', bg: 'rgba(249, 115, 22, 0.55)', glow: 'rgba(249, 115, 22, 0.25)' }
  if (count >= 15) return { color: '#EAB308', bg: 'rgba(234, 179, 8, 0.55)', glow: 'rgba(234, 179, 8, 0.25)' }
  if (count >= 5)  return { color: '#06B6D4', bg: 'rgba(6, 182, 212, 0.55)', glow: 'rgba(6, 182, 212, 0.25)' }
  return { color: '#3B82F6', bg: 'rgba(59, 130, 246, 0.55)', glow: 'rgba(59, 130, 246, 0.25)' }
}

function createClusterIcon(cluster) {
  const count = cluster.getChildCount()
  const { color, bg, glow } = getHeatStyle(count)
  const size = Math.min(90, 44 + Math.sqrt(count) * 4)
  return L.divIcon({
    html: `<div class="heatmap-zone" style="
      width:${size}px;height:${size}px;
      background:radial-gradient(circle, ${bg} 30%, ${glow} 65%, transparent 100%);
      border:2px solid ${color};
      color:#fff;
      font-size:${count >= 100 ? 13 : 15}px;
      box-shadow:0 0 ${Math.round(size * 0.6)}px ${glow};
    "><span>${count}</span></div>`,
    className: 'heatmap-cluster-icon',
    iconSize: L.point(size, size),
  })
}

/* ── Small dot for individual markers in heatmap mode ── */

function createDotIcon(companyType, isHQ) {
  const fill = TYPE_COLORS[companyType] || '#9CA3AF'
  const sz = isHQ ? 14 : 10
  return L.divIcon({
    html: `<div style="width:${sz}px;height:${sz}px;border-radius:50%;background:${fill};border:${isHQ ? 2 : 1}px solid ${fill};opacity:0.85;${isHQ ? 'box-shadow:0 0 4px ' + fill + ';' : ''}"></div>`,
    className: 'heatmap-dot-icon',
    iconSize: L.point(sz, sz),
    iconAnchor: L.point(sz / 2, sz / 2),
  })
}

/* ── Shared popup content ── */

function PopupContent({ c, onSelectCompany, watchlistIds, onToggleWatchlist }) {
  const baseColor = TYPE_COLORS[c.company_type] || '#9CA3AF'
  const isHQ = c.is_hq
  const starred = watchlistIds.has(c.id)
  const [busy, setBusy] = React.useState(false)

  async function handleStar(e) {
    e.stopPropagation()
    setBusy(true)
    await onToggleWatchlist(c.id, starred)
    setBusy(false)
  }

  return (
    <div className="min-w-[200px]">
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="font-bold text-bmw-text-primary text-sm leading-tight">{c.company_name}</div>
        <button
          onClick={handleStar}
          disabled={busy}
          title={starred ? 'Remove from watchlist' : 'Add to watchlist'}
          className="flex-shrink-0 text-lg leading-none transition-colors disabled:opacity-40"
          style={{ color: starred ? '#F59E0B' : '#D1D5DB' }}
        >
          {starred ? '★' : '☆'}
        </button>
      </div>
      {c.facility_name && c.facility_name !== c.company_name && (
        <div className="text-xs text-bmw-text-secondary font-medium mb-1">{c.facility_name}</div>
      )}
      <div className="text-xs text-gray-600 space-y-0.5">
        <div>
          <span className="font-medium">{isHQ ? 'HQ' : 'Facility'}:</span>{' '}
          {[c.facility_city, c.facility_state, c.facility_country].filter(Boolean).join(', ') || '—'}
        </div>
        <div>
          <span className="font-medium">Type:</span>{' '}
          <span style={{ color: baseColor }}>{c.company_type || 'Unknown'}</span>
        </div>
        <div><span className="font-medium">Segment:</span> {c.supply_chain_segment || '—'}</div>
        <div><span className="font-medium">Status:</span> {c.status || c.company_status || '—'}</div>
        {c.product && <div><span className="font-medium">Product:</span> {c.product}</div>}
        {c.product_type && <div><span className="font-medium">Product Type:</span> {c.product_type}</div>}
        {c.capacity && (
          <div><span className="font-medium">Capacity:</span> {c.capacity}{c.capacity_units ? ` ${c.capacity_units}` : ''}</div>
        )}
        {c.workforce && <div><span className="font-medium">Workforce:</span> {c.workforce}</div>}
        {c.chemistries && <div><span className="font-medium">Chemistries:</span> {c.chemistries}</div>}
        {c.company_website && (
          <div>
            <a href={c.company_website} target="_blank" rel="noreferrer" className="text-bmw-blue hover:underline">
              Website
            </a>
          </div>
        )}
      </div>
      <button
        onClick={() => onSelectCompany(c.id)}
        className="mt-2 w-full bg-bmw-blue text-white text-xs py-1 rounded hover:bg-[#3a88ee]"
      >
        Company Details
      </button>
    </div>
  )
}

/* ── Legend ── */

function Legend({ hoveredType, pinnedType, onHoverType, onPinType }) {
  const [collapsed, setCollapsed] = React.useState(false)
  const activeType = pinnedType || hoveredType
  return (
    <div className={`absolute bottom-8 left-4 z-[1000] rounded-lg shadow-lg text-xs border border-bmw-border overflow-hidden transition-colors ${
      collapsed ? 'bg-white' : 'bg-bmw-gray-light'
    }`}>
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="flex items-center justify-between w-full px-3 py-2 font-semibold text-[text-bmw-text-primary] hover:bg-white/80"
      >
        <span className="flex items-center gap-1">
          <span>Company Type</span>
          {/* Keep icon slot fixed so clicking pin never changes legend width */}
          <span
            className={`text-[10px] w-3 inline-flex justify-center ${pinnedType ? 'text-bmw-blue' : 'text-transparent'}`}
            aria-hidden="true"
          >
            📌
          </span>
        </span>
        <span className="ml-4 text-gray-400">{collapsed ? '▲' : '▼'}</span>
      </button>
      {!collapsed && (
        <div
          className="px-2 pb-2 pt-1 space-y-0.5 bg-white"
          onMouseLeave={() => onHoverType?.(null)}
        >
          {Object.entries(TYPE_COLORS).map(([type, color]) => {
            const isActive = activeType === type
            const isDimmed = activeType && activeType !== type
            const isPinned = pinnedType === type
            return (
              <div
                key={type}
                onMouseEnter={() => onHoverType?.(type)}
                onClick={() => onPinType?.(type)}
                title={isPinned ? 'Click to unpin' : 'Click to pin highlight'}
                className={`flex items-center gap-2 px-2 py-0.5 rounded cursor-pointer transition-all ${
                  isActive ? 'bg-gray-100 font-semibold' : isDimmed ? 'opacity-40' : ''
                }`}
              >
                <span
                  className="inline-block w-3 h-3 rounded-full flex-shrink-0 transition-transform"
                  style={{
                    backgroundColor: color,
                    boxShadow: isActive ? `0 0 6px ${color}` : 'none',
                    transform: isActive ? 'scale(1.25)' : 'scale(1)',
                  }}
                />
                <span className="text-gray-700 capitalize text-[11px] flex-1">{type}</span>
                {isPinned && <span className="text-[10px] text-bmw-blue">📌</span>}
              </div>
            )
          })}
          {pinnedType && (
            <button
              onClick={() => onPinType?.(pinnedType)}
              className="w-full mt-1 text-[10px] text-bmw-blue hover:underline text-left px-2 py-0.5"
            >
              Clear pin
            </button>
          )}
        </div>
      )}
    </div>
  )
}

/* ── Heat legend (discrete bands) ── */

function HeatLegend() {
  const bands = [
    { label: '50+', color: '#EF4444' },
    { label: '30–49', color: '#F97316' },
    { label: '15–29', color: '#EAB308' },
    { label: '5–14', color: '#06B6D4' },
    { label: '1–4', color: '#3B82F6' },
  ]
  return (
    <div className="absolute bottom-8 left-4 z-[1000] bg-white rounded-lg shadow-lg text-xs border border-bmw-border px-3 py-2">
      <div className="font-semibold text-[text-bmw-text-primary] mb-1.5">Density</div>
      <div className="space-y-1">
        {bands.map(({ label, color }) => (
          <div key={label} className="flex items-center gap-2">
            <span className="inline-block w-3 h-3 rounded-full flex-shrink-0" style={{ backgroundColor: color, opacity: 0.8 }} />
            <span className="text-gray-600">{label}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ── Main component ── */

export default function CompanyMap({ filters, onSelectCompany, highlightName }) {
  const [companies, setCompanies] = useState([])
  const [loading, setLoading] = useState(true)
  const [heatmapMode, setHeatmapMode] = useState(false)
  const [watchlistIds, setWatchlistIds] = useState(new Set())
  const [hoveredType, setHoveredType] = useState(null)
  // Click-to-pin: when a legend row is clicked, its type stays highlighted
  // until the user clicks it again (or clicks a different row). Pinned state
  // takes precedence over hover so the markers don't flicker.
  const [pinnedType, setPinnedType] = useState(null)
  const activeType = pinnedType || hoveredType

  useEffect(() => {
    getCompaniesMap()
      .then(({ data }) => setCompanies(data))
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    getWatchlist()
      .then(({ data }) => setWatchlistIds(new Set(data.map((w) => w.company_id))))
      .catch(() => {})
  }, [])

  const handleToggleWatchlist = useCallback(async (companyId, currentlyStarred) => {
    // Optimistic update; rollback + re-fetch on failure so the star doesn't
    // drift out of sync with the server.
    setWatchlistIds((prev) => {
      const next = new Set(prev)
      if (currentlyStarred) next.delete(companyId); else next.add(companyId)
      return next
    })
    try {
      if (currentlyStarred) await removeFromWatchlist(companyId)
      else await addToWatchlist(companyId)
    } catch (err) {
      console.error('Watchlist toggle failed:', err)
      getWatchlist()
        .then(({ data }) => setWatchlistIds(new Set(data.map((w) => w.company_id))))
        .catch(() => {})
    }
  }, [])

  const filtered = useMemo(() => companies.filter((c) => {
    if (filters.search) {
      const q = filters.search.toLowerCase()
      if (!c.company_name?.toLowerCase().includes(q)) return false
    }
    if (filters.statuses.length && !filters.statuses.includes(c.company_status)) return false
    if (filters.segments.length) {
      const segs = (c.supply_chain_segment || '').split(' | ')
      if (!filters.segments.some((seg) => segs.includes(seg))) return false
    }
    if (filters.countries.length) {
      const hq = (c.company_hq_country || '').trim().toLowerCase()
      const fac = (c.facility_country || '').trim().toLowerCase()
      const matched = filters.countries.some((co) => {
        const aliases = COUNTRY_ALIASES[co] || [co.toLowerCase()]
        return aliases.includes(hq) || aliases.includes(fac)
      })
      if (!matched) return false
    }
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
        worldCopyJump={false}
        maxBounds={[[-90, -180], [90, 180]]}
        maxBoundsViscosity={1.0}
        zoomAnimation={true}
        zoomAnimationThreshold={4}
        wheelPxPerZoomLevel={120}
        wheelDebounceTime={80}
        minZoom={2}
      >
        <TileLayer
          key="light"
          attribution={LIGHT_ATTR}
          url={LIGHT_TILES}
          noWrap={true}
          bounds={[[-90, -180], [90, 180]]}
        />

        {heatmapMode ? (
          <MarkerClusterGroup
              key="heatmap-clusters"
              chunkedLoading
              iconCreateFunction={createClusterIcon}
              maxClusterRadius={80}
              disableClusteringAtZoom={SPLIT_ZOOM}
              spiderfyOnMaxZoom={false}
              animate={true}
              animateAddingMarkers={false}
            >
              {filtered.map((c, idx) => (
                <Marker
                  key={`heat-${c.id}-${idx}`}
                  position={[c.lat, c.lng]}
                  icon={createDotIcon(c.company_type, c.is_hq)}
                >
                  <Popup>
                    <PopupContent c={c} onSelectCompany={onSelectCompany} watchlistIds={watchlistIds} onToggleWatchlist={handleToggleWatchlist} />
                  </Popup>
                </Marker>
              ))}
            </MarkerClusterGroup>
        ) : (
          filtered.map((c, idx) => {
            const isHighlighted = highlightName && c.company_name === highlightName
            const isHQ = c.is_hq
            const baseColor = TYPE_COLORS[c.company_type] || '#9CA3AF'
            // Legend-hover highlight: when the user mouses over a legend row,
            // markers of that type pop (fully opaque, larger radius, heavier
            // stroke) and every other marker fades out so the group is easy
            // to pick out of the cluttered map.
            const isTypeHovered = activeType && c.company_type === activeType
            const isTypeDimmed = activeType && !isTypeHovered
            const baseRadius = isHighlighted ? 12 : isHQ ? 8 : 6
            const radius = isTypeHovered ? baseRadius + 4 : baseRadius
            const baseFillOpacity = isHighlighted ? 1 : isHQ ? 0.9 : 0.7
            const fillOpacity = isTypeDimmed ? 0.08 : isTypeHovered ? 1 : baseFillOpacity
            const strokeOpacity = isTypeDimmed ? 0.15 : 1
            const baseWeight = isHighlighted ? 3 : isHQ ? 2 : 1
            const weight = isTypeHovered ? baseWeight + 1 : baseWeight
            return (
              <React.Fragment key={`${c.id}-${idx}`}>
                {isHQ && (
                  <CircleMarker
                    center={[c.lat, c.lng]}
                    radius={isHighlighted ? 18 : isTypeHovered ? 17 : 13}
                    pathOptions={{
                      color: isHighlighted ? '#EE0405' : baseColor,
                      fillColor: 'transparent',
                      fillOpacity: 0,
                      weight: 2,
                      opacity: strokeOpacity,
                      dashArray: '4 4',
                    }}
                    interactive={false}
                  />
                )}
                <CircleMarker
                  center={[c.lat, c.lng]}
                  radius={radius}
                  pane={isTypeHovered ? 'markerPane' : undefined}
                  pathOptions={{
                    color: isHighlighted ? '#EE0405' : baseColor,
                    fillColor: isHighlighted ? '#EE0405' : baseColor,
                    fillOpacity,
                    opacity: strokeOpacity,
                    weight,
                  }}
                >
                  <Popup>
                    <PopupContent c={c} onSelectCompany={onSelectCompany} watchlistIds={watchlistIds} onToggleWatchlist={handleToggleWatchlist} />
                  </Popup>
                </CircleMarker>
              </React.Fragment>
            )
          })
        )}
      </MapContainer>

      {/* Heatmap toggle */}
      <button
        onClick={() => setHeatmapMode(!heatmapMode)}
        className={`absolute top-3 right-4 z-[1000] flex items-center gap-1.5 px-3 py-1.5 rounded-lg shadow text-xs font-semibold border transition-all ${
          heatmapMode
            ? 'bg-gradient-to-r from-red-500 to-orange-400 text-white border-red-400'
            : 'bg-white text-gray-600 border-bmw-border hover:bg-bmw-gray-light'
        }`}
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 2C8 7 4 10 4 14a8 8 0 0016 0c0-4-4-7-8-12z" />
        </svg>
        Heatmap
      </button>

      {heatmapMode ? <HeatLegend /> : (
        <Legend
          hoveredType={hoveredType}
          pinnedType={pinnedType}
          onHoverType={setHoveredType}
          onPinType={(type) => setPinnedType((cur) => (cur === type ? null : type))}
        />
      )}

      <div className="absolute top-3 left-14 z-[1000] bg-white rounded shadow px-3 py-1.5 text-xs text-gray-600 border border-bmw-border">
        Showing <strong>{filtered.length}</strong> of <strong>{companies.length}</strong> locations
      </div>
    </div>
  )
}
