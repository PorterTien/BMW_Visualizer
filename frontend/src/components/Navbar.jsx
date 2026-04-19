import React, { useState, useEffect } from 'react'
import { getSyncStatus, triggerSync } from '../api/client'

const TABS = [
  { id: 'map', label: 'Company Map' },
  { id: 'table', label: 'Company Table' },
  { id: 'watchlist', label: 'Watchlist' },
  { id: 'network', label: 'Partnership Network' },
]

export default function Navbar({ activeTab, setActiveTab, watchlistBreaking = 0, onOpenDataImport = () => {} }) {
  const [syncInfo, setSyncInfo] = useState(null)
  const [syncing, setSyncing] = useState(false)

  useEffect(() => {
    loadSync()
    const interval = setInterval(loadSync, 60000)
    return () => clearInterval(interval)
  }, [])

  async function loadSync() {
    try {
      const { data } = await getSyncStatus()
      setSyncInfo(data)
    } catch (_) {}
  }

  async function handleSync() {
    setSyncing(true)
    try {
      await triggerSync()
      setTimeout(loadSync, 3000)
    } catch (_) {}
    setTimeout(() => setSyncing(false), 2000)
  }

  const lastSynced = syncInfo?.last_sync?.run_at
    ? new Date(syncInfo.last_sync.run_at).toLocaleDateString()
    : 'Never'

  return (
    <nav className="bg-white select-none border-b border-bmw-border shadow-light" style={{ height: '56px' }}>
      <div className="flex items-center h-full px-6 gap-4">
        {/* Logo + Title */}
        <div className="flex items-center gap-3 min-w-fit">
          <img
            src="https://upload.wikimedia.org/wikipedia/commons/thumb/4/44/BMW.svg/600px-BMW.svg.png"
            alt="BMW"
            className="w-8 h-8 rounded-full object-cover flex-shrink-0"
          />
          <span className="text-bmw-navy font-bold text-base whitespace-nowrap tracking-tight font-display">
            BMW Battery
          </span>
        </div>

        {/* Tabs */}
        <div className="flex items-center h-full flex-1 overflow-x-auto gap-0.5">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`relative h-full px-5 text-sm font-medium whitespace-nowrap transition-all rounded-t ${
                activeTab === tab.id
                  ? 'text-bmw-blue bg-bmw-gray-light'
                  : 'text-bmw-text-secondary hover:bg-bmw-gray-light hover:text-bmw-text-primary'
              }`}
            >
              <span className="flex items-center gap-1.5">
                {tab.label}
                {tab.id === 'watchlist' && watchlistBreaking > 0 && (
                  <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
                )}
              </span>
              {activeTab === tab.id && (
                <span className="absolute bottom-0 left-0 right-0 h-[3px] bg-bmw-blue" />
              )}
            </button>
          ))}
        </div>

        {/* Sync badge + Data Import */}
        <div className="flex items-center gap-2 min-w-fit">
          <span className="text-bmw-text-secondary text-xs whitespace-nowrap">
            Synced: <span className="text-bmw-text-primary font-medium">{lastSynced}</span>
          </span>
          <button
            onClick={handleSync}
            disabled={syncing}
            className="bg-bmw-blue hover:bg-[#3a88ee] text-white disabled:opacity-40 text-xs px-4 py-1.5 rounded font-medium transition-colors"
          >
            {syncing ? 'Syncing\u2026' : 'Sync Now'}
          </button>
          <button
            onClick={() => onOpenDataImport()}
            className="bg-bmw-blue hover:bg-[#3a88ee] text-white text-xs px-4 py-1.5 rounded font-medium transition-colors"
          >
            Data Import
          </button>
        </div>
      </div>
    </nav>
  )
}
