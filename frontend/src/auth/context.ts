import { createContext, useContext, useSyncExternalStore } from 'react'
import type { AuthStore } from './store'
export const AuthContext = createContext<AuthStore | null>(null)
export function useAuth() {
  const store = useContext(AuthContext)
  if (!store) throw new Error('AuthProvider is required')
  const state = useSyncExternalStore(store.subscribe, store.snapshot)
  return { ...state, store, authenticate: store.authenticate, logout: store.logout }
}
