import { createClient } from '@supabase/supabase-js'

const SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL
const SUPABASE_ANON_KEY = import.meta.env.VITE_SUPABASE_ANON_KEY

// Visible in DevTools console — tells you immediately if env vars are missing
if (!SUPABASE_URL || !SUPABASE_ANON_KEY) {
  console.error('❌ SUPABASE: Missing VITE_SUPABASE_URL or VITE_SUPABASE_ANON_KEY — auth will not work. Check Railway Variables.')
} else {
  console.log('✅ SUPABASE: env vars loaded, project =', SUPABASE_URL)
}

export const supabase = createClient(
  SUPABASE_URL || 'https://placeholder.supabase.co',
  SUPABASE_ANON_KEY || 'placeholder',
  {
    auth: {
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: false, // we handle it manually below
      flowType: 'implicit',
    },
  }
)

// Manually extract tokens from URL hash after OAuth redirect.
// Supabase's built-in detectSessionInUrl calls /auth/v1/user to validate,
// which fails if the anon key is wrong. setSession() skips that call and
// decodes the JWT locally instead — works as long as the token itself is valid.
if (typeof window !== 'undefined' && window.location.hash.includes('access_token')) {
  const params = new URLSearchParams(window.location.hash.substring(1))
  const access_token = params.get('access_token')
  const refresh_token = params.get('refresh_token')
  if (access_token && refresh_token) {
    supabase.auth.setSession({ access_token, refresh_token }).then(({ error }) => {
      if (!error) window.history.replaceState(null, '', window.location.pathname)
      else console.error('[Auth] setSession failed:', error.message)
    })
  }
}

export async function signInWithGoogle() {
  return supabase.auth.signInWithOAuth({
    provider: 'google',
    options: { redirectTo: window.location.origin },
  })
}

export async function signOut() {
  return supabase.auth.signOut()
}

export function getSession() {
  return supabase.auth.getSession()
}
