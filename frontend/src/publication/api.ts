import type { AuthStore } from '../auth/store'

export type PublicationStatus = {
  published: boolean; public_id: string | null; version: number | null; published_at: string | null
  draft_fingerprint: string; has_changes: boolean
  readiness: 'ready' | 'fallback_only' | 'needs_preparation' | 'processing' | 'failed'
}
export type PublishedResult = { public_id: string; version: number; published_at: string; draft_fingerprint: string; replayed: boolean }
export type EmbedResult = { public_id: string; snippet: string }

export function publicationApi(store: AuthStore, assistantId: string, signal: AbortSignal) {
  const { session, epoch } = store.snapshot()
  const owner = session?.user.id
  const current = () => !!owner && store.snapshot().session?.user.id === owner && store.snapshot().epoch === epoch && !signal.aborted
  async function request<T>(path: string, method = 'GET', body?: object): Promise<T> {
    if (!current()) throw new Error('Session changed. Please sign in again.')
    const token = await store.accessToken(owner!, epoch)
    if (!current()) throw new Error('Session changed. Please sign in again.')
    const response = await fetch(`/api/assistants/${encodeURIComponent(assistantId)}${path}`, {
      method, cache: 'no-store', signal: AbortSignal.any([signal, AbortSignal.timeout(20000)]),
      headers: { Authorization: `Bearer ${token}`, ...(body ? { 'Content-Type': 'application/json' } : {}), ...(method === 'POST' ? { 'Idempotency-Key': crypto.randomUUID() } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    })
    if (!current()) throw new Error('Session changed. Please sign in again.')
    if (response.status === 401) { void store.logout(); throw new Error('Your session expired. Please sign in again.') }
    if (!response.ok) {
      let code = ''
      try { const payload = await response.json() as { detail?: { code?: string } }; code = payload.detail?.code ?? '' } catch { /* response body is not trusted */ }
      const errors: Record<string, string> = {
        draft_changed: 'The draft changed while you were publishing. Refresh status and review it before publishing again.',
        publication_changed: 'Another publish completed first. Refresh publication status.',
        knowledge_not_ready: 'Finish or remove processing/failed files and prepare all attached knowledge before publishing.',
        idempotency_conflict: 'This publish request conflicted. Refresh publication status before retrying.',
        not_published: 'Publish this assistant before requesting an embed snippet.',
      }
      throw new Error(errors[code] ?? (response.status === 404 ? 'Assistant not found.' : 'Publication is unavailable. Refresh status before retrying.'))
    }
    const data = await response.json() as T
    if (!current()) throw new Error('Session changed. Please sign in again.')
    return data
  }
  return {
    status: () => request<PublicationStatus>('/publication'),
    publish: (status: PublicationStatus) => request<PublishedResult>('/publication', 'POST', {
      expected_draft_fingerprint: status.draft_fingerprint,
      expected_published_version: status.version,
    }),
    embed: () => request<EmbedResult>('/embed'),
  }
}
