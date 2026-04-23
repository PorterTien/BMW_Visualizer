import { useState, useEffect, useCallback, useRef } from 'react'
import Navbar from './components/Navbar'
import Sidebar from './components/Sidebar'
import CompanyMap from './components/CompanyMap'
import CompanyTable from './components/CompanyTable'
import PartnershipNetwork from './components/PartnershipNetwork'
import ResearchPanel from './components/ResearchPanel'
import WatchlistPanel from './components/WatchlistPanel'
import CompanyDetailPage from './components/CompanyDetailPage'
import { getSeedStatus, triggerSeed, getWatchlistDigest, getCompanies, getCompaniesMap, getCompaniesNetwork } from './api/client'
import { supabase } from './lib/supabase'
import { setAuthToken } from './api/client'

export default function App() {
  const [session, setSession] = useState(null)
  const [activeTab, setActiveTab] = useState('watchlist')
  const [filters, setFilters] = useState({ search: '', types: [], statuses: [], segments: [], countries: [] })
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [highlightCompany, setHighlightCompany] = useState(null)
  const [seedBanner, setSeedBanner] = useState(false)
  // Company detail full page view
  const [detailCompanyId, setDetailCompanyId] = useState(null)
  const [dataImportOpen, setDataImportOpen] = useState(false)
  const seedPollRef = useRef(null)

  // Auth: listen for Supabase session changes
  useEffect(() => {
    // Subscribe first so we don't miss the INITIAL_SESSION event that fires
    // when getSession() resolves the URL hash tokens after an OAuth redirect.
    const { data: { subscription } } = supabase.auth.onAuthStateChange((event, s) => {
      console.log('[Auth] event:', event, 'user:', s?.user?.email ?? 'none')
      setSession(s)
      setAuthToken(s?.access_token ?? null)
    })
    supabase.auth.getSession().then(({ data: { session: s } }) => {
      console.log('[Auth] getSession:', s?.user?.email ?? 'no session')
      setSession(s)
      setAuthToken(s?.access_token ?? null)
    })
    return () => subscription.unsubscribe()
  }, [])

  // Prefetch heavy list endpoints into the module-level cache on startup
  useEffect(() => {
    getCompanies({ limit: 2000 })
    getCompaniesMap()
    getCompaniesNetwork()
  }, [])

  // Resizable company detail panel
  const [panelWidth, setPanelWidth] = useState(700)
  const panelResizeRef = useRef({ active: false, startX: 0, startW: 0 })
  const startPanelResize = useCallback((e) => {
    e.preventDefault()
    panelResizeRef.current = { active: true, startX: e.clientX, startW: panelWidth }
    const onMove = (ev) => {
      if (!panelResizeRef.current.active) return
      const delta = panelResizeRef.current.startX - ev.clientX
      setPanelWidth(Math.max(400, Math.min(window.innerWidth - 120, panelResizeRef.current.startW + delta)))
    }
    const onUp = () => {
      panelResizeRef.current.active = false
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }, [panelWidth])

  const [watchlistBreaking, setWatchlistBreaking] = useState(0)

  // Poll for breaking news count to show badge in navbar (only when logged in)
  useEffect(() => {
    if (!session) return
    function checkBreaking() {
      getWatchlistDigest()
        .then(({ data }) => setWatchlistBreaking(data.filter((d) => d.has_breaking).length))
        .catch(() => {})
    }
    checkBreaking()
    const iv = setInterval(checkBreaking, 60000)
    return () => clearInterval(iv)
  }, [session])

  useEffect(() => {
    getSeedStatus()
      .then(({ data }) => {
        if (!data.seeded) {
          setSeedBanner(true)
          triggerSeed()
            .then(() => {
              seedPollRef.current = setInterval(() => {
                getSeedStatus().then(({ data: s }) => {
                  if (s.seeded) {
                    clearInterval(seedPollRef.current)
                    setSeedBanner(false)
                  }
                })
              }, 5000)
            })
            .catch(() => setSeedBanner(false))
        }
      })
      .catch(() => {})
    return () => clearInterval(seedPollRef.current)
  }, [])

  // Navigate to full company detail page
  const handleOpenCompanyPage = useCallback((id) => setDetailCompanyId(id), [])
  const handleCloseCompanyPage = useCallback(() => setDetailCompanyId(null), [])

  const showSidebar = activeTab === 'map' || activeTab === 'table'

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-white">
      <Navbar
        activeTab={activeTab}
        setActiveTab={(tab) => { setDetailCompanyId(null); setActiveTab(tab) }}
        watchlistBreaking={watchlistBreaking}
        onOpenDataImport={() => setDataImportOpen(true)}
        user={session?.user}
      />

      {/* Seeding banner */}
      {seedBanner && (
        <div className="bg-bmw-blue text-white text-sm text-center py-2 px-4 flex items-center justify-center gap-3">
          <span className="animate-spin"></span>
          Importing battery company database — this may take a few minutes on first run…
        </div>
      )}

      <div className="flex flex-1 overflow-hidden min-h-0 bg-white">
        {/* Sidebar — only for map and table views */}
        {showSidebar && (
          <Sidebar
            filters={filters}
            setFilters={setFilters}
            collapsed={sidebarCollapsed}
            setCollapsed={setSidebarCollapsed}
            onHighlightCompany={setHighlightCompany}
          />
        )}

        {/* Main content */}
        <main className="flex-1 min-w-0 min-h-0 flex flex-col overflow-y-auto overflow-x-hidden">
          {activeTab === 'map' && (
            <CompanyMap
              filters={filters}
              onSelectCompany={handleOpenCompanyPage}
              highlightName={highlightCompany}
            />
          )}
          {activeTab === 'table' && (
            <CompanyTable filters={filters} onOpenCompany={handleOpenCompanyPage} />
          )}
          {activeTab === 'watchlist' && <WatchlistPanel onOpenCompany={handleOpenCompanyPage} user={session?.user} />}
{activeTab === 'network' && (
            <PartnershipNetwork onSelectCompany={handleOpenCompanyPage} />
          )}
        </main>
      </div>

      {/* Company detail drawer */}
      {detailCompanyId && (
        <div className="fixed inset-0 z-[1100] flex">
          {/* Backdrop — click to close */}
          <div className="flex-1 bg-black/20" onClick={handleCloseCompanyPage} />
          {/* Panel */}
          <div
            style={{ width: panelWidth }}
            className="relative bg-white shadow-2xl flex flex-col overflow-hidden border-l border-gray-200 animate-slide-in-right shrink-0"
          >
            {/* Drag handle — left edge */}
            <div
              onMouseDown={startPanelResize}
              className="absolute left-0 top-0 w-1.5 h-full cursor-col-resize z-20 group"
              title="Drag to resize"
            >
              <div className="w-full h-full bg-transparent group-hover:bg-bmw-blue/25 transition-colors" />
            </div>
            <CompanyDetailPage
              key={detailCompanyId}
              companyId={detailCompanyId}
              onClose={handleCloseCompanyPage}
              onOpenCompany={handleOpenCompanyPage}
            />
          </div>
        </div>
      )}

      {/* Data Import Modal */}
      {dataImportOpen && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-[9999]">
          <div className="bg-white rounded-lg shadow-xl w-full max-w-3xl max-h-[90vh] overflow-auto">
            <div className="flex items-center justify-between p-4 border-b border-gray-200">
              <h2 className="text-lg font-semibold text-gray-800">Data Import</h2>
              <button
                onClick={() => setDataImportOpen(false)}
                className="text-gray-500 hover:text-gray-700 text-2xl leading-none"
              >
                ✕
              </button>
            </div>
            <div className="p-6">
              <ResearchPanel />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

