import React, { useEffect, useState, useCallback, useRef } from 'react'
import {
  getWatchlist,
  getWatchlistDigest,
  triggerWatchlistDigest,
  triggerCompanyDigest,
  removeFromWatchlist,
  getArticleThumbnail,
  getCompanyDetail,
  getWatchlistLists,
  createWatchlistList,
  renameWatchlistList,
  deleteWatchlistList,
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

import { faviconUrl as getFaviconUrl } from '../utils/favicon'

// Module-level cache so thumbnails persist across re-renders
const thumbCache = {}

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
  const [faviconFailed, setFaviconFailed] = useState(false)
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
      {favicon && !faviconFailed ? (
        <img src={favicon} alt="" className="w-6 h-6 object-contain opacity-50" onError={() => setFaviconFailed(true)} />
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
function useDraggableList(items, setItems) {
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
  const src = getFaviconUrl(website)
  const initials = (name || '').replace(/[^A-Za-z0-9]/g, '').slice(0, 2).toUpperCase() || '?'
  const sizeClass = `w-${size} h-${size}`
  if (src && !failed) {
    return (
      <img
        src={src}
        alt=""
        className={`${sizeClass} rounded-lg object-contain bg-white p-0.5 border border-gray-100 flex-shrink-0`}
        referrerPolicy="no-referrer"
        loading="lazy"
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

export default function WatchlistPanel({ onOpenCompany, session }) {
  const [watchlist, setWatchlist] = useState([])
  const [digests, setDigests] = useState([])
  const [loading, setLoading] = useState(true)
  const [runningAll, setRunningAll] = useState(false)
  const [refreshingId, setRefreshingId] = useState(null)
  const [lastRefreshed, setLastRefreshed] = useState(null)
  // Poll state: `pollActive` drives the "Fetching news…" label; the refs hold
  // the interval + timeout handles so we can tear them down on unmount or on
  // a re-trigger (without the refs the previous poll keeps firing for 60s).
  const [pollActive, setPollActive] = useState(false)
  const pollIntervalRef = useRef(null)
  const pollTimeoutRef = useRef(null)
  const [selectedId, setSelectedId] = useState(null)
  const [orderedIds, setOrderedIds] = useState([])   // user-dragged order
  const [companyDetail, setCompanyDetail] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [infoWidth, setInfoWidth] = useState(() => Math.max(220, Math.floor((window.innerWidth - 224) / 2)))

  // Multi-list state
  const [lists, setLists] = useState([])
  const [collapsedLists, setCollapsedLists] = useState(new Set())
  const [renamingListId, setRenamingListId] = useState(null)
  const [renameValue, setRenameValue] = useState('')
  const [addingList, setAddingList] = useState(false)
  const [newListName, setNewListName] = useState('')
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
      const [{ data: wl }, { data: dg }, { data: ls }] = await Promise.all([
        getWatchlist(),
        getWatchlistDigest(),
        getWatchlistLists(),
      ])
      setWatchlist(wl)
      setDigests(dg)
      setLists(ls)
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

  useEffect(() => {
    loadData().finally(() => setLoading(false))
  }, [loadData])

  // Re-fetch whenever the user logs in or out
  useEffect(() => {
    if (session === undefined) return   // still initializing
    if (!session) {
      // Logged out — clear everything immediately
      setWatchlist([])
      setDigests([])
      setOrderedIds([])
      setSelectedId(null)
      return
    }
    // Logged in — reload
    loadData()
  }, [session, loadData])

  // Fetch full company detail when selection changes
  useEffect(() => {
    if (!selectedId) { setCompanyDetail(null); return }
    // Guard against stale responses if the user clicks through companies
    // quickly: only the latest selection's response is allowed to land.
    let cancelled = false
    setDetailLoading(true)
    setCompanyDetail(null)
    getCompanyDetail(selectedId)
      .then(({ data }) => { if (!cancelled) setCompanyDetail(data) })
      .catch(() => { if (!cancelled) setCompanyDetail(null) })
      .finally(() => { if (!cancelled) setDetailLoading(false) })
    return () => { cancelled = true }
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

  const stopPolling = useCallback(() => {
    if (pollIntervalRef.current) { clearInterval(pollIntervalRef.current); pollIntervalRef.current = null }
    if (pollTimeoutRef.current)  { clearTimeout(pollTimeoutRef.current);   pollTimeoutRef.current = null }
    setPollActive(false)
  }, [])

  function startPolling() {
    stopPolling()
    pollIntervalRef.current = setInterval(() => loadData(), 4000)
    pollTimeoutRef.current  = setTimeout(stopPolling, 60000)
    setPollActive(true)
  }

  useEffect(() => stopPolling, [stopPolling])

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

  async function handleRemove(companyId, listId = null) {
    try {
      await removeFromWatchlist(companyId, listId)
      // If removing from a specific list, only remove from watchlist if no longer in any list
      if (listId !== null) {
        // Reload to get accurate state
        const { data: wl } = await getWatchlist()
        const { data: ls } = await getWatchlistLists()
        setWatchlist(wl)
        setLists(ls)
        const stillWatched = wl.some((w) => w.company_id === companyId)
        if (!stillWatched) {
          setOrderedIds((prev) => prev.filter((id) => id !== companyId))
          setSelectedId((prev) => (prev === companyId ? null : prev))
        }
      } else {
        setWatchlist((prev) => prev.filter((w) => w.company_id !== companyId))
        setDigests((prev) => prev.filter((d) => d.company_id !== companyId))
        setOrderedIds((prev) => prev.filter((id) => id !== companyId))
        setSelectedId((prev) => (prev === companyId ? null : prev))
        getWatchlistLists().then(({ data }) => setLists(data)).catch(() => {})
      }
    } catch (e) { console.error(e) }
  }

  function toggleCollapse(listId) {
    setCollapsedLists((prev) => {
      const next = new Set(prev)
      if (next.has(listId)) next.delete(listId); else next.add(listId)
      return next
    })
  }

  async function handleCreateList() {
    const name = newListName.trim()
    if (!name) return
    try {
      const { data: lst } = await createWatchlistList(name)
      setLists((prev) => [...prev, lst])
    } catch (e) { console.error(e) }
    setAddingList(false)
    setNewListName('')
  }

  async function handleRenameList(listId) {
    const name = renameValue.trim()
    if (!name) { setRenamingListId(null); return }
    try {
      await renameWatchlistList(listId, name)
      setLists((prev) => prev.map((l) => l.id === listId ? { ...l, name } : l))
    } catch (e) { console.error(e) }
    setRenamingListId(null)
    setRenameValue('')
  }

  async function handleDeleteList(listId) {
    if (!window.confirm('Delete this list? Companies in it will be removed.')) return
    try {
      await deleteWatchlistList(listId)
      setLists((prev) => prev.filter((l) => l.id !== listId))
      setCollapsedLists((prev) => { const next = new Set(prev); next.delete(listId); return next })
      const { data: wl } = await getWatchlist()
      setWatchlist(wl)
      setOrderedIds((prev) => prev.filter((id) => wl.some((w) => w.company_id === id)))
      setSelectedId((prev) => (wl.some((w) => w.company_id === prev) ? prev : null))
    } catch (e) { console.error(e) }
  }

  const digestMap = Object.fromEntries(digests.map((d) => [d.company_id, d]))
  const breakingCount = digests.filter((d) => d.has_breaking).length

  // Group watchlist entries by list_id for accordion display
  const entriesByList = {}
  for (const lst of lists) entriesByList[lst.id] = []
  for (const entry of watchlist) {
    if (entry.list_id != null && entriesByList[entry.list_id]) {
      entriesByList[entry.list_id].push(entry)
    }
  }

  // Unique company count across all lists
  const totalUniqueCompanies = new Set(watchlist.map((w) => w.company_id)).size

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
          <span className="text-xs text-gray-400">{totalUniqueCompanies} companies</span>
          {breakingCount > 0 && (
            <span className="flex items-center gap-1 text-[11px] font-semibold text-red-600 bg-red-100 px-2 py-0.5 rounded-full">
              <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" />
              {breakingCount} with breaking news
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          {lastRefreshed && <span className="text-xs text-gray-400">Updated {lastRefreshed}</span>}
          {pollActive && <span className="text-xs text-bmw-blue animate-pulse">Fetching news…</span>}
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

      <div className="flex flex-1 min-h-0">
          {/* ── Left: accordion lists ── */}
          <div className="w-64 flex-shrink-0 border-r border-[#DDE4EA] bg-white flex flex-col overflow-hidden">
            <div className="flex-1 overflow-y-auto">
              {lists.length === 0 && (
                <div className="flex flex-col items-center justify-center py-10 gap-2 text-center px-4">
                  <svg className="w-10 h-10 text-gray-200" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M11.48 3.499a.562.562 0 0 1 1.04 0l2.125 5.111a.563.563 0 0 0 .475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 0 0-.182.557l1.285 5.385a.562.562 0 0 1-.84.61l-4.725-2.885a.562.562 0 0 0-.586 0L6.982 20.54a.562.562 0 0 1-.84-.61l1.285-5.386a.562.562 0 0 0-.182-.557l-4.204-3.602a.562.562 0 0 1 .321-.988l5.518-.442a.563.563 0 0 0 .475-.345L11.48 3.5Z" />
                  </svg>
                  <div className="text-gray-400 text-xs">No lists yet. Create one below.</div>
                </div>
              )}
              {lists.map((lst) => {
                const listEntries = entriesByList[lst.id] || []
                const isCollapsed = collapsedLists.has(lst.id)
                const listBreaking = listEntries.some((e) => digestMap[e.company_id]?.has_breaking)
                return (
                  <div key={lst.id} className="border-b border-[#DDE4EA]">
                    {/* List header — click to collapse/expand */}
                    <div
                      onClick={() => toggleCollapse(lst.id)}
                      className="flex items-center justify-between px-3 py-2.5 bg-[#F7F9FB] cursor-pointer hover:bg-[#EEF2F6] select-none group"
                    >
                      <div className="flex items-center gap-2 min-w-0 flex-1">
                        <svg
                          className={`w-3 h-3 text-gray-400 flex-shrink-0 transition-transform duration-150 ${isCollapsed ? '' : 'rotate-90'}`}
                          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2.5"
                        >
                          <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
                        </svg>
                        {renamingListId === lst.id ? (
                          <input
                            autoFocus
                            type="text"
                            value={renameValue}
                            onClick={(e) => e.stopPropagation()}
                            onChange={(e) => setRenameValue(e.target.value)}
                            onBlur={() => handleRenameList(lst.id)}
                            onKeyDown={(e) => {
                              e.stopPropagation()
                              if (e.key === 'Enter') handleRenameList(lst.id)
                              if (e.key === 'Escape') { setRenamingListId(null); setRenameValue('') }
                            }}
                            className="flex-1 text-xs border border-bmw-blue rounded px-1.5 py-0.5 focus:outline-none bg-white"
                          />
                        ) : (
                          <span className="text-xs font-semibold text-gray-700 truncate">{lst.name}</span>
                        )}
                        {listBreaking && <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse flex-shrink-0" />}
                      </div>
                      <div className="flex items-center gap-1 flex-shrink-0 ml-1">
                        <span className="text-[10px] text-gray-400">{listEntries.length}</span>
                        <button
                          onClick={(e) => { e.stopPropagation(); setRenamingListId(lst.id); setRenameValue(lst.name) }}
                          title="Rename"
                          className="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-bmw-blue transition-all p-0.5"
                        >
                          <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
                            <path strokeLinecap="round" strokeLinejoin="round" d="m16.862 4.487 1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L6.832 19.82a4.5 4.5 0 0 1-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 0 1 1.13-1.897L16.863 4.487Z" />
                          </svg>
                        </button>
                        <button
                          onClick={(e) => { e.stopPropagation(); handleDeleteList(lst.id) }}
                          title="Delete list"
                          className="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-400 transition-all p-0.5"
                        >
                          <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
                            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                          </svg>
                        </button>
                      </div>
                    </div>
                    {/* Companies in this list */}
                    {!isCollapsed && (
                      <div>
                        {listEntries.length === 0 ? (
                          <div className="px-4 py-3 text-[11px] text-gray-300 italic">No companies yet</div>
                        ) : listEntries.map((entry) => {
                          const digest = digestMap[entry.company_id]
                          const articleCount = digest?.articles?.length ?? 0
                          const hasBreaking = digest?.has_breaking ?? false
                          const isSelected = selectedId === entry.company_id
                          return (
                            <div
                              key={`${lst.id}-${entry.company_id}`}
                              onClick={() => setSelectedId(entry.company_id)}
                              className={`flex items-center justify-between px-3 py-2.5 border-b border-[#F0F3F6] cursor-pointer transition-colors select-none
                                ${isSelected ? 'bg-[#EBF2FD] border-l-2 border-l-bmw-blue' : 'hover:bg-[#F7F9FB]'}`}
                            >
                              <div className="flex items-center gap-2 min-w-0 flex-1">
                                {hasBreaking && <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse flex-shrink-0" />}
                                <CompanyFavicon website={entry.company_website} name={entry.company_name} size={6} />
                                <div className="min-w-0">
                                  <div className={`text-xs font-medium truncate ${isSelected ? 'text-bmw-blue' : 'text-gray-800'}`}>
                                    {entry.company_name}
                                  </div>
                                  <div className="text-[10px] text-gray-400">
                                    {articleCount > 0 ? `${articleCount} article${articleCount !== 1 ? 's' : ''}` : 'No news yet'}
                                    {hasBreaking && <span className="ml-1 text-red-500 font-medium">· Breaking</span>}
                                  </div>
                                </div>
                              </div>
                              <div className="flex items-center gap-1 flex-shrink-0 ml-1">
                                <button
                                  onClick={(e) => { e.stopPropagation(); handleRefreshOne(entry.company_id) }}
                                  disabled={refreshingId === entry.company_id}
                                  title="Refresh news"
                                  className="text-gray-300 hover:text-bmw-blue disabled:opacity-40 transition-colors"
                                >
                                  <svg className={`w-3 h-3 ${refreshingId === entry.company_id ? 'animate-spin' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
                                    <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182m0-4.991v4.99" />
                                  </svg>
                                </button>
                                <button
                                  onClick={(e) => { e.stopPropagation(); handleRemove(entry.company_id, lst.id) }}
                                  title="Remove from this list"
                                  className="text-amber-400 hover:text-gray-300 transition-colors"
                                >
                                  <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor" stroke="none">
                                    <path d="M12 17.27L18.18 21l-1.64-7.03L22 9.24l-7.19-.61L12 2 9.19 8.63 2 9.24l5.46 4.73L5.82 21z" />
                                  </svg>
                                </button>
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
            {/* New list footer */}
            <div className="border-t border-[#DDE4EA] px-3 py-2 bg-[#F7F9FB] flex-shrink-0">
              {addingList ? (
                <div className="flex gap-1.5">
                  <input
                    autoFocus
                    type="text"
                    placeholder="List name…"
                    value={newListName}
                    onChange={(e) => setNewListName(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') handleCreateList()
                      if (e.key === 'Escape') { setAddingList(false); setNewListName('') }
                    }}
                    className="flex-1 text-xs border border-gray-200 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-bmw-blue"
                  />
                  <button onClick={handleCreateList} className="text-xs bg-bmw-blue text-white px-2.5 py-1 rounded hover:bg-[#2a7de8]">Add</button>
                  <button onClick={() => { setAddingList(false); setNewListName('') }} className="text-xs text-gray-400 hover:text-gray-600 px-1">Cancel</button>
                </div>
              ) : (
                <button
                  onClick={() => setAddingList(true)}
                  className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-bmw-blue transition-colors w-full"
                >
                  <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
                  </svg>
                  New list
                </button>
              )}
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
    </div>
  )
}
