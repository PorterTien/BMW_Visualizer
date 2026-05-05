import React, { useEffect, useState, useRef, useCallback, useMemo } from 'react'
import { getCompanyDetail, refreshCompanyDetail, researchCompany, getJob, chatWithCompany, updateCompany } from '../api/client'
import { faviconUrl } from '../utils/favicon'

/* ── Logo helper ── */
function nameColor(name) {
  let h = 0
  for (let i = 0; i < (name || '').length; i++) h = (Math.imul(31, h) + name.charCodeAt(i)) | 0
  const hue = ((h >>> 0) % 12) * 30
  return `hsl(${hue}, 55%, 50%)`
}

function LogoImg({ website, name }) {
  const [failed, setFailed] = useState(false)
  const src = faviconUrl(website)
  const initials = (name || '').replace(/[^A-Za-z0-9]/g, '').slice(0, 2).toUpperCase() || '?'
  const bg = nameColor(name || '')

  if (src && !failed) {
    return (
      <img
        src={src}
        alt={name}
        referrerPolicy="no-referrer"
        loading="lazy"
        onError={() => setFailed(true)}
        className="w-12 h-12 rounded-xl bg-white object-contain p-1.5 shrink-0 shadow-sm border border-white/20"
      />
    )
  }
  return (
    <div
      className="w-12 h-12 rounded-xl flex items-center justify-center shrink-0 text-white font-bold shadow-sm select-none border border-white/20"
      style={{ backgroundColor: bg, fontSize: '18px' }}
    >
      {initials}
    </div>
  )
}

function formatMoney(valueMillion) {
  if (!valueMillion) return null
  if (valueMillion >= 1000) return `$${(valueMillion / 1000).toFixed(1)}B`
  return `$${Math.round(valueMillion)}M`
}

const PARTNERSHIP_TYPE_COLORS = {
  jv: '#34D399',
  supply_agreement: '#F472B6',
  licensing: '#FBBF24',
  equity_stake: '#60A5FA',
  r_and_d_collab: '#A78BFA',
  government_grant: '#FB923C',
  other: '#94A3B8',
}

const PARTNERSHIP_TYPE_LABELS = {
  jv: 'Joint Venture',
  supply_agreement: 'Supply Agreement',
  licensing: 'Licensing',
  equity_stake: 'Equity Stake',
  r_and_d_collab: 'R&D Collaboration',
  government_grant: 'Government Grant',
  other: 'Other',
}

const STAGE_COLORS = {
  announced: 'bg-bmw-gray-light text-bmw-text-secondary',
  signed: 'bg-blue-50 text-bmw-blue',
  active: 'bg-green-50 text-green-700',
  dissolved: 'bg-red-50 text-red-700',
}

const CATEGORY_COLORS = {
  funding: 'bg-blue-50 text-bmw-blue',
  partnership: 'bg-blue-50 text-bmw-blue',
  'product launch': 'bg-gray-100 text-bmw-text-secondary',
  facility: 'bg-gray-100 text-bmw-text-secondary',
  regulatory: 'bg-red-50 text-red-700',
  research: 'bg-blue-50 text-bmw-blue',
  other: 'bg-gray-100 text-bmw-gray-dark',
}

/* ── Main Component ── */
export default function CompanyDetailPage({ companyId, onClose, onOpenCompany }) {
  const [company, setCompany] = useState(null)
  const [loading, setLoading] = useState(true)
  const [activeSection, setActiveSection] = useState('overview')
  const [researching, setResearching] = useState(false)
  const [researchStatus, setResearchStatus] = useState(null)
  const [chatMessages, setChatMessages] = useState([])
  const [chatInput, setChatInput] = useState('')
  const [chatLoading, setChatLoading] = useState(false)
  const [selectedPartnership, setSelectedPartnership] = useState(null)
  const [editMode, setEditMode] = useState(false)
  const [editValues, setEditValues] = useState({})
  const [saving, setSaving] = useState(false)
  const [saveMsg, setSaveMsg] = useState(null)
  const [notesValue, setNotesValue] = useState('')
  const [notesSaving, setNotesSaving] = useState(false)
  const [notesSaved, setNotesSaved] = useState(false)
  const chatBottomRef = useRef(null)
  const pollRef = useRef(null)
  const scrollRef = useRef(null)
  const sectionRefs = useRef({})

  const sectionOffsetTop = (el) => {
    // Position of `el` relative to the scroll container (robust regardless
    // of where the offsetParent happens to be).
    const container = scrollRef.current
    if (!el || !container) return 0
    return el.getBoundingClientRect().top
      - container.getBoundingClientRect().top
      + container.scrollTop
  }

  const handleScroll = useCallback(() => {
    const container = scrollRef.current
    if (!container) return
    const scrollTop = container.scrollTop
    const ids = ['overview', 'facilities', 'partnerships', 'news', 'ai', 'similar', 'citations']

    const atBottom = container.scrollHeight - scrollTop - container.clientHeight < 8
    if (atBottom) {
      setActiveSection(ids[ids.length - 1])
      return
    }

    let current = ids[0]
    for (const id of ids) {
      const el = sectionRefs.current[id]
      if (el && sectionOffsetTop(el) - 16 <= scrollTop) current = id
    }
    setActiveSection(current)
  }, [])

  const scrollToSection = useCallback((id) => {
    const el = sectionRefs.current[id]
    if (el && scrollRef.current) {
      scrollRef.current.scrollTo({ top: sectionOffsetTop(el) - 8, behavior: 'smooth' })
    }
    setActiveSection(id)
  }, [])

  useEffect(() => () => clearInterval(pollRef.current), [])
  useEffect(() => {
    chatBottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [chatMessages])

  useEffect(() => {
    if (!companyId) return
    let cancelled = false
    setLoading(true)
    setChatMessages([])
    setSelectedPartnership(null)
    setActiveSection('overview')
    setEditMode(false)
    setEditValues({})
    setSaveMsg(null)
    getCompanyDetail(companyId)
      .then(({ data }) => {
        if (cancelled) return
        setCompany(data)
        setNotesValue(data.notes || '')
      })
      .catch((e) => { if (!cancelled) console.error(e) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [companyId])

  async function handleReResearch() {
    if (!company) return
    setResearching(true)
    setResearchStatus('Starting...')
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
              const { data: updated } = await refreshCompanyDetail(companyId)
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
      setChatMessages(prev => [...prev, { role: 'assistant', text: 'Error getting response.' }])
    }
    setChatLoading(false)
  }

  function startEdit() {
    setEditValues({
      company_website: company.company_website || '',
      crunchbase_url: company.crunchbase_url || '',
      linkedin_url: company.linkedin_url || '',
      pitchbook_url: company.pitchbook_url || '',
      company_type: company.company_type || '',
      company_status: company.company_status || '',
      company_hq_city: company.company_hq_city || '',
      company_hq_state: company.company_hq_state || '',
      company_hq_country: company.company_hq_country || '',
      company_hq_lat: company.company_hq_lat ?? '',
      company_hq_lng: company.company_hq_lng ?? '',
      founding_year: company.founding_year ?? '',
      number_of_employees: company.number_of_employees ?? '',
      summary: company.summary || '',
    })
    setEditMode(true)
    setSaveMsg(null)
  }

  async function handleSaveEdits() {
    setSaving(true)
    setSaveMsg(null)
    const numericFields = new Set(['company_hq_lat', 'company_hq_lng', 'founding_year', 'number_of_employees'])
    const cleaned = Object.fromEntries(
      Object.entries(editValues).map(([k, v]) => [
        k,
        numericFields.has(k) ? (v === '' || v === null ? null : Number(v)) : v,
      ])
    )
    try {
      const { data: updated } = await updateCompany(company.id, cleaned)
      setCompany(prev => ({ ...prev, ...updated }))
      setEditMode(false)
      setSaveMsg('Saved')
      setTimeout(() => setSaveMsg(null), 3000)
    } catch {
      setSaveMsg('Save failed')
    }
    setSaving(false)
  }

  async function handleSaveNotes() {
    setNotesSaving(true)
    setNotesSaved(false)
    try {
      await updateCompany(company.id, { notes: notesValue })
      setCompany(prev => ({ ...prev, notes: notesValue }))
      setNotesSaved(true)
      setTimeout(() => setNotesSaved(false), 3000)
    } catch {}
    setNotesSaving(false)
  }

  // Merge partnerships from new table + legacy
  const allPartnerships = useMemo(() => {
    if (!company) return []
    const fromTable = (company.partnerships || []).map(p => ({ ...p, _source: 'table' }))
    const fromLegacy = (company.partnerships_legacy || []).map((p, i) => ({
      id: `legacy_${i}`,
      partnership_name: `${company.company_name} - ${p.partner_name}`,
      partnership_type: mapLegacyType(p.type_of_partnership),
      stage: 'active',
      date_announced: p.date,
      deal_value: null,
      scope: p.scale,
      members: [
        { company_id: company.id, company_name: company.company_name, role: 'partner' },
        { company_id: null, company_name: p.partner_name, role: 'partner' },
      ],
      _source: 'legacy',
    }))
    return [...fromTable, ...fromLegacy]
  }, [company])

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center text-gray-400">
        Loading company details...
      </div>
    )
  }

  if (!company) {
    return (
      <div className="h-full flex items-center justify-center text-gray-400">
        Company not found
      </div>
    )
  }

  const sections = [
    { id: 'overview', label: 'Overview' },
    { id: 'facilities', label: `Facilities (${(company.facilities || []).length})` },
    { id: 'partnerships', label: `Partnerships (${allPartnerships.length})` },
    { id: 'news', label: `News (${(company.news || []).length})` },
    { id: 'ai', label: 'AI Chat' },
    { id: 'similar', label: 'Similar Companies' },
    { id: 'citations', label: 'Citations' },
  ]

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* ── Top header ── */}
      <div className="bg-bmw-navy text-white px-6 py-4 flex-shrink-0 sticky top-0 z-10">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-3 min-w-0 flex-1">
            {company.company_website && (
              <LogoImg website={company.company_website} name={company.company_name} />
            )}
            <div className="min-w-0 flex-1">
              <h1 className="text-lg font-display font-bold leading-snug break-words">{company.company_name}</h1>
              <div className="mt-1 space-y-0.5">
                {company.company_type && (
                  <div className="text-sm text-gray-300">{company.company_type}</div>
                )}
                {company.company_status && (
                  <div><span className="bg-white/10 px-2 py-0.5 rounded text-xs">{company.company_status}</span></div>
                )}
                {company.company_hq_country && (
                  <div className="text-sm text-gray-400">{[company.company_hq_city, company.company_hq_state, company.company_hq_country].filter(Boolean).join(', ')}</div>
                )}
              </div>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-white text-sm flex items-center gap-1 shrink-0 transition-colors mt-0.5"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
            Close
          </button>
        </div>
      </div>

      {/* ── Section tabs ── */}
      <div className="bg-white border-b border-bmw-border px-6 flex items-center gap-1 overflow-x-auto sticky top-0 z-10">
        {sections.map((s) => (
          <button
            key={s.id}
            onClick={() => scrollToSection(s.id)}
            className={`px-4 py-2.5 text-sm font-medium whitespace-nowrap border-b-2 transition-colors ${
              activeSection === s.id
                ? 'text-bmw-blue border-bmw-blue'
                : 'text-bmw-text-secondary border-transparent hover:text-bmw-text-primary'
            }`}
          >
            {s.label}
          </button>
        ))}
      </div>

      {/* ── Content ── */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto relative" onScroll={handleScroll}>
        <div className="max-w-6xl mx-auto px-6 py-6 space-y-12">

          {/* OVERVIEW */}
          <div ref={el => { sectionRefs.current['overview'] = el }}>
            <SectionDivider title="Overview" />
            <div className="space-y-6">
              {/* Edit toolbar */}
              <div className="flex items-center justify-between">
                <span />
                <div className="flex items-center gap-2">
                  {saveMsg && <span className={`text-xs ${saveMsg === 'Saved' ? 'text-green-600' : 'text-red-500'}`}>{saveMsg}</span>}
                  {editMode ? (
                    <>
                      <button
                        onClick={() => setEditMode(false)}
                        className="text-xs px-3 py-1.5 border border-bmw-border rounded text-gray-500 hover:bg-bmw-gray-light transition-colors"
                      >
                        Cancel
                      </button>
                      <button
                        onClick={handleSaveEdits}
                        disabled={saving}
                        className="text-xs px-3 py-1.5 bg-bmw-blue text-white rounded hover:bg-[#3a88ee] disabled:opacity-60 transition-colors"
                      >
                        {saving ? 'Saving...' : 'Save changes'}
                      </button>
                    </>
                  ) : (
                    <button
                      onClick={startEdit}
                      className="text-xs px-3 py-1.5 border border-bmw-border rounded text-gray-500 hover:bg-bmw-gray-light transition-colors flex items-center gap-1.5"
                    >
                      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125" />
                      </svg>
                      Edit
                    </button>
                  )}
                </div>
              </div>

              {/* Financial highlights row */}
              {(company.market_cap_usd || company.revenue_usd || company.total_funding_usd || company.number_of_employees || company.employee_size) && (
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  {company.market_cap_usd && (
                    <div className="bg-bmw-gray-light rounded-lg px-4 py-3 text-center">
                      <div className="text-lg font-bold text-bmw-navy">{formatMoney(company.market_cap_usd)}</div>
                      <div className="text-xs text-gray-500 mt-0.5">Market Cap</div>
                    </div>
                  )}
                  {company.revenue_usd && (
                    <div className="bg-bmw-gray-light rounded-lg px-4 py-3 text-center">
                      <div className="text-lg font-bold text-bmw-navy">{formatMoney(company.revenue_usd)}</div>
                      <div className="text-xs text-gray-500 mt-0.5">Revenue</div>
                    </div>
                  )}
                  {company.total_funding_usd && (
                    <div className="bg-bmw-gray-light rounded-lg px-4 py-3 text-center">
                      <div className="text-lg font-bold text-bmw-navy">{formatMoney(company.total_funding_usd)}</div>
                      <div className="text-xs text-gray-500 mt-0.5">Total Funding</div>
                    </div>
                  )}
                  {(company.number_of_employees || company.employee_size) && (
                    <div className="bg-bmw-gray-light rounded-lg px-4 py-3 text-center">
                      <div className="text-lg font-bold text-bmw-navy">
                        {company.number_of_employees ? company.number_of_employees.toLocaleString() : company.employee_size}
                      </div>
                      <div className="text-xs text-gray-500 mt-0.5">Employees</div>
                    </div>
                  )}
                </div>
              )}

              {/* Full info grid — mirrors company table columns */}
              <div className="grid grid-cols-2 gap-3">
                <InfoCard label="Company Type" value={company.company_type} />
                <InfoCard label="Status" value={company.company_status} />
                <InfoCard label="Segment" value={company.supply_chain_segment || company.industry_segment} />
                <InfoCard label="Funding Stage" value={company.funding_status} />
                <InfoCard label="HQ" value={[company.company_hq_city, company.company_hq_state, company.company_hq_country].filter(Boolean).join(', ')} />
                <InfoCard label="Founding Year" value={company.founding_year} />
                <InfoCard label="Last Fundraise" value={company.last_fundraise_date} />
                <InfoCard label="Chemistries" value={company.chemistries} />
                <InfoCard label="Feedstock" value={company.feedstock} />
                <InfoCard label="Plant Start Date" value={company.plant_start_date} />
                {company.hq_company && <InfoCard label="Parent Company" value={company.hq_company} />}
                <InfoCard label="NAATBatt Member" value={company.naatbatt_member ? 'Yes' : undefined} />
                <InfoCard label="Volta Member" value={company.volta_member ? 'Yes' : undefined} />
                <InfoCard label="Data Source" value={company.data_source} />
              </div>

              {/* Links */}
              {editMode && (
                <div className="bg-bmw-gray-light border border-bmw-border rounded-lg p-4 space-y-3">
                  <div className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-1">Edit Links</div>
                  {[
                    { key: 'company_website', label: 'Website' },
                    { key: 'crunchbase_url', label: 'Crunchbase' },
                    { key: 'linkedin_url', label: 'LinkedIn' },
                    { key: 'pitchbook_url', label: 'PitchBook' },
                  ].map(({ key, label }) => (
                    <div key={key} className="flex items-center gap-2">
                      <label className="text-xs text-gray-500 w-24 shrink-0">{label}</label>
                      <input
                        type="url"
                        value={editValues[key] || ''}
                        onChange={e => setEditValues(prev => ({ ...prev, [key]: e.target.value }))}
                        placeholder={`https://...`}
                        className="flex-1 border border-bmw-border rounded px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-bmw-blue"
                      />
                      {company.manual_overrides?.includes(key) && (
                        <span className="text-[10px] text-amber-600 bg-amber-50 px-1.5 py-0.5 rounded shrink-0">locked</span>
                      )}
                    </div>
                  ))}
                  <p className="text-[11px] text-gray-400">Saved links won't be overwritten when you re-research this company.</p>
                </div>
              )}
              {editMode && (
                <div className="bg-bmw-gray-light border border-bmw-border rounded-lg p-4 space-y-3">
                  <div className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-1">Edit Details</div>
                  {[
                    { key: 'company_type', label: 'Type', type: 'text' },
                    { key: 'company_status', label: 'Status', type: 'text' },
                    { key: 'company_hq_city', label: 'HQ City', type: 'text' },
                    { key: 'company_hq_state', label: 'HQ State', type: 'text' },
                    { key: 'company_hq_country', label: 'HQ Country', type: 'text' },
                    { key: 'company_hq_lat', label: 'Latitude', type: 'number' },
                    { key: 'company_hq_lng', label: 'Longitude', type: 'number' },
                    { key: 'founding_year', label: 'Founded', type: 'number' },
                    { key: 'number_of_employees', label: 'Employees', type: 'number' },
                  ].map(({ key, label, type }) => (
                    <div key={key} className="flex items-center gap-2">
                      <label className="text-xs text-gray-500 w-24 shrink-0">{label}</label>
                      <input
                        type={type}
                        value={editValues[key] ?? ''}
                        onChange={e => setEditValues(prev => ({ ...prev, [key]: e.target.value }))}
                        className="flex-1 border border-bmw-border rounded px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-bmw-blue"
                      />
                      {company.manual_overrides?.includes(key) && (
                        <span className="text-[10px] text-amber-600 bg-amber-50 px-1.5 py-0.5 rounded shrink-0">locked</span>
                      )}
                    </div>
                  ))}
                  <div className="flex items-start gap-2">
                    <label className="text-xs text-gray-500 w-24 shrink-0 pt-1.5">Summary</label>
                    <textarea
                      value={editValues.summary || ''}
                      onChange={e => setEditValues(prev => ({ ...prev, summary: e.target.value }))}
                      rows={3}
                      className="flex-1 border border-bmw-border rounded px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-bmw-blue resize-none"
                    />
                    {company.manual_overrides?.includes('summary') && (
                      <span className="text-[10px] text-amber-600 bg-amber-50 px-1.5 py-0.5 rounded shrink-0 mt-1.5">locked</span>
                    )}
                  </div>
                  <p className="text-[11px] text-gray-400">Saved details won't be overwritten when you re-research this company.</p>
                </div>
              )}
              {!editMode && (
                <div className="flex flex-wrap gap-3">
                  {company.company_website && (
                    <ExtLink label="Website" url={company.company_website} locked={company.manual_overrides?.includes('company_website')} />
                  )}
                  {company.crunchbase_url && (
                    <ExtLink label="Crunchbase" url={company.crunchbase_url} locked={company.manual_overrides?.includes('crunchbase_url')} />
                  )}
                  {company.linkedin_url && (
                    <ExtLink label="LinkedIn" url={company.linkedin_url} locked={company.manual_overrides?.includes('linkedin_url')} />
                  )}
                  {company.pitchbook_url && (
                    <ExtLink label="PitchBook" url={company.pitchbook_url} locked={company.manual_overrides?.includes('pitchbook_url')} />
                  )}
                  {!company.company_website && !company.crunchbase_url && !company.linkedin_url && !company.pitchbook_url && (
                    <button onClick={startEdit} className="text-xs text-gray-400 hover:text-bmw-blue transition-colors">+ Add links</button>
                  )}
                </div>
              )}

              {/* Summary */}
              {company.summary && (
                <Section title="Summary">
                  <p className="text-sm text-gray-700 leading-relaxed">{company.summary}</p>
                </Section>
              )}

              {/* Long description */}
              {company.long_description && (
                <Section title="Description">
                  <p className="text-sm text-gray-600 leading-relaxed">{company.long_description}</p>
                </Section>
              )}

              {/* Extra description */}
              {company.extra_description && (
                <Section title="Additional Profile">
                  <p className="text-sm text-gray-600 leading-relaxed">{company.extra_description}</p>
                </Section>
              )}

              {/* Products */}
              {company.products && (
                <Section title="Products">
                  <p className="text-sm text-gray-600">{company.products}</p>
                </Section>
              )}
              {company.product_services_desc && (
                <Section title="Product/Services Description">
                  <p className="text-sm text-gray-600 leading-relaxed">{company.product_services_desc}</p>
                </Section>
              )}

              {/* Keywords */}
              {company.keywords?.length > 0 && (
                <Section title="Keywords">
                  <div className="flex flex-wrap gap-1.5">
                    {company.keywords.map((k) => (
                      <span key={k} className="bg-bmw-gray-light border border-bmw-border text-xs px-2.5 py-1 rounded-full">{k}</span>
                    ))}
                  </div>
                </Section>
              )}

              {/* Battery Chemistry Flags */}
              {company.battery_chemistry_flags && Object.keys(company.battery_chemistry_flags).length > 0 && (
                <Section title="Battery Chemistries">
                  <div className="flex flex-wrap gap-1.5">
                    {Object.entries(company.battery_chemistry_flags).filter(([, v]) => v).map(([k]) => (
                      <span key={k} className="bg-blue-50 text-blue-700 text-xs px-2.5 py-1 rounded-full">{k}</span>
                    ))}
                  </div>
                </Section>
              )}

              {/* Supply Chain Flags */}
              {company.supply_chain_flags && Object.keys(company.supply_chain_flags).length > 0 && (
                <Section title="Supply Chain Segments">
                  <div className="flex flex-wrap gap-1.5">
                    {Object.entries(company.supply_chain_flags).filter(([, v]) => v).map(([k]) => (
                      <span key={k} className="bg-green-50 text-green-700 text-xs px-2.5 py-1 rounded-full">{k}</span>
                    ))}
                  </div>
                </Section>
              )}

              {/* GWh Capacity */}
              {company.gwh_capacity && Object.keys(company.gwh_capacity).length > 0 && (
                <Section title="Manufacturing Capacity (GWh)">
                  <div className="grid grid-cols-4 md:grid-cols-6 gap-2">
                    {Object.entries(company.gwh_capacity).sort(([a], [b]) => a.localeCompare(b)).map(([year, val]) => (
                      <div key={year} className="bg-bmw-gray-light rounded p-2 text-center">
                        <div className="text-xs text-gray-500">{year}</div>
                        <div className="text-sm font-semibold text-[text-bmw-text-primary]">{val}</div>
                      </div>
                    ))}
                  </div>
                </Section>
              )}

              {/* Contact */}
              {(company.contact_name || company.contact_email || company.contact_phone) && (
                <Section title="Contact">
                  <div className="bg-bmw-gray-light rounded-lg p-4 space-y-1">
                    {company.contact_name && <div className="text-sm font-medium text-[text-bmw-text-primary]">{company.contact_name}</div>}
                    {company.contact_email && <a href={`mailto:${company.contact_email}`} className="text-sm text-bmw-blue hover:underline block">{company.contact_email}</a>}
                    {company.contact_email2 && <a href={`mailto:${company.contact_email2}`} className="text-sm text-bmw-blue hover:underline block">{company.contact_email2}</a>}
                    {company.contact_phone && <div className="text-sm text-gray-500">{company.contact_phone}</div>}
                  </div>
                </Section>
              )}

              {/* Notes — always editable */}
              <Section title="Notes">
                <textarea
                  value={notesValue}
                  onChange={e => { setNotesValue(e.target.value); setNotesSaved(false) }}
                  placeholder="Add notes about this company..."
                  rows={4}
                  className="w-full border border-bmw-border rounded-lg px-3 py-2.5 text-sm text-gray-700 leading-relaxed focus:outline-none focus:ring-2 focus:ring-bmw-blue resize-y"
                />
                <div className="flex items-center gap-2 mt-1.5">
                  <button
                    onClick={handleSaveNotes}
                    disabled={notesSaving}
                    className="text-xs px-3 py-1 bg-bmw-blue text-white rounded hover:bg-[#3a88ee] disabled:opacity-60 transition-colors"
                  >
                    {notesSaving ? 'Saving...' : 'Save notes'}
                  </button>
                  {notesSaved && <span className="text-xs text-green-600">Saved</span>}
                </div>
              </Section>

              {/* Metrics from metrics table */}
              {company.metrics?.length > 0 && (
                <Section title="Additional Metrics">
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                    {company.metrics.map((m, i) => (
                      <div key={i} className="bg-bmw-gray-light rounded p-3">
                        <div className="text-xs text-gray-500 uppercase">{m.metric_name.replace(/_/g, ' ')}</div>
                        <div className="text-sm font-semibold text-[text-bmw-text-primary] mt-0.5">
                          {m.metric_value?.toLocaleString()} {m.metric_unit || ''}
                        </div>
                        {m.date_recorded && <div className="text-xs text-gray-400 mt-0.5">{m.date_recorded}</div>}
                      </div>
                    ))}
                  </div>
                </Section>
              )}
            </div>
          </div>

          {/* FACILITIES */}
          <div ref={el => { sectionRefs.current['facilities'] = el }}>
            <SectionDivider title={`Facilities (${(company.facilities || []).length})`} />
            <div className="space-y-3">
              {(company.facilities || []).length === 0 ? (
                <EmptyState text="No facility data available" />
              ) : (
                company.facilities.map((f, i) => (
                  <div key={f.id || i} className="bg-white border border-bmw-border rounded-lg p-4 space-y-2">
                    <div className="flex items-start justify-between">
                      <div>
                        {f.facility_name && <div className="font-medium text-[text-bmw-text-primary]">{f.facility_name}</div>}
                        <div className="text-sm text-gray-500 mt-0.5">
                          {[f.address, f.city, f.state, f.country, f.zip_code].filter(Boolean).join(', ')}
                        </div>
                      </div>
                      {f.status && (
                        <span className="text-xs bg-bmw-gray-light px-2 py-0.5 rounded">{f.status}</span>
                      )}
                    </div>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs text-gray-600">
                      {f.product_type && <span><b>Type:</b> {f.product_type}</span>}
                      {f.product && <span><b>Product:</b> {f.product}</span>}
                      {f.chemistries && <span><b>Chemistries:</b> {f.chemistries}</span>}
                      {f.feedstock && <span><b>Feedstock:</b> {f.feedstock}</span>}
                      {f.capacity && <span><b>Capacity:</b> {f.capacity} {f.capacity_units || ''}</span>}
                      {f.workforce && <span><b>Workforce:</b> {f.workforce}</span>}
                      {f.segment && <span><b>Segment:</b> {f.segment}</span>}
                      {f.phone && <span><b>Phone:</b> {f.phone}</span>}
                    </div>
                    <div className="flex items-center gap-4 text-xs text-gray-400">
                      {f.source_name && <span>Source: {f.source_name}</span>}
                      {f.date_added && <span>Added: {f.date_added.split('T')[0]}</span>}
                      {f.qc && <span>QC: {f.qc} {f.qc_date || ''}</span>}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* PARTNERSHIPS */}
          <div ref={el => { sectionRefs.current['partnerships'] = el }}>
            <SectionDivider title={`Partnerships (${allPartnerships.length})`} />
            <div className="space-y-3">
              {allPartnerships.length === 0 ? (
                <EmptyState text="No partnership data available" />
              ) : (
                allPartnerships.map((p) => (
                  <div
                    key={p.id}
                    className="bg-white border border-bmw-border rounded-lg p-4 cursor-pointer hover:border-bmw-blue transition-colors"
                    onClick={() => setSelectedPartnership(selectedPartnership?.id === p.id ? null : p)}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <span className="w-3 h-3 rounded-full shrink-0 bg-bmw-blue opacity-70" />
                        <div>
                          <div className="font-medium text-[text-bmw-text-primary] text-sm">{p.partnership_name || 'Partnership'}</div>
                          <div className="text-xs text-gray-500 mt-0.5">
                            {PARTNERSHIP_TYPE_LABELS[p.partnership_type] || p.partnership_type}
                            {p.date_announced && ` -- ${p.date_announced}`}
                          </div>
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        {p.deal_value && (
                          <span className="text-xs font-medium text-[text-bmw-text-primary]">{formatMoney(p.deal_value)}</span>
                        )}
                        {p.stage && (
                          <span className={`text-xs px-2 py-0.5 rounded ${STAGE_COLORS[p.stage] || 'bg-gray-100 text-gray-700'}`}>
                            {p.stage}
                          </span>
                        )}
                      </div>
                    </div>
                    {/* Members */}
                    <div className="flex flex-wrap gap-2 mt-2">
                      {(p.members || []).map((m, i) => (
                        <span
                          key={i}
                          className={`text-xs px-2 py-0.5 rounded-full ${
                            m.company_id === company.id
                              ? 'bg-blue-50 text-blue-700'
                              : 'bg-gray-100 text-gray-600 cursor-pointer hover:bg-gray-200'
                          }`}
                          onClick={(e) => {
                            e.stopPropagation()
                            if (m.company_id && m.company_id !== company.id && onOpenCompany) {
                              onOpenCompany(m.company_id)
                            }
                          }}
                        >
                          {m.company_name} ({m.role})
                        </span>
                      ))}
                    </div>
                    {/* Expanded detail on click */}
                    {selectedPartnership?.id === p.id && (
                      <div className="mt-3 pt-3 border-t border-bmw-border space-y-2 text-sm">
                        {p.scope && <div><b className="text-gray-500">Scope:</b> {p.scope}</div>}
                        {p.geography && <div><b className="text-gray-500">Geography:</b> {p.geography}</div>}
                        {p.direction && <div><b className="text-gray-500">Direction:</b> {p.direction.replace(/_/g, ' ')}</div>}
                        {p.date_effective && <div><b className="text-gray-500">Effective:</b> {p.date_effective}</div>}
                        {p.date_expiration && <div><b className="text-gray-500">Expiration:</b> {p.date_expiration}</div>}
                        {p.source_name && <div><b className="text-gray-500">Source:</b> {p.source_name}</div>}
                        {p.source_url && (
                          <a href={p.source_url} target="_blank" rel="noreferrer" className="text-bmw-blue hover:underline text-xs">
                            View source
                          </a>
                        )}
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>
          </div>

          {/* NEWS */}
          <div ref={el => { sectionRefs.current['news'] = el }}>
            <SectionDivider title={`News (${(company.news || []).length})`} />
            <div className="space-y-3">
              {(company.news || []).length === 0 ? (
                <EmptyState text="No news articles available" />
              ) : (
                company.news.map((n) => (
                  <div key={n.id} className="bg-white border border-bmw-border rounded-lg p-4">
                    <div className="font-medium text-[text-bmw-text-primary] text-sm">{n.news_headline}</div>
                    <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                      <span className={`text-xs px-2 py-0.5 rounded-full ${CATEGORY_COLORS[n.category] || CATEGORY_COLORS.other}`}>
                        {n.category}
                      </span>
                      <span className="text-gray-400 text-xs">{n.date_of_article}</span>
                      {n.news_source && <span className="text-gray-400 text-xs">{n.news_source}</span>}
                      {n.url && (
                        <a href={n.url} target="_blank" rel="noreferrer" className="text-bmw-blue text-xs hover:underline">
                          Source
                        </a>
                      )}
                    </div>
                    {n.summary && <p className="text-sm text-gray-600 mt-2 leading-relaxed">{n.summary}</p>}
                    {n.topics?.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-2">
                        {n.topics.map((t, i) => (
                          <span key={i} className="text-[10px] bg-bmw-gray-light px-1.5 py-0.5 rounded">{t}</span>
                        ))}
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>
          </div>

          {/* AI CHAT */}
          <div ref={el => { sectionRefs.current['ai'] = el }}>
            <SectionDivider title="AI Chat" />
            <div className="space-y-4 max-w-2xl">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-medium text-gray-500 uppercase">Ask AI about {company.company_name}</h3>
                <button
                  onClick={handleReResearch}
                  disabled={researching}
                  className="text-xs bg-[text-bmw-text-primary] hover:bg-[#0D2A5E] disabled:opacity-60 text-white px-4 py-1.5 rounded transition-colors"
                >
                  {researching ? 'Researching...' : 'Full re-research'}
                </button>
              </div>
              {researchStatus && <div className="text-xs text-gray-500">{researchStatus}</div>}

              {chatMessages.length > 0 && (
                <div className="space-y-3 max-h-96 overflow-y-auto pr-1">
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
                  placeholder={`Ask about ${company.company_name}...`}
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

          {/* SIMILAR COMPANIES */}
          <div ref={el => { sectionRefs.current['similar'] = el }}>
            <SectionDivider title="Similar Companies" />
            <div className="space-y-3">
              {(company.similar_companies || []).length === 0 ? (
                <EmptyState text="No similar companies found" />
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                  {company.similar_companies.map((sc) => (
                    <div
                      key={sc.id}
                      onClick={() => onOpenCompany && onOpenCompany(sc.id)}
                      className="bg-white border border-bmw-border rounded-lg p-4 cursor-pointer hover:border-bmw-blue hover:shadow-sm transition-all"
                    >
                      <div className="font-medium text-[#1A5FAD] text-sm">{sc.company_name}</div>
                      <div className="text-xs text-gray-500 mt-1">
                        {sc.company_type && <span>{sc.company_type}</span>}
                        {sc.company_hq_country && <span> -- {sc.company_hq_country}</span>}
                      </div>
                      {sc.industry_segment && (
                        <span className="text-[10px] bg-bmw-gray-light px-1.5 py-0.5 rounded mt-1.5 inline-block">{sc.industry_segment}</span>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* CITATIONS */}
          <div ref={el => { sectionRefs.current['citations'] = el }}>
            <SectionDivider title="Citations" />
            <div className="space-y-2">
              <p className="text-sm text-gray-500 mb-4">
                All data sources used to compile this company's information:
              </p>
              {(company.citations || []).length === 0 ? (
                <EmptyState text="No citation data available" />
              ) : (
                <div className="space-y-2">
                  {company.citations.map((c, i) => (
                    <div key={i} className="bg-white border border-bmw-border rounded-lg px-4 py-3 flex items-center justify-between">
                      <span className="text-sm text-[text-bmw-text-primary]">{c.source_name}</span>
                      {c.source_url ? (
                        <a href={c.source_url} target="_blank" rel="noreferrer" className="text-bmw-blue text-sm hover:underline">
                          {c.source_url}
                        </a>
                      ) : (
                        <span className="text-xs text-gray-400">No URL available</span>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

        </div>
      </div>
    </div>
  )
}

/* ── Helper components ── */

function SectionDivider({ title }) {
  return (
    <div className="flex items-center gap-3 mb-5">
      <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-widest whitespace-nowrap">{title}</h2>
      <div className="flex-1 h-px bg-gray-200" />
    </div>
  )
}

function InfoCard({ label, value }) {
  if (!value) return null
  return (
    <div className="bg-bmw-gray-light rounded-lg p-3">
      <div className="text-[10px] font-medium text-gray-500 uppercase tracking-wider">{label}</div>
      <div className="text-sm text-[text-bmw-text-primary] mt-0.5 font-medium break-words leading-snug">{value}</div>
    </div>
  )
}

function Section({ title, children }) {
  return (
    <div>
      <h3 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-2">{title}</h3>
      {children}
    </div>
  )
}

function ExtLink({ label, url, locked }) {
  return (
    <a
      href={url}
      target="_blank"
      rel="noreferrer"
      className="inline-flex items-center gap-1.5 text-xs text-bmw-blue hover:underline bg-blue-50 px-3 py-1.5 rounded-full"
    >
      {locked && (
        <svg className="w-3 h-3 text-amber-500" fill="currentColor" viewBox="0 0 20 20">
          <path fillRule="evenodd" d="M10 1a4.5 4.5 0 00-4.5 4.5V9H5a2 2 0 00-2 2v6a2 2 0 002 2h10a2 2 0 002-2v-6a2 2 0 00-2-2h-.5V5.5A4.5 4.5 0 0010 1zm3 8V5.5a3 3 0 10-6 0V9h6z" clipRule="evenodd" />
        </svg>
      )}
      {label}
      <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
        <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
      </svg>
    </a>
  )
}

function EmptyState({ text }) {
  return (
    <div className="text-center text-gray-400 py-12">
      <div className="text-lg">{text}</div>
      <div className="text-sm mt-1">Run AI research to populate this section</div>
    </div>
  )
}

function mapLegacyType(legacy) {
  const mapping = {
    'Joint Venture': 'jv',
    'Investment': 'equity_stake',
    'MOU': 'r_and_d_collab',
    'Off-take': 'supply_agreement',
    'Supply Agreement': 'supply_agreement',
    'Other': 'other',
  }
  return mapping[legacy] || 'other'
}
