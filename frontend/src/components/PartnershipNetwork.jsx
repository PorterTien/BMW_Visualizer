import React, { useEffect, useState, useRef, useCallback } from 'react'
import { getCompaniesNetwork } from '../api/client'

const LINK_COLORS = {
  'Joint Venture': '#34D399',
  'Investment': '#60A5FA',
  'MOU': '#FBBF24',
  'Off-take': '#A78BFA',
  'Supply Agreement': '#F472B6',
  'Other': '#64748B',
}

const NODE_COLORS = {
  'start-up': '#A78BFA',
  'cell supplier': '#38BDF8',
  'materials supplier': '#FBBF24',
  'EV OEM': '#34D399',
  'testing partner': '#F472B6',
  'prototyping partner': '#FB923C',
  'recycler': '#94A3B8',
  'equipment supplier': '#22D3EE',
  'R&D': '#818CF8',
  'services': '#86EFAC',
  'modeling/software': '#C084FC',
  'other': '#64748B',
}

const NODE_FILL_DARK = {
  'start-up': '#7C3AED',
  'cell supplier': '#0EA5E9',
  'materials supplier': '#D97706',
  'EV OEM': '#059669',
  'testing partner': '#DB2777',
  'prototyping partner': '#EA580C',
  'recycler': '#64748B',
  'equipment supplier': '#0891B2',
  'R&D': '#4F46E5',
  'services': '#16A34A',
  'modeling/software': '#9333EA',
  'other': '#475569',
}

const NODE_FILL_LIGHT = {
  'start-up': '#C4B5FD',
  'cell supplier': '#7DD3FC',
  'materials supplier': '#FDE68A',
  'EV OEM': '#6EE7B7',
  'testing partner': '#F9A8D4',
  'prototyping partner': '#FDBA74',
  'recycler': '#CBD5E1',
  'equipment supplier': '#67E8F9',
  'R&D': '#A5B4FC',
  'services': '#86EFAC',
  'modeling/software': '#D8B4FE',
  'other': '#CBD5E1',
}

const SCALE_METRICS = [
  { key: 'employees', label: 'Employees', format: (v) => `${v?.toLocaleString()} emp.` },
  { key: 'market_cap_usd', label: 'Market Cap', format: (v) => `$${v >= 1000 ? (v / 1000).toFixed(1) + 'B' : v + 'M'}` },
  { key: 'revenue_usd', label: 'Revenue', format: (v) => `$${v >= 1000 ? (v / 1000).toFixed(1) + 'B' : v + 'M'}` },
  { key: 'total_funding_usd', label: 'Total Funding', format: (v) => `$${v >= 1000 ? (v / 1000).toFixed(1) + 'B' : v + 'M'}` },
]

function getNodeRadius(node, metricKey) {
  if (node.in_db === false) return 5
  const val = node[metricKey]
  if (!val) return 7
  switch (metricKey) {
    case 'employees':        return Math.max(7, Math.min(36, Math.sqrt(val / 3) + 4))
    case 'market_cap_usd':   return Math.max(7, Math.min(36, Math.sqrt(val / 50) + 4))
    case 'revenue_usd':      return Math.max(7, Math.min(36, Math.sqrt(val / 20) + 4))
    case 'total_funding_usd':return Math.max(7, Math.min(36, Math.sqrt(val / 10) + 4))
    default:                 return 8
  }
}

export default function PartnershipNetwork({ onSelectCompany, darkMode }) {
  const dark = darkMode ?? false
  const [graphData, setGraphData] = useState({ nodes: [], links: [] })
  const [loading, setLoading] = useState(true)
  const [highlight, setHighlight] = useState('')
  const [tooltip, setTooltip] = useState(null)
  const [FG, setFG] = useState(null)
  const [hoveredNode, setHoveredNode] = useState(null)
  const [filterType, setFilterType] = useState('all')
  const [scaleMetric, setScaleMetric] = useState('employees')
  const containerRef = useRef(null)
  const fgRef = useRef(null)
  const animRadiiRef = useRef({})
  const [dims, setDims] = useState({ w: 800, h: 600 })
  const layoutDoneRef = useRef(false)

  useEffect(() => {
    import('react-force-graph-2d').then((mod) => setFG(() => mod.default))
  }, [])

  useEffect(() => {
    getCompaniesNetwork()
      .then(({ data }) => setGraphData(data))
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (!containerRef.current) return
    const obs = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect
      setDims({ w: width, h: height })
    })
    obs.observe(containerRef.current)
    return () => obs.disconnect()
  }, [])

  // Animate radius transitions on metric change
  useEffect(() => {
    const startTime = Date.now()
    const duration = 500
    const animate = () => {
      if (Date.now() - startTime < duration) {
        fgRef.current?.refresh()
        requestAnimationFrame(animate)
      }
    }
    requestAnimationFrame(animate)
  }, [scaleMetric])

  // Configure strong repulsion for good initial spacing
  useEffect(() => {
    const fg = fgRef.current
    if (!fg) return
    const t = setTimeout(() => {
      const charge = fg.d3Force('charge')
      if (charge) charge.strength(-600).distanceMax(800)
      const center = fg.d3Force('center')
      if (center) center.strength(0.03)
      fg.d3ReheatSimulation()
    }, 50)
    return () => clearTimeout(t)
  }, [FG])

  // Refresh canvas when theme changes
  useEffect(() => {
    fgRef.current?.refresh()
  }, [dark])

  const filteredGraph = React.useMemo(() => {
    if (filterType === 'all') return graphData
    const filteredLinks = graphData.links.filter((l) => l.type === filterType)
    const connectedIds = new Set()
    filteredLinks.forEach((l) => {
      connectedIds.add(typeof l.source === 'object' ? l.source.id : l.source)
      connectedIds.add(typeof l.target === 'object' ? l.target.id : l.target)
    })
    return {
      nodes: graphData.nodes.filter((n) => connectedIds.has(n.id)),
      links: filteredLinks,
    }
  }, [graphData, filterType])

  // Reset layout when filter changes
  useEffect(() => {
    layoutDoneRef.current = false
  }, [filterType])

  // Pre-compute curvature for each link (handles parallel edges)
  React.useMemo(() => {
    const pairGroups = {}
    filteredGraph.links.forEach((link) => {
      const srcId = typeof link.source === 'object' ? link.source.id : link.source
      const tgtId = typeof link.target === 'object' ? link.target.id : link.target
      const key = [srcId, tgtId].sort().join('::')
      if (!pairGroups[key]) pairGroups[key] = []
      pairGroups[key].push(link)
    })
    Object.values(pairGroups).forEach((group) => {
      if (group.length === 1) {
        group[0].__curvature = 0.2
      } else {
        group.forEach((link, i) => {
          link.__curvature = 0.12 + (i - (group.length - 1) / 2) * 0.16
        })
      }
    })
  }, [filteredGraph.links])

  const nodeCanvasObject = useCallback(
    (node, ctx, globalScale) => {
      if (node.x == null || node.y == null || isNaN(node.x) || isNaN(node.y)) return

      const isHighlighted =
        highlight && node.name.toLowerCase().includes(highlight.toLowerCase())
      const isHovered = hoveredNode && hoveredNode.id === node.id

      const targetR = getNodeRadius(node, scaleMetric)
      const prevR = animRadiiRef.current[node.id] ?? targetR
      const r = prevR + (targetR - prevR) * 0.18
      animRadiiRef.current[node.id] = r

      const FILLS = dark ? NODE_FILL_DARK : NODE_FILL_LIGHT
      const fillColor = node.in_db === false
        ? (dark ? '#1E2D3D' : '#E2E8F0')
        : (FILLS[node.type] || FILLS.other)
      const borderColor = node.in_db === false
        ? (dark ? '#475569' : '#94A3B8')
        : (NODE_COLORS[node.type] || NODE_COLORS.other)

      // Ambient glow (dark mode only)
      if (dark) {
        const ambientGlow = ctx.createRadialGradient(node.x, node.y, r * 0.5, node.x, node.y, r + 6)
        ambientGlow.addColorStop(0, `${borderColor}20`)
        ambientGlow.addColorStop(1, `${borderColor}00`)
        ctx.beginPath()
        ctx.arc(node.x, node.y, r + 6, 0, 2 * Math.PI)
        ctx.fillStyle = ambientGlow
        ctx.fill()
      }

      // Glow ring for hovered / highlighted
      if (isHovered || isHighlighted) {
        const glowAlpha = dark ? '50' : '30'
        const glowMid = dark ? '20' : '10'
        const glow = ctx.createRadialGradient(node.x, node.y, r, node.x, node.y, r + 14)
        glow.addColorStop(0, `${borderColor}${glowAlpha}`)
        glow.addColorStop(0.5, `${borderColor}${glowMid}`)
        glow.addColorStop(1, `${borderColor}00`)
        ctx.beginPath()
        ctx.arc(node.x, node.y, r + 14, 0, 2 * Math.PI)
        ctx.fillStyle = glow
        ctx.fill()
      }

      // Main circle
      ctx.beginPath()
      ctx.arc(node.x, node.y, r, 0, 2 * Math.PI)
      ctx.fillStyle = fillColor
      ctx.fill()

      // Border
      ctx.strokeStyle = borderColor
      ctx.lineWidth = isHovered ? 2.5 : 1.2
      ctx.globalAlpha = isHovered ? 1 : 0.7
      ctx.stroke()
      ctx.globalAlpha = 1

      // External partner dashed ring
      if (node.in_db === false) {
        ctx.setLineDash([2, 2])
        ctx.strokeStyle = dark ? '#64748B' : '#94A3B8'
        ctx.lineWidth = 1
        ctx.stroke()
        ctx.setLineDash([])
      }

      // Label — always show
      const fontSize = Math.max(4, Math.min(12, 11 / globalScale))
      ctx.font = `${isHovered ? 'bold ' : ''}${fontSize}px Inter, sans-serif`
      ctx.textAlign = 'center'
      ctx.textBaseline = 'top'

      const label = node.name.length > 24 ? node.name.slice(0, 22) + '\u2026' : node.name
      const textY = node.y + r + 3 / globalScale

      if (dark) {
        ctx.fillStyle = 'rgba(0,0,0,0.7)'
        ctx.fillText(label, node.x + 0.6 / globalScale, textY + 0.6 / globalScale)
        ctx.fillStyle = isHovered ? '#ffffff' : 'rgba(255,255,255,0.82)'
      } else {
        ctx.fillStyle = 'rgba(255,255,255,0.85)'
        ctx.fillText(label, node.x + 0.5 / globalScale, textY + 0.5 / globalScale)
        ctx.fillStyle = isHovered ? '#031E49' : '#374151'
      }
      ctx.fillText(label, node.x, textY)
      ctx.textBaseline = 'alphabetic'
    },
    [highlight, hoveredNode, scaleMetric, dark]
  )

  const linkCanvasObject = useCallback((link, ctx, globalScale) => {
    const start = link.source
    const end = link.target
    if (!start || !end || typeof start !== 'object' || typeof end !== 'object') return
    if (start.x == null || end.x == null || start.y == null || end.y == null) return

    const dx = end.x - start.x
    const dy = end.y - start.y
    const dist = Math.sqrt(dx * dx + dy * dy)
    if (dist < 1) return

    const nx = -dy / dist
    const ny = dx / dist

    const curvature = link.__curvature || 0.2
    const srcId = start.id != null ? start.id : 0
    const tgtId = end.id != null ? end.id : 0
    const sign = srcId < tgtId ? 1 : -1
    const perpDist = curvature * dist * sign

    const midX = (start.x + end.x) / 2
    const midY = (start.y + end.y) / 2
    const cpX = midX + nx * perpDist
    const cpY = midY + ny * perpDist

    const color = LINK_COLORS[link.type] || LINK_COLORS.Other

    ctx.strokeStyle = color
    ctx.lineWidth = Math.max(0.8, 1.5 / globalScale)
    ctx.globalAlpha = dark ? 0.5 : 0.65
    ctx.beginPath()
    ctx.moveTo(start.x, start.y)
    ctx.quadraticCurveTo(cpX, cpY, end.x, end.y)
    ctx.stroke()

    // Arrowhead
    const tangentAngle = Math.atan2(end.y - cpY, end.x - cpX)
    const targetR = getNodeRadius(end, scaleMetric) + 3
    const arrowTipX = end.x - Math.cos(tangentAngle) * targetR
    const arrowTipY = end.y - Math.sin(tangentAngle) * targetR
    const arrowLen = Math.max(4, 7 / globalScale)
    const arrowHalf = Math.PI / 7

    ctx.fillStyle = color
    ctx.globalAlpha = dark ? 0.7 : 0.8
    ctx.beginPath()
    ctx.moveTo(arrowTipX, arrowTipY)
    ctx.lineTo(
      arrowTipX - arrowLen * Math.cos(tangentAngle - arrowHalf),
      arrowTipY - arrowLen * Math.sin(tangentAngle - arrowHalf)
    )
    ctx.lineTo(
      arrowTipX - arrowLen * Math.cos(tangentAngle + arrowHalf),
      arrowTipY - arrowLen * Math.sin(tangentAngle + arrowHalf)
    )
    ctx.closePath()
    ctx.fill()
    ctx.globalAlpha = 1
  }, [scaleMetric, dark])

  const linkTypes = React.useMemo(
    () => [...new Set(graphData.links.map((l) => l.type).filter(Boolean))],
    [graphData.links]
  )

  const FILLS = dark ? NODE_FILL_DARK : NODE_FILL_LIGHT

  if (loading || !FG) {
    return (
      <div className="flex items-center justify-center h-full bg-[#F0F4F8] text-gray-500">
        {loading ? 'Loading network data\u2026' : 'Initializing graph\u2026'}
      </div>
    )
  }

  if (graphData.links.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full bg-[#F0F4F8] text-gray-400 gap-3">
        <div className="text-lg font-medium text-gray-600">No partnership data yet</div>
        <div className="text-sm text-center max-w-xs text-gray-500">
          Go to the AI Research tab and run &ldquo;Research a Company&rdquo; on a few companies.
          The AI will extract their partnerships and populate this graph.
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col flex-1 min-h-0 bg-[#F0F4F8]">
      {/* Controls */}
      <div className="bg-white border-b border-[#B8CAD1] px-4 py-2.5 flex items-center gap-4 flex-wrap">
        <input
          type="text"
          placeholder="Highlight company\u2026"
          value={highlight}
          onChange={(e) => setHighlight(e.target.value)}
          className="border border-[#B8CAD1] rounded px-3 py-1.5 text-sm w-52 focus:outline-none focus:ring-2 focus:ring-[#4599FE]"
        />

        {/* Scale by selector */}
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-500 whitespace-nowrap">Scale by:</span>
          <div className="flex gap-1">
            {SCALE_METRICS.map((m) => (
              <button
                key={m.key}
                onClick={() => setScaleMetric(m.key)}
                className={`text-xs px-2.5 py-1 rounded-full border transition-colors whitespace-nowrap ${
                  scaleMetric === m.key
                    ? 'bg-[#031E49] text-white border-[#031E49]'
                    : 'border-[#B8CAD1] text-gray-600 hover:border-[#4599FE]'
                }`}
              >
                {m.label}
              </button>
            ))}
          </div>
        </div>

        {/* Link type filter */}
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="text-xs text-gray-500 mr-1">Filter:</span>
          <button
            onClick={() => setFilterType('all')}
            className={`text-xs px-2.5 py-1 rounded-full border transition-colors ${
              filterType === 'all'
                ? 'bg-[#031E49] text-white border-[#031E49]'
                : 'border-[#B8CAD1] text-gray-600 hover:border-[#4599FE]'
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
                  : 'border-[#B8CAD1] text-gray-600 hover:border-[#4599FE]'
              }`}
              style={filterType === type ? { backgroundColor: LINK_COLORS[type] || '#64748B' } : {}}
            >
              {type}
            </button>
          ))}
        </div>

        <div className="ml-auto flex items-center gap-4 text-xs text-gray-500">
          <span>{filteredGraph.nodes.length} companies</span>
          <span>{filteredGraph.links.length} partnerships</span>
          <span className="text-gray-400">Scroll to zoom · Drag to pan · Drag nodes to rearrange</span>
        </div>
      </div>

      {/* Legend */}
      <div className="bg-[#F0F4F8] border-b border-[#B8CAD1] px-4 py-1.5 flex items-center gap-5 flex-wrap">
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-xs font-medium text-gray-500 uppercase tracking-wider">Node:</span>
          {Object.entries(FILLS).slice(0, 7).map(([type, color]) => (
            <div key={type} className="flex items-center gap-1">
              <span
                className="w-3 h-3 rounded-full inline-block border"
                style={{ backgroundColor: color, borderColor: NODE_COLORS[type] || '#64748B' }}
              />
              <span className="text-xs text-gray-600 capitalize">{type}</span>
            </div>
          ))}
        </div>
        <div className="flex items-center gap-3 ml-4 flex-wrap">
          <span className="text-xs font-medium text-gray-500 uppercase tracking-wider">Link:</span>
          {Object.entries(LINK_COLORS).map(([type, color]) => (
            <div key={type} className="flex items-center gap-1">
              <svg width="20" height="10" viewBox="0 0 20 10" className="inline-block">
                <path d="M2 8 Q10 -2 18 8" stroke={color} fill="none" strokeWidth="1.5" opacity="0.7" />
                <polygon points="18,8 14,6 15,9" fill={color} opacity="0.7" />
              </svg>
              <span className="text-xs text-gray-600">{type}</span>
            </div>
          ))}
          <div className="flex items-center gap-1">
            <span className="w-3 h-3 rounded-full inline-block border-2 border-dashed border-gray-400" />
            <span className="text-xs text-gray-500">External partner</span>
          </div>
        </div>
      </div>

      {/* Graph canvas */}
      <div ref={containerRef} className="flex-1 relative">
        <FG
          ref={fgRef}
          graphData={filteredGraph}
          width={dims.w}
          height={dims.h}
          nodeCanvasObject={nodeCanvasObject}
          nodeCanvasObjectMode={() => 'replace'}
          linkCanvasObject={linkCanvasObject}
          linkCanvasObjectMode={() => 'replace'}
          enableNodeDrag={true}
          onNodeDrag={(node) => {
            // Magnet behavior: just move this node, arrows stretch
            node.fx = node.x
            node.fy = node.y
          }}
          onNodeDragEnd={(node) => {
            node.fx = node.x
            node.fy = node.y
          }}
          onNodeClick={(node) => {
            if (node.in_db !== false && onSelectCompany) {
              onSelectCompany(node.id)
            }
          }}
          onNodeHover={(node) => {
            setHoveredNode(node || null)
            if (node) {
              setTooltip({
                name: node.name,
                type: node.type,
                employees: node.employees,
                market_cap_usd: node.market_cap_usd,
                revenue_usd: node.revenue_usd,
                total_funding_usd: node.total_funding_usd,
                segment: node.segment,
                in_db: node.in_db,
              })
            } else {
              setTooltip(null)
            }
          }}
          nodePointerAreaPaint={(node, color, ctx) => {
            if (node.x == null || node.y == null || isNaN(node.x) || isNaN(node.y)) return
            const r = getNodeRadius(node, scaleMetric)
            ctx.beginPath()
            ctx.arc(node.x, node.y, r + 4, 0, 2 * Math.PI)
            ctx.fillStyle = color
            ctx.fill()
          }}
          backgroundColor={dark ? '#0D1B2E' : '#F0F4F8'}
          cooldownTicks={300}
          d3AlphaDecay={0.01}
          d3VelocityDecay={0.3}
          d3AlphaMin={0.001}
          d3LinkDistance={400}
          onEngineStop={() => {
            if (layoutDoneRef.current) return
            layoutDoneRef.current = true
            // Pin all nodes — whiteboard mode: nodes stay where placed
            filteredGraph.nodes.forEach((node) => {
              node.fx = node.x
              node.fy = node.y
            })
          }}
        />

        {/* Fit All button — bottom left */}
        <button
          onClick={() => fgRef.current?.zoomToFit(400, 60)}
          className="absolute bottom-4 left-4 z-10 bg-white border border-[#B8CAD1] rounded-lg shadow px-3 py-2 text-xs font-medium text-gray-600 hover:bg-[#F0F4F8] hover:border-[#4599FE] hover:text-[#4599FE] transition-colors flex items-center gap-1.5"
          title="Fit all nodes in view"
        >
          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
            <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 3.75v4.5m0-4.5h4.5m-4.5 0L9 9M3.75 20.25v-4.5m0 4.5h4.5m-4.5 0L9 15M20.25 3.75h-4.5m4.5 0v4.5m0-4.5L15 9m5.25 11.25h-4.5m4.5 0v-4.5m0 4.5L15 15" />
          </svg>
          Fit All
        </button>

        {/* Tooltip card */}
        {tooltip && (
          <div className="absolute top-4 left-4 bg-white rounded-xl shadow-lg px-4 py-3 text-sm border border-[#B8CAD1] pointer-events-none max-w-[240px]">
            <div className="font-semibold text-[#031E49] leading-tight">{tooltip.name}</div>
            {tooltip.in_db === false && (
              <div className="text-xs text-amber-600 font-medium mt-0.5">External partner</div>
            )}
            {tooltip.type && tooltip.type !== 'other' && (
              <div className="flex items-center gap-1.5 mt-1">
                <span
                  className="w-2 h-2 rounded-full inline-block"
                  style={{ backgroundColor: FILLS[tooltip.type] || '#475569' }}
                />
                <span className="text-xs text-gray-500 capitalize">{tooltip.type}</span>
              </div>
            )}
            {tooltip.segment && (
              <div className="text-xs text-gray-400 mt-0.5">{tooltip.segment}</div>
            )}
            {tooltip.in_db !== false && (
              <div className="mt-2 space-y-0.5">
                {tooltip.employees && (
                  <div className="text-xs text-gray-600 flex justify-between gap-4">
                    <span className="text-gray-400">Employees</span>
                    <span className="font-medium">{tooltip.employees.toLocaleString()}</span>
                  </div>
                )}
                {tooltip.market_cap_usd && (
                  <div className="text-xs text-gray-600 flex justify-between gap-4">
                    <span className="text-gray-400">Market Cap</span>
                    <span className="font-medium">
                      {tooltip.market_cap_usd >= 1000
                        ? `$${(tooltip.market_cap_usd / 1000).toFixed(1)}B`
                        : `$${tooltip.market_cap_usd}M`}
                    </span>
                  </div>
                )}
                {tooltip.revenue_usd && (
                  <div className="text-xs text-gray-600 flex justify-between gap-4">
                    <span className="text-gray-400">Revenue</span>
                    <span className="font-medium">
                      {tooltip.revenue_usd >= 1000
                        ? `$${(tooltip.revenue_usd / 1000).toFixed(1)}B`
                        : `$${tooltip.revenue_usd}M`}
                    </span>
                  </div>
                )}
                {tooltip.total_funding_usd && (
                  <div className="text-xs text-gray-600 flex justify-between gap-4">
                    <span className="text-gray-400">Total Funding</span>
                    <span className="font-medium">
                      {tooltip.total_funding_usd >= 1000
                        ? `$${(tooltip.total_funding_usd / 1000).toFixed(1)}B`
                        : `$${tooltip.total_funding_usd}M`}
                    </span>
                  </div>
                )}
              </div>
            )}
            {tooltip.in_db !== false && (
              <div className="text-xs text-[#4599FE] mt-2">Click to open profile</div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
