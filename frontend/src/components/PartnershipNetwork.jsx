import React, { useEffect, useState, useRef, useCallback, useMemo } from 'react'
import { getCompaniesNetwork } from '../api/client'

/* ── Colour maps (NAATBatt category names) ── */
const TYPE_COLORS = {
  'Raw Materials':                  { border: '#F59E0B', light: '#FDE68A', dark: '#D97706' },
  'Battery Grade Materials':        { border: '#EAB308', light: '#FEF08A', dark: '#CA8A04' },
  'Other Battery Components & Mat.':{ border: '#D97706', light: '#FCD34D', dark: '#B45309' },
  'Electrode & Cell Manufacturing': { border: '#4599FE', light: '#93C5FD', dark: '#2563EB' },
  'Module-Pack Manufacturing':      { border: '#2563EB', light: '#93C5FD', dark: '#1D4ED8' },
  'Recycling-Repurposing':          { border: '#10B981', light: '#6EE7B7', dark: '#059669' },
  'Equipment':                      { border: '#06B6D4', light: '#67E8F9', dark: '#0891B2' },
  'R&D':                            { border: '#8B5CF6', light: '#C4B5FD', dark: '#7C3AED' },
  'Services & Consulting':          { border: '#84CC16', light: '#BEF264', dark: '#65A30D' },
  'Modeling & Software':            { border: '#A855F7', light: '#D8B4FE', dark: '#9333EA' },
  'Distributors':                   { border: '#F97316', light: '#FDBA74', dark: '#EA580C' },
  'Professional Services':          { border: '#EC4899', light: '#F9A8D4', dark: '#DB2777' },
  'other':                          { border: '#9CA3AF', light: '#E5E7EB', dark: '#6B7280' },
}

const LINK_COLORS = {
  'Joint Venture':    '#34D399',
  'Investment':       '#60A5FA',
  'MOU':              '#FBBF24',
  'Off-take':         '#A78BFA',
  'Supply Agreement': '#F472B6',
  'Other':            '#94A3B8',
}

const SCALE_OPTIONS = [
  { key: 'employees',        label: 'Employees' },
  { key: 'revenue_usd',      label: 'Revenue' },
  { key: 'market_cap_usd',   label: 'Market Cap' },
  { key: 'total_funding_usd',label: 'Total Funding' },
]

/* ── Helpers ── */
function typeColors(type, isDark) {
  const c = TYPE_COLORS[type] || TYPE_COLORS.other
  return { fill: isDark ? c.dark : c.light, border: c.border }
}

function nodeRadius(node, metric) {
  if (node.in_db === false) return 5
  const v = node[metric]
  if (!v) return 7
  const scales = { employees: 3, revenue_usd: 20, market_cap_usd: 50, total_funding_usd: 10 }
  return Math.max(7, Math.min(36, Math.sqrt(v / (scales[metric] || 10)) + 4))
}

function fmtVal(v) {
  if (v == null) return null
  return v >= 1000 ? `$${(v / 1000).toFixed(1)}B` : `$${Math.round(v)}M`
}

/* ── Component ── */
export default function PartnershipNetwork({ onSelectCompany, darkMode }) {
  const dark = darkMode ?? false
  const [graphData, setGraphData] = useState({ nodes: [], links: [] })
  const [loading, setLoading] = useState(true)
  const [highlight, setHighlight] = useState('')
  const [filterType, setFilterType] = useState('all')
  const [scaleMetric, setScaleMetric] = useState('employees')
  const [hoveredNode, setHoveredNode] = useState(null)
  const [FG, setFG] = useState(null)
  const containerRef = useRef(null)
  const fgRef = useRef(null)
  const [dims, setDims] = useState({ w: 800, h: 600 })
  const fitDoneRef = useRef(false)

  // Lazy-load react-force-graph-2d
  useEffect(() => {
    import('react-force-graph-2d').then((m) => setFG(() => m.default))
  }, [])

  // Fetch data
  useEffect(() => {
    getCompaniesNetwork()
      .then(({ data }) => setGraphData(data))
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  // Resize observer
  useEffect(() => {
    if (!containerRef.current) return
    const obs = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect
      if (width > 0 && height > 0) setDims({ w: width, h: height })
    })
    obs.observe(containerRef.current)
    return () => obs.disconnect()
  }, [])

  // Configure forces
  useEffect(() => {
    const fg = fgRef.current
    if (!fg) return
    const t = setTimeout(() => {
      fg.d3Force('charge')?.strength(-400).distanceMax(600)
      fg.d3Force('center')?.strength(0.1)
      fg.d3ReheatSimulation()
    }, 100)
    return () => clearTimeout(t)
  }, [FG, graphData])

  // Theme refresh
  useEffect(() => { fgRef.current?.refresh() }, [dark])

  // Animate on metric change
  useEffect(() => {
    let raf
    const start = Date.now()
    const tick = () => {
      if (Date.now() - start < 400) { fgRef.current?.refresh(); raf = requestAnimationFrame(tick) }
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [scaleMetric])

  /* ── Filtered graph ── */
  const filteredGraph = useMemo(() => {
    if (filterType === 'all') return graphData
    const links = graphData.links.filter((l) => l.type === filterType)
    const ids = new Set()
    links.forEach((l) => {
      ids.add(typeof l.source === 'object' ? l.source.id : l.source)
      ids.add(typeof l.target === 'object' ? l.target.id : l.target)
    })
    return { nodes: graphData.nodes.filter((n) => ids.has(n.id)), links }
  }, [graphData, filterType])

  // Re-fit on filter change
  useEffect(() => {
    fitDoneRef.current = false
    const t = setTimeout(() => fgRef.current?.zoomToFit(400, 60), 800)
    return () => clearTimeout(t)
  }, [filterType])

  // Compute link curvatures for parallel edges
  useMemo(() => {
    const groups = {}
    filteredGraph.links.forEach((link) => {
      const s = typeof link.source === 'object' ? link.source.id : link.source
      const t = typeof link.target === 'object' ? link.target.id : link.target
      const key = [Math.min(s, t), Math.max(s, t)].join('::')
      ;(groups[key] ??= []).push(link)
    })
    Object.values(groups).forEach((g) => {
      if (g.length === 1) { g[0]._curve = 0.15; return }
      g.forEach((l, i) => { l._curve = 0.1 + (i - (g.length - 1) / 2) * 0.14 })
    })
  }, [filteredGraph.links])

  const linkTypes = useMemo(
    () => [...new Set(graphData.links.map((l) => l.type).filter(Boolean))],
    [graphData.links]
  )

  /* ── Canvas: node ── */
  const paintNode = useCallback((node, ctx, globalScale) => {
    if (node.x == null || node.y == null) return
    const r = nodeRadius(node, scaleMetric)
    const { fill, border } = node.in_db === false
      ? { fill: dark ? '#1E293B' : '#E2E8F0', border: dark ? '#475569' : '#94A3B8' }
      : typeColors(node.type, dark)
    const isHl = highlight && node.name.toLowerCase().includes(highlight.toLowerCase())
    const isHov = hoveredNode?.id === node.id

    // Glow for hovered/highlighted
    if (isHov || isHl) {
      const g = ctx.createRadialGradient(node.x, node.y, r, node.x, node.y, r + 12)
      g.addColorStop(0, border + (dark ? '50' : '30'))
      g.addColorStop(1, border + '00')
      ctx.beginPath(); ctx.arc(node.x, node.y, r + 12, 0, Math.PI * 2)
      ctx.fillStyle = g; ctx.fill()
    }

    // Circle
    ctx.beginPath(); ctx.arc(node.x, node.y, r, 0, Math.PI * 2)
    ctx.fillStyle = fill; ctx.fill()
    ctx.strokeStyle = border
    ctx.lineWidth = isHov ? 2.5 : 1.2
    ctx.globalAlpha = isHov ? 1 : 0.8
    ctx.stroke(); ctx.globalAlpha = 1

    // Dashed ring for external
    if (node.in_db === false) {
      ctx.setLineDash([2, 2]); ctx.strokeStyle = dark ? '#64748B' : '#94A3B8'
      ctx.lineWidth = 1; ctx.stroke(); ctx.setLineDash([])
    }

    // Label
    const fs = Math.max(4, Math.min(11, 10 / globalScale))
    ctx.font = `${isHov ? 'bold ' : ''}${fs}px Inter, system-ui, sans-serif`
    ctx.textAlign = 'center'; ctx.textBaseline = 'top'
    const label = node.name.length > 22 ? node.name.slice(0, 20) + '\u2026' : node.name
    const ty = node.y + r + 2.5 / globalScale

    // Shadow
    ctx.fillStyle = dark ? 'rgba(0,0,0,0.6)' : 'rgba(255,255,255,0.8)'
    ctx.fillText(label, node.x + 0.5 / globalScale, ty + 0.5 / globalScale)
    // Text
    ctx.fillStyle = dark
      ? (isHov ? '#fff' : 'rgba(255,255,255,0.8)')
      : (isHov ? '#0F172A' : '#374151')
    ctx.fillText(label, node.x, ty)
    ctx.textBaseline = 'alphabetic'
  }, [highlight, hoveredNode, scaleMetric, dark])

  /* ── Canvas: link ── */
  const paintLink = useCallback((link, ctx, globalScale) => {
    const s = link.source, t = link.target
    if (!s || !t || typeof s !== 'object' || typeof t !== 'object') return
    if (s.x == null || t.x == null) return

    const dx = t.x - s.x, dy = t.y - s.y
    const dist = Math.sqrt(dx * dx + dy * dy)
    if (dist < 1) return

    // Control point for curved edge
    const nx = -dy / dist, ny = dx / dist
    const curve = link._curve || 0.15
    const sign = (s.id ?? 0) < (t.id ?? 0) ? 1 : -1
    const cpX = (s.x + t.x) / 2 + nx * curve * dist * sign
    const cpY = (s.y + t.y) / 2 + ny * curve * dist * sign

    const color = LINK_COLORS[link.type] || LINK_COLORS.Other

    ctx.strokeStyle = color
    ctx.lineWidth = Math.max(0.6, 1.2 / globalScale)
    ctx.globalAlpha = dark ? 0.45 : 0.6
    ctx.beginPath(); ctx.moveTo(s.x, s.y); ctx.quadraticCurveTo(cpX, cpY, t.x, t.y); ctx.stroke()

    // Arrowhead
    const angle = Math.atan2(t.y - cpY, t.x - cpX)
    const tr = nodeRadius(t, scaleMetric) + 2
    const ax = t.x - Math.cos(angle) * tr
    const ay = t.y - Math.sin(angle) * tr
    const al = Math.max(3.5, 6 / globalScale)
    const ah = Math.PI / 7
    ctx.fillStyle = color; ctx.globalAlpha = dark ? 0.6 : 0.75
    ctx.beginPath(); ctx.moveTo(ax, ay)
    ctx.lineTo(ax - al * Math.cos(angle - ah), ay - al * Math.sin(angle - ah))
    ctx.lineTo(ax - al * Math.cos(angle + ah), ay - al * Math.sin(angle + ah))
    ctx.closePath(); ctx.fill()
    ctx.globalAlpha = 1
  }, [scaleMetric, dark])

  /* ── Hit area ── */
  const pointerArea = useCallback((node, color, ctx) => {
    if (node.x == null || node.y == null) return
    const r = nodeRadius(node, scaleMetric) + 4
    ctx.beginPath(); ctx.arc(node.x, node.y, r, 0, Math.PI * 2)
    ctx.fillStyle = color; ctx.fill()
  }, [scaleMetric])

  /* ── Loading / empty states ── */
  if (loading || !FG) {
    return (
      <div className={`flex items-center justify-center h-full ${dark ? 'bg-[#0D1B2E] text-gray-400' : 'bg-[#F0F4F8] text-gray-500'}`}>
        {loading ? 'Loading network data\u2026' : 'Initializing graph\u2026'}
      </div>
    )
  }

  if (graphData.links.length === 0) {
    return (
      <div className={`flex flex-col items-center justify-center h-full gap-3 ${dark ? 'bg-[#0D1B2E]' : 'bg-[#F0F4F8]'}`}>
        <div className={`text-lg font-medium ${dark ? 'text-gray-300' : 'text-gray-600'}`}>No partnership data yet</div>
        <div className={`text-sm text-center max-w-xs ${dark ? 'text-gray-500' : 'text-gray-400'}`}>
          Go to the AI Research tab and run &ldquo;Research a Company&rdquo; to populate partnerships.
        </div>
      </div>
    )
  }

  const bg = dark ? '#0D1B2E' : '#F0F4F8'
  const panelBg = dark ? 'bg-[#0F1D2F]' : 'bg-white'
  const borderClr = dark ? 'border-gray-700' : 'border-[#B8CAD1]'
  const textMuted = dark ? 'text-gray-400' : 'text-gray-500'
  const textNormal = dark ? 'text-gray-200' : 'text-gray-600'

  return (
    <div className={`flex flex-col flex-1 min-h-0 ${dark ? 'bg-[#0D1B2E]' : 'bg-[#F0F4F8]'}`}>
      {/* ── Controls bar ── */}
      <div className={`${panelBg} border-b ${borderClr} px-4 py-2.5 flex items-center gap-4 flex-wrap`}>
        <input
          type="text"
          placeholder="Highlight company\u2026"
          value={highlight}
          onChange={(e) => setHighlight(e.target.value)}
          className={`border rounded px-3 py-1.5 text-sm w-48 focus:outline-none focus:ring-2 focus:ring-[#4599FE] ${
            dark ? 'bg-[#1E293B] border-gray-600 text-gray-200 placeholder-gray-500'
                 : 'border-[#B8CAD1] text-gray-800 placeholder-gray-400'
          }`}
        />

        {/* Scale by */}
        <div className="flex items-center gap-2">
          <span className={`text-xs ${textMuted} whitespace-nowrap`}>Scale by:</span>
          <div className="flex gap-1">
            {SCALE_OPTIONS.map((m) => (
              <button
                key={m.key}
                onClick={() => setScaleMetric(m.key)}
                className={`text-xs px-2.5 py-1 rounded-full border transition-colors whitespace-nowrap ${
                  scaleMetric === m.key
                    ? (dark ? 'bg-blue-600 text-white border-blue-600' : 'bg-[#031E49] text-white border-[#031E49]')
                    : `${dark ? 'border-gray-600 text-gray-400 hover:border-blue-500' : 'border-[#B8CAD1] text-gray-600 hover:border-[#4599FE]'}`
                }`}
              >
                {m.label}
              </button>
            ))}
          </div>
        </div>

        {/* Link type filter */}
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className={`text-xs ${textMuted} mr-1`}>Filter:</span>
          <button
            onClick={() => setFilterType('all')}
            className={`text-xs px-2.5 py-1 rounded-full border transition-colors ${
              filterType === 'all'
                ? (dark ? 'bg-blue-600 text-white border-blue-600' : 'bg-[#031E49] text-white border-[#031E49]')
                : `${dark ? 'border-gray-600 text-gray-400 hover:border-blue-500' : 'border-[#B8CAD1] text-gray-600 hover:border-[#4599FE]'}`
            }`}
          >
            All
          </button>
          {linkTypes.map((type) => (
            <button
              key={type}
              onClick={() => setFilterType(filterType === type ? 'all' : type)}
              className={`text-xs px-2.5 py-1 rounded-full border transition-colors ${
                filterType === type
                  ? 'text-white border-transparent'
                  : `${dark ? 'border-gray-600 text-gray-400 hover:border-blue-500' : 'border-[#B8CAD1] text-gray-600 hover:border-[#4599FE]'}`
              }`}
              style={filterType === type ? { backgroundColor: LINK_COLORS[type] || '#94A3B8' } : {}}
            >
              {type}
            </button>
          ))}
        </div>

        <div className={`ml-auto flex items-center gap-4 text-xs ${textMuted}`}>
          <span>{filteredGraph.nodes.length} companies</span>
          <span>{filteredGraph.links.length} partnerships</span>
        </div>
      </div>

      {/* ── Legend ── */}
      <div className={`${dark ? 'bg-[#0D1B2E]' : 'bg-[#F0F4F8]'} border-b ${borderClr} px-4 py-1.5 flex items-center gap-5 flex-wrap`}>
        <div className="flex items-center gap-3 flex-wrap">
          <span className={`text-xs font-medium ${textMuted} uppercase tracking-wider`}>Node:</span>
          {Object.entries(TYPE_COLORS).filter(([k]) => k !== 'other').map(([type, c]) => (
            <div key={type} className="flex items-center gap-1">
              <span className="w-2.5 h-2.5 rounded-full inline-block border"
                style={{ backgroundColor: dark ? c.dark : c.light, borderColor: c.border }} />
              <span className={`text-xs ${textNormal}`}>{type}</span>
            </div>
          ))}
        </div>
        <div className="flex items-center gap-3 ml-4 flex-wrap">
          <span className={`text-xs font-medium ${textMuted} uppercase tracking-wider`}>Link:</span>
          {Object.entries(LINK_COLORS).map(([type, color]) => (
            <div key={type} className="flex items-center gap-1">
              <svg width="18" height="8" viewBox="0 0 18 8" className="inline-block">
                <path d="M1 7 Q9 -1 17 7" stroke={color} fill="none" strokeWidth="1.5" opacity="0.65" />
                <polygon points="17,7 13,5.5 14,8" fill={color} opacity="0.65" />
              </svg>
              <span className={`text-xs ${textNormal}`}>{type}</span>
            </div>
          ))}
          <div className="flex items-center gap-1 ml-1">
            <span className={`w-2.5 h-2.5 rounded-full inline-block border-2 border-dashed ${dark ? 'border-gray-500' : 'border-gray-400'}`} />
            <span className={`text-xs ${textMuted}`}>External partner</span>
          </div>
        </div>
      </div>

      {/* ── Graph ── */}
      <div ref={containerRef} className="flex-1 relative min-h-0">
        <FG
          ref={fgRef}
          graphData={filteredGraph}
          width={dims.w}
          height={dims.h}
          nodeCanvasObject={paintNode}
          nodeCanvasObjectMode={() => 'replace'}
          linkCanvasObject={paintLink}
          linkCanvasObjectMode={() => 'replace'}
          nodePointerAreaPaint={pointerArea}
          enableNodeDrag={true}
          onNodeDrag={(node) => { node.fx = node.x; node.fy = node.y }}
          onNodeDragEnd={(node) => { node.fx = node.x; node.fy = node.y }}
          onNodeClick={(node) => { if (node.in_db !== false && onSelectCompany) onSelectCompany(node.id) }}
          onNodeHover={(node) => setHoveredNode(node || null)}
          backgroundColor={bg}
          cooldownTicks={250}
          d3AlphaDecay={0.015}
          d3VelocityDecay={0.35}
          d3AlphaMin={0.002}
          warmupTicks={50}
          onEngineStop={() => {
            if (fitDoneRef.current) return
            fitDoneRef.current = true
            // Pin nodes after layout settles
            filteredGraph.nodes.forEach((n) => { n.fx = n.x; n.fy = n.y })
            fgRef.current?.zoomToFit(400, 60)
          }}
        />

        {/* Fit All button */}
        <button
          onClick={() => fgRef.current?.zoomToFit(400, 60)}
          className={`absolute bottom-4 left-4 z-10 rounded-lg shadow px-3 py-2 text-xs font-medium transition-colors flex items-center gap-1.5
            ${dark
              ? 'bg-[#1E293B] border border-gray-600 text-gray-300 hover:bg-[#2D3B4F] hover:border-blue-500 hover:text-blue-400'
              : 'bg-white border border-[#B8CAD1] text-gray-600 hover:bg-[#F0F4F8] hover:border-[#4599FE] hover:text-[#4599FE]'
            }`}
          title="Fit all nodes in view"
        >
          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
            <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 3.75v4.5m0-4.5h4.5m-4.5 0L9 9M3.75 20.25v-4.5m0 4.5h4.5m-4.5 0L9 15M20.25 3.75h-4.5m4.5 0v4.5m0-4.5L15 9m5.25 11.25h-4.5m4.5 0v-4.5m0 4.5L15 15" />
          </svg>
          Fit All
        </button>

        {/* Tooltip card */}
        {hoveredNode && (
          <div className={`absolute top-4 left-4 rounded-xl shadow-lg px-4 py-3 text-sm border pointer-events-none max-w-[240px]
            ${dark ? 'bg-[#1E293B] border-gray-600' : 'bg-white border-[#B8CAD1]'}`}
          >
            <div className={`font-semibold leading-tight ${dark ? 'text-gray-100' : 'text-[#031E49]'}`}>
              {hoveredNode.name}
            </div>
            {hoveredNode.in_db === false && (
              <div className="text-xs text-amber-500 font-medium mt-0.5">External partner</div>
            )}
            {hoveredNode.type && hoveredNode.type !== 'other' && (
              <div className="flex items-center gap-1.5 mt-1">
                <span className="w-2 h-2 rounded-full inline-block"
                  style={{ backgroundColor: typeColors(hoveredNode.type, dark).fill }} />
                <span className={`text-xs ${textMuted}`}>{hoveredNode.type}</span>
              </div>
            )}
            {hoveredNode.segment && (
              <div className={`text-xs mt-0.5 ${dark ? 'text-gray-500' : 'text-gray-400'}`}>{hoveredNode.segment}</div>
            )}
            {hoveredNode.in_db !== false && (
              <div className="mt-2 space-y-0.5">
                {hoveredNode.employees != null && (
                  <Row dark={dark} label="Employees" value={hoveredNode.employees.toLocaleString()} />
                )}
                {hoveredNode.revenue_usd != null && (
                  <Row dark={dark} label="Revenue" value={fmtVal(hoveredNode.revenue_usd)} />
                )}
                {hoveredNode.market_cap_usd != null && (
                  <Row dark={dark} label="Total Assets" value={fmtVal(hoveredNode.market_cap_usd)} />
                )}
                {hoveredNode.total_funding_usd != null && (
                  <Row dark={dark} label="Total Funding" value={fmtVal(hoveredNode.total_funding_usd)} />
                )}
              </div>
            )}
            {hoveredNode.in_db !== false && (
              <div className="text-xs text-[#4599FE] mt-2">Click to open profile</div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function Row({ dark, label, value }) {
  return (
    <div className="text-xs flex justify-between gap-4">
      <span className={dark ? 'text-gray-500' : 'text-gray-400'}>{label}</span>
      <span className={`font-medium ${dark ? 'text-gray-200' : 'text-gray-700'}`}>{value}</span>
    </div>
  )
}
