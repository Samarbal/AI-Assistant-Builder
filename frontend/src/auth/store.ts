import type { AuthChangeEvent, Session } from '@supabase/supabase-js'
import { authError } from './errors'

export interface AuthPort {
  subscribe(callback: (event: AuthChangeEvent, session: Session | null) => void): () => void
  session(): Promise<Session | null>
  login(email: string, password: string): Promise<Session | null>
  register(email: string, password: string): Promise<Session | null>
  logout(): Promise<void>
}
type Snapshot = { session: Session | null; status: 'loading' | 'ready' | 'unconfigured'; error: string | null; busy: boolean; epoch: number }
export class AuthStore {
  private state: Snapshot
  private listeners = new Set<() => void>()
  private revision = 0
  private accepting = true
  private expiry?: ReturnType<typeof setTimeout>
  private port: AuthPort | null
  constructor(port: AuthPort | null, configurationError: string | null = null) {
    this.port = port
    this.state = { session: null, status: port ? 'loading' : 'unconfigured', error: configurationError, busy: false, epoch: 0 }
  }
  snapshot = () => this.state
  accessToken = async (owner: string, epoch: number) => {
    const session = await this.port?.session()
    if (!session || session.user.id !== owner || this.state.session?.user.id !== owner || this.state.epoch !== epoch || !session.expires_at || session.expires_at * 1000 <= Date.now()) throw new Error('Session changed. Please sign in again.')
    return session.access_token
  }
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener) } }
  private update(patch: Partial<Snapshot>) { this.state = { ...this.state, ...patch }; this.listeners.forEach(listener => listener()) }
  private accept(session: Session | null) {
    clearTimeout(this.expiry)
    if (session && (!session.expires_at || session.expires_at * 1000 <= Date.now())) session = null
    const changed = this.state.session?.user.id !== session?.user.id
    this.update({ session, status: 'ready', epoch: this.state.epoch + (changed ? 1 : 0) })
    if (session?.expires_at) {
      this.expiry = setTimeout(() => {
        this.revision++
        this.accept(null)
        this.update({ error: 'Your session expired. Please sign in again.' })
      }, Math.min(session.expires_at * 1000 - Date.now(), 2147483647))
    }
  }
  start = () => {
    if (!this.port) return () => {}
    let active = true
    const timeout = setTimeout(() => {
      if (active && this.state.status === 'loading') {
        this.revision++
        this.accept(null)
        this.update({ error: 'Could not restore your session. Please sign in again.' })
      }
    }, 15000)
    const unsubscribe = this.port.subscribe((_event, session) => {
      if (!active || !this.accepting) return
      this.revision++
      this.accept(session)
    })
    const revision = this.revision
    void this.port.session().then(session => {
      if (active && this.accepting && revision === this.revision) this.accept(session)
    }).catch(() => {
      if (active && revision === this.revision) { this.accept(null); this.update({ error: 'Could not restore your session. Please sign in again.' }) }
    })
    return () => { active = false; unsubscribe(); clearTimeout(timeout); clearTimeout(this.expiry) }
  }
  authenticate = async (mode: 'login' | 'register', email: string, password: string) => {
    if (!this.port || this.state.busy) return { ok: false, confirmation: false }
    this.accepting = false
    this.revision++
    this.accept(null)
    this.update({ busy: true, error: null })
    try {
      const session = await this.port[mode](email, password)
      if (mode === 'login' && !session) throw new Error('Missing session')
      this.accept(session)
      this.accepting = true
      return { ok: true, confirmation: mode === 'register' && !session }
    } catch (error) { this.update({ error: authError(error) }); return { ok: false, confirmation: false } }
    finally { this.update({ busy: false }) }
  }
  logout = async () => {
    if (!this.port || this.state.busy) return
    this.accepting = false // Late refresh events must not restore the departing owner.
    this.revision++
    this.accept(null) // Unmount owner subtree before waiting for the network.
    this.update({ busy: true, error: null })
    try { await this.port.logout() }
    catch { this.update({ error: 'Signed out on this tab. Server session revocation could not be confirmed. Sign in again when connected.' }) }
    finally { this.update({ busy: false }) }
  }
}
