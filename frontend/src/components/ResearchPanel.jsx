import React, { useState, useEffect, useRef } from 'react'
import {
  researchCompany,
  discoverCompanies,
  bulkResearch,
  uploadCSV,
  uploadDocument,
  uploadPartnerships,
  getJob,
  listJobs,
  customSearch,
} from '../api/client'

const SEGMENTS = [
  'Raw Materials', 'Battery Grade Materials', 'Other Battery Components & Mat.',
  'Electrode & Cell Manufacturing', 'Module-Pack Manufacturing',
  'Recycling-Repurposing', 'Equipment', 'R&D', 'Services & Consulting', 'Modeling & Software',
]

const STATUS_LABELS = {
  pending: 'Pending',
  running: 'Running',
  complete: 'Done',
  failed: 'Failed',
}
const STATUS_COLORS = {
  pending: 'text-gray-400',
  running: 'text-blue-500',
  complete: 'text-green-600',
  failed: 'text-red-500',
}

function useJobPoller(jobId, onDone) {
  useEffect(() => {
    if (!jobId) return
    const iv = setInterval(async () => {
      try {
        const { data } = await getJob(jobId)
        if (data.status === 'complete' || data.status === 'failed') {
          clearInterval(iv)
          onDone(data)
        }
      } catch (_) {
        clearInterval(iv)
      }
    }, 3000)
    return () => clearInterval(iv)
  }, [jobId])
}

function DropZone({ label, accept, onUpload, uploading }) {
  const inputRef = useRef()
  const [dragging, setDragging] = useState(false)

  function handleFile(file) {
    if (file) onUpload(file)
  }

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDragging(false)
        handleFile(e.dataTransfer.files[0])
      }}
      onClick={() => inputRef.current?.click()}
      className={`border-2 border-dashed rounded-lg p-6 text-center cursor-pointer transition-colors ${
        dragging ? 'border-[#4599FE] bg-blue-50' : 'border-[#B8CAD1] hover:border-[#4599FE]'
      }`}
    >
      <input ref={inputRef} type="file" accept={accept} className="hidden"
        onChange={(e) => handleFile(e.target.files[0])} />
      <div className="text-xs font-medium text-gray-400 mb-2">Upload</div>
      <div className="text-sm font-medium text-gray-700">{label}</div>
      <div className="text-xs text-gray-400 mt-1">Click or drag & drop</div>
      {uploading && <div className="mt-2 text-xs text-[#4599FE] animate-pulse">Uploading…</div>}
    </div>
  )
}

// Render markdown-ish summary (bold, bullets)
function MarkdownText({ text }) {
  if (!text) return null
  return (
    <div className="text-sm text-gray-700 space-y-1">
      {text.split('\n').map((line, i) => {
        if (line.startsWith('## ')) return <h3 key={i} className="font-bold text-gray-900 mt-2">{line.slice(3)}</h3>
        if (line.startsWith('# ')) return <h2 key={i} className="font-bold text-gray-900 mt-2 text-base">{line.slice(2)}</h2>
        if (line.startsWith('- ') || line.startsWith('* ')) return <div key={i} className="flex gap-2"><span>•</span><span>{line.slice(2)}</span></div>
        if (line.startsWith('**') && line.endsWith('**')) return <div key={i} className="font-semibold">{line.slice(2, -2)}</div>
        if (!line.trim()) return <div key={i} className="h-1" />
        return <div key={i}>{line}</div>
      })}
    </div>
  )
}

export default function ResearchPanel() {
  // Custom search
  const [customQuery, setCustomQuery] = useState('')
  const [customSearching, setCustomSearching] = useState(false)
  const [customJobId, setCustomJobId] = useState(null)
  const [customResult, setCustomResult] = useState(null)

  // Discover
  const [discoverSegment, setDiscoverSegment] = useState(SEGMENTS[0])
  const [discoverCustomQuery, setDiscoverCustomQuery] = useState('')
  const [discovering, setDiscovering] = useState(false)
  const [discoverJobId, setDiscoverJobId] = useState(null)
  const [discoverResult, setDiscoverResult] = useState(null)
  const [bulkResearching, setBulkResearching] = useState(false)
  const [selectedForResearch, setSelectedForResearch] = useState([])

  // Research
  const [researchName, setResearchName] = useState('')
  const [researching, setResearching] = useState(false)
  const [researchJobId, setResearchJobId] = useState(null)
  const [researchResult, setResearchResult] = useState(null)

  // Upload CSV
  const [csvUploading, setCsvUploading] = useState(false)
  const [csvResult, setCsvResult] = useState(null)

  // Upload Document
  const [docUploading, setDocUploading] = useState(false)
  const [docJobId, setDocJobId] = useState(null)
  const [docResult, setDocResult] = useState(null)

  // PitchBook / Crunchbase import
  const [pbUploading, setPbUploading] = useState(false)
  const [pbResult, setPbResult] = useState(null)

  // Job queue
  const [jobs, setJobs] = useState([])

  useJobPoller(customJobId, (job) => {
    setCustomSearching(false)
    setCustomResult(job.result)
  })
  useJobPoller(discoverJobId, (job) => {
    setDiscovering(false)
    setDiscoverResult(job.result)
  })
  useJobPoller(researchJobId, (job) => {
    setResearching(false)
    setResearchResult(job.result)
  })
  useJobPoller(docJobId, (job) => {
    setDocResult(job.result)
  })

  useEffect(() => {
    listJobs().then(({ data }) => setJobs(data)).catch(() => {})
    const iv = setInterval(() => {
      listJobs().then(({ data }) => setJobs(data)).catch(() => {})
    }, 5000)
    return () => clearInterval(iv)
  }, [])

  async function handleCustomSearch() {
    if (!customQuery.trim()) return
    setCustomSearching(true)
    setCustomResult(null)
    try {
      const { data } = await customSearch(customQuery.trim())
      setCustomJobId(data.job_id)
    } catch (e) {
      setCustomSearching(false)
    }
  }

  async function handleDiscover() {
    setDiscovering(true)
    setDiscoverResult(null)
    setSelectedForResearch([])
    try {
      const { data } = await discoverCompanies(discoverSegment, 10, discoverCustomQuery)
      setDiscoverJobId(data.job_id)
    } catch (e) {
      setDiscovering(false)
    }
  }

  async function handleBulkResearch() {
    if (selectedForResearch.length === 0) return
    setBulkResearching(true)
    try {
      await bulkResearch(selectedForResearch)
      setSelectedForResearch([])
    } catch (e) {}
    setBulkResearching(false)
  }

  function toggleSelect(name) {
    setSelectedForResearch(prev =>
      prev.includes(name) ? prev.filter(n => n !== name) : [...prev, name]
    )
  }

  async function handleResearch() {
    if (!researchName.trim()) return
    setResearching(true)
    setResearchResult(null)
    try {
      const { data } = await researchCompany(researchName.trim())
      setResearchJobId(data.job_id)
    } catch (e) {
      setResearching(false)
    }
  }

  async function handleCsvUpload(file) {
    setCsvUploading(true)
    setCsvResult(null)
    try {
      const { data } = await uploadCSV(file)
      setCsvResult(data)
    } catch (e) {
      setCsvResult({ error: e.message })
    }
    setCsvUploading(false)
  }

  async function handleDocUpload(file) {
    setDocUploading(true)
    setDocResult(null)
    try {
      const { data } = await uploadDocument(file)
      setDocJobId(data.job_id)
    } catch (e) {
      setDocResult({ error: e.message })
    }
    setDocUploading(false)
  }

  async function handlePbUpload(file) {
    setPbUploading(true)
    setPbResult(null)
    try {
      const { data } = await uploadPartnerships(file)
      setPbResult(data)
    } catch (e) {
      const msg = e.response?.data?.detail || e.message
      setPbResult({ error: msg })
    }
    setPbUploading(false)
  }

  return (
    <div className="flex h-full overflow-hidden">
      {/* Left column */}
      <div className="flex-1 overflow-y-auto p-5 space-y-6">

        {/* Custom Search */}
        <Section title="Custom Intelligence Search" icon="">
          <p className="text-xs text-gray-500 mb-3">
            Ask anything about battery industry trends, technologies, companies, or market dynamics.
            Gemini searches the web and Claude synthesizes the findings.
          </p>
          <div className="flex gap-3">
            <input
              type="text"
              placeholder="e.g. solid-state battery startups raising funding 2025, or LFP cathode supplier partnerships with US OEMs"
              value={customQuery}
              onChange={(e) => setCustomQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleCustomSearch()}
              className="flex-1 border border-[#B8CAD1] rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#4599FE]"
            />
            <button
              onClick={handleCustomSearch}
              disabled={customSearching || !customQuery.trim()}
              className="bg-[#4599FE] hover:bg-[#4599FE] disabled:opacity-60 text-white px-4 py-2 rounded text-sm font-medium whitespace-nowrap"
            >
              {customSearching ? 'Searching…' : 'Search'}
            </button>
          </div>
          {customSearching && (
            <div className="mt-3 text-sm text-gray-500 animate-pulse">
              Searching the web + synthesizing with Claude…
            </div>
          )}
          {customResult && !customSearching && (
            <div className="mt-4 border border-[#B8CAD1] rounded-lg overflow-hidden">
              <div className="bg-[#031E49] text-white text-xs px-4 py-2 font-medium">
                Intelligence Summary — "{customResult.query}"
              </div>
              <div className="p-4">
                <MarkdownText text={customResult.summary} />
              </div>
              <details className="border-t border-[#B8CAD1]">
                <summary className="px-4 py-2 text-xs text-gray-400 cursor-pointer hover:text-gray-600">
                  View raw search data
                </summary>
                <pre className="p-4 text-xs text-gray-500 overflow-x-auto whitespace-pre-wrap bg-[#F0F4F8]">
                  {customResult.raw}
                </pre>
              </details>
            </div>
          )}
        </Section>

        {/* Discover Companies */}
        <Section title="Discover Companies Not in Database" icon="">
          <p className="text-xs text-gray-500 mb-3">
            Search for battery companies that aren't in your database yet. Select any you want to add and research.
          </p>
          <div className="space-y-2 mb-3">
            <input
              type="text"
              placeholder="Custom search (e.g. 'solid-state battery startups US 2025') — or leave blank to search by segment"
              value={discoverCustomQuery}
              onChange={(e) => setDiscoverCustomQuery(e.target.value)}
              className="w-full border border-[#B8CAD1] rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#4599FE]"
            />
            <div className="flex gap-3">
              <select
                value={discoverSegment}
                onChange={(e) => setDiscoverSegment(e.target.value)}
                disabled={!!discoverCustomQuery}
                className="flex-1 border border-[#B8CAD1] rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#4599FE] disabled:opacity-40"
              >
                {SEGMENTS.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
              <button
                onClick={handleDiscover}
                disabled={discovering}
                className="bg-[#4599FE] hover:bg-[#4599FE] disabled:opacity-60 text-white px-4 py-2 rounded text-sm font-medium"
              >
                {discovering ? 'Searching…' : 'Discover'}
              </button>
            </div>
          </div>

          {discoverResult && (
            <div className="mt-2">
              {Array.isArray(discoverResult?.new_companies) && discoverResult.new_companies.length > 0 ? (
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <div className="text-sm font-medium text-gray-700">
                      Found {discoverResult.new_companies.length} new companies:
                    </div>
                    <div className="flex gap-2">
                      <button
                        onClick={() => setSelectedForResearch(discoverResult.new_companies)}
                        className="text-xs text-[#4599FE] hover:underline"
                      >
                        Select all
                      </button>
                      {selectedForResearch.length > 0 && (
                        <button
                          onClick={handleBulkResearch}
                          disabled={bulkResearching}
                          className="bg-[#4599FE] hover:bg-[#4599FE] disabled:opacity-60 text-white text-xs px-3 py-1 rounded"
                        >
                          {bulkResearching ? 'Queuing…' : `Research & Add ${selectedForResearch.length} selected`}
                        </button>
                      )}
                    </div>
                  </div>
                  {discoverResult.new_companies.map((name) => (
                    <div
                      key={name}
                      onClick={() => toggleSelect(name)}
                      className={`flex items-center justify-between rounded px-3 py-2 cursor-pointer transition-colors ${
                        selectedForResearch.includes(name)
                          ? 'bg-blue-100 border border-[#4599FE]'
                          : 'bg-[#F0F4F8] hover:bg-blue-50'
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        <input
                          type="checkbox"
                          checked={selectedForResearch.includes(name)}
                          onChange={() => toggleSelect(name)}
                          className="accent-[#4599FE]"
                          onClick={e => e.stopPropagation()}
                        />
                        <span className="text-sm font-medium">{name}</span>
                      </div>
                      <button
                        onClick={(e) => { e.stopPropagation(); setResearchName(name) }}
                        className="text-xs text-[#4599FE] hover:underline"
                      >
                        Research only
                      </button>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-sm text-gray-500">No new companies found.</div>
              )}
            </div>
          )}
        </Section>

        {/* Research a Company */}
        <Section title="Research a Company" icon="">
          <p className="text-xs text-gray-500 mb-3">
            Enriches a company's profile with funding, partnerships, employee count, keywords, and recent news.
          </p>
          <div className="flex gap-3">
            <input
              type="text"
              placeholder="Company name (e.g. QuantumScape, Solid Power)…"
              value={researchName}
              onChange={(e) => setResearchName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleResearch()}
              className="flex-1 border border-[#B8CAD1] rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#4599FE]"
            />
            <button
              onClick={handleResearch}
              disabled={researching || !researchName.trim()}
              className="bg-[#4599FE] hover:bg-[#4599FE] disabled:opacity-60 text-white px-4 py-2 rounded text-sm font-medium"
            >
              {researching ? 'Working…' : 'Research'}
            </button>
          </div>
          {researching && (
            <div className="mt-3 text-sm text-gray-500 animate-pulse">
              Running Gemini searches + Claude synthesis…
            </div>
          )}
          {researchResult && !researching && (
            <div className="mt-3 bg-[#F0F4F8] rounded p-3 text-sm space-y-2">
              <div className="font-medium text-gray-700">Research complete</div>
              {researchResult?.company?.summary && (
                <p className="text-gray-600 text-xs leading-relaxed">{researchResult.company.summary}</p>
              )}
              {researchResult?.company?.announced_partners?.length > 0 && (
                <div className="text-xs text-gray-500">
                  Partners found: {researchResult.company.announced_partners.map(p => p.partner_name).join(', ')}
                </div>
              )}
              {researchResult?.company?.keywords?.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {researchResult.company.keywords.map(k => (
                    <span key={k} className="bg-[#E8F1FF] text-[#4599FE] text-xs px-2 py-0.5 rounded-full">{k}</span>
                  ))}
                </div>
              )}
              {researchResult?.news_count !== undefined && (
                <div className="text-xs text-gray-400">+ {researchResult.news_count} news articles saved to News Feed</div>
              )}
            </div>
          )}
        </Section>

        {/* PitchBook / Crunchbase Import */}
        <Section title="Import from PitchBook or Crunchbase">
          <p className="text-xs text-gray-500 mb-3">
            Export a company list, deals sheet, or funding rounds CSV/XLSX from PitchBook or Crunchbase
            and drop it here. The format is auto-detected and partnerships are wired into the network graph.
          </p>
          <div className="text-xs text-gray-400 mb-3 space-y-1">
            <div className="font-medium text-gray-500">Supported exports:</div>
            <div className="grid grid-cols-2 gap-x-4">
              <span>· PitchBook — Company List</span>
              <span>· PitchBook — Deals</span>
              <span>· Crunchbase — Organizations</span>
              <span>· Crunchbase — Funding Rounds</span>
            </div>
          </div>
          <DropZone
            label="PitchBook or Crunchbase export (.csv or .xlsx)"
            accept=".csv,.xlsx"
            onUpload={handlePbUpload}
            uploading={pbUploading}
          />
          {pbResult && (
            <div className="mt-3 text-xs rounded-lg p-3 border border-[#B8CAD1] bg-[#F0F4F8]">
              {pbResult.error ? (
                <span className="text-red-500">{pbResult.error}</span>
              ) : (
                <div className="space-y-1">
                  <div className="font-medium text-gray-700">{pbResult.source}</div>
                  <div className="text-gray-600">
                    {pbResult.companies_added} companies added · {pbResult.companies_updated} updated
                    {pbResult.partnerships_added > 0 && ` · ${pbResult.partnerships_added} partnerships linked`}
                  </div>
                  <div className="text-gray-400">Refresh the Partnership Network tab to see changes.</div>
                </div>
              )}
            </div>
          )}
        </Section>

        {/* Upload Data */}
        <Section title="Upload Data" icon="">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <div className="text-xs font-medium text-gray-500 mb-2 uppercase tracking-wider">CSV / XLSX Import</div>
              <DropZone label="Companies spreadsheet" accept=".csv,.xlsx" onUpload={handleCsvUpload} uploading={csvUploading} />
              {csvResult && (
                <div className="mt-2 text-xs text-gray-600">
                  {csvResult.error
                    ? <span className="text-red-500">{csvResult.error}</span>
                    : <span>Added {csvResult.added}, updated {csvResult.updated} companies</span>}
                </div>
              )}
            </div>
            <div>
              <div className="text-xs font-medium text-gray-500 mb-2 uppercase tracking-wider">PDF / Text Document</div>
              <DropZone label="Conference paper, press release, or transcript" accept=".pdf,.txt,.md" onUpload={handleDocUpload} uploading={docUploading} />
              {docResult && (
                <div className="mt-2 text-xs text-gray-600">
                  {docResult.error
                    ? <span className="text-red-500">{docResult.error}</span>
                    : <span>Added {docResult.companies_added} companies, {docResult.news_added} news, {docResult.proceedings_added} proceedings</span>}
                </div>
              )}
            </div>
          </div>
        </Section>
      </div>

      {/* Right column: Job Queue */}
      <div className="w-72 bg-white border-l border-[#B8CAD1] flex flex-col">
        <div className="px-4 py-3 border-b border-[#B8CAD1]">
          <h3 className="font-semibold text-sm text-[#031E49]">Job Queue</h3>
        </div>
        <div className="flex-1 overflow-y-auto p-3 space-y-2">
          {jobs.length === 0 ? (
            <div className="text-xs text-gray-400 text-center mt-8">No recent jobs</div>
          ) : (
            jobs.map((j) => (
              <div key={j.id} className="bg-[#F0F4F8] rounded p-2.5 text-xs">
                <div className="flex items-center justify-between">
                  <span className="font-medium capitalize">{j.job_type?.replace(/_/g, ' ')}</span>
                  <span title={j.status} className={STATUS_COLORS[j.status] || 'text-gray-400'}>{STATUS_LABELS[j.status] || j.status}</span>
                </div>
                <div className="text-gray-500 mt-0.5 truncate">{j.target}</div>
                <div className="text-gray-400 mt-0.5">
                  {j.updated_at ? new Date(j.updated_at).toLocaleTimeString() : ''}
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}

function Section({ title, children }) {
  return (
    <div className="bg-white rounded-lg border border-[#B8CAD1] p-5">
      <h3 className="font-semibold text-[#031E49] mb-4">{title}</h3>
      {children}
    </div>
  )
}
