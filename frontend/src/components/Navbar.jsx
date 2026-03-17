import React, { useState, useEffect, useRef } from 'react'
import { getSyncStatus, triggerSync } from '../api/client'

const TABS = [
  { id: 'map', label: 'Company Map' },
  { id: 'table', label: 'Company Table' },
  { id: 'news', label: 'News Feed' },
  { id: 'network', label: 'Partnership Network' },
  { id: 'research', label: 'Research Panel' },
  { id: 'proceedings', label: 'Conference Proceedings' },
]

export default function Navbar({ activeTab, setActiveTab, darkMode, setDarkMode }) {
  const [syncInfo, setSyncInfo] = useState(null)
  const [syncing, setSyncing] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const settingsRef = useRef(null)

  useEffect(() => {
    loadSync()
    const interval = setInterval(loadSync, 60000)
    return () => clearInterval(interval)
  }, [])

  // Close dropdown on outside click
  useEffect(() => {
    function handleClick(e) {
      if (settingsRef.current && !settingsRef.current.contains(e.target)) {
        setSettingsOpen(false)
      }
    }
    if (settingsOpen) document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [settingsOpen])

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
    <nav className="bg-[#031E49] select-none border-b border-[#0a2a5e]" style={{ height: '44px' }}>
      <div className="flex items-center h-full px-4 gap-6">
        {/* Logo + Title */}
        <div className="flex items-center gap-2 min-w-fit">
          <img
            src="https://upload.wikimedia.org/wikipedia/commons/thumb/4/44/BMW.svg/600px-BMW.svg.png"
            alt="BMW"
            className="w-6 h-6 rounded-full object-cover flex-shrink-0"
          />
          <span className="text-white font-semibold text-sm whitespace-nowrap tracking-wide">
            BMW Battery Intelligence
          </span>
        </div>

        {/* Tabs */}
        <div className="flex items-center h-full flex-1 overflow-x-auto">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`relative h-full px-4 text-sm whitespace-nowrap transition-colors ${
                activeTab === tab.id
                  ? 'text-white'
                  : 'text-[#8aa4be] hover:text-white'
              }`}
            >
              {tab.label}
              {activeTab === tab.id && (
                <span className="absolute bottom-0 left-0 right-0 h-[2px] bg-[#4599FE]" />
              )}
            </button>
          ))}
        </div>

        {/* Sync badge */}
        <div className="flex items-center gap-2 min-w-fit">
          <span className="text-[#8aa4be] text-xs whitespace-nowrap">
            Synced: <span className="text-white">{lastSynced}</span>
          </span>
          <button
            onClick={handleSync}
            disabled={syncing}
            className="border border-[#4599FE] text-[#4599FE] hover:bg-[#4599FE] hover:text-white disabled:opacity-40 text-xs px-3 py-1 rounded transition-colors"
          >
            {syncing ? 'Syncing\u2026' : 'Sync Now'}
          </button>
        </div>

        {/* Settings gear */}
        <div className="relative" ref={settingsRef}>
          <button
            onClick={() => setSettingsOpen((o) => !o)}
            className={`p-1.5 rounded transition-colors ${
              settingsOpen
                ? 'bg-[#0a2a5e] text-white'
                : 'text-[#8aa4be] hover:text-white'
            }`}
            title="Settings"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.5">
              <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28Z" />
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
            </svg>
          </button>

          {/* Dropdown */}
          {settingsOpen && (
            <div className="absolute right-0 top-full mt-1 w-56 bg-[#031E49] border border-[#0a2a5e] rounded-lg shadow-2xl z-50 py-1 overflow-hidden">
              <div className="px-3 py-2 text-[10px] font-semibold text-[#8aa4be] uppercase tracking-wider">
                Appearance
              </div>

              {/* Light mode option */}
              <button
                onClick={() => { setDarkMode(false); setSettingsOpen(false) }}
                className={`w-full flex items-center gap-3 px-3 py-2 text-sm transition-colors ${
                  !darkMode
                    ? 'text-white bg-[#0a2a5e]'
                    : 'text-[#8aa4be] hover:text-white hover:bg-[#0a2a5e]/50'
                }`}
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.5">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 3v2.25m6.364.386-1.591 1.591M21 12h-2.25m-.386 6.364-1.591-1.591M12 18.75V21m-4.773-4.227-1.591 1.591M5.25 12H3m4.227-4.773L5.636 5.636M15.75 12a3.75 3.75 0 1 1-7.5 0 3.75 3.75 0 0 1 7.5 0Z" />
                </svg>
                Light
                {!darkMode && (
                  <svg className="w-3.5 h-3.5 ml-auto text-[#4599FE]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2.5">
                    <path strokeLinecap="round" strokeLinejoin="round" d="m4.5 12.75 6 6 9-13.5" />
                  </svg>
                )}
              </button>

              {/* Dark mode option */}
              <button
                onClick={() => { setDarkMode(true); setSettingsOpen(false) }}
                className={`w-full flex items-center gap-3 px-3 py-2 text-sm transition-colors ${
                  darkMode
                    ? 'text-white bg-[#0a2a5e]'
                    : 'text-[#8aa4be] hover:text-white hover:bg-[#0a2a5e]/50'
                }`}
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.5">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M21.752 15.002A9.72 9.72 0 0 1 18 15.75c-5.385 0-9.75-4.365-9.75-9.75 0-1.33.266-2.597.748-3.752A9.753 9.753 0 0 0 3 11.25C3 16.635 7.365 21 12.75 21a9.753 9.753 0 0 0 9.002-5.998Z" />
                </svg>
                Dark
                {darkMode && (
                  <svg className="w-3.5 h-3.5 ml-auto text-[#4599FE]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2.5">
                    <path strokeLinecap="round" strokeLinejoin="round" d="m4.5 12.75 6 6 9-13.5" />
                  </svg>
                )}
              </button>
            </div>
          )}
        </div>
      </div>
    </nav>
  )
}
