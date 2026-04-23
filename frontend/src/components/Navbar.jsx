import React, { useState, useEffect, useRef } from 'react'
import { signOut, signInWithGoogle } from '../lib/supabase'

const TABS = [
  { id: 'map', label: 'Company Map' },
  { id: 'table', label: 'Company Table' },
  { id: 'watchlist', label: 'Watchlist' },
  { id: 'network', label: 'Partnership Network' },
]

export default function Navbar({ activeTab, setActiveTab, watchlistBreaking = 0, onOpenDataImport = () => {}, user = null }) {
  const [profileOpen, setProfileOpen] = useState(false)
  const profileRef = useRef(null)

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

        {/* Right side: Data Import + Profile */}
        <div className="flex items-center gap-2 min-w-fit">
          <button
            onClick={() => onOpenDataImport()}
            className="bg-bmw-blue hover:bg-[#3a88ee] text-white text-xs px-4 py-1.5 rounded font-medium transition-colors"
          >
            Data Import
          </button>

          {/* Profile avatar + dropdown */}
          <div className="relative" ref={profileRef}>
            <button
              onClick={() => setProfileOpen(v => !v)}
              className="flex items-center gap-2 pl-2 pr-1 py-1 rounded-full hover:bg-gray-100 transition-colors"
            >
              {user ? (
                avatarUrl ? (
                  <img src={avatarUrl} alt={displayName} className="w-7 h-7 rounded-full object-cover" />
                ) : (
                  <div className="w-7 h-7 rounded-full bg-bmw-blue flex items-center justify-center text-white text-xs font-bold">
                    {initials}
                  </div>
                )
              ) : (
                <div className="w-7 h-7 rounded-full bg-gray-200 flex items-center justify-center">
                  <svg className="w-4 h-4 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                  </svg>
                </div>
              )}
            </button>

            {profileOpen && (
              <div className="absolute right-0 top-full mt-1 w-56 bg-white border border-gray-200 rounded-xl shadow-lg z-[9999] py-1">
                {user ? (
                  <>
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
                  </>
                ) : (
                  <>
                    <div className="px-4 py-3 border-b border-gray-100">
                      <p className="text-sm font-semibold text-gray-800">Sign in</p>
                      <p className="text-xs text-gray-500">Access your personal watchlist</p>
                    </div>
                    <button
                      onClick={() => { setProfileOpen(false); signInWithGoogle() }}
                      className="w-full text-left px-4 py-2.5 text-sm text-gray-700 hover:bg-gray-50 flex items-center gap-3"
                    >
                      <svg className="w-4 h-4 shrink-0" viewBox="0 0 24 24">
                        <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
                        <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                        <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z"/>
                        <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
                      </svg>
                      Continue with Google
                    </button>
                  </>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </nav>
  )
}
