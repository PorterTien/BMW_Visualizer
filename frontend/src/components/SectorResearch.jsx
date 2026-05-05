import { useState, useEffect, useRef, useCallback } from 'react'
import {
  getSectorCategories,
  runSectorResearch,
  getSectorJob,
  verifySectorUrls,
  approveSectorResearch,
  chatWithSector,
} from '../api/client'

// ── Utility ──────────────────────────────────────────────────────────────────

function UrlBadge({ url, verification }) {
  if (!url) return <span className="text-bmw-gray-dark text-xs">—</span>
  const v = verification[url]
  const shortUrl = url.replace(/^https?:\/\//, '').slice(0, 36) + '…'
  const link = (
    <a href={url} target="_blank" rel="noopener noreferrer"
      className="text-bmw-blue text-xs underline truncate max-w-[140px]"
      title={url}>
      {shortUrl}
    </a>
  )
  if (!v || (!v.valid && v.status_code !== 404)) {
    return <span className="flex items-center gap-1 min-w-0">{link}</span>
  }
  return (
    <span className="flex items-center gap-1 min-w-0">
      <span className={`text-xs font-bold flex-shrink-0 ${v.valid ? 'text-bmw-green' : 'text-bmw-red'}`}>
        {v.valid ? '✓' : '404'}
      </span>
      {link}
    </span>
  )
}

function CategoryBadge({ category }) {
  const colors = {
    'R&D Discovery': 'bg-purple-100 text-purple-800',
    'Start-up Announcement': 'bg-green-100 text-green-800',
    'Cell Supplier Announcement': 'bg-blue-100 text-blue-800',
    'Solid-State': 'bg-indigo-100 text-indigo-800',
    'Electric Vehicle OEM Announcement': 'bg-orange-100 text-orange-800',
    'Facility': 'bg-yellow-100 text-yellow-800',
    'Funding': 'bg-emerald-100 text-emerald-800',
    'Regulatory': 'bg-red-100 text-red-800',
    'Market': 'bg-gray-100 text-gray-800',
  }
  const cls = colors[category] || 'bg-gray-100 text-gray-700'
  return (
    <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded whitespace-nowrap ${cls}`}>
      {category || '—'}
    </span>
  )
}

function StatusBadge({ status }) {
  const colors = {
    Commercial: 'bg-green-100 text-green-800',
    Operational: 'bg-green-100 text-green-800',
    'Pre-commercial/startup': 'bg-yellow-100 text-yellow-800',
    'Pilot Plant': 'bg-orange-100 text-orange-800',
    Planned: 'bg-gray-100 text-gray-700',
    'Under Construction': 'bg-blue-100 text-blue-800',
    Closed: 'bg-red-100 text-red-800',
    Paused: 'bg-red-100 text-red-700',
  }
  const cls = colors[status] || 'bg-gray-100 text-gray-700'
  return (
    <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded whitespace-nowrap ${cls}`}>
      {status || '—'}
    </span>
  )
}

// ── Companies table ───────────────────────────────────────────────────────────

function CompaniesTable({ companies, selected, onToggle, onSelectAll, verification }) {
  const allSelected = companies.length > 0 && companies.every((_, i) => selected.has(i))

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr className="bg-bmw-gray-light border-b border-bmw-border">
            <th className="w-8 px-3 py-2">
              <input type="checkbox" checked={allSelected} onChange={onSelectAll}
                className="w-3.5 h-3.5 accent-bmw-blue cursor-pointer" />
            </th>
            <th className="px-3 py-2 text-left font-semibold text-bmw-navy whitespace-nowrap">Company</th>
            <th className="px-3 py-2 text-left font-semibold text-bmw-navy whitespace-nowrap">Type</th>
            <th className="px-3 py-2 text-left font-semibold text-bmw-navy whitespace-nowrap">Status</th>
            <th className="px-3 py-2 text-left font-semibold text-bmw-navy whitespace-nowrap">HQ</th>
            <th className="px-3 py-2 text-left font-semibold text-bmw-navy whitespace-nowrap">Employees</th>
            <th className="px-3 py-2 text-left font-semibold text-bmw-navy whitespace-nowrap">Funding ($M)</th>
            <th className="px-3 py-2 text-left font-semibold text-bmw-navy whitespace-nowrap">Website</th>
            <th className="px-3 py-2 text-left font-semibold text-bmw-navy">Summary</th>
          </tr>
        </thead>
        <tbody>
          {companies.map((c, i) => (
            <tr key={i}
              onClick={() => onToggle(i)}
              className={`border-b border-bmw-border cursor-pointer transition-colors ${
                selected.has(i) ? 'bg-blue-50' : 'hover:bg-bmw-gray-light'
              }`}
            >
              <td className="px-3 py-2" onClick={e => e.stopPropagation()}>
                <input type="checkbox" checked={selected.has(i)} onChange={() => onToggle(i)}
                  className="w-3.5 h-3.5 accent-bmw-blue cursor-pointer" />
              </td>
              <td className="px-3 py-2 font-medium text-bmw-navy whitespace-nowrap">{c.company_name}</td>
              <td className="px-3 py-2 whitespace-nowrap">
                <span className="text-bmw-text-secondary">{c.company_type || '—'}</span>
              </td>
              <td className="px-3 py-2 whitespace-nowrap">
                <StatusBadge status={c.company_status} />
              </td>
              <td className="px-3 py-2 text-bmw-text-secondary whitespace-nowrap">
                {[c.company_hq_city, c.company_hq_state].filter(Boolean).join(', ') || '—'}
              </td>
              <td className="px-3 py-2 text-center text-bmw-text-secondary">
                {c.number_of_employees?.toLocaleString() || '—'}
              </td>
              <td className="px-3 py-2 text-center text-bmw-text-secondary">
                {c.total_funding_usd != null ? `$${c.total_funding_usd.toFixed(0)}M` : '—'}
              </td>
              <td className="px-3 py-2">
                <UrlBadge url={c.company_website} verification={verification} />
              </td>
              <td className="px-3 py-2 text-bmw-text-secondary max-w-xs">
                <span className="line-clamp-2">{c.summary}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── News table (read-only reference) ─────────────────────────────────────────

function NewsTable({ news, verification }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr className="bg-bmw-gray-light border-b border-bmw-border">
            <th className="px-3 py-2 text-left font-semibold text-bmw-navy">Headline</th>
            <th className="px-3 py-2 text-left font-semibold text-bmw-navy whitespace-nowrap">Category</th>
            <th className="px-3 py-2 text-left font-semibold text-bmw-navy whitespace-nowrap">Date</th>
            <th className="px-3 py-2 text-left font-semibold text-bmw-navy whitespace-nowrap">Source</th>
            <th className="px-3 py-2 text-left font-semibold text-bmw-navy">Partners</th>
            <th className="px-3 py-2 text-left font-semibold text-bmw-navy">URL</th>
            <th className="px-3 py-2 text-left font-semibold text-bmw-navy">Summary</th>
          </tr>
        </thead>
        <tbody>
          {news.map((n, i) => (
            <tr key={i} className="border-b border-bmw-border hover:bg-bmw-gray-light">
              <td className="px-3 py-2 font-medium text-bmw-navy max-w-[240px]">
                <span className="line-clamp-2">{n.news_headline}</span>
              </td>
              <td className="px-3 py-2 whitespace-nowrap">
                <CategoryBadge category={n.category} />
              </td>
              <td className="px-3 py-2 text-bmw-text-secondary whitespace-nowrap">{n.date_of_article || '—'}</td>
              <td className="px-3 py-2 text-bmw-text-secondary whitespace-nowrap">{n.news_source || '—'}</td>
              <td className="px-3 py-2 text-bmw-text-secondary max-w-[120px]">
                {Array.isArray(n.partners) ? n.partners.slice(0, 2).join(', ') : '—'}
              </td>
              <td className="px-3 py-2">
                <UrlBadge url={n.url} verification={verification} />
              </td>
              <td className="px-3 py-2 text-bmw-text-secondary max-w-xs">
                <span className="line-clamp-2">{n.summary}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function SectorResearch() {
  const [categories, setCategories] = useState([])
  const [category, setCategory] = useState('')
  const [jobId, setJobId] = useState(null)
  const [jobStatus, setJobStatus] = useState(null)
  const [companies, setCompanies] = useState([])
  const [news, setNews] = useState([])
  const [activeTab, setActiveTab] = useState('companies')
  const [selectedCompanies, setSelectedCompanies] = useState(new Set())
  const [verification, setVerification] = useState({})
  const [verifying, setVerifying] = useState(false)
  const [approving, setApproving] = useState(false)
  const [approvalResult, setApprovalResult] = useState(null)
  const [error, setError] = useState(null)
  const [chatMessages, setChatMessages] = useState([])
  const [chatInput, setChatInput] = useState('')
  const [chatLoading, setChatLoading] = useState(false)
  const pollRef = useRef(null)
  const chatBottomRef = useRef(null)

  useEffect(() => {
    getSectorCategories()
      .then(({ data }) => {
        setCategories(data.categories || [])
        if (data.categories?.length) setCategory(data.categories[0])
      })
      .catch(() => {})
  }, [])

  // Poll job until complete/failed
  useEffect(() => {
    if (!jobId) return
    pollRef.current = setInterval(async () => {
      try {
        const { data } = await getSectorJob(jobId)
        setJobStatus(data.status)
        if (data.status === 'complete' && data.result) {
          const co = data.result.companies || []
          const ne = data.result.news || []
          setCompanies(co)
          setNews(ne)
          setSelectedCompanies(new Set(co.map((_, i) => i)))
          setActiveTab('companies')
          clearInterval(pollRef.current)
        } else if (data.status === 'failed') {
          setError(data.result?.error || 'Research failed')
          clearInterval(pollRef.current)
        }
      } catch (e) {
        clearInterval(pollRef.current)
      }
    }, 3000)
    return () => clearInterval(pollRef.current)
  }, [jobId])

  useEffect(() => {
    chatBottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [chatMessages])

  async function handleChatSend() {
    const msg = chatInput.trim()
    if (!msg || chatLoading) return
    setChatInput('')
    setChatMessages(prev => [...prev, { role: 'user', text: msg }])
    setChatLoading(true)
    try {
      const { data } = await chatWithSector(msg, category, companies, news)
      setChatMessages(prev => [...prev, { role: 'assistant', text: data.response }])
    } catch {
      setChatMessages(prev => [...prev, { role: 'assistant', text: 'Error getting response.' }])
    }
    setChatLoading(false)
  }

  async function handleRun() {
    if (!category) return
    setError(null)
    setApprovalResult(null)
    setCompanies([])
    setNews([])
    setVerification({})
    setSelectedCompanies(new Set())
    setJobId(null)
    setJobStatus(null)
    try {
      const { data } = await runSectorResearch(category)
      setJobId(data.job_id)
      setJobStatus('pending')
    } catch (e) {
      setError('Failed to start research. Check that the backend is running.')
    }
  }

  function handleToggle(idx) {
    setSelectedCompanies(prev => {
      const next = new Set(prev)
      next.has(idx) ? next.delete(idx) : next.add(idx)
      return next
    })
  }

  function handleSelectAll() {
    const allSelected = companies.every((_, i) => selectedCompanies.has(i))
    setSelectedCompanies(allSelected ? new Set() : new Set(companies.map((_, i) => i)))
  }

  async function handleVerifyUrls() {
    const urls = []
    companies.forEach(c => { if (c.company_website) urls.push(c.company_website) })
    news.forEach(n => { if (n.url) urls.push(n.url) })
    const unique = [...new Set(urls)]
    if (!unique.length) return
    setVerifying(true)
    try {
      const { data } = await verifySectorUrls(unique)
      setVerification(data)
    } catch (e) {
      setError('URL verification failed')
    } finally {
      setVerifying(false)
    }
  }

  async function handleApprove(approveAll = false) {
    const approved = approveAll
      ? companies
      : companies.filter((_, i) => selectedCompanies.has(i))
    if (!approved.length) return
    setApproving(true)
    setError(null)
    try {
      const { data } = await approveSectorResearch(approved, [])
      setApprovalResult(data)
    } catch (e) {
      setError('Approval failed. Check backend logs.')
    } finally {
      setApproving(false)
    }
  }

  const isRunning = jobStatus === 'pending' || jobStatus === 'running'
  const hasResults = companies.length > 0
  const selectedCount = selectedCompanies.size

  // Collect all URLs for batch verify
  const allUrls = [
    ...companies.map(c => c.company_website),
    ...news.map(n => n.url),
  ].filter(Boolean)
  const verifiedCount = Object.keys(verification).length

  return (
    <div className="flex flex-col h-full bg-white overflow-hidden">
      {/* ── Header ── */}
      <div className="border-b border-bmw-border bg-white px-6 py-4 flex-shrink-0">
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-base font-bold text-bmw-navy font-display">AI Sector Research</h1>
            <p className="text-xs text-bmw-text-secondary mt-0.5">
              Discover top companies and news in a battery supply chain category using AI
            </p>
          </div>

          <div className="flex items-center gap-3 flex-wrap">
            {/* Category dropdown */}
            <select
              value={category}
              onChange={e => setCategory(e.target.value)}
              disabled={isRunning}
              className="border border-bmw-border rounded px-3 py-1.5 text-sm text-bmw-text-primary bg-white
                focus:outline-none focus:border-bmw-blue disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {categories.map(c => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>

            <button
              onClick={handleRun}
              disabled={isRunning || !category}
              className="bg-bmw-blue hover:bg-[#3a88ee] disabled:opacity-50 disabled:cursor-not-allowed
                text-white text-sm px-4 py-1.5 rounded font-medium transition-colors flex items-center gap-2"
            >
              {isRunning ? (
                <>
                  <span className="inline-block w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  Researching…
                </>
              ) : 'Run Research'}
            </button>
          </div>
        </div>
      </div>

      {/* ── Body ── */}
      <div className="flex-1 overflow-y-auto">

        {/* Error banner */}
        {error && (
          <div className="mx-6 mt-4 px-4 py-3 bg-red-50 border border-red-200 rounded text-sm text-red-700 flex items-start gap-2">
            <span className="flex-shrink-0 font-bold">!</span>
            <span>{error}</span>
          </div>
        )}

        {/* Approval result banner */}
        {approvalResult && (
          <div className="mx-6 mt-4 px-4 py-3 bg-green-50 border border-green-200 rounded text-sm text-green-800 flex items-start gap-2">
            <span className="flex-shrink-0 font-bold">✓</span>
            <span>
              Queued <strong>{approvalResult.queued}</strong> compan{approvalResult.queued === 1 ? 'y' : 'ies'} for full AI enrichment.
              Check the Company Table in a few minutes.
            </span>
          </div>
        )}

        {/* Loading state */}
        {isRunning && (
          <div className="flex flex-col items-center justify-center py-20 gap-4">
            <div className="w-10 h-10 border-4 border-bmw-blue border-t-transparent rounded-full animate-spin" />
            <div className="text-center">
              <p className="text-sm font-medium text-bmw-navy">
                {jobStatus === 'pending' ? 'Starting research…' : 'Searching the web and extracting data…'}
              </p>
              <p className="text-xs text-bmw-text-secondary mt-1">
                This usually takes 30–90 seconds
              </p>
            </div>
          </div>
        )}

        {/* Empty state */}
        {!isRunning && !hasResults && !error && !approvalResult && (
          <div className="flex flex-col items-center justify-center py-20 gap-3">
            <div className="w-12 h-12 bg-bmw-gray-light rounded-full flex items-center justify-center">
              <svg className="w-6 h-6 text-bmw-gray-dark" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                  d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
            </div>
            <p className="text-sm font-medium text-bmw-text-secondary">
              Select a category and click Run Research to discover companies and news
            </p>
          </div>
        )}

        {/* Results */}
        {!isRunning && hasResults && (
          <div className="px-6 py-4 space-y-4">

            {/* ── Toolbar ── */}
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <span className="text-sm font-semibold text-bmw-navy">
                {companies.length} companies found
              </span>

              {/* URL verification */}
              <div className="flex items-center gap-2">
                {verifiedCount > 0 && (
                  <span className="text-xs text-bmw-text-secondary flex items-center gap-1">
                    {verifiedCount}/{allUrls.length} URLs checked
                    {' · '}
                    <span className="text-bmw-green">
                      {Object.values(verification).filter(v => v.valid).length} live
                    </span>
                    {' · '}
                    <span className="text-bmw-red">
                      {Object.values(verification).filter(v => v.status_code === 404).length} 404
                    </span>
                    {' · '}
                    <span className="text-bmw-text-secondary flex items-center gap-0.5">
                      {Object.values(verification).filter(v => !v.valid && v.status_code !== 404).length} timed out
                      <span className="relative group cursor-default">
                        <span className="inline-flex items-center justify-center w-3.5 h-3.5 rounded-full border border-bmw-gray-dark text-bmw-gray-dark text-[9px] font-bold leading-none ml-0.5">i</span>
                        <span className="absolute top-full left-1/2 -translate-x-1/2 mt-1.5 w-52 bg-bmw-navy text-white text-[10px] rounded px-2 py-1.5 leading-snug opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity z-[9999] shadow-lg">
                          Not a broken link — the server blocked automated access. Open it manually in a browser.
                        </span>
                      </span>
                    </span>
                  </span>
                )}
                <button
                  onClick={handleVerifyUrls}
                  disabled={verifying || allUrls.length === 0}
                  className="border border-bmw-border hover:border-bmw-blue text-bmw-text-primary
                    hover:text-bmw-blue disabled:opacity-40 disabled:cursor-not-allowed
                    text-xs px-3 py-1.5 rounded font-medium transition-colors flex items-center gap-1.5"
                >
                  {verifying ? (
                    <>
                      <span className="inline-block w-3 h-3 border border-bmw-blue border-t-transparent rounded-full animate-spin" />
                      Verifying…
                    </>
                  ) : `Verify ${allUrls.length} URLs`}
                </button>
              </div>
            </div>

            {/* ── Table ── */}
            <div className="border border-bmw-border rounded-lg overflow-hidden shadow-light">
              <CompaniesTable
                companies={companies}
                selected={selectedCompanies}
                onToggle={handleToggle}
                onSelectAll={handleSelectAll}
                verification={verification}
              />
            </div>

            {/* ── Approve bar (companies only) ── */}
            <div className="flex items-center justify-between gap-3 pt-1 flex-wrap">
              <p className="text-xs text-bmw-text-secondary">
                {selectedCount} of {companies.length} companies selected — approving will add them to the
                database and trigger full AI enrichment for each
              </p>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => handleApprove(false)}
                  disabled={approving || selectedCount === 0}
                  className="border border-bmw-blue text-bmw-blue hover:bg-blue-50
                    disabled:opacity-40 disabled:cursor-not-allowed
                    text-sm px-4 py-1.5 rounded font-medium transition-colors"
                >
                  {approving ? 'Queuing…' : `Add & Enrich Selected (${selectedCount})`}
                </button>
                <button
                  onClick={() => handleApprove(true)}
                  disabled={approving}
                  className="bg-bmw-blue hover:bg-[#3a88ee] text-white
                    disabled:opacity-40 disabled:cursor-not-allowed
                    text-sm px-4 py-1.5 rounded font-medium transition-colors"
                >
                  Add & Enrich All ({companies.length})
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Chat — always visible at bottom */}
        <div className="px-6 py-4 border-t border-bmw-border">
          <h3 className="text-sm font-medium text-gray-500 uppercase mb-3">
            Ask AI about {category || 'battery supply chain'}
          </h3>
          {chatMessages.length > 0 && (
            <div className="space-y-3 max-h-96 overflow-y-auto pr-1 mb-3">
              {chatMessages.map((m, i) => (
                <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div className={`max-w-[85%] rounded-lg px-4 py-2.5 text-sm whitespace-pre-wrap leading-relaxed ${
                    m.role === 'user'
                      ? 'bg-bmw-blue text-white'
                      : 'bg-bmw-gray-light text-gray-800 border border-bmw-border'
                  }`}>
                    {m.text}
                  </div>
                </div>
              ))}
              {chatLoading && (
                <div className="flex justify-start">
                  <div className="bg-bmw-gray-light border border-bmw-border rounded-lg px-4 py-2.5 text-sm text-gray-400 animate-pulse">
                    Thinking...
                  </div>
                </div>
              )}
              <div ref={chatBottomRef} />
            </div>
          )}
          <div className="flex gap-2">
            <input
              type="text"
              placeholder={`Ask about ${category || 'battery supply chain'}...`}
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleChatSend()}
              disabled={chatLoading}
              className="flex-1 border border-bmw-border rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-bmw-blue disabled:opacity-60"
            />
            <button
              onClick={handleChatSend}
              disabled={chatLoading || !chatInput.trim()}
              className="bg-bmw-blue hover:bg-[#3a88ee] disabled:opacity-60 text-white px-5 py-2 rounded text-sm font-medium transition-colors"
            >
              Send
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
