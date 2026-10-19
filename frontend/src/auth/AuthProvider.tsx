import { useEffect, type ReactNode } from 'react'
import { Navigate, Outlet } from 'react-router'
import { Alert, LoadingState } from '../components/ui'
import { AuthStore } from './store'
import { AuthContext, useAuth } from './context'

export function AuthProvider({ store, children }: { store: AuthStore; children: ReactNode }) {
  useEffect(() => store.start(), [store])
  return <AuthContext.Provider value={store}>{children}</AuthContext.Provider>
}
export function RequireOwner() {
  const auth = useAuth()
  if (auth.status === 'loading') return <LoadingState label="Restoring your session…" />
  if (auth.status === 'unconfigured') return <AuthUnavailable />
  if (!auth.session) return <Navigate to="/login" replace />
  // Changing user or signing out destroys all descendant component state.
  return <Outlet key={`${auth.session.user.id}:${auth.epoch}`} />
}
export function AuthUnavailable() {
  const auth = useAuth()
  return <Alert kind="error">{auth.error ?? 'Authentication is not configured. Set the public Supabase URL and publishable key in frontend/.env.local, then restart Vite.'}</Alert>
}
