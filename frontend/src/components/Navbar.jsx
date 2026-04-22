import React, { useState, useEffect, useRef } from 'react'
import { getSyncStatus, triggerSync } from '../api/client'
import { signOut } from '../lib/supabase'

const TABS = [
  { id: 'map', label: 'Company Map' },
  { id: 'table', label: 'Company Table' },
  { id: 'watchlist', label: 'Watchlist' },
  { id: 'network', label: 'Partnership Network' },
]

export default function Navbar({ activeTab, setActiveTab, watchlistBreaking = 0, onOpenDataImport = () => {}, user = null }) {
  const [syncInfo, setSyncInfo] = useState(null)
  const [syncing, setSyncing] = useState(false)
  const [profileOpen, setProfileOpen] = useState(false)
  const profileRef = useRef(null)

  useEffect(() => {
    loadSync()
    const interval = setInterval(loadSync, 60000)
    return () => clearInterval(interval)
  }, [])

  // Close profile dropdown on outside click
  useEffect(() => {
    function onClickOutside(e) {
      if (profileRef.current && !profileRef.current.contains(e.target)) {
        setProfileOpen(false)
      }
    }
    document.addEventListener('mousedown', onClickOutside)
    return () => document.removeEventListener('mousedown', onClickOutside)
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

  const avatarUrl = user?.user_metadata?.avatar_url
  const displayName = user?.user_metadata?.full_name || user?.email || 'User'
  const initials = displayName.split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase()

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

        {/* Right side: Sync + Data Import + Profile */}
        <div className="flex items-center gap-2 min-w-fit">
          <span className="text-bmw-text-secondary text-xs whitespace-nowrap">
            Synced: <span className="text-bmw-text-primary font-medium">{lastSynced}</span>
          </span>
          <button
            onClick={handleSync}
            disabled={syncing}
            className="bg-bmw-blue hover:bg-[#3a88ee] text-white disabled:opacity-40 text-xs px-4 py-1.5 rounded font-medium transition-colors"
          >
            {syncing ? 'Syncing…' : 'Sync Now'}
          </button>
          <button
            onClick={() => onOpenDataImport()}
            className="bg-bmw-blue hover:bg-[#3a88ee] text-white text-xs px-4 py-1.5 rounded font-medium transition-colors"
          >
            Data Import
          </button>

          {/* Profile avatar + dropdown */}
          {user && (
            <div className="relative" ref={profileRef}>
              <button
                onClick={() => setProfileOpen(v => !v)}
                className="flex items-center gap-2 pl-2 pr-1 py-1 rounded-full hover:bg-gray-100 transition-colors"
              >
                {avatarUrl ? (
                  <img src={avatarUrl} alt={displayName} className="w-7 h-7 rounded-full object-cover" />
                ) : (
                  <div className="w-7 h-7 rounded-full bg-bmw-blue flex items-center justify-center text-white text-xs font-bold">
                    {initials}
                  </div>
                )}
                <svg className="w-3 h-3 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                </svg>
              </button>

              {profileOpen && (
                <div className="absolute right-0 top-full mt-1 w-56 bg-white border border-gray-200 rounded-xl shadow-lg z-[9999] py-1">
                  <div className="px-4 py-3 border-b border-gray-100">
                    <p className="text-sm font-semibold text-gray-800 truncate">{displayName}</p>
                    <p className="text-xs text-gray-500 truncate">{user.email}</p>
                  </div>
                  <button
                    onClick={() => { setProfileOpen(false); signOut() }}
                    className="w-full text-left px-4 py-2.5 text-sm text-gray-700 hover:bg-gray-50 flex items-center gap-2"
                  >
                    <svg className="w-4 h-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2h6a2 2 0 012 2v1" />
                    </svg>
                    Sign out
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </nav>
  )
}
