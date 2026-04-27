import React, { useState, useRef, useEffect } from 'react'
import { signInWithGoogle, signOut } from '../lib/supabase'

const TABS = [
  { id: 'watchlist', label: 'Watchlist' },
  { id: 'map', label: 'Company Map' },
  { id: 'table', label: 'Company Table' },
  { id: 'network', label: 'Partnership Network' },
  { id: 'ai-research', label: 'AI Research' },
]

export default function Navbar({ activeTab, setActiveTab, watchlistBreaking = 0, onOpenDataImport = () => {}, user = null }) {
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

        {/* Right side: Data Import + auth */}
        <div className="flex items-center gap-3 min-w-fit">
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
