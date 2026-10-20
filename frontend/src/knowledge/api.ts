import type { AuthStore } from '../auth/store'

export const MAX_FILE_BYTES = 10_000_000
export const MAX_FILES = 5
export type KnowledgeFile = {
  id: string; assistant_id: string; original_filename: string; file_format: string
  size_bytes: number; processing_state: string; error_code: string | null; created_at: string
}
export type DownloadLink = { download_url: string; expires_in: number }
export class KnowledgeError extends Error {}

export function validateFile(file: File): string | null {
  if (!/\.(pdf|docx)$/i.test(file.name) || file.name.length > 255) return 'Choose a PDF or DOCX file with a filename of at most 255 characters.'
  if (file.size === 0 || file.size > MAX_FILE_BYTES) return 'Choose a non-empty file no larger than 10 MB (10,000,000 bytes).'
  return null
}
export function knowledgeError(error: unknown): string {
  return error instanceof KnowledgeError ? error.message : 'Connection interrupted or timed out. Refresh the file list before retrying; the operation may have completed.'
}

// Same verified-session/epoch boundary as assistantApi; multipart must retain its browser boundary.
export function knowledgeApi(store: AuthStore, assistantId: string, signal: AbortSignal) {
  const { session, epoch } = store.snapshot()
  const owner = session?.user.id
  const current = () => owner && store.snapshot().session?.user.id === owner && store.snapshot().epoch === epoch && !signal.aborted
  const check = () => { if (!current()) throw new KnowledgeError('Session changed. Please sign in again.') }
  async function request<T>(suffix: string, method = 'GET', body?: FormData): Promise<T> {
    check()
    const token = await store.accessToken(owner!, epoch)
    check()
    const response = await fetch(`/api/assistants/${encodeURIComponent(assistantId)}/knowledge-files${suffix}`, {
      method, body, cache: 'no-store', signal: AbortSignal.any([signal, AbortSignal.timeout(body ? 120000 : 20000)]),
      headers: { Authorization: `Bearer ${token}` },
    })
    check()
    if (response.status === 401) { void store.logout(); throw new KnowledgeError('Your session expired. Please sign in again.') }
    if (!response.ok) {
      const messages: Record<number, string> = {
        400: 'The upload could not be read. Choose one PDF or DOCX file and try again.',
        403: 'You do not have access to this assistant or file.',
        404: 'Assistant or file not found. It may have been removed or belong to another account.',
        409: method === 'POST' && body ? 'The five-file limit was reached or the file operation changed. Refresh the list and remove an attachment before retrying.' : 'The file is not available for this operation. Refresh its status.',
        413: 'File too large. Choose a non-empty file no larger than 10 MB (10,000,000 bytes).',
        422: 'The document could not be accepted. Use a readable, unencrypted PDF or DOCX. Remove any failed attachment before uploading again.',
        503: 'The service is unavailable. Refresh the list before retrying; a failed or pending attachment may remain.',
      }
      throw new KnowledgeError(messages[response.status] ?? 'The request failed. Refresh the file list before retrying.')
    }
    const data = response.status === 204 ? undefined : await response.json()
    check()
    return data as T
  }
  return {
    list: () => request<KnowledgeFile[]>(''),
    upload: (file: File) => { const body = new FormData(); body.append('file', file); return request<KnowledgeFile>('', 'POST', body) },
    remove: (id: string) => request<void>(`/${encodeURIComponent(id)}`, 'DELETE'),
    download: (id: string) => request<DownloadLink>(`/${encodeURIComponent(id)}/download-url`, 'POST'),
  }
}
