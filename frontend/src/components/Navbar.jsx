import React, { useState, useRef, useEffect } from 'react'
import { signInWithGoogle, signOut } from '../lib/supabase'

const TABS = [
  { id: 'watchlist', label: 'Watchlist' },
  { id: 'map', label: 'Company Map' },
  { id: 'table', label: 'Company Table' },
  { id: 'network', label: 'Partnership Network' },
  { id: 'ai-research', label: 'AI Research' },
]

function SyncIcon({ spinning }) {
  return (
    <svg
      className={`w-3 h-3 flex-shrink-0 ${spinning ? 'animate-spin' : ''}`}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M13.5 2.5A6.5 6.5 0 0 0 2 8" />
      <path d="M2.5 13.5A6.5 6.5 0 0 0 14 8" />
      <polyline points="2 2 2 6 6 6" />
      <polyline points="14 14 14 10 10 10" />
    </svg>
  )
}

function formatSyncAge(runAt) {
  if (!runAt) return null
  const ms = Date.now() - new Date(runAt).getTime()
  const minutes = Math.floor(ms / 60000)
  const hours = Math.floor(ms / 3600000)
  const days = Math.floor(ms / 86400000)
  if (minutes < 2) return 'just now'
  if (hours < 1) return `${minutes}m ago`
  if (hours < 24) return `${hours}h ago`
  if (days === 1) return 'yesterday'
  return `${days}d ago`
}

function getDaysSince(runAt) {
  if (!runAt) return null
  return Math.floor((Date.now() - new Date(runAt).getTime()) / 86400000)
}

function SyncBadge({ syncStatus, syncing, onSyncNow }) {
  const runAt = syncStatus?.last_sync?.run_at
  const days = getDaysSince(runAt)
  const age = formatSyncAge(runAt)

  // Urgency levels
  const urgency =
    syncing ? 'syncing'
    : days === null ? 'unknown'
    : days < 14 ? 'ok'
    : days < 30 ? 'warn'
    : 'critical'

  const label = syncing
    ? 'Syncing…'
    : days === null
    ? 'Never synced'
    : `Last synced ${age}`

  const base = 'flex items-center gap-1.5 text-xs font-medium px-4 py-1.5 rounded whitespace-nowrap transition-colors'

  if (urgency === 'ok') {
    return (
      <div className="flex items-center gap-2">
        <span className="text-xs text-gray-400 whitespace-nowrap">{label}</span>
        <button
          onClick={onSyncNow}
          title="Sync NAATBatt data now"
          className={`${base} text-gray-500 border border-gray-200 hover:text-bmw-blue hover:border-bmw-blue`}
        >
          <SyncIcon spinning={false} />
          <span>Sync Now</span>
        </button>
      </div>
    )
  }

  if (urgency === 'syncing') {
    return (
      <div className={`${base} text-bmw-blue bg-blue-50 border border-blue-200 cursor-default`}>
        <SyncIcon spinning={true} />
        <span>Syncing…</span>
      </div>
    )
  }

  if (urgency === 'unknown') {
    return (
      <button
        onClick={onSyncNow}
        className={`${base} text-gray-500 border border-gray-200 hover:text-bmw-blue hover:border-bmw-blue`}
      >
        <SyncIcon spinning={false} />
        <span>Sync Now</span>
      </button>
    )
  }

  if (urgency === 'warn') {
    return (
      <button
        onClick={onSyncNow}
        title={`Last synced ${age} — click to sync now`}
        className={`${base} text-amber-700 bg-amber-50 border border-amber-300 hover:bg-amber-100`}
      >
        <svg className="w-3 h-3 flex-shrink-0" viewBox="0 0 16 16" fill="currentColor">
          <path d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1zm0 4a.75.75 0 0 1 .75.75v3a.75.75 0 0 1-1.5 0v-3A.75.75 0 0 1 8 5zm0 6.5a.875.875 0 1 1 0-1.75.875.875 0 0 1 0 1.75z"/>
        </svg>
        <span>{label} · Sync Now</span>
      </button>
    )
  }

  // Critical — red throb
  return (
    <button
      onClick={onSyncNow}
      title={`Last synced ${age} — overdue! Click to sync now`}
      className={`${base} animate-throb text-white bg-red-500 hover:bg-red-600`}
    >
      <SyncIcon spinning={false} />
      <span className="animate-pulse-dim">{label} · Sync Now</span>
    </button>
  )
}

export default function Navbar({
  activeTab,
  setActiveTab,
  watchlistBreaking = 0,
  onOpenDataImport = () => {},
  user = null,
  syncStatus = null,
  syncing = false,
  onSyncNow = () => {},
}) {
  const [dropdownOpen, setDropdownOpen] = useState(false)
  const dropdownRef = useRef(null)

  useEffect(() => {
    function handleClickOutside(e) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

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

        {/* Right side: Sync badge + Data Import + auth */}
        <div className="flex items-center gap-3 min-w-fit">
          <SyncBadge syncStatus={syncStatus} syncing={syncing} onSyncNow={onSyncNow} />

          <button
            onClick={() => onOpenDataImport()}
            className="bg-bmw-blue hover:bg-[#3a88ee] text-white text-xs px-4 py-1.5 rounded font-medium transition-colors"
          >
            Data Import
          </button>

          {user ? (
            <div className="relative" ref={dropdownRef}>
              <button
                onClick={() => setDropdownOpen((v) => !v)}
                className="flex items-center gap-2 rounded-full focus:outline-none"
                title={user.email}
              >
                {user.user_metadata?.avatar_url ? (
                  <img
                    src={user.user_metadata.avatar_url}
                    alt=""
                    className="w-8 h-8 rounded-full object-cover border border-gray-200"
                    referrerPolicy="no-referrer"
                    onError={(e) => { e.currentTarget.style.display = 'none' }}
                  />
                ) : (
                  <div className="w-8 h-8 rounded-full bg-bmw-blue flex items-center justify-center text-white text-sm font-semibold">
                    {(user.email?.[0] ?? '?').toUpperCase()}
                  </div>
                )}
              </button>

              {dropdownOpen && (
                <div className="absolute right-0 mt-2 w-52 bg-white rounded-lg shadow-lg border border-gray-100 z-50 py-1">
                  <div className="px-3 py-2 border-b border-gray-100">
                    <p className="text-xs font-medium text-gray-800 truncate">
                      {user.user_metadata?.full_name || user.email}
                    </p>
                    <p className="text-[11px] text-gray-400 truncate">{user.email}</p>
                  </div>
                  <button
                    onClick={() => { setDropdownOpen(false); signOut() }}
                    className="w-full text-left px-3 py-2 text-sm text-gray-600 hover:bg-gray-50 transition-colors"
                  >
                    Sign out
                  </button>
                </div>
              )}
            </div>
          ) : (
            <button
              onClick={() => signInWithGoogle()}
              className="flex items-center gap-2 border border-gray-200 hover:border-gray-300 bg-white text-gray-700 text-xs px-3 py-1.5 rounded font-medium transition-colors"
            >
              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24">
                <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
                <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z"/>
                <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
              </svg>
              Sign in
            </button>
          )}
        </div>
      </div>
    </nav>
  )
}
