import { useEffect, useState, useRef, useCallback, useMemo, memo } from 'react'
import { getPartnershipGraph, getCompaniesNetwork, enrichPartnershipNetwork, getJob } from '../api/client'
import { forceCollide } from 'd3-force'

/* ── Constants ── */

const INVESTOR_META_ID = '__investors__'

const TYPE_COLORS = {
  'investors_group':                { border: '#F59E0B', light: '#FEF3C7', dark: '#92400E' },
  'Raw Materials':                  { border: '#F59E0B', light: '#FDE68A', dark: '#D97706' },
  'Battery Grade Materials':        { border: '#EAB308', light: '#FEF08A', dark: '#CA8A04' },
  'Other Battery Components & Mat.':{ border: '#D97706', light: '#FCD34D', dark: '#B45309' },
  'Electrode & Cell Manufacturing': { border: '#1C69D4', light: '#93C5FD', dark: '#2563EB' },
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

// Partnership type colors for arrows
const LINK_TYPE_COLORS = {
  jv:               { base: '#34D399', label: 'Joint Venture' },
  supply_agreement: { base: '#F472B6', label: 'Supply Agreement' },
  licensing:        { base: '#FBBF24', label: 'Licensing' },
  equity_stake:     { base: '#60A5FA', label: 'Equity Stake' },
  r_and_d_collab:   { base: '#A78BFA', label: 'R&D Collaboration' },
  government_grant: { base: '#FB923C', label: 'Government Grant' },
  other:            { base: '#94A3B8', label: 'Other' },
}

const SCALE_OPTIONS = [
  { key: 'market_cap_usd',             label: 'Market Cap' },
  { key: 'revenue_usd',                label: 'Revenue' },
  { key: 'employee_count',             label: 'Employees' },
  { key: 'total_funding_usd',          label: 'Total Funding' },
  { key: 'manufacturing_capacity_gwh', label: 'Capacity (GWh)' },
  { key: 'patent_count',               label: 'Patents' },
  { key: 'partnership_investment_total',label: 'Partnership Value' },
]

const STAGES = ['announced', 'signed', 'active', 'dissolved']

const INDUSTRY_SEGMENTS = [
  'cell_manufacturing', 'materials_mining', 'recycling', 'ev_oem', 'energy_storage', 'other'
]

// Supply chain hierarchy for vertical gravity
const HIERARCHY_ORDER = {
  'Raw Materials': 0,
  'Battery Grade Materials': 1,
  'Other Battery Components & Mat.': 2,
  'Electrode & Cell Manufacturing': 3,
  'Module-Pack Manufacturing': 4,
  'Recycling-Repurposing': 5,
  'Equipment': 3,
  'R&D': 2,
  'Services & Consulting': 4,
  'Modeling & Software': 3,
  'Distributors': 5,
  'Professional Services': 4,
  'other': 3,
}

/* ── Helpers ── */

function hashColor(str) {
  let h = 0
  for (let i = 0; i < str.length; i++) h = (Math.imul(31, h) + str.charCodeAt(i)) | 0
  const hue = ((h >>> 0) % 12) * 30
  return { fill: `hsl(${hue}, 55%, 70%)`, border: `hsl(${hue}, 55%, 42%)` }
}

function typeColors(type, isDark, name = '') {
  const c = TYPE_COLORS[type]
  if (c) return { fill: isDark ? c.dark : c.light, border: c.border }
  return hashColor(name || type || 'x')
}

function nodeRadius(node, metric, maxValues, linkCounts) {
  if (node._investorList) return 46
  if (node.in_db === false) return 10
  const v = node[metric]
  if (v != null && v > 0 && maxValues[metric]) {
    const ratio = v / maxValues[metric]
    return Math.max(12, Math.min(44, 12 + Math.sqrt(ratio) * 32))
  }
  // Fall back to partnership count — more connected = larger bubble
  const maxLinks = (linkCounts?.__max) || 1
  const myLinks = (linkCounts?.[node.id]) || 1
  const ratio = myLinks / maxLinks
  return Math.max(10, Math.min(36, 10 + Math.sqrt(ratio) * 26))
}

function linkColor(type, date, isDark) {
  const info = LINK_TYPE_COLORS[type] || LINK_TYPE_COLORS.other
  const base = info.base
  let alpha = isDark ? 0.65 : 0.7
  if (date) {
    const year = parseInt(date)
    if (year >= 2025) alpha = 1.0
    else if (year >= 2023) alpha = isDark ? 0.85 : 0.88
    else if (year >= 2020) alpha = isDark ? 0.75 : 0.78
  }
  return { color: base, alpha }
}

function fmtVal(v) {
  if (v == null) return null
  if (typeof v === 'number') {
    if (v >= 1000) return `$${(v / 1000).toFixed(1)}B`
    if (v >= 1) return `$${Math.round(v)}M`
    return `$${(v * 1000).toFixed(0)}K`
  }
  return String(v)
}

/* ── Component ── */

function PartnershipNetwork({ onSelectCompany }) {
  const dark = false
  const [graphData, setGraphData] = useState({ nodes: [], links: [] })
  const [loading, setLoading] = useState(true)
  const [FG, setFG] = useState(null)
  const containerRef = useRef(null)
  const fgRef = useRef(null)
  const [dims, setDims] = useState({ w: 800, h: 600 })
  const fitDoneRef = useRef(false)
  const zoomLevelRef = useRef(1)
  const rafRef = useRef(null)
  const displayGraphRef = useRef({ nodes: [], links: [] })
  const draggingRef = useRef(null)          // { id, nodeMap, connected: { id: {x,y} } }


  // Controls
  const [searchQuery, setSearchQuery] = useState('')
  const [scaleMetric, setScaleMetric] = useState('employee_count')
  const [panMode, setPanMode] = useState(false)   // default: node drag enabled; toggle for pan-only mode
  // hoveredNodeRef: used inside canvas paintNode callback (stable ref, no re-render)
  // tooltipSetterRef: imperative channel to HoverTooltip — avoids triggering parent re-renders on hover
  const hoveredNodeRef = useRef(null)
  const hoveredConnectedRef = useRef(null)  // Set of node IDs connected to hovered node (incl. itself), null when no hover
  const tooltipSetterRef = useRef(null)
  // State version counter — incremented on hover change so paintNode/paintLink are recreated
  // with a new function reference, forcing react-force-graph to pick up the latest callbacks.
  const [hovVersion, setHovVersion] = useState(0)
  const clickedNodeRef = useRef(null)   // mirrors clickedNode state for canvas use

  // Clicked-node: store only the ID (never store the mutable D3 node object in state)
  const [clickedNodeId, setClickedNodeId] = useState(null)
  clickedNodeRef.current = clickedNodeId

  // Clicked-link detail panel
  const [clickedLink, setClickedLink] = useState(null)

  // Filter state
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [investorPanelOpen, setInvestorPanelOpen] = useState(false)
  const [investorGroup, setInvestorGroup] = useState([])
  const [filterTypes, setFilterTypes] = useState([])       // partnership types
  const [filterStages, setFilterStages] = useState([])
  const [filterSegments, setFilterSegments] = useState([])
  const [filterDateFrom, setFilterDateFrom] = useState('')
  const [filterDateTo, setFilterDateTo] = useState('')
  const [filterGeography, setFilterGeography] = useState('')
  const [filterGovToggle, setFilterGovToggle] = useState('all') // all, gov_only, private_only

  // Classify state
  const [classifyState, setClassifyState] = useState('idle') // idle | running | done | error
  const [classifyResult, setClassifyResult] = useState(null)
  const classifyPollRef = useRef(null)

  const handleClassify = useCallback(async () => {
    setClassifyState('running')
    setClassifyResult(null)
    try {
      const { data } = await enrichPartnershipNetwork()
      const jobId = data.job_id
      classifyPollRef.current = setInterval(async () => {
        try {
          const { data: job } = await getJob(jobId)
          if (job.status === 'complete') {
            clearInterval(classifyPollRef.current)
            setClassifyState('done')
            setClassifyResult(job.result || {})
            // Reload graph to reflect new classifications
            getPartnershipGraph().then(({ data: g }) => setGraphData(g)).catch(() => {})
          } else if (job.status === 'failed') {
            clearInterval(classifyPollRef.current)
            setClassifyState('error')
          }
        } catch (_) {}
      }, 3000)
    } catch (_) {
      setClassifyState('error')
    }
  }, [])

  useEffect(() => () => clearInterval(classifyPollRef.current), [])
  useEffect(() => () => { if (rafRef.current) cancelAnimationFrame(rafRef.current) }, [])

  // Lazy-load react-force-graph-2d
  useEffect(() => {
    import('react-force-graph-2d').then((m) => setFG(() => m.default))
  }, [])

  // Fetch data only. AI classification used to auto-kick here on every mount —
  // that fired hundreds of Claude calls in the background and re-fetched the
  // graph when done, making the tab feel unresponsive for minutes. Users can
  // trigger it explicitly via the Classify button.
  useEffect(() => {
    getPartnershipGraph()
      .then(({ data }) => setGraphData(data))
      .catch((err) => {
        console.error('Failed to load partnership graph, falling back to legacy:', err)
        getCompaniesNetwork()
          .then(({ data }) => setGraphData(data))
          .catch(console.error)
      })
      .finally(() => setLoading(false))
  }, [])

  // Resize observer — must re-run when FG/loading change so containerRef is populated
  useEffect(() => {
    if (!containerRef.current) return
    const obs = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect
      if (width > 0 && height > 0) setDims({ w: width, h: height })
    })
    obs.observe(containerRef.current)
    return () => obs.disconnect()
  }, [FG, loading])

  // Configure forces — only runs when FG or graphData changes, not on resize.
  // Tuned to prevent hub-clumping: hubs (e.g. Tesla with 50+ partnerships) used
  // to crush every neighbour into one knot because link.strength was a flat 0.2.
  // We use d3's default adaptive link strength (1 / min(deg(s), deg(t))) so each
  // extra edge on a hub pulls its neighbours proportionally less, and we pair
  // that with size-aware charge + a generous collide buffer so nodes can never
  // visually overlap.
  useEffect(() => {
    const fg = fgRef.current
    if (!fg) return
    const t = setTimeout(() => {
      const nodeCount = displayGraphRef.current.nodes.length || 1
      const chargeStrength = -600 - Math.sqrt(nodeCount) * 80

      fg.d3Force('charge')
        ?.strength(chargeStrength)
        .distanceMin(10)
        .distanceMax(1400)

      fg.d3Force('center')?.strength(0.01)

      fg.d3Force('link')
        ?.distance(220)
        .strength((link) => {
          const counts = linkCountsRef.current
          const s = typeof link.source === 'object' ? link.source.id : link.source
          const t2 = typeof link.target === 'object' ? link.target.id : link.target
          const deg = Math.min(counts[s] || 1, counts[t2] || 1)
          return 1 / Math.max(1, deg)
        })

      fg.d3Force('y', null) // remove any leftover Y force

      fg.d3Force(
        'collide',
        forceCollide((n) => {
          return nodeRadius(n, scaleMetricRef.current, maxValuesRef.current, linkCountsRef.current) + 22
        })
          .strength(1)
          .iterations(4),
      )

      // Unpin everything and re-heat so the new forces actually take effect
      displayGraphRef.current.nodes.forEach((n) => {
        n.fx = undefined
        n.fy = undefined
      })
      fg.d3ReheatSimulation?.()
    }, 100)
    return () => clearTimeout(t)
  }, [FG, graphData])

  useEffect(() => { fgRef.current?.refresh() }, [dark])

  const handleNodeClick = useCallback((node) => {
    // Defer state updates so D3 can finish processing its click event first
    setTimeout(() => {
      if (node.id === INVESTOR_META_ID) {
        setInvestorGroup(node._investorList || [])
        setInvestorPanelOpen(true)
        setClickedNodeId(null)
        clickedNodeRef.current = null
        setClickedLink(null)
      } else {
        setClickedNodeId(node.id)
        clickedNodeRef.current = node.id
        setClickedLink(null)
        setInvestorPanelOpen(false)
        if (node.in_db !== false) {
          onSelectCompany?.(node.id)
        }
      }
    }, 0)
  }, [onSelectCompany])

  const handleLinkClick = useCallback((link) => {
    setTimeout(() => {
      setClickedLink(link)
      setClickedNodeId(null)
      clickedNodeRef.current = null
      setInvestorPanelOpen(false)
    }, 0)
  }, [])

  const MAX_EDGE_LENGTH = 320  // graph-space units; edge clamps here and neighbour follows

  const handleNodeDrag = useCallback((node, translate) => {
    // First tick of a new drag: snapshot every node's start position and build connected set
    if (draggingRef.current?.id !== node.id) {
      const connected = new Set()
      displayGraphRef.current.links.forEach(l => {
        const s = typeof l.source === 'object' ? l.source.id : l.source
        const t = typeof l.target === 'object' ? l.target.id : l.target
        if (s === node.id) connected.add(t)
        if (t === node.id) connected.add(s)
      })
      const startPositions = {}
      displayGraphRef.current.nodes.forEach(n => {
        startPositions[n.id] = { x: n.fx != null ? n.fx : n.x, y: n.fy != null ? n.fy : n.y }
      })
      draggingRef.current = { id: node.id, connected, startPositions, nodeStartX: node.x, nodeStartY: node.y }
    }

    const { connected, startPositions, nodeStartX, nodeStartY } = draggingRef.current
    const metric = scaleMetricRef.current
    const maxVals = maxValuesRef.current
    const ax = nodeStartX + translate.x   // dragged node centre (translate is cumulative)
    const ay = nodeStartY + translate.y
    const lc = linkCountsRef.current
    const draggedR = nodeRadius(node, metric, maxVals, lc)

    displayGraphRef.current.nodes.forEach(n => {
      if (n.id === node.id) return

      const nR = nodeRadius(n, metric, maxVals, lc)
      const minSep = draggedR + nR + 2   // hard boundary: sum of radii + small gap

      // Current position (may have been pushed by a previous drag tick)
      const nx = n.fx != null ? n.fx : n.x
      const ny = n.fy != null ? n.fy : n.y
      const dx = nx - ax
      const dy = ny - ay
      const dist = Math.sqrt(dx * dx + dy * dy) || 0.001

      if (dist < minSep) {
        // COLLISION — push this node out to the hard boundary
        const scale = minSep / dist
        n.fx = ax + dx * scale
        n.fy = ay + dy * scale
        return   // collision wins; skip tether logic for this node
      }

      if (connected.has(n.id)) {
        // TETHER — measure from start position so the anchor doesn't drift
        const sp = startPositions[n.id]
        const sdx = sp.x - ax
        const sdy = sp.y - ay
        const sDist = Math.sqrt(sdx * sdx + sdy * sdy) || 0.001
        if (sDist > MAX_EDGE_LENGTH) {
          const scale = MAX_EDGE_LENGTH / sDist
          n.fx = ax + sdx * scale
          n.fy = ay + sdy * scale
        } else {
          n.fx = sp.x   // within tether — hold at original position
          n.fy = sp.y
        }
      }
      // Non-connected, no collision: leave untouched
    })
  }, [])

  const handleNodeDragEnd = useCallback((node) => {
    node.fx = node.x
    node.fy = node.y
    // Pin every node that was pushed or pulled during the drag
    displayGraphRef.current.nodes.forEach(n => {
      if (n.x != null) {
        n.fx = n.fx != null ? n.fx : n.x
        n.fy = n.fy != null ? n.fy : n.y
      }
    })
    draggingRef.current = null
  }, [])

  const handleNodeHover = useCallback((node) => {
    hoveredNodeRef.current = node || null
    if (node) {
      const connected = new Set([node.id])
      displayGraphRef.current.links.forEach(l => {
        const s = typeof l.source === 'object' ? l.source.id : l.source
        const t = typeof l.target === 'object' ? l.target.id : l.target
        if (s === node.id) connected.add(t)
        if (t === node.id) connected.add(s)
      })
      hoveredConnectedRef.current = connected
    } else {
      hoveredConnectedRef.current = null
    }
    setHovVersion(v => v + 1)
    tooltipSetterRef.current?.(node || null)
  }, [])

  const handleZoom = useCallback(({ k }) => { zoomLevelRef.current = k }, [])

  const handleEngineStop = useCallback(() => {
    if (!fitDoneRef.current) {
      fitDoneRef.current = true
      fgRef.current?.zoomToFit(400, 60)
    }
    // Pin every node so drag/click interactions don't reheat the simulation
    // and send nodes flying off-screen
    displayGraphRef.current.nodes.forEach(n => {
      if (n.x != null) { n.fx = n.x; n.fy = n.y }
    })
  }, [])

  // Max values for scaling
  const maxValues = useMemo(() => {
    const max = {}
    for (const opt of SCALE_OPTIONS) {
      const vals = graphData.nodes.map(n => n[opt.key]).filter(v => v != null && v > 0)
      max[opt.key] = vals.length > 0 ? Math.max(...vals) : 1
    }
    return max
  }, [graphData.nodes])

  // Stable refs so drag handler and forceCollide always see current values without dep churn
  const scaleMetricRef = useRef(scaleMetric)
  scaleMetricRef.current = scaleMetric
  const maxValuesRef = useRef(maxValues)
  maxValuesRef.current = maxValues
  const linkCountsRef = useRef({})  // updated after displayGraph is computed below

  // Detect unknowns for auto-classify nudge
  const unknownCount = useMemo(() => {
    const unknownNodes = graphData.nodes.filter(n => !n.type || n.type === 'other').length
    const unknownLinks = graphData.links.filter(l => !l.type || l.type === 'other').length
    return unknownNodes + unknownLinks
  }, [graphData])

  /* ── Filtered graph ── */
  const filteredGraph = useMemo(() => {
    let links = [...graphData.links]

    // Filter by partnership type
    if (filterTypes.length > 0) {
      links = links.filter(l => filterTypes.includes(l.type))
    }
    // Filter by stage
    if (filterStages.length > 0) {
      links = links.filter(l => filterStages.includes(l.stage))
    }
    // Filter by date range
    if (filterDateFrom) {
      links = links.filter(l => !l.date || l.date >= filterDateFrom)
    }
    if (filterDateTo) {
      links = links.filter(l => !l.date || l.date <= filterDateTo)
    }
    // Filter by geography
    if (filterGeography) {
      const geoLower = filterGeography.toLowerCase()
      const geoNodeIds = new Set(
        graphData.nodes.filter(n =>
          (n.industry_segment || '').toLowerCase().includes(geoLower) ||
          (n.type || '').toLowerCase().includes(geoLower)
        ).map(n => n.id)
      )
      links = links.filter(l => {
        const s = typeof l.source === 'object' ? l.source.id : l.source
        const t = typeof l.target === 'object' ? l.target.id : l.target
        return geoNodeIds.has(s) || geoNodeIds.has(t)
      })
    }
    // Gov toggle
    if (filterGovToggle === 'gov_only') {
      links = links.filter(l => l.type === 'government_grant')
    } else if (filterGovToggle === 'private_only') {
      links = links.filter(l => l.type !== 'government_grant')
    }

    // Filter nodes to only those connected
    const connectedIds = new Set()
    links.forEach(l => {
      connectedIds.add(typeof l.source === 'object' ? l.source.id : l.source)
      connectedIds.add(typeof l.target === 'object' ? l.target.id : l.target)
    })

    let nodes = graphData.nodes.filter(n => connectedIds.has(n.id))

    // Search filter
    if (searchQuery) {
      const q = searchQuery.toLowerCase()
      const matchIds = new Set(nodes.filter(n => n.name.toLowerCase().includes(q)).map(n => n.id))
      // Show matching nodes + their direct partners
      const expandedIds = new Set(matchIds)
      links.forEach(l => {
        const s = typeof l.source === 'object' ? l.source.id : l.source
        const t = typeof l.target === 'object' ? l.target.id : l.target
        if (matchIds.has(s)) expandedIds.add(t)
        if (matchIds.has(t)) expandedIds.add(s)
      })
      nodes = nodes.filter(n => expandedIds.has(n.id))
      links = links.filter(l => {
        const s = typeof l.source === 'object' ? l.source.id : l.source
        const t = typeof l.target === 'object' ? l.target.id : l.target
        return expandedIds.has(s) && expandedIds.has(t)
      })
    }

    // Filter by industry segment
    if (filterSegments.length > 0) {
      const segNodeIds = new Set(nodes.filter(n => filterSegments.includes(n.industry_segment)).map(n => n.id))
      links = links.filter(l => {
        const s = typeof l.source === 'object' ? l.source.id : l.source
        const t = typeof l.target === 'object' ? l.target.id : l.target
        return segNodeIds.has(s) || segNodeIds.has(t)
      })
      const finalIds = new Set()
      links.forEach(l => {
        finalIds.add(typeof l.source === 'object' ? l.source.id : l.source)
        finalIds.add(typeof l.target === 'object' ? l.target.id : l.target)
      })
      nodes = nodes.filter(n => finalIds.has(n.id))
    }

    return { nodes, links }
  }, [graphData, filterTypes, filterStages, filterDateFrom, filterDateTo, filterGeography, filterGovToggle, filterSegments, searchQuery])

  /* ── Collapse investor nodes into one meta-bubble ── */
  const isInvestorNode = (node) => {
    const type = (node.type || '').toLowerCase()
    const seg  = (node.industry_segment || '').toLowerCase()
    return (
      type.includes('invest') || seg.includes('invest') ||
      type.includes('venture') || type.includes('private equity') ||
      type.includes('angel') || type.includes('family office')
    )
  }

  const displayGraph = useMemo(() => {
    const investorNodes = filteredGraph.nodes.filter(isInvestorNode)
    if (investorNodes.length < 2) return filteredGraph  // not enough to group

    const investorIds = new Set(investorNodes.map(n => n.id))
    const metaNode = {
      id: INVESTOR_META_ID,
      name: `Investors (${investorNodes.length})`,
      type: 'investors_group',
      in_db: true,
      _investorList: investorNodes,
      employee_count: investorNodes.length * 200,
    }

    const nodes = [
      ...filteredGraph.nodes.filter(n => !investorIds.has(n.id)),
      metaNode,
    ]

    const seenLinkKeys = new Set()
    const links = filteredGraph.links
      .map(l => {
        const s = typeof l.source === 'object' ? l.source.id : l.source
        const t = typeof l.target === 'object' ? l.target.id : l.target
        const ns = investorIds.has(s) ? INVESTOR_META_ID : s
        const nt = investorIds.has(t) ? INVESTOR_META_ID : t
        if (ns === nt) return null
        const key = `${[ns, nt].sort().join('::')}::${l.type}`
        if (seenLinkKeys.has(key)) return null
        seenLinkKeys.add(key)
        return { ...l, source: ns, target: nt }
      })
      .filter(Boolean)

    return { nodes, links }
  }, [filteredGraph])  // eslint-disable-line react-hooks/exhaustive-deps

  // Re-fit on filter change — unpin nodes so they can re-layout, and reheat the
  // simulation so the collide + charge forces actually push them apart again
  // (without reheat they stay pinned-in-place at their previous positions).
  useEffect(() => {
    fitDoneRef.current = false
    displayGraphRef.current.nodes.forEach(n => { n.fx = undefined; n.fy = undefined })
    fgRef.current?.d3ReheatSimulation?.()
    const t = setTimeout(() => fgRef.current?.zoomToFit(400, 60), 800)
    return () => clearTimeout(t)
  }, [filteredGraph])

  // Keep ref updated so onEngineStop can access current nodes without a closure dep
  displayGraphRef.current = displayGraph

  // Link counts per node — used as fallback scaling when no financial metric data exists
  // Must be defined AFTER displayGraph
  const linkCounts = useMemo(() => {
    const counts = {}
    displayGraph.links.forEach(l => {
      const s = typeof l.source === 'object' ? l.source.id : l.source
      const t = typeof l.target === 'object' ? l.target.id : l.target
      counts[s] = (counts[s] || 0) + 1
      counts[t] = (counts[t] || 0) + 1
    })
    counts.__max = Math.max(1, ...Object.values(counts).filter(v => typeof v === 'number'))
    return counts
  }, [displayGraph.links])
  linkCountsRef.current = linkCounts

  // Compute link curvatures for parallel edges (use displayGraph — what FG actually renders)
  useMemo(() => {
    const groups = {}
    displayGraph.links.forEach((link) => {
      const s = typeof link.source === 'object' ? link.source.id : link.source
      const t = typeof link.target === 'object' ? link.target.id : link.target
      const key = [s, t].sort().join('::')
      ;(groups[key] ??= []).push(link)
    })
    Object.values(groups).forEach((g) => {
      if (g.length === 1) { g[0]._curve = 0.15; return }
      g.forEach((l, i) => { l._curve = 0.08 + (i - (g.length - 1) / 2) * 0.12 })
    })
  }, [displayGraph.links])

  /* ── Canvas: node ── */
  const paintNode = useCallback((node, ctx, globalScale) => {
    if (node.x == null || node.y == null) return
    const r = nodeRadius(node, scaleMetric, maxValues, linkCounts)
    const { fill, border } = node.in_db === false
      ? hashColor(node.name || node.id || 'x')
      : typeColors(node.type, dark, node.name || '')
    const isSearch  = searchQuery && node.name.toLowerCase().includes(searchQuery.toLowerCase())
    const isHov     = hoveredNodeRef.current?.id === node.id
    const isClicked = clickedNodeRef.current === node.id
    const connected = hoveredConnectedRef.current
    const isDimmed  = connected != null && !connected.has(node.id)

    // Dimmed — draw faint circle only, skip glow and label
    if (isDimmed) {
      ctx.globalAlpha = 0.1
      ctx.beginPath(); ctx.arc(node.x, node.y, r, 0, Math.PI * 2)
      ctx.fillStyle = fill; ctx.fill()
      ctx.strokeStyle = border; ctx.lineWidth = 1; ctx.stroke()
      ctx.globalAlpha = 1
      return
    }

    // Outer glow (hover / search) — use globalAlpha so HSL colors work too
    if (isHov || isSearch) {
      const g = ctx.createRadialGradient(node.x, node.y, r, node.x, node.y, r + 12)
      g.addColorStop(0, border)
      g.addColorStop(1, 'rgba(0,0,0,0)')
      ctx.save()
      ctx.globalAlpha = dark ? 0.5 : 0.3
      ctx.beginPath(); ctx.arc(node.x, node.y, r + 12, 0, Math.PI * 2)
      ctx.fillStyle = g; ctx.fill()
      ctx.restore()
    }

    // Selection ring (clicked node)
    if (isClicked) {
      ctx.beginPath(); ctx.arc(node.x, node.y, r + 5, 0, Math.PI * 2)
      ctx.strokeStyle = '#EE0405'
      ctx.lineWidth = 2.5
      ctx.globalAlpha = 0.9
      ctx.stroke(); ctx.globalAlpha = 1
    }

    ctx.beginPath(); ctx.arc(node.x, node.y, r, 0, Math.PI * 2)
    ctx.fillStyle = fill; ctx.fill()
    ctx.strokeStyle = isClicked ? '#EE0405' : border
    ctx.lineWidth = (isHov || isClicked) ? 2.5 : 1.2
    ctx.globalAlpha = (isHov || isClicked) ? 1 : 0.8
    ctx.stroke(); ctx.globalAlpha = 1

    // Dashed ring for external
    if (node.in_db === false) {
      ctx.setLineDash([2, 2]); ctx.strokeStyle = dark ? '#64748B' : '#94A3B8'
      ctx.lineWidth = 1; ctx.stroke(); ctx.setLineDash([])
    }

    // Label
    const fs = Math.max(4, Math.min(11, 10 / globalScale))
    ctx.font = `${(isHov || isClicked) ? 'bold ' : ''}${fs}px Inter, system-ui, sans-serif`
    ctx.textAlign = 'center'; ctx.textBaseline = 'top'
    const rawName = node.name || ''
    const label = rawName.length > 22 ? rawName.slice(0, 20) + '\u2026' : rawName
    const ty = node.y + r + 2.5 / globalScale

    ctx.fillStyle = dark ? 'rgba(0,0,0,0.6)' : 'rgba(255,255,255,0.8)'
    ctx.fillText(label, node.x + 0.5 / globalScale, ty + 0.5 / globalScale)
    ctx.fillStyle = dark
      ? ((isHov || isClicked) ? '#fff' : 'rgba(255,255,255,0.8)')
      : ((isHov || isClicked) ? '#0F172A' : '#374151')
    ctx.fillText(label, node.x, ty)
    ctx.textBaseline = 'alphabetic'
  }, [searchQuery, scaleMetric, dark, maxValues, linkCounts, hovVersion])

  /* ── Canvas: link ── */
  const paintLink = useCallback((link, ctx, globalScale) => {
    const s = link.source, t = link.target
    if (!s || !t || typeof s !== 'object' || typeof t !== 'object') return
    if (s.x == null || t.x == null) return

    const dx = t.x - s.x, dy = t.y - s.y
    const dist = Math.sqrt(dx * dx + dy * dy)
    if (dist < 1) return

    const nx = -dy / dist, ny = dx / dist
    const curve = link._curve || 0.15
    const sign = (s.id ?? 0) < (t.id ?? 0) ? 1 : -1
    const cpX = (s.x + t.x) / 2 + nx * curve * dist * sign
    const cpY = (s.y + t.y) / 2 + ny * curve * dist * sign

    const hovConn = hoveredConnectedRef.current
    const hovId   = hoveredNodeRef.current?.id
    const isHighlighted = hovConn == null || s.id === hovId || t.id === hovId

    const { color, alpha } = linkColor(link.type, link.date, dark)
    const effectiveAlpha = isHighlighted ? alpha : alpha * 0.06

    ctx.strokeStyle = color
    ctx.lineWidth = Math.max(0.8, 1.8 / globalScale)
    ctx.globalAlpha = effectiveAlpha
    ctx.beginPath(); ctx.moveTo(s.x, s.y); ctx.quadraticCurveTo(cpX, cpY, t.x, t.y); ctx.stroke()

    // Arrowhead
    const dir = link.direction || 'bidirectional'
    const drawArrow = (fromX, fromY, toX, toY, targetNode) => {
      const angle = Math.atan2(toY - fromY, toX - fromX)
      const tr = nodeRadius(targetNode, scaleMetric, maxValues, linkCounts) + 2
      const ax = toX - Math.cos(angle) * tr
      const ay = toY - Math.sin(angle) * tr
      const al = Math.max(3.5, 6 / globalScale)
      const ah = Math.PI / 7
      ctx.fillStyle = color; ctx.globalAlpha = effectiveAlpha * 0.9
      ctx.beginPath(); ctx.moveTo(ax, ay)
      ctx.lineTo(ax - al * Math.cos(angle - ah), ay - al * Math.sin(angle - ah))
      ctx.lineTo(ax - al * Math.cos(angle + ah), ay - al * Math.sin(angle + ah))
      ctx.closePath(); ctx.fill()
    }

    // Forward arrow (source -> target)
    drawArrow(cpX, cpY, t.x, t.y, t)

    // Bidirectional: also draw reverse arrow
    if (dir === 'bidirectional') {
      drawArrow(cpX, cpY, s.x, s.y, s)
    }

    ctx.globalAlpha = 1
  }, [scaleMetric, dark, maxValues, linkCounts, hovVersion])

  /* ── Hit area ── */
  const pointerArea = useCallback((node, color, ctx) => {
    if (node.x == null || node.y == null) return
    const r = nodeRadius(node, scaleMetric, maxValues, linkCounts) + 4
    ctx.beginPath(); ctx.arc(node.x, node.y, r, 0, Math.PI * 2)
    ctx.fillStyle = color; ctx.fill()
  }, [scaleMetric, maxValues, linkCounts])

  /* ── Loading / empty ── */
  if (loading || !FG) {
    return (
      <div className={`flex items-center justify-center h-full ${dark ? 'bg-[#0D1B2E] text-gray-400' : 'bg-bmw-gray-light text-gray-500'}`}>
        {loading ? 'Loading network data\u2026' : 'Initializing graph\u2026'}
      </div>
    )
  }

  if (graphData.links.length === 0) {
    return (
      <div className={`flex flex-col items-center justify-center h-full gap-3 ${dark ? 'bg-[#0D1B2E]' : 'bg-bmw-gray-light'}`}>
        <div className={`text-lg font-medium ${dark ? 'text-gray-300' : 'text-gray-600'}`}>No partnership data yet</div>
        <div className={`text-sm text-center max-w-sm ${dark ? 'text-gray-500' : 'text-gray-400'}`}>
          The network only shows companies with known partnerships. Go to the Research tab, run "Research a Company", or use "Classify All" above to populate connections.
        </div>
      </div>
    )
  }

  const bg = dark ? '#0D1B2E' : '#F5F7FA'
  const panelBg = dark ? 'bg-[#0F1D2F]' : 'bg-white'
  const borderClr = dark ? 'border-gray-700' : 'border-bmw-border'
  const textMuted = dark ? 'text-gray-400' : 'text-gray-500'
  const textNormal = dark ? 'text-gray-200' : 'text-gray-600'
  const inputBg = dark ? 'bg-[#1E293B] border-gray-600 text-gray-200 placeholder-gray-500' : 'border-bmw-border text-gray-800 placeholder-gray-400'

  return (
    <div className={`flex flex-1 min-h-0 ${dark ? 'bg-[#0D1B2E]' : 'bg-bmw-gray-light'}`}>
      {/* ── Filter sidebar ── */}
      {sidebarOpen && (
        <div className={`w-64 ${panelBg} border-r ${borderClr} flex flex-col overflow-y-auto shrink-0`}>
          <div className="px-4 py-3 border-b border-inherit flex items-center justify-between">
            <span className={`text-xs font-semibold uppercase tracking-wider ${textMuted}`}>Filters</span>
            <button onClick={() => setSidebarOpen(false)} className={`text-sm ${textMuted} hover:text-gray-300`}>x</button>
          </div>

          {/* Partnership Type */}
          <FilterSection title="Partnership Type" dark={dark}>
            {Object.entries(LINK_TYPE_COLORS).map(([key, { label, base }]) => (
              <label key={key} className="flex items-center gap-2 text-xs cursor-pointer">
                <input
                  type="checkbox"
                  checked={filterTypes.includes(key)}
                  onChange={() => setFilterTypes(prev =>
                    prev.includes(key) ? prev.filter(t => t !== key) : [...prev, key]
                  )}
                  className="rounded"
                />
                <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: base }} />
                <span className={textNormal}>{label}</span>
              </label>
            ))}
          </FilterSection>

          {/* Stage */}
          <FilterSection title="Stage" dark={dark}>
            {STAGES.map(s => (
              <label key={s} className="flex items-center gap-2 text-xs cursor-pointer">
                <input
                  type="checkbox"
                  checked={filterStages.includes(s)}
                  onChange={() => setFilterStages(prev =>
                    prev.includes(s) ? prev.filter(t => t !== s) : [...prev, s]
                  )}
                  className="rounded"
                />
                <span className={`${textNormal} capitalize`}>{s}</span>
              </label>
            ))}
          </FilterSection>

          {/* Date Range */}
          <FilterSection title="Date Range" dark={dark}>
            <div className="space-y-1.5">
              <input
                type="text"
                placeholder="From (YYYY)"
                value={filterDateFrom}
                onChange={e => setFilterDateFrom(e.target.value)}
                className={`w-full border rounded px-2 py-1 text-xs ${inputBg}`}
              />
              <input
                type="text"
                placeholder="To (YYYY)"
                value={filterDateTo}
                onChange={e => setFilterDateTo(e.target.value)}
                className={`w-full border rounded px-2 py-1 text-xs ${inputBg}`}
              />
            </div>
          </FilterSection>

          {/* Industry Segment */}
          <FilterSection title="Industry Segment" dark={dark}>
            {INDUSTRY_SEGMENTS.map(s => (
              <label key={s} className="flex items-center gap-2 text-xs cursor-pointer">
                <input
                  type="checkbox"
                  checked={filterSegments.includes(s)}
                  onChange={() => setFilterSegments(prev =>
                    prev.includes(s) ? prev.filter(t => t !== s) : [...prev, s]
                  )}
                  className="rounded"
                />
                <span className={`${textNormal} capitalize`}>{s.replace(/_/g, ' ')}</span>
              </label>
            ))}
          </FilterSection>

          {/* Government Toggle */}
          <FilterSection title="Government / Private" dark={dark}>
            {['all', 'gov_only', 'private_only'].map(opt => (
              <label key={opt} className="flex items-center gap-2 text-xs cursor-pointer">
                <input
                  type="radio"
                  name="gov"
                  checked={filterGovToggle === opt}
                  onChange={() => setFilterGovToggle(opt)}
                />
                <span className={textNormal}>
                  {opt === 'all' ? 'All' : opt === 'gov_only' ? 'Government Only' : 'Private Only'}
                </span>
              </label>
            ))}
          </FilterSection>

          {/* Clear all */}
          <div className="px-4 py-3">
            <button
              onClick={() => {
                setFilterTypes([]); setFilterStages([]); setFilterDateFrom(''); setFilterDateTo('')
                setFilterGeography(''); setFilterGovToggle('all'); setFilterSegments([])
              }}
              className="w-full text-xs text-bmw-blue hover:underline"
            >
              Clear all filters
            </button>
          </div>
        </div>
      )}

      {/* ── Main graph area ── */}
      <div className="flex flex-col flex-1 min-h-0 min-w-0">
        {/* Controls bar */}
        <div className={`${panelBg} border-b ${borderClr} px-4 py-2.5 flex items-center gap-3 flex-wrap`}>
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className={`text-xs px-3 py-1.5 rounded border transition-colors ${
              sidebarOpen
                ? (dark ? 'bg-blue-600 text-white border-blue-600' : 'bg-[text-bmw-text-primary] text-white border-[text-bmw-text-primary]')
                : `${dark ? 'border-gray-600 text-gray-400 hover:border-blue-500' : 'border-bmw-border text-gray-600 hover:border-bmw-blue'}`
            }`}
          >
            Filters
          </button>

          {/* Zoom controls */}
          <div className="flex items-center gap-1">
            <button
              onClick={() => {
                const fg = fgRef.current
                if (!fg) return
                zoomLevelRef.current = zoomLevelRef.current * 1.4
                fg.zoom(zoomLevelRef.current, 300)
              }}
              title="Zoom in"
              className={`w-7 h-7 flex items-center justify-center rounded border text-base font-bold transition-colors ${
                dark ? 'border-gray-600 text-gray-300 hover:bg-gray-700' : 'border-bmw-border text-gray-600 hover:bg-bmw-gray-light'
              }`}
            >+</button>
            <button
              onClick={() => {
                const fg = fgRef.current
                if (!fg) return
                zoomLevelRef.current = zoomLevelRef.current / 1.4
                fg.zoom(zoomLevelRef.current, 300)
              }}
              title="Zoom out"
              className={`w-7 h-7 flex items-center justify-center rounded border text-base font-bold transition-colors ${
                dark ? 'border-gray-600 text-gray-300 hover:bg-gray-700' : 'border-bmw-border text-gray-600 hover:bg-bmw-gray-light'
              }`}
            >−</button>
          </div>


          {/* Classify All button */}
          <button
            onClick={classifyState === 'idle' || classifyState === 'done' || classifyState === 'error' ? handleClassify : undefined}
            disabled={classifyState === 'running'}
            title="AI-classify all untyped companies and partnerships"
            className={`text-xs px-3 py-1.5 rounded border transition-colors flex items-center gap-1.5 ${
              classifyState === 'running'
                ? (dark ? 'border-purple-600 text-purple-400 bg-purple-900/20' : 'border-purple-400 text-purple-600 bg-purple-50')
              : classifyState === 'done'
                ? (dark ? 'border-green-600 text-green-400' : 'border-green-500 text-green-600')
              : classifyState === 'error'
                ? (dark ? 'border-red-600 text-red-400' : 'border-red-400 text-red-600')
              : (dark ? 'border-gray-600 text-gray-400 hover:border-purple-500' : 'border-bmw-border text-gray-600 hover:border-purple-400')
            }`}
          >
            {classifyState === 'running' ? (
              <><svg className="animate-spin" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 12a9 9 0 1 1-6.219-8.56" /></svg> Classifying…</>
            ) : classifyState === 'done' && classifyResult ? (
              <span>
                Classified ({classifyResult.companies_classified ?? 0}co · {classifyResult.partnerships_classified ?? 0}p)
              </span>
            ) : (
              <>
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="3"/><path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83"/></svg>
                Classify All
              </>
            )}
          </button>

          <input
            type="text"
            placeholder="Search companies, types, geography\u2026"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className={`border rounded px-3 py-1.5 text-sm w-64 focus:outline-none focus:ring-2 focus:ring-bmw-blue ${inputBg}`}
          />

          {/* Scale by */}
          <div className="flex items-center gap-2">
            <span className={`text-xs ${textMuted} whitespace-nowrap`}>Bubble size:</span>
            <select
              value={scaleMetric}
              onChange={(e) => setScaleMetric(e.target.value)}
              className={`text-xs border rounded px-2 py-1.5 ${inputBg}`}
            >
              {SCALE_OPTIONS.map(m => (
                <option key={m.key} value={m.key}>{m.label}</option>
              ))}
            </select>
          </div>

          <div className={`ml-auto flex items-center gap-4 text-xs ${textMuted}`}>
            <span>{filteredGraph.nodes.length} companies</span>
            <span>{filteredGraph.links.length} partnerships</span>
          </div>
        </div>

        {/* Auto-classify nudge — shown when unknowns exist and not already classifying */}
        {unknownCount > 0 && classifyState === 'idle' && (
          <div className={`flex items-center gap-3 px-4 py-1.5 text-xs border-b ${borderClr} ${dark ? 'bg-amber-900/20 text-amber-300' : 'bg-amber-50 text-amber-700'}`}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><path d="M12 8v4m0 4h.01"/></svg>
            <span>{unknownCount} unclassified company/partnership type{unknownCount !== 1 ? 's' : ''} detected.</span>
            <button
              onClick={handleClassify}
              className={`font-semibold underline hover:no-underline ${dark ? 'text-amber-200' : 'text-amber-800'}`}
            >
              Classify now
            </button>
          </div>
        )}

        {/* Legend */}
        <div className={`${dark ? 'bg-[#0D1B2E]' : 'bg-bmw-gray-light'} border-b ${borderClr} px-4 py-1.5 flex items-center gap-4 flex-wrap`}>
          <span className={`text-xs font-medium ${textMuted} uppercase tracking-wider shrink-0`}>Arrows:</span>
          {Object.entries(LINK_TYPE_COLORS).map(([key, { base, label }]) => (
            <div key={key} className="flex items-center gap-1">
              <svg width="18" height="8" viewBox="0 0 18 8" className="inline-block shrink-0">
                <path d="M1 7 Q9 -1 17 7" stroke={base} fill="none" strokeWidth="1.5" opacity="0.8" />
                <polygon points="17,7 13,5.5 14,8" fill={base} opacity="0.8" />
              </svg>
              <span className={`text-xs ${textNormal} whitespace-nowrap`}>{label}</span>
            </div>
          ))}
          <div className="flex items-center gap-1">
            <span className={`w-2.5 h-2.5 rounded-full inline-block border-2 border-dashed shrink-0 ${dark ? 'border-gray-500' : 'border-gray-400'}`} />
            <span className={`text-xs ${textMuted}`}>External</span>
          </div>
        </div>

        {/* Graph canvas */}
        <div ref={containerRef} className="flex-1 relative min-h-0" style={{ cursor: panMode ? 'grab' : 'default' }}>
          <FG
            ref={fgRef}
            graphData={displayGraph}
            width={dims.w}
            height={dims.h}
            nodeCanvasObject={paintNode}
            nodeCanvasObjectMode={() => 'replace'}
            linkCanvasObject={paintLink}
            linkCanvasObjectMode={() => 'replace'}
            nodePointerAreaPaint={pointerArea}
            enableZoomPanInteraction={true}
            enableNodeDrag={!panMode}
            onNodeDrag={handleNodeDrag}
            onNodeDragEnd={handleNodeDragEnd}
            onNodeClick={handleNodeClick}
            onLinkClick={handleLinkClick}
            onNodeHover={handleNodeHover}
            onZoom={handleZoom}
            backgroundColor={bg}
            cooldownTicks={150}
            d3AlphaDecay={0.04}
            d3VelocityDecay={0.4}
            d3AlphaMin={0.005}
            warmupTicks={0}
            onEngineStop={handleEngineStop}
          />

          {/* Fit All button */}
          <button
            onClick={() => { zoomLevelRef.current = 1; fgRef.current?.zoomToFit(400, 60) }}
            className={`absolute bottom-4 left-4 z-10 rounded-lg shadow px-3 py-2 text-xs font-medium transition-colors flex items-center gap-1.5
              ${dark
                ? 'bg-[#1E293B] border border-gray-600 text-gray-300 hover:bg-[#2D3B4F]'
                : 'bg-white border border-bmw-border text-gray-600 hover:bg-bmw-gray-light'
              }`}
          >
            Fit All
          </button>

          {/* Tooltip — isolated component so hover never re-renders the parent/FG */}
          <HoverTooltip listenRef={tooltipSetterRef} dark={dark} />

          {/* Link click panel — shows partnership details */}
          {clickedLink && (
            <LinkDetailPanel
              link={clickedLink}
              dark={dark}
              onClose={() => setClickedLink(null)}
              onOpenCompany={(id) => { setClickedLink(null); onSelectCompany?.(id) }}
            />
          )}

          {/* Interaction hint */}
          <div className={`absolute bottom-4 right-4 text-[10px] pointer-events-none select-none ${dark ? 'text-gray-600' : 'text-gray-400'}`}>
            {panMode ? 'Pan mode: drag to pan · Scroll to zoom' : 'Scroll to zoom · Click node to view company · Click link for details'}
          </div>

          {/* Investor panel */}
          {investorPanelOpen && investorGroup.length > 0 && (
            <div className={`absolute top-4 right-4 z-20 rounded-xl shadow-lg border w-60 overflow-hidden
              ${dark ? 'bg-[#1E293B] border-gray-600' : 'bg-white border-bmw-border'}`}
            >
              <div className={`flex items-center justify-between px-3 py-2 border-b ${dark ? 'border-gray-700' : 'border-gray-200'}`}>
                <span className={`text-xs font-semibold ${dark ? 'text-gray-200' : 'text-gray-700'}`}>
                  Investors ({investorGroup.length})
                </span>
                <button
                  onClick={() => setInvestorPanelOpen(false)}
                  className={`text-xs leading-none ${dark ? 'text-gray-400 hover:text-gray-200' : 'text-gray-400 hover:text-gray-600'}`}
                >✕</button>
              </div>
              <div className="max-h-64 overflow-y-auto">
                {investorGroup.map(n => (
                  <button
                    key={n.id}
                    onClick={() => { if (n.in_db !== false && onSelectCompany) { setInvestorPanelOpen(false); onSelectCompany(n.id) } }}
                    className={`w-full text-left px-3 py-1.5 text-xs border-b last:border-0 transition-colors
                      ${dark ? 'border-gray-700 text-gray-300 hover:bg-[#2D3B4F]' : 'border-gray-100 text-gray-700 hover:bg-gray-50'}
                      ${n.in_db !== false ? 'cursor-pointer' : 'cursor-default opacity-60'}`}
                  >
                    {n.name}
                    {n.in_db === false && <span className={`ml-1 text-[10px] ${dark ? 'text-gray-500' : 'text-gray-400'}`}>(external)</span>}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default memo(PartnershipNetwork)

/* ── Sub-components ── */

/**
 * LinkDetailPanel — shown when a user clicks a partnership connection line.
 * Displays deal details and lets the user navigate to either company's full profile.
 */
function LinkDetailPanel({ link, dark, onClose, onOpenCompany }) {
  const src = typeof link.source === 'object' ? link.source : { id: link.source, name: String(link.source), in_db: false }
  const tgt = typeof link.target === 'object' ? link.target : { id: link.target, name: String(link.target), in_db: false }
  const typeInfo = LINK_TYPE_COLORS[link.type] || LINK_TYPE_COLORS.other

  const panelBg = dark ? 'bg-[#1E293B] border-gray-600' : 'bg-white border-bmw-border'
  const headBg  = dark ? 'bg-[#263345] border-gray-700' : 'bg-[#F7F9FB] border-gray-200'
  const textPri = dark ? 'text-gray-100' : 'text-gray-800'
  const textMut = dark ? 'text-gray-400' : 'text-gray-500'
  const detailBg = dark ? 'bg-[#1A2535] border-gray-700' : 'bg-gray-50 border-gray-100'

  const CompanyCard = ({ company }) => (
    <button
      onClick={() => company.in_db !== false && onOpenCompany?.(company.id)}
      className={`w-full text-left px-3 py-2.5 rounded-lg border transition-colors ${
        company.in_db !== false
          ? (dark ? 'border-gray-600 hover:bg-[#2D3B4F] cursor-pointer' : 'border-gray-200 hover:bg-blue-50 cursor-pointer')
          : (dark ? 'border-gray-700 opacity-60 cursor-default' : 'border-gray-100 opacity-60 cursor-default')
      }`}
    >
      <div className={`text-sm font-semibold leading-tight ${textPri}`}>{company.name}</div>
      {company.in_db === false
        ? <div className={`text-xs mt-0.5 ${textMut}`}>External partner</div>
        : <div className="text-xs mt-0.5 text-bmw-blue">Click to view full profile →</div>
      }
    </button>
  )

  return (
    <div className={`absolute top-4 right-4 z-20 rounded-xl shadow-xl border w-80 overflow-hidden ${panelBg}`}>
      {/* Header */}
      <div className={`px-4 py-3 border-b flex items-center justify-between ${headBg}`}>
        <div className="flex items-center gap-2">
          <span className="w-3 h-3 rounded-full shrink-0" style={{ backgroundColor: typeInfo.base }} />
          <span className={`font-bold text-sm ${textPri}`}>{typeInfo.label}</span>
        </div>
        <button onClick={onClose} className={`text-lg leading-none ${textMut} hover:text-red-400`}>✕</button>
      </div>

      {/* Companies */}
      <div className="px-4 py-3 space-y-2">
        <div className={`text-[10px] font-semibold uppercase tracking-wider mb-2 ${textMut}`}>Partnership Between</div>
        <CompanyCard company={src} />
        <div className="flex items-center justify-center py-0.5">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={typeInfo.base} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <line x1="12" y1="5" x2="12" y2="19"/><polyline points="19 12 12 19 5 12"/>
          </svg>
        </div>
        <CompanyCard company={tgt} />
      </div>

      {/* Deal details */}
      <div className={`px-4 py-3 border-t space-y-2 ${detailBg}`}>
        <div className="flex flex-wrap gap-1.5">
          <span className="text-[11px] px-2 py-0.5 rounded-full font-medium text-white" style={{ backgroundColor: typeInfo.base }}>
            {typeInfo.label}
          </span>
          {link.stage && (
            <span className={`text-[11px] px-2 py-0.5 rounded-full capitalize ${
              link.stage === 'active'    ? 'bg-green-100 text-green-700' :
              link.stage === 'signed'    ? 'bg-blue-100 text-blue-700' :
              link.stage === 'announced' ? 'bg-yellow-100 text-yellow-700' :
              link.stage === 'dissolved' ? 'bg-red-100 text-red-700' :
                                           'bg-gray-100 text-gray-600'
            }`}>{link.stage}</span>
          )}
          {link.date && <span className={`text-[11px] ${textMut}`}>{link.date}</span>}
        </div>
        {link.deal_value != null && (
          <div className="flex justify-between items-center">
            <span className={`text-xs ${textMut}`}>Deal Value</span>
            <span className={`text-sm font-bold ${textPri}`}>{fmtVal(link.deal_value)}</span>
          </div>
        )}
        {link.scope && (
          <p className={`text-xs leading-relaxed ${textMut}`}>{link.scope}</p>
        )}
      </div>
    </div>
  )
}

/**
 * HoverTooltip — owns its own state so hover updates never re-render the parent.
 * Parent hands down a `listenRef`: setting listenRef.current = setNode wires the channel.
 * onNodeHover calls listenRef.current(node) imperatively — zero parent re-renders.
 */
function HoverTooltip({ listenRef, dark }) {
  const [node, setNode] = useState(null)
  useEffect(() => {
    listenRef.current = setNode
    return () => { listenRef.current = null }
  }, [listenRef])

  if (!node) return null
  const panelBg = dark ? 'bg-[#1E293B] border-gray-600' : 'bg-white border-bmw-border'
  const textMuted = dark ? 'text-gray-400' : 'text-gray-500'
  return (
    <div className={`absolute top-4 left-4 rounded-xl shadow-lg px-4 py-3 text-sm border pointer-events-none max-w-[260px] ${panelBg}`}>
      <div className={`font-semibold leading-tight ${dark ? 'text-gray-100' : 'text-gray-800'}`}>
        {node.name}
      </div>
      {node.in_db === false && (
        <div className="text-xs text-amber-500 font-medium mt-0.5">External partner</div>
      )}
      {node.type && node.type !== 'other' && node.id !== INVESTOR_META_ID && (
        <div className="flex items-center gap-1.5 mt-1">
          <span className="w-2 h-2 rounded-full" style={{ backgroundColor: typeColors(node.type, dark, node.name || '').fill }} />
          <span className={`text-xs ${textMuted}`}>{node.type}</span>
        </div>
      )}
      {node.industry_segment && (
        <div className={`text-xs mt-0.5 ${dark ? 'text-gray-500' : 'text-gray-400'}`}>{node.industry_segment}</div>
      )}
      {node.in_db !== false && (
        <div className="mt-2 space-y-0.5">
          {node.employee_count != null && <HRow dark={dark} label="Employees" value={node.employee_count.toLocaleString()} />}
          {node.revenue_usd != null && <HRow dark={dark} label="Revenue" value={fmtVal(node.revenue_usd)} />}
          {node.market_cap_usd != null && <HRow dark={dark} label="Market Cap" value={fmtVal(node.market_cap_usd)} />}
          {node.total_funding_usd != null && <HRow dark={dark} label="Funding" value={fmtVal(node.total_funding_usd)} />}
          {node.manufacturing_capacity_gwh != null && <HRow dark={dark} label="Capacity" value={`${node.manufacturing_capacity_gwh} GWh`} />}
        </div>
      )}
      {node.id === INVESTOR_META_ID && (
        <div className="text-xs text-bmw-blue mt-2">Click to see all investors</div>
      )}
      {node.in_db !== false && node.id !== INVESTOR_META_ID && (
        <div className="text-xs text-bmw-blue mt-2">Click to open profile</div>
      )}
    </div>
  )
}

function HRow({ dark, label, value }) {
  return (
    <div className="text-xs flex justify-between gap-4">
      <span className={dark ? 'text-gray-500' : 'text-gray-400'}>{label}</span>
      <span className={`font-medium ${dark ? 'text-gray-200' : 'text-gray-700'}`}>{value}</span>
    </div>
  )
}

function FilterSection({ title, dark, children }) {
  const [open, setOpen] = useState(true)
  return (
    <div className={`border-b ${dark ? 'border-gray-700' : 'border-bmw-border'}`}>
      <button
        onClick={() => setOpen(!open)}
        className={`w-full px-4 py-2.5 text-xs font-medium uppercase tracking-wider flex items-center justify-between ${
          dark ? 'text-gray-400 hover:text-gray-300' : 'text-gray-500 hover:text-gray-700'
        }`}
      >
        {title}
        <span className="text-[10px]">{open ? '\u25B2' : '\u25BC'}</span>
      </button>
      {open && (
        <div className="px-4 pb-3 space-y-2">
          {children}
        </div>
      )}
    </div>
  )
}
