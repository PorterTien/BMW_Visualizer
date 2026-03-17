import React, { useEffect, useRef, useState } from 'react'
import { getCompany, researchCompany, getJob, chatWithCompany } from '../api/client'

function LogoImg({ website, name }) {
  const [failed, setFailed] = useState(false)
  let domain = ''
  try { domain = new URL(website).hostname.replace('www.', '') } catch { return null }
  if (failed || !domain) return null
  return (
    <img
      src={`https://logo.clearbit.com/${domain}`}
      alt={name}
      onError={() => setFailed(true)}
      className="w-10 h-10 rounded-lg bg-white object-contain p-1 shrink-0"
    />
  )
}

const CATEGORY_COLORS = {
  funding: 'bg-green-100 text-green-800',
  partnership: 'bg-blue-100 text-blue-800',
  'product launch': 'bg-purple-100 text-purple-800',
  facility: 'bg-orange-100 text-orange-800',
  regulatory: 'bg-red-100 text-red-800',
  research: 'bg-teal-100 text-teal-800',
  other: 'bg-gray-100 text-gray-700',
}

export default function CompanyDetail({ companyId, onClose }) {
  const [company, setCompany] = useState(null)
  const [loading, setLoading] = useState(true)
  const [researching, setResearching] = useState(false)
  const [researchStatus, setResearchStatus] = useState(null)

  // Chat state
  const [chatMessages, setChatMessages] = useState([])
  const [chatInput, setChatInput] = useState('')
  const [chatLoading, setChatLoading] = useState(false)
  const chatBottomRef = useRef(null)
  const pollRef = useRef(null)

  useEffect(() => () => clearInterval(pollRef.current), [])

  useEffect(() => {
    chatBottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [chatMessages])

  useEffect(() => {
    if (!companyId) return
    setLoading(true)
    getCompany(companyId)
      .then(({ data }) => setCompany(data))
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [companyId])

  async function handleReResearch() {
    if (!company) return
    setResearching(true)
    setResearchStatus('Starting…')
    try {
      const { data } = await researchCompany(company.company_name)
      const jobId = data.job_id
      pollRef.current = setInterval(async () => {
        try {
          const { data: job } = await getJob(jobId)
          setResearchStatus(`Status: ${job.status}`)
          if (job.status === 'complete' || job.status === 'failed') {
            clearInterval(pollRef.current)
            setResearching(false)
            if (job.status === 'complete') {
              const { data: updated } = await getCompany(companyId)
              setCompany(updated)
              setResearchStatus('Research complete!')
            } else {
              setResearchStatus('Research failed.')
            }
          }
        } catch (_) {
          clearInterval(pollRef.current)
          setResearching(false)
        }
      }, 3000)
    } catch (e) {
      setResearching(false)
      setResearchStatus('Error starting research.')
    }
  }

  async function handleChatSend() {
    const msg = chatInput.trim()
    if (!msg || chatLoading || !company) return
    setChatInput('')
    setChatMessages(prev => [...prev, { role: 'user', text: msg }])
    setChatLoading(true)
    try {
      const { data } = await chatWithCompany(company.id, msg)
      setChatMessages(prev => [...prev, { role: 'assistant', text: data.response }])
    } catch (e) {
      setChatMessages(prev => [...prev, { role: 'assistant', text: 'Error getting response. Please try again.' }])
    }
    setChatLoading(false)
  }

  if (!companyId) return null

  return (
    <div className="fixed inset-0 z-50 flex">
      {/* Backdrop */}
      <div className="flex-1 bg-black/40" onClick={onClose} />
      {/* Panel */}
      <div className="w-[520px] bg-white shadow-2xl flex flex-col overflow-hidden">
        {/* Header */}
        <div className="bg-[#031E49] text-white px-5 py-4 flex items-start justify-between">
          <div className="flex items-center gap-3 min-w-0">
            {company?.company_website && (
              <LogoImg website={company.company_website} name={company.company_name} />
            )}
            <div className="min-w-0">
              <h2 className="text-lg font-bold leading-tight">
                {loading ? 'Loading…' : company?.company_name}
              </h2>
              {company && (
                <div className="text-sm text-blue-300 mt-0.5">
                  {company.company_type} · {company.company_status}
                </div>
              )}
            </div>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-white text-2xl leading-none ml-4 shrink-0">
            ×
          </button>
        </div>

        {loading ? (
          <div className="flex-1 flex items-center justify-center text-gray-400">Loading…</div>
        ) : !company ? (
          <div className="flex-1 flex items-center justify-center text-gray-400">Not found</div>
        ) : (
          <div className="flex-1 overflow-y-auto p-5 space-y-5">
            {/* Quick facts */}
            <div className="grid grid-cols-2 gap-3 text-sm">
              <Info label="HQ" value={[company.company_hq_city, company.company_hq_state, company.company_hq_country].filter(Boolean).join(', ')} />
              <Info label="Segment" value={company.supply_chain_segment} />
              <Info label="Employees" value={company.number_of_employees?.toLocaleString()} />
              <Info label="Market Cap" value={formatMoney(company.market_cap_usd)} />
              <Info label="Revenue" value={formatMoney(company.revenue_usd)} />
              <Info label="Total Funding" value={formatMoney(company.total_funding_usd)} />
              <Info label="Last Fundraise" value={company.last_fundraise_date} />
              <Info label="Chemistries" value={company.chemistries} />
              <Info label="Feedstock" value={company.feedstock} />
              <Info label="NAATBatt Member" value={company.naatbatt_member ? 'Yes' : 'No'} />
              <Info label="Data Source" value={company.data_source} />
              {company.hq_company && (
                <div className="col-span-2">
                  <span className="text-xs font-medium text-gray-500 uppercase tracking-wider">Parent Company</span>
                  <div className="text-sm text-[#031E49] mt-0.5">
                    {company.hq_company}
                    {company.hq_company_website && (
                      <a href={company.hq_company_website} target="_blank" rel="noreferrer" className="text-[#4599FE] hover:underline ml-2 text-xs">
                        website
                      </a>
                    )}
                  </div>
                </div>
              )}
              {company.company_website && (
                <div className="col-span-2">
                  <span className="text-xs font-medium text-gray-500 uppercase tracking-wider">Website</span>
                  <div className="mt-0.5">
                    <a href={company.company_website} target="_blank" rel="noreferrer" className="text-[#4599FE] hover:underline text-sm break-all">
                      {company.company_website}
                    </a>
                  </div>
                </div>
              )}
            </div>

            {/* Contact */}
            {(company.contact_name || company.contact_email || company.contact_phone) && (
              <div className="bg-[#F0F4F8] rounded-lg p-3 space-y-1">
                <div className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-2">Contact</div>
                {company.contact_name && <div className="text-sm font-medium text-[#031E49]">{company.contact_name}</div>}
                {company.contact_email && (
                  <a href={`mailto:${company.contact_email}`} className="text-sm text-[#4599FE] hover:underline block">{company.contact_email}</a>
                )}
                {company.contact_phone && <div className="text-sm text-gray-500">{company.contact_phone}</div>}
              </div>
            )}

            {/* Notes */}
            {company.notes && (
              <div>
                <div className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-1">Notes</div>
                <p className="text-sm text-gray-600 leading-relaxed">{company.notes}</p>
              </div>
            )}

            {/* Keywords */}
            {company.keywords?.length > 0 && (
              <div>
                <div className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-2">Keywords</div>
                <div className="flex flex-wrap gap-1">
                  {company.keywords.map((k) => (
                    <span key={k} className="bg-[#F0F4F8] border border-[#B8CAD1] text-xs px-2 py-0.5 rounded-full">
                      {k}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Summary */}
            {company.summary && (
              <div>
                <div className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-2">Summary</div>
                <p className="text-sm text-gray-700 leading-relaxed">{company.summary}</p>
              </div>
            )}

            {/* Long description */}
            {company.long_description && (
              <div>
                <div className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-2">Description</div>
                <p className="text-sm text-gray-600 leading-relaxed">{company.long_description}</p>
              </div>
            )}

            {/* Partnerships */}
            {company.announced_partners?.length > 0 && (
              <div>
                <div className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-2">
                  Partnerships ({company.announced_partners.length})
                </div>
                <div className="space-y-2">
                  {company.announced_partners.map((p, i) => (
                    <div key={i} className="bg-[#F0F4F8] rounded p-3 text-sm">
                      <div className="font-medium">{p.partner_name}</div>
                      <div className="text-gray-500 text-xs mt-0.5">
                        {p.type_of_partnership} {p.scale ? `· ${p.scale}` : ''} {p.date ? `· ${p.date}` : ''}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Locations */}
            {company.company_locations?.length > 0 && (
              <div>
                <div className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-2">
                  Facilities ({company.company_locations.length})
                </div>
                <div className="space-y-2">
                  {company.company_locations.map((loc, i) => (
                    <div key={i} className="bg-[#F0F4F8] rounded p-3 text-sm">
                      {loc.facility_name && <div className="font-medium text-[#031E49]">{loc.facility_name}</div>}
                      <div className="text-gray-500 text-xs mt-0.5">
                        {[loc.address, loc.city, loc.state, loc.country, loc.zip].filter(Boolean).join(', ')}
                      </div>
                      <div className="flex flex-wrap gap-x-4 gap-y-0.5 mt-1 text-xs text-gray-500">
                        {loc.product_type && <span>{loc.product_type}</span>}
                        {loc.product && <span>Product: {loc.product}</span>}
                        {loc.chemistries && <span>Chemistries: {loc.chemistries}</span>}
                        {loc.feedstock && <span>Feedstock: {loc.feedstock}</span>}
                        {loc.capacity && <span>Capacity: {loc.capacity} {loc.capacity_units || ''}</span>}
                        {loc.workforce && <span>Workforce: {loc.workforce}</span>}
                        {loc.status && <span>Status: {loc.status}</span>}
                        {loc.phone && <span>{loc.phone}</span>}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Related News */}
            {company.news?.length > 0 && (
              <div>
                <div className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-2">Recent News</div>
                <div className="space-y-2">
                  {company.news.map((n) => (
                    <div key={n.id} className="border border-[#B8CAD1] rounded p-3 text-sm">
                      <div className="font-medium">{n.news_headline}</div>
                      <div className="flex items-center gap-2 mt-1">
                        <span className={`text-xs px-2 py-0.5 rounded-full ${CATEGORY_COLORS[n.category] || CATEGORY_COLORS.other}`}>
                          {n.category}
                        </span>
                        <span className="text-gray-400 text-xs">{n.date_of_article}</span>
                        {n.url && (
                          <a href={n.url} target="_blank" rel="noreferrer" className="text-[#4599FE] text-xs hover:underline">
                            Source
                          </a>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Proceedings */}
            {company.proceedings?.length > 0 && (
              <div>
                <div className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-2">Conference Proceedings</div>
                <div className="space-y-1">
                  {company.proceedings.map((p) => (
                    <div key={p.id} className="text-sm text-gray-700">
                      <span className="font-medium">{p.title}</span>
                      {p.event_name && <span className="text-gray-400"> · {p.event_name}</span>}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* AI Chat */}
            <div className="border-t border-[#B8CAD1] pt-4 space-y-3">
              <div className="flex items-center justify-between">
                <div className="text-xs font-medium text-gray-500 uppercase tracking-wider">Ask AI about this company</div>
                <button
                  onClick={handleReResearch}
                  disabled={researching}
                  className="text-xs bg-[#031E49] hover:bg-[#0D2A5E] disabled:opacity-60 text-white px-3 py-1 rounded transition-colors"
                >
                  {researching ? 'Researching…' : 'Full re-research'}
                </button>
              </div>
              {researchStatus && (
                <div className="text-xs text-gray-500">{researchStatus}</div>
              )}

              {/* Message history */}
              {chatMessages.length > 0 && (
                <div className="max-h-64 overflow-y-auto space-y-3 pr-1">
                  {chatMessages.map((m, i) => (
                    <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                      <div className={`max-w-[85%] rounded-lg px-3 py-2 text-sm whitespace-pre-wrap leading-relaxed ${
                        m.role === 'user'
                          ? 'bg-[#4599FE] text-white'
                          : 'bg-[#F0F4F8] text-gray-800 border border-[#B8CAD1]'
                      }`}>
                        {m.text}
                      </div>
                    </div>
                  ))}
                  {chatLoading && (
                    <div className="flex justify-start">
                      <div className="bg-[#F0F4F8] border border-[#B8CAD1] rounded-lg px-3 py-2 text-sm text-gray-400 animate-pulse">
                        Thinking…
                      </div>
                    </div>
                  )}
                  <div ref={chatBottomRef} />
                </div>
              )}

              {/* Input */}
              <div className="flex gap-2">
                <input
                  type="text"
                  placeholder={`Ask about ${company?.company_name ?? 'this company'}…`}
                  value={chatInput}
                  onChange={(e) => setChatInput(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleChatSend()}
                  disabled={chatLoading}
                  className="flex-1 border border-[#B8CAD1] rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#4599FE] disabled:opacity-60"
                />
                <button
                  onClick={handleChatSend}
                  disabled={chatLoading || !chatInput.trim()}
                  className="bg-[#4599FE] hover:bg-[#3a88ee] disabled:opacity-60 text-white px-4 py-2 rounded text-sm font-medium transition-colors"
                >
                  Send
                </button>
              </div>
              <div className="text-xs text-gray-400">
                Searches the web + synthesizes with AI in real time
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function formatMoney(valueMillion) {
  if (!valueMillion) return null
  if (valueMillion >= 1000) return `$${(valueMillion / 1000).toFixed(1)}B`
  return `$${Math.round(valueMillion)}M`
}

function Info({ label, value }) {
  if (!value) return null
  return (
    <div>
      <div className="text-xs font-medium text-gray-500 uppercase tracking-wider">{label}</div>
      <div className="text-sm text-[#031E49] mt-0.5">{value}</div>
    </div>
  )
}
