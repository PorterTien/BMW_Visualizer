import React, { useState, useEffect, useCallback, useRef } from 'react'
import Navbar from './components/Navbar'
import Sidebar from './components/Sidebar'
import CompanyMap from './components/CompanyMap'
import CompanyTable from './components/CompanyTable'
import NewsFeed from './components/NewsFeed'
import PartnershipNetwork from './components/PartnershipNetwork'
import ResearchPanel from './components/ResearchPanel'
import Proceedings from './components/Proceedings'
import CompanyDetail from './components/CompanyDetail'
import { getSeedStatus, triggerSeed } from './api/client'

export default function App() {
  const [activeTab, setActiveTab] = useState('map')
  const [filters, setFilters] = useState({ search: '', types: [], statuses: [], segments: [], countries: [] })
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [selectedCompanyId, setSelectedCompanyId] = useState(null)
  const [highlightCompany, setHighlightCompany] = useState(null)
  const [seeding, setSeeding] = useState(false)
  const [seedBanner, setSeedBanner] = useState(false)
  const seedPollRef = useRef(null)

  // Dark mode — persisted in localStorage
  const [darkMode, setDarkMode] = useState(() => {
    const saved = localStorage.getItem('bmw-dark-mode')
    return saved === 'true'
  })

  useEffect(() => {
    const root = document.documentElement
    if (darkMode) {
      root.classList.add('dark')
    } else {
      root.classList.remove('dark')
    }
    localStorage.setItem('bmw-dark-mode', darkMode)
  }, [darkMode])

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

  const handleSelectCompany = useCallback((id) => setSelectedCompanyId(id), [])
  const handleCloseDetail = useCallback(() => setSelectedCompanyId(null), [])

  const showSidebar = activeTab === 'map' || activeTab === 'table'

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-[#F0F4F8]">
      <Navbar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        darkMode={darkMode}
        setDarkMode={setDarkMode}
      />

      {/* Seeding banner */}
      {seedBanner && (
        <div className="bg-[#4599FE] text-white text-sm text-center py-2 px-4 flex items-center justify-center gap-3">
          <span className="animate-spin"></span>
          Importing NAATBatt battery company database — this may take a few minutes on first run…
        </div>
      )}

      <div className="flex flex-1 overflow-hidden min-h-0">
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
              onSelectCompany={handleSelectCompany}
              highlightName={highlightCompany}
              darkMode={darkMode}
            />
          )}
          {activeTab === 'table' && <CompanyTable filters={filters} />}
          {activeTab === 'news' && <NewsFeed />}
          {activeTab === 'network' && (
            <PartnershipNetwork onSelectCompany={handleSelectCompany} darkMode={darkMode} />
          )}
          {activeTab === 'research' && <ResearchPanel />}
          {activeTab === 'proceedings' && <Proceedings />}
        </main>
      </div>

      {/* Global company detail panel (map, network) */}
      {selectedCompanyId && (
        <CompanyDetail
          companyId={selectedCompanyId}
          onClose={handleCloseDetail}
        />
      )}
    </div>
  )
}
