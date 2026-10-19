import type { AuthStore } from '../auth/store'

export type Configuration = { name: string; role: string; response_style: string; tone: string; fallback_message: string; colors: Record<string, string> }
export type Assistant = Configuration & { id: string; state: string; created_at: string; updated_at: string }
export function assistantApi(store: AuthStore, signal: AbortSignal) {
  const { session, epoch } = store.snapshot()
  const owner = session?.user.id
  const current = () => owner && store.snapshot().session?.user.id === owner && store.snapshot().epoch === epoch && !signal.aborted
  async function request<T>(path: string, method = 'GET', body?: Partial<Configuration>): Promise<T> {
    if (!owner || !current()) throw new Error('Session changed. Please sign in again.')
    const token = await store.accessToken(owner, epoch)
    if (!current()) throw new Error('Session changed. Please sign in again.')
    const response = await fetch(`/api/assistants${path}`, { method, signal: AbortSignal.any([signal, AbortSignal.timeout(20000)]), headers: { Authorization: `Bearer ${token}`, ...(body ? { 'Content-Type': 'application/json' } : {}) }, body: body ? JSON.stringify(body) : undefined })
    if (!current()) throw new Error('Session changed. Please sign in again.')
    if (response.status === 401) { void store.logout(); throw new Error('Please sign in again.') }
    if (!response.ok) throw new Error(response.status === 404 ? 'Assistant not found.' : response.status === 422 ? 'Check the required fields and their lengths.' : 'Could not complete the request. Check your connection and try again. If saving, check the assistant list before retrying.')
    const data: T = await response.json()
    if (!current()) throw new Error('Session changed. Please sign in again.')
    return data
  }
  return { list: () => request<Assistant[]>(''), get: (id: string) => request<Assistant>(`/${encodeURIComponent(id)}`), create: (body: Configuration) => request<Assistant>('', 'POST', body), update: (id: string, body: Partial<Configuration>) => request<Assistant>(`/${encodeURIComponent(id)}`, 'PATCH', body) }
}
