import React, { useState, useEffect, useCallback, useRef } from 'react'
import Navbar from './components/Navbar'
import Sidebar from './components/Sidebar'
import CompanyMap from './components/CompanyMap'
import CompanyTable from './components/CompanyTable'
import PartnershipNetwork from './components/PartnershipNetwork'
import ResearchPanel from './components/ResearchPanel'
import WatchlistPanel from './components/WatchlistPanel'
import CompanyDetailPage from './components/CompanyDetailPage'
import { getSeedStatus, triggerSeed, getWatchlistDigest } from './api/client'

export default function App() {
  const [activeTab, setActiveTab] = useState('map')
  const [filters, setFilters] = useState({ search: '', types: [], statuses: [], segments: [], countries: [] })
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [selectedCompanyId, setSelectedCompanyId] = useState(null)
  const [highlightCompany, setHighlightCompany] = useState(null)
  const [seeding, setSeeding] = useState(false)
  const [seedBanner, setSeedBanner] = useState(false)
  // Company detail full page view
  const [detailCompanyId, setDetailCompanyId] = useState(null)
  const [dataImportOpen, setDataImportOpen] = useState(false)
  const seedPollRef = useRef(null)

  const [watchlistBreaking, setWatchlistBreaking] = useState(0)

  // Poll for breaking news count to show badge in navbar
  useEffect(() => {
    function checkBreaking() {
      getWatchlistDigest()
        .then(({ data }) => setWatchlistBreaking(data.filter((d) => d.has_breaking).length))
        .catch(() => {})
    }
    checkBreaking()
    const iv = setInterval(checkBreaking, 60000)
    return () => clearInterval(iv)
  }, [])

  useEffect(() => {
    getSeedStatus()
      .then(({ data }) => {
        if (!data.seeded) {
          setSeedBanner(true)
          setSeeding(true)
          triggerSeed()
            .then(() => {
              seedPollRef.current = setInterval(() => {
                getSeedStatus().then(({ data: s }) => {
                  if (s.seeded) {
                    clearInterval(seedPollRef.current)
                    setSeeding(false)
                    setSeedBanner(false)
                  }
                })
              }, 5000)
            })
            .catch(() => setSeeding(false))
        }
      })
      .catch(() => {})
    return () => clearInterval(seedPollRef.current)
  }, [])

  // Navigate to full company detail page
  const handleOpenCompanyPage = useCallback((id) => setDetailCompanyId(id), [])
  const handleCloseCompanyPage = useCallback(() => setDetailCompanyId(null), [])

  const showSidebar = !detailCompanyId && (activeTab === 'map' || activeTab === 'table')

  // If a company detail page is open, show it full screen
  if (detailCompanyId) {
    return (
      <div className="flex flex-col h-screen overflow-hidden bg-bmw-gray-light">
        <Navbar
          activeTab={activeTab}
          setActiveTab={(tab) => { setDetailCompanyId(null); setActiveTab(tab) }}
          watchlistBreaking={watchlistBreaking}
          onOpenDataImport={() => setDataImportOpen(true)}
        />
        <CompanyDetailPage
          companyId={detailCompanyId}
          onClose={handleCloseCompanyPage}
          onOpenCompany={handleOpenCompanyPage}
        />  
      </div>
    )
  }

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-white">
      <Navbar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        watchlistBreaking={watchlistBreaking}
        onOpenDataImport={() => setDataImportOpen(true)}
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
        <main className="flex-1 min-w-0 min-h-0 flex flex-col overflow-hidden">
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
          {activeTab === 'watchlist' && <WatchlistPanel />}
{activeTab === 'network' && (
            <PartnershipNetwork onSelectCompany={handleOpenCompanyPage} />
          )}
        </main>
      </div>

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

