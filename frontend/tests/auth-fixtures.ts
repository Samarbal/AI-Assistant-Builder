import { vi } from 'vitest'
import type { Session, AuthChangeEvent } from '@supabase/supabase-js'
import type { AuthPort } from '../src/auth/store'
export function session(id = 'owner-a'): Session {
  return { access_token: `test-token-${id}`, refresh_token: 'test-refresh', expires_in: 3600,
    expires_at: Math.floor(Date.now() / 1000) + 3600, token_type: 'bearer',
    user: { id, aud: 'authenticated', role: 'authenticated', email: `${id}@example.test`, app_metadata: {}, user_metadata: {}, created_at: '' } }
}
export function authPort(initial: Session | null = null) {
  let callback: ((event: AuthChangeEvent, session: Session | null) => void) | undefined
  const port: AuthPort = {
    subscribe: fn => { callback = fn; return () => { callback = undefined } },
    session: vi.fn(async () => initial), login: vi.fn(async () => session()),
    register: vi.fn(async () => null), logout: vi.fn(async () => {}),
  }
  return { port, emit: (value: Session | null) => callback?.(value ? 'SIGNED_IN' : 'SIGNED_OUT', value) }
}
