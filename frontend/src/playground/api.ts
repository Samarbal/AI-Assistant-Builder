import type { AuthStore } from '../auth/store'
import type { Assistant } from '../assistants/api'

export type Citation = { file_id: string; chunk_id: string; filename: string; excerpt: string }
export type PlaygroundAnswer = { answer: string; outcome: 'grounded' | 'fallback'; citations: Citation[] }

export class PlaygroundError extends Error {}

const messages: Record<string, string> = {
  assistant_not_found: 'Assistant not found.',
  knowledge_not_ready: 'Your assistant knowledge is still being prepared. Try again shortly.',
  draft_changed: 'The assistant changed while this answer was being prepared. Please try again.',
  rag_invalid_request: 'Enter a question of up to 4,000 characters.',
  playground_unavailable: 'The Playground is temporarily unavailable. Try again shortly.',
  embedding_configuration: 'The Playground is not fully configured yet.',
  embedding_auth: 'The knowledge search service could not authenticate. Contact the project administrator.',
  embedding_quota_or_rate_limited: 'The knowledge search service is busy. Wait a moment and try again.',
  embedding_timeout: 'Knowledge search took too long. Please try again.',
  generation_auth: 'The answer service could not authenticate. Contact the project administrator.',
  generation_rate_limited: 'The answer service is busy. Wait a moment and try again.',
  generation_timeout: 'Generating an answer took too long. Please try again.',
  generation_invalid_output: 'The answer could not be safely validated. Please try again.',
  generation_output_invalid_json: 'The answer could not be safely validated. Please try again.',
  generation_output_invalid_envelope: 'The answer could not be safely validated. Please try again.',
  generation_output_invalid_usage: 'The answer could not be safely validated. Please try again.',
  generation_output_incomplete: 'The answer was incomplete. Please try again.',
  generation_output_refused: 'The answer service could not complete this request. Please try again.',
  generation_output_invalid_schema: 'The answer could not be safely validated. Please try again.',
  generation_output_invalid_citation: 'The answer citations could not be verified. Please try again.',
  generation_output_too_large: 'The answer service returned too much data. Please try again.',
}

export function playgroundApi(store: AuthStore, assistantId: string, signal: AbortSignal) {
  const { session, epoch } = store.snapshot()
  const owner = session?.user.id
  const current = () => !!owner && store.snapshot().session?.user.id === owner &&
    store.snapshot().epoch === epoch && !signal.aborted
  const check = () => { if (!current()) throw new PlaygroundError('Session changed. Please sign in again.') }

  async function request<T>(path: string, body?: unknown): Promise<T> {
    check()
    const token = await store.accessToken(owner!, epoch)
    check()
    const response = await fetch(`/api/assistants/${encodeURIComponent(assistantId)}${path}`, {
      method: body ? 'POST' : 'GET', cache: 'no-store',
      signal: AbortSignal.any([signal, AbortSignal.timeout(60000)]),
      headers: { Authorization: `Bearer ${token}`, ...(body ? { 'Content-Type': 'application/json' } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    })
    check()
    if (response.status === 401) {
      void store.logout()
      throw new PlaygroundError('Your session expired. Please sign in again.')
    }
    if (!response.ok) {
      let code = ''
      try {
        const payload = await response.json() as { detail?: { code?: unknown } }
        if (typeof payload.detail?.code === 'string') code = payload.detail.code
      } catch { /* Ignore untrusted or empty error bodies. */ }
      check()
      throw new PlaygroundError(messages[code] ?? (response.status === 404
        ? 'Assistant not found.' : 'The Playground could not complete this request. Try again shortly.'))
    }
    const data = await response.json() as T
    check()
    return data
  }

  return {
    assistant: () => request<Assistant>(''),
    send: (message: string) => request<PlaygroundAnswer>(`/playground/messages`, { message }),
  }
}
