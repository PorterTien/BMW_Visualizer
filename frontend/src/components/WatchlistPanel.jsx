import React, { useEffect, useState, useCallback, useRef } from 'react'
import {
  getWatchlist,
  getWatchlistDigest,
  triggerWatchlistDigest,
  triggerCompanyDigest,
  removeFromWatchlist,
  getArticleThumbnail,
  getCompanyDetail,
} from '../api/client'

const CATEGORY_COLORS = {
  funding:     'bg-blue-50 text-bmw-blue',
  partnership: 'bg-blue-50 text-bmw-blue',
  regulatory:  'bg-red-50 text-red-700',
  technology:  'bg-blue-50 text-bmw-blue',
  expansion:   'bg-gray-100 text-bmw-text-secondary',
  leadership:  'bg-gray-100 text-bmw-text-secondary',
  financial:   'bg-gray-100 text-bmw-text-secondary',
  other:       'bg-gray-100 text-bmw-gray-dark',
}

// Module-level cache so thumbnails persist across re-renders
const thumbCache = {}

function getFaviconUrl(url) {
  try {
    const domain = new URL(url).hostname.replace(/^www\./, '')
    return `https://www.google.com/s2/favicons?sz=64&domain=${domain}`
  } catch { return null }
}

function ImportanceDots({ score }) {
  return (
    <div className="flex gap-0.5 items-center">
      {Array.from({ length: 10 }).map((_, i) => (
        <div key={i} className={`w-1.5 h-1.5 rounded-full ${
          i < score
            ? score >= 8 ? 'bg-red-500' : score >= 5 ? 'bg-amber-400' : 'bg-gray-300'
            : 'bg-gray-100'
        }`} />
      ))}
    </div>
  )
}

// Fetches og:image from the backend and shows it; falls back to favicon
function ArticleThumbnail({ url }) {
  const [src, setSrc] = useState(thumbCache[url] ?? null)
  const [loaded, setLoaded] = useState(!!thumbCache[url])
  const [imgFailed, setImgFailed] = useState(false)
  const favicon = url ? getFaviconUrl(url) : null

  useEffect(() => {
    if (!url) return
    if (thumbCache[url] !== undefined) {
      setSrc(thumbCache[url])
      setLoaded(true)
      return
    }
    getArticleThumbnail(url)
      .then(({ data }) => {
        thumbCache[url] = data.thumbnail_url || null
        setSrc(data.thumbnail_url || null)
        setLoaded(true)
      })
      .catch(() => {
        thumbCache[url] = null
        setLoaded(true)
      })
  }, [url])

  if (!loaded) {
    // Skeleton while fetching
    return <div className="w-20 h-14 rounded bg-gray-100 animate-pulse flex-shrink-0" />
  }

  if (src && !imgFailed) {
    return (
      <div className="w-20 h-14 rounded overflow-hidden flex-shrink-0 bg-gray-100">
        <img
          src={src}
          alt=""
          className="w-full h-full object-cover"
          onError={() => setImgFailed(true)}
        />
      </div>
    )
  }

  // Fallback: favicon in a box
  return (
    <div className="w-20 h-14 rounded flex-shrink-0 bg-gray-50 border border-gray-100 flex items-center justify-center">
      {favicon ? (
        <img src={favicon} alt="" className="w-6 h-6 object-contain opacity-50" />
      ) : (
        <svg className="w-6 h-6 text-gray-200" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.5">
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 7.5h1.5m-1.5 3h1.5m-7.5 3h7.5m-7.5 3h7.5m3-9h3.375c.621 0 1.125.504 1.125 1.125V18a2.25 2.25 0 0 1-2.25 2.25M16.5 7.5V18a2.25 2.25 0 0 0 2.25 2.25M16.5 7.5V4.875c0-.621-.504-1.125-1.125-1.125H4.125C3.504 3.75 3 4.254 3 4.875V18a2.25 2.25 0 0 0 2.25 2.25h13.5M6 7.5h3v3H6v-3Z" />
        </svg>
      )}
    </div>
  )
}

function ArticleRow({ article }) {
  return (
    <div className={`flex gap-3 p-3 rounded-lg border ${article.is_breaking ? 'border-red-200 bg-red-50' : 'border-gray-100 bg-white'}`}>
      <ArticleThumbnail url={article.url} />

      <div className="flex-1 min-w-0">
        <div className="flex items-start justify-between gap-2">
          <a
            href={article.url}
            target="_blank"
            rel="noreferrer"
            className={`text-sm font-medium leading-snug hover:underline line-clamp-2 ${article.is_breaking ? 'text-red-700' : 'text-[#1A5FAD]'}`}
          >
            {article.title}
            {article.is_breaking && (
              <span className="ml-2 inline-flex items-center text-[10px] font-bold text-red-600 bg-red-100 px-1.5 py-0.5 rounded uppercase tracking-wide">
                Breaking
              </span>
            )}
          </a>
          <div className="flex-shrink-0 pt-0.5">
            <ImportanceDots score={article.importance || 0} />
          </div>
        </div>
        {article.why && (
          <p className="text-xs text-gray-500 mt-1 leading-relaxed line-clamp-2">{article.why}</p>
        )}
        <div className="flex items-center gap-2 mt-1.5 flex-wrap">
          {article.category && (
            <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${CATEGORY_COLORS[article.category] || CATEGORY_COLORS.other}`}>
              {article.category}
            </span>
          )}
          {article.published_date && (
            <span className="text-[10px] text-gray-400">{article.published_date}</span>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Drag-to-reorder hook ──────────────────────────────────────────────────────
function useDraggableList(items, setItems, keyFn) {
  const dragIdx = useRef(null)
  const overIdx = useRef(null)

  const onDragStart = (i) => { dragIdx.current = i }
  const onDragEnter = (i) => {
    if (dragIdx.current === null || dragIdx.current === i) return
    overIdx.current = i
    const next = [...items]
    const [moved] = next.splice(dragIdx.current, 1)
    next.splice(i, 0, moved)
    dragIdx.current = i
    setItems(next)
  }
  const onDragEnd = () => { dragIdx.current = null; overIdx.current = null }

  const itemProps = (i) => ({
    draggable: true,
    onDragStart: () => onDragStart(i),
    onDragEnter: () => onDragEnter(i),
    onDragEnd,
    onDragOver: (e) => e.preventDefault(),
  })

  return { itemProps }
}

function fmtMoney(v) {
  if (v == null || v === '') return null
  const n = Number(v)
  if (isNaN(n) || n === 0) return null
  if (n >= 1000) return `$${(n / 1000).toFixed(1)}B`
  if (n >= 1) return `$${Math.round(n)}M`
  return `$${(n * 1000).toFixed(0)}K`
}

function nameColor(name) {
  let h = 0
  for (let i = 0; i < (name || '').length; i++) h = (Math.imul(31, h) + name.charCodeAt(i)) | 0
  return `hsl(${((h >>> 0) % 12) * 30}, 55%, 52%)`
}

function CompanyFavicon({ website, name, size = 10 }) {
  const [failed, setFailed] = useState(false)
  let domain = ''
  try { domain = new URL(website).hostname.replace(/^www\./, '') } catch {}
  const initials = (name || '').replace(/[^A-Za-z0-9]/g, '').slice(0, 2).toUpperCase() || '?'
  const sizeClass = `w-${size} h-${size}`
  if (domain && !failed) {
    return (
      <img
        src={`https://www.google.com/s2/favicons?sz=128&domain=${domain}`}
        alt=""
        className={`${sizeClass} rounded-lg object-contain bg-white p-0.5 border border-gray-100 flex-shrink-0`}
        onError={() => setFailed(true)}
      />
    )
  }
  return (
    <div
      className={`${sizeClass} rounded-lg flex items-center justify-center text-white font-bold flex-shrink-0`}
      style={{ backgroundColor: nameColor(name || ''), fontSize: size * 1.5 }}
    >
      {initials}
    </div>
  )
}

function InfoRow({ label, value }) {
  if (!value) return null
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">{label}</span>
      <span className="text-xs text-gray-700 leading-snug">{value}</span>
    </div>
  )
}

export default function WatchlistPanel({ onOpenCompany }) {
  const [watchlist, setWatchlist] = useState([])
  const [digests, setDigests] = useState([])
  const [loading, setLoading] = useState(true)
  const [runningAll, setRunningAll] = useState(false)
  const [refreshingId, setRefreshingId] = useState(null)
  const [lastRefreshed, setLastRefreshed] = useState(null)
  const [pollTimer, setPollTimer] = useState(null)
  const [selectedId, setSelectedId] = useState(null)
  const [orderedIds, setOrderedIds] = useState([])   // user-dragged order
  const [companyDetail, setCompanyDetail] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [infoWidth, setInfoWidth] = useState(288)   // px — default 288 (w-72)
  const resizingRef = useRef(false)
  const resizeStartRef = useRef({ x: 0, w: 0 })

  const startInfoResize = useCallback((e) => {
    e.preventDefault()
    resizingRef.current = true
    resizeStartRef.current = { x: e.clientX, w: infoWidth }
    const onMove = (ev) => {
      if (!resizingRef.current) return
      const delta = ev.clientX - resizeStartRef.current.x
      setInfoWidth(Math.max(180, Math.min(520, resizeStartRef.current.w + delta)))
    }
    const onUp = () => {
      resizingRef.current = false
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }, [infoWidth])

  const loadData = useCallback(async () => {
    try {
      const [{ data: wl }, { data: dg }] = await Promise.all([
        getWatchlist(),
        getWatchlistDigest(),
      ])
      setWatchlist(wl)
      setDigests(dg)
      setOrderedIds((prev) => {
        // Preserve existing order, append any new companies at the end
        const prevSet = new Set(prev)
        const newIds = wl.map((w) => w.company_id).filter((id) => !prevSet.has(id))
        const kept = prev.filter((id) => wl.some((w) => w.company_id === id))
        return [...kept, ...newIds]
      })
      setSelectedId((prev) => prev ?? (wl[0]?.company_id ?? null))
    } catch (e) { console.error(e) }
  }, [])

  useEffect(() => { loadData().finally(() => setLoading(false)) }, [loadData])

  // Fetch full company detail when selection changes
  useEffect(() => {
    if (!selectedId) { setCompanyDetail(null); return }
    setDetailLoading(true)
    setCompanyDetail(null)
    getCompanyDetail(selectedId)
      .then(({ data }) => setCompanyDetail(data))
      .catch(() => setCompanyDetail(null))
      .finally(() => setDetailLoading(false))
  }, [selectedId])

  // Persist order to localStorage
  useEffect(() => {
    if (orderedIds.length > 0) {
      try { localStorage.setItem('watchlist-order', JSON.stringify(orderedIds)) } catch {}
    }
  }, [orderedIds])
  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem('watchlist-order') || '[]')
      if (saved.length > 0) setOrderedIds(saved)
    } catch {}
  }, [])

  function startPolling() {
    const t = setInterval(() => loadData(), 4000)
    setPollTimer(t)
    setTimeout(() => { clearInterval(t); setPollTimer(null) }, 60000)
  }

  async function handleRunAll() {
    setRunningAll(true)
    try { await triggerWatchlistDigest(); setLastRefreshed(new Date().toLocaleTimeString()); startPolling() }
    catch (e) { console.error(e) }
    setTimeout(() => setRunningAll(false), 2000)
  }

  async function handleRefreshOne(companyId) {
    setRefreshingId(companyId)
    try { await triggerCompanyDigest(companyId); setLastRefreshed(new Date().toLocaleTimeString()); startPolling() }
    catch (e) { console.error(e) }
    setTimeout(() => setRefreshingId(null), 2000)
  }

  async function handleRemove(companyId) {
    try {
      await removeFromWatchlist(companyId)
      setWatchlist((prev) => prev.filter((w) => w.company_id !== companyId))
      setDigests((prev) => prev.filter((d) => d.company_id !== companyId))
      setOrderedIds((prev) => prev.filter((id) => id !== companyId))
      setSelectedId((prev) => (prev === companyId ? null : prev))
    } catch (e) { console.error(e) }
  }

  const digestMap = Object.fromEntries(digests.map((d) => [d.company_id, d]))
  const breakingCount = digests.filter((d) => d.has_breaking).length

  // Apply drag order to watchlist
  const orderedWatchlist = orderedIds
    .map((id) => watchlist.find((w) => w.company_id === id))
    .filter(Boolean)

  const { itemProps } = useDraggableList(orderedWatchlist, (next) => {
    setOrderedIds(next.map((w) => w.company_id))
  }, (w) => w.company_id)

  const selectedDigest = selectedId ? digestMap[selectedId] : null
  const selectedCompany = watchlist.find((w) => w.company_id === selectedId)
  const selectedArticles = [...(selectedDigest?.articles || [])].sort((a, b) => {
    if (a.is_breaking !== b.is_breaking) return a.is_breaking ? -1 : 1
    return (b.importance || 0) - (a.importance || 0)
  })

  if (loading) {
    return <div className="flex items-center justify-center h-full text-gray-400 text-sm">Loading watchlist…</div>
  }

  return (
    <div className="flex flex-col h-full overflow-hidden bg-[#F5F7FA]">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-3 bg-white border-b border-[#DDE4EA] flex-shrink-0">
        <div className="flex items-center gap-3">
          <h2 className="font-semibold text-gray-800 text-sm">Watchlist</h2>
          <span className="text-xs text-gray-400">{watchlist.length} companies</span>
          {breakingCount > 0 && (
            <span className="flex items-center gap-1 text-[11px] font-semibold text-red-600 bg-red-100 px-2 py-0.5 rounded-full">
              <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" />
              {breakingCount} with breaking news
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          {lastRefreshed && <span className="text-xs text-gray-400">Updated {lastRefreshed}</span>}
          {pollTimer && <span className="text-xs text-bmw-blue animate-pulse">Fetching news…</span>}
          <button
            onClick={handleRunAll}
            disabled={runningAll || watchlist.length === 0}
            className="flex items-center gap-1.5 bg-bmw-blue hover:bg-[#2a7de8] disabled:opacity-50 text-white text-xs px-3 py-1.5 rounded transition-colors"
          >
            <svg className={`w-3.5 h-3.5 ${runningAll ? 'animate-spin' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
              <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182m0-4.991v4.99" />
            </svg>
            {runningAll ? 'Running…' : 'Refresh All'}
          </button>
        </div>
      </div>

      {watchlist.length === 0 ? (
        <div className="flex flex-col items-center justify-center flex-1 gap-3 text-center">
          <svg className="w-12 h-12 text-gray-200" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1">
            <path strokeLinecap="round" strokeLinejoin="round" d="M11.48 3.499a.562.562 0 0 1 1.04 0l2.125 5.111a.563.563 0 0 0 .475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 0 0-.182.557l1.285 5.385a.562.562 0 0 1-.84.61l-4.725-2.885a.562.562 0 0 0-.586 0L6.982 20.54a.562.562 0 0 1-.84-.61l1.285-5.386a.562.562 0 0 0-.182-.557l-4.204-3.602a.562.562 0 0 1 .321-.988l5.518-.442a.563.563 0 0 0 .475-.345L11.48 3.5Z" />
          </svg>
          <div className="text-gray-400 text-sm">No companies in your watchlist yet.</div>
          <div className="text-gray-300 text-xs">Star companies in the Company Table to track them here.</div>
        </div>
      ) : (
        <div className="flex flex-1 min-h-0">
          {/* ── Left: draggable company list ── */}
          <div className="w-56 flex-shrink-0 border-r border-[#DDE4EA] bg-white flex flex-col overflow-hidden">
            <div className="px-4 py-2 border-b border-[#DDE4EA] bg-[#F7F9FB] flex items-center justify-between">
              <span className="text-[11px] font-semibold text-gray-500 uppercase tracking-wider">Companies</span>
            </div>
            <div className="flex-1 overflow-y-auto">
              {orderedWatchlist.map((company, i) => {
                const digest = digestMap[company.company_id]
                const articleCount = digest?.articles?.length ?? 0
                const hasBreaking = digest?.has_breaking ?? false
                const isSelected = selectedId === company.company_id
                return (
                  <div
                    key={company.company_id}
                    {...itemProps(i)}
                    onClick={() => setSelectedId(company.company_id)}
                    className={`flex items-center justify-between px-4 py-3 border-b border-[#EEF2F5] cursor-pointer transition-colors select-none
                      ${isSelected ? 'bg-[#EBF2FD] border-l-2 border-l-bmw-blue' : 'hover:bg-[#F7F9FB]'}`}
                  >
                    {/* Drag handle */}
                    <svg className="w-3.5 h-3.5 text-gray-300 mr-2 flex-shrink-0 cursor-grab" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 5.25h16.5m-16.5 6h16.5m-16.5 6h16.5" />
                    </svg>

                    <div className="flex items-center gap-2 min-w-0 flex-1">
                      {hasBreaking && <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse flex-shrink-0" />}
                      <div className="min-w-0">
                        <div className={`text-sm font-medium truncate ${isSelected ? 'text-bmw-blue' : 'text-gray-800'}`}>
                          {company.company_name}
                        </div>
                        <div className="text-[10px] text-gray-400 mt-0.5">
                          {articleCount > 0 ? `${articleCount} article${articleCount !== 1 ? 's' : ''}` : 'No news yet'}
                          {hasBreaking && <span className="ml-1 text-red-500 font-medium">· Breaking</span>}
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center gap-1.5 flex-shrink-0 ml-2">
                      <button
                        onClick={(e) => { e.stopPropagation(); handleRefreshOne(company.company_id) }}
                        disabled={refreshingId === company.company_id}
                        title="Refresh news"
                        className="text-gray-400 hover:text-bmw-blue disabled:opacity-40 transition-colors"
                      >
                        <svg className={`w-3.5 h-3.5 ${refreshingId === company.company_id ? 'animate-spin' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
                          <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182m0-4.991v4.99" />
                        </svg>
                      </button>
                      <button
                        onClick={(e) => { e.stopPropagation(); handleRemove(company.company_id) }}
                        title="Remove from watchlist"
                        className="text-gray-300 hover:text-red-500 transition-colors"
                      >
                        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
                          <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
                        </svg>
                      </button>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>

          {/* ── Middle: company info panel (resizable) ── */}
          <div className="flex-shrink-0 border-r border-[#DDE4EA] bg-white flex flex-col overflow-hidden relative" style={{ width: infoWidth }}>
            {selectedCompany ? (
              detailLoading ? (
                <div className="flex items-center justify-center flex-1 text-gray-400 text-sm">Loading…</div>
              ) : companyDetail ? (
                <div className="flex-1 overflow-y-auto">
                  {/* Company header */}
                  <div className="px-5 py-4 border-b border-[#DDE4EA]">
                    <div className="flex items-center gap-3 mb-3">
                      <CompanyFavicon website={companyDetail.company_website} name={companyDetail.company_name} size={10} />
                      <div className="min-w-0">
                        <button
                          onClick={() => onOpenCompany?.(selectedId)}
                          className="block w-full font-bold text-gray-800 text-sm leading-snug text-left hover:text-bmw-blue hover:underline break-words"
                        >
                          {companyDetail.company_name}
                        </button>
                        {companyDetail.company_type && (
                          <div className="text-xs text-bmw-blue font-medium mt-0.5">{companyDetail.company_type}</div>
                        )}
                      </div>
                    </div>
                    {/* Status + location */}
                    <div className="flex flex-wrap gap-1.5">
                      {companyDetail.company_status && (
                        <span className="text-[10px] bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full">{companyDetail.company_status}</span>
                      )}
                      {[companyDetail.company_hq_city, companyDetail.company_hq_state, companyDetail.company_hq_country].filter(Boolean).length > 0 && (
                        <span className="text-[10px] text-gray-400">
                          {[companyDetail.company_hq_city, companyDetail.company_hq_state, companyDetail.company_hq_country].filter(Boolean).join(', ')}
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Key metrics */}
                  <div className="px-5 py-3 border-b border-[#DDE4EA]">
                    <div className="grid grid-cols-2 gap-x-4 gap-y-3">
                      {fmtMoney(companyDetail.market_cap_usd) && (
                        <InfoRow label="Market Cap" value={fmtMoney(companyDetail.market_cap_usd)} />
                      )}
                      {fmtMoney(companyDetail.revenue_usd) && (
                        <InfoRow label="Revenue" value={fmtMoney(companyDetail.revenue_usd)} />
                      )}
                      {fmtMoney(companyDetail.total_funding_usd) && (
                        <InfoRow label="Total Funding" value={fmtMoney(companyDetail.total_funding_usd)} />
                      )}
                      {(companyDetail.number_of_employees || companyDetail.employee_size) && (
                        <InfoRow label="Employees" value={
                          companyDetail.number_of_employees
                            ? companyDetail.number_of_employees.toLocaleString()
                            : companyDetail.employee_size
                        } />
                      )}
                      {companyDetail.funding_status && (
                        <InfoRow label="Stage" value={companyDetail.funding_status} />
                      )}
                      {companyDetail.supply_chain_segment && (
                        <InfoRow label="Segment" value={companyDetail.supply_chain_segment} />
                      )}
                    </div>
                  </div>

                  {/* Summary */}
                  {companyDetail.summary && (
                    <div className="px-5 py-3 border-b border-[#DDE4EA]">
                      <p className="text-xs text-gray-600 leading-relaxed">{companyDetail.summary}</p>
                    </div>
                  )}

                  {/* Chemistries / products */}
                  <div className="px-5 py-3 border-b border-[#DDE4EA] space-y-2">
                    {companyDetail.chemistries && (
                      <InfoRow label="Chemistries" value={companyDetail.chemistries} />
                    )}
                    {companyDetail.products && (
                      <InfoRow label="Products" value={companyDetail.products} />
                    )}
                    {companyDetail.feedstock && (
                      <InfoRow label="Feedstock" value={companyDetail.feedstock} />
                    )}
                    {companyDetail.hq_company && (
                      <InfoRow label="Parent Company" value={companyDetail.hq_company} />
                    )}
                  </div>

                  {/* Links */}
                  <div className="px-5 py-3 flex flex-wrap gap-2">
                    {companyDetail.company_website && (
                      <a href={companyDetail.company_website} target="_blank" rel="noreferrer"
                        className="text-[11px] text-bmw-blue hover:underline flex items-center gap-1">
                        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2"><path strokeLinecap="round" strokeLinejoin="round" d="M13.19 8.688a4.5 4.5 0 0 1 1.242 7.244l-4.5 4.5a4.5 4.5 0 0 1-6.364-6.364l1.757-1.757m13.35-.622 1.757-1.757a4.5 4.5 0 0 0-6.364-6.364l-4.5 4.5a4.5 4.5 0 0 0 1.242 7.244" /></svg>
                        Website
                      </a>
                    )}
                    {companyDetail.linkedin_url && (
                      <a href={companyDetail.linkedin_url} target="_blank" rel="noreferrer"
                        className="text-[11px] text-[#0A66C2] hover:underline">LinkedIn</a>
                    )}
                    {companyDetail.crunchbase_url && (
                      <a href={companyDetail.crunchbase_url} target="_blank" rel="noreferrer"
                        className="text-[11px] text-[#0288D1] hover:underline">Crunchbase</a>
                    )}
                  </div>
                </div>
              ) : (
                <div className="flex items-center justify-center flex-1 text-gray-300 text-xs">No data available</div>
              )
            ) : (
              <div className="flex items-center justify-center flex-1 text-gray-300 text-xs">Select a company</div>
            )}

            {/* Drag-resize handle on the right edge */}
            <div
              onMouseDown={startInfoResize}
              className="absolute top-0 right-0 w-1.5 h-full cursor-col-resize z-10 group"
              title="Drag to resize"
            >
              <div className="w-full h-full bg-[#DDE4EA] group-hover:bg-bmw-blue transition-colors" />
            </div>
          </div>

          {/* ── Right: news panel ── */}
          <div className="flex-1 min-w-0 flex flex-col overflow-hidden">
            {selectedCompany ? (
              <>
                <div className="px-5 py-3 bg-white border-b border-[#DDE4EA] flex-shrink-0 flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    {selectedDigest?.has_breaking && (
                      <span className="flex items-center gap-1 text-[11px] font-semibold text-red-600 bg-red-100 px-2 py-0.5 rounded-full">
                        <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" />
                        Breaking News
                      </span>
                    )}
                    <span className="text-xs text-gray-500 font-medium">
                      {selectedArticles.length} article{selectedArticles.length !== 1 ? 's' : ''}
                    </span>
                    {selectedDigest?.run_date && (
                      <span className="text-[10px] text-gray-400">· fetched {selectedDigest.run_date}</span>
                    )}
                  </div>
                </div>

                <div className="flex-1 overflow-y-auto p-4">
                  {selectedArticles.length === 0 ? (
                    <div className="flex flex-col items-center justify-center h-full gap-3 text-center">
                      <svg className="w-10 h-10 text-gray-200" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.5">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M12 7.5h1.5m-1.5 3h1.5m-7.5 3h7.5m-7.5 3h7.5m3-9h3.375c.621 0 1.125.504 1.125 1.125V18a2.25 2.25 0 0 1-2.25 2.25M16.5 7.5V18a2.25 2.25 0 0 0 2.25 2.25M16.5 7.5V4.875c0-.621-.504-1.125-1.125-1.125H4.125C3.504 3.75 3 4.254 3 4.875V18a2.25 2.25 0 0 0 2.25 2.25h13.5M6 7.5h3v3H6v-3Z" />
                      </svg>
                      <div className="text-gray-400 text-sm">No articles yet.</div>
                      <button
                        onClick={() => handleRefreshOne(selectedId)}
                        className="text-xs text-bmw-blue hover:underline"
                      >
                        Fetch news now →
                      </button>
                    </div>
                  ) : (
                    <div className="space-y-2 max-w-2xl">
                      {selectedArticles.map((article, i) => (
                        <ArticleRow key={i} article={article} />
                      ))}
                    </div>
                  )}
                </div>
              </>
            ) : (
              <div className="flex items-center justify-center flex-1 text-gray-400 text-sm">
                Select a company to see its news.
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
