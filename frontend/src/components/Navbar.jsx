import React from 'react'

const TABS = [
  { id: 'watchlist', label: 'Watchlist' },
  { id: 'map', label: 'Company Map' },
  { id: 'table', label: 'Company Table' },
  { id: 'network', label: 'Partnership Network' },
]

export default function Navbar({ activeTab, setActiveTab, watchlistBreaking = 0, onOpenDataImport = () => {} }) {
  return (
    <nav className="bg-white select-none border-b border-bmw-border shadow-light" style={{ height: '56px' }}>
      <div className="flex items-center h-full px-6 gap-4">
        {/* Logo + Title */}
        <div className="flex items-center gap-3 min-w-fit">
          <img
            src="/bmw-logo.png"
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

        {/* Data Import button */}
        <div className="min-w-fit">
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
