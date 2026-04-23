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
      detectSessionInUrl: true,
      // pkce is more reliable than implicit for SPAs — no hash-parsing race conditions
      flowType: 'pkce',
    },
  }
)

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
