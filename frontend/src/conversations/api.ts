import type { AuthStore } from '../auth/store'

export type ConversationSummary = {
  conversation_id: string; created_at: string; last_activity_at: string | null
  latest_status: 'idle' | 'pending' | 'completed' | 'fallback' | 'failed' | 'uncertain' | 'version_changed'
  latest_outcome: 'grounded' | 'fallback' | null; latest_published_version: number | null
}
export type ConversationPage = { items: ConversationSummary[]; next_cursor: string | null; limit: number }
export type Turn = { user_message: string; user_created_at: string; assistant_message: string | null; assistant_created_at: string | null; status: 'pending' | 'completed' | 'fallback' | 'failed' | 'uncertain' | 'version_changed'; outcome: 'grounded' | 'fallback' | null; published_version: number }
export type ConversationDetail = { conversation_id: string; created_at: string; turns: Turn[]; next_cursor: string | null; limit: number }

export function conversationApi(store: AuthStore, assistantId: string, signal: AbortSignal) {
  const { session, epoch } = store.snapshot()
  const owner = session?.user.id
  const current = () => !!owner && store.snapshot().session?.user.id === owner && store.snapshot().epoch === epoch && !signal.aborted
  async function get<T>(path: string): Promise<T> {
    if (!current()) throw new Error('Session changed. Please sign in again.')
    const token = await store.accessToken(owner!, epoch)
    if (!current()) throw new Error('Session changed. Please sign in again.')
    const response = await fetch(`/api/assistants/${encodeURIComponent(assistantId)}/conversations${path}`, {
      cache: 'no-store', headers: { Authorization: `Bearer ${token}` },
      signal: AbortSignal.any([signal, AbortSignal.timeout(20000)]),
    })
    if (!current()) throw new Error('Session changed. Please sign in again.')
    if (response.status === 401) { void store.logout(); throw new Error('Your session expired. Please sign in again.') }
    if (!response.ok) throw new Error(response.status === 404 ? 'Conversation not found.' : response.status === 422 ? 'That history page expired. Go back to the conversation list.' : 'Conversation history is unavailable. Try again.')
    const data = await response.json() as T
    if (!current()) throw new Error('Session changed. Please sign in again.')
    return data
  }
  function page(path: string, cursor?: string) {
    const query = new URLSearchParams({ limit: '20' })
    if (cursor) query.set('cursor', cursor)
    return get<ConversationPage | ConversationDetail>(`${path}?${query}`)
  }
  return { list: (cursor?: string) => page('', cursor) as Promise<ConversationPage>, detail: (conversationId: string, cursor?: string) => page(`/${encodeURIComponent(conversationId)}`, cursor) as Promise<ConversationDetail> }
}
