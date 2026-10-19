import { createClient } from '@supabase/supabase-js'
import type { AuthPort } from './store'
import { publicAuthConfig } from './config'

export function createAuthPort(env: Record<string, unknown>, storage: Storage): AuthPort | null {
  const config = publicAuthConfig(env)
  if (!config) return null
  const storageKey = `assistant-builder-${new URL(config.url).hostname}-auth`
  const blockedKey = `${storageKey}-signed-out`
  let blocked = storage.getItem(blockedKey) === '1'
  const clear = () => { for (const suffix of ['', '-code-verifier', '-user']) storage.removeItem(storageKey + suffix) }
  if (blocked) clear()
  const client = createClient(config.url, config.key, {
    global: { fetch: (input, init) => fetch(input, { ...init, signal: init?.signal
      ? AbortSignal.any([init.signal, AbortSignal.timeout(20000)]) : AbortSignal.timeout(20000) }) },
    auth: {
    storageKey, persistSession: true, autoRefreshToken: true, detectSessionInUrl: false,
    storage: {
      getItem: key => storage.getItem(key),
      setItem: (key, value) => { if (!blocked) storage.setItem(key, value) },
      removeItem: key => storage.removeItem(key),
    },
  } })
  async function authenticate(mode: 'login' | 'register', email: string, password: string) {
    clear()
    blocked = false
    storage.removeItem(blockedKey)
    const { data, error } = mode === 'login'
      ? await client.auth.signInWithPassword({ email, password })
      : await client.auth.signUp({ email, password })
    if (error) throw error
    return data.session
  }
  return {
    subscribe: callback => { const { data } = client.auth.onAuthStateChange(callback); return () => data.subscription.unsubscribe() },
    session: async () => { const { data, error } = await client.auth.getSession(); if (error) throw error; return data.session },
    login: (email, password) => authenticate('login', email, password),
    register: (email, password) => authenticate('register', email, password),
    logout: async () => {
      blocked = true
      storage.setItem(blockedKey, '1')
      try {
        const { error } = await client.auth.signOut({ scope: 'local' })
        if (error) throw error
      } finally { clear() }
    },
  }
}
