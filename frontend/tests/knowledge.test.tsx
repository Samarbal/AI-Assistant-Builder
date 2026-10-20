import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from '../src/auth/AuthProvider'
import { AuthStore } from '../src/auth/store'
import { AppRoutes } from '../src/app/routes'
import { knowledgeApi, validateFile } from '../src/knowledge/api'
import { authPort, session } from './auth-fixtures'
import { knowledgeFile } from './knowledge-fixture'

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status })
function app() {
  const auth = authPort(session())
  const store = new AuthStore(auth.port)
  render(<AuthProvider store={store}><MemoryRouter initialEntries={['/assistants/example/knowledge']}><AppRoutes /></MemoryRouter></AuthProvider>)
  return { auth, store }
}
describe('knowledge UX', () => {
  it('shows states, metadata, and disables downloads until text is extracted', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json([knowledgeFile, { ...knowledgeFile, id: 'two', original_filename: 'Failed.docx', processing_state: 'failed', error_code: 'invalid_document' }, { ...knowledgeFile, id: 'three', original_filename: 'Pending.pdf', processing_state: 'processing' }])))
    app()
    expect(await screen.findByText('Text extracted')).toBeInTheDocument()
    expect(screen.getByText('3 of 5 files')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Download Failed.docx' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Download Pending.pdf' })).toBeDisabled()
    expect(screen.getByText(/Remove this attachment, then upload/)).toBeInTheDocument()
  })
  it('rejects unsupported, empty, oversized and long filenames, accepting exactly 10 MB', () => {
    expect(validateFile(new File(['x'], 'x.doc'))).toContain('PDF or DOCX')
    expect(validateFile(new File([], 'x.pdf'))).toContain('non-empty')
    const file = new File(['x'], 'x.PDF')
    Object.defineProperty(file, 'size', { value: 10_000_000, configurable: true })
    expect(validateFile(file)).toBeNull()
    Object.defineProperty(file, 'size', { value: 10_000_001 })
    expect(validateFile(file)).toContain('10 MB')
    expect(validateFile(new File(['x'], `${'x'.repeat(252)}.pdf`))).toContain('255')
  })
  it('blocks invalid selections before any upload and counts failed files in the limit', async () => {
    const fetch = vi.fn(async () => json(Array.from({ length: 5 }, (_, i) => ({ ...knowledgeFile, id: `${i}`, processing_state: 'failed' }))))
    vi.stubGlobal('fetch', fetch); app()
    await screen.findByText('5 of 5 files')
    expect(screen.getByRole('button', { name: 'Browse files' })).toBeDisabled()
    expect(fetch).toHaveBeenCalledOnce()
  })
  it('uploads only one multipart file and reconciles an extraction failure', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(json([])).mockResolvedValueOnce(json({ detail: 'unsafe raw detail' }, 422)).mockResolvedValueOnce(json([{ ...knowledgeFile, processing_state: 'failed', error_code: 'invalid_document' }]))
    vi.stubGlobal('fetch', fetch); app(); await screen.findByText(/No knowledge files yet/)
    await userEvent.upload(screen.getByLabelText('Choose knowledge file'), new File(['pdf'], 'Policies.pdf', { type: 'application/pdf' }))
    await userEvent.click(screen.getByRole('button', { name: 'Upload file' }))
    await screen.findByText('Needs attention')
    expect(screen.getByRole('alert')).toHaveTextContent('document could not be accepted')
    expect(screen.queryByText('unsafe raw detail')).not.toBeInTheDocument()
    const init = fetch.mock.calls[1][1] as RequestInit
    expect(init.body).toBeInstanceOf(FormData)
    expect(Array.from((init.body as FormData).keys())).toEqual(['file'])
    expect(init.headers).toEqual({ Authorization: 'Bearer test-token-owner-a' })
    expect(fetch).toHaveBeenCalledTimes(3)
  })
  it('requires confirmation, handles DELETE 204, and frees a slot for replacement', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(json([knowledgeFile])).mockResolvedValueOnce(new Response(null, { status: 204 })).mockResolvedValueOnce(json([]))
    vi.stubGlobal('fetch', fetch); app(); await screen.findByText('Text extracted')
    await userEvent.click(screen.getByRole('button', { name: 'Remove Policies.pdf' }))
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(fetch).toHaveBeenCalledOnce()
    await userEvent.click(screen.getByRole('button', { name: 'Remove Policies.pdf' }))
    await userEvent.click(screen.getByRole('button', { name: 'Confirm removal' }))
    await screen.findByText(/No knowledge files yet/)
    expect(fetch.mock.calls[1][1].method).toBe('DELETE')
    expect(screen.getByRole('button', { name: 'Browse files' })).toBeEnabled()
  })
  it('blocks operations if reconciliation fails after an uncertain upload', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(json([])).mockRejectedValue(new TypeError('network'))
    vi.stubGlobal('fetch', fetch); app(); await screen.findByText(/No knowledge files yet/)
    await userEvent.upload(screen.getByLabelText('Choose knowledge file'), new File(['x'], 'x.docx'))
    await userEvent.click(screen.getByRole('button', { name: 'Upload file' }))
    await screen.findByText('List not confirmed')
    expect(screen.getByRole('button', { name: 'Browse files' })).toBeDisabled()
    expect(screen.getByRole('alert')).toHaveTextContent('Refresh the list')
  })
  it('expires signed links locally and never persists them', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(json([knowledgeFile])).mockResolvedValueOnce(json({ download_url: 'https://files.example.test/private?token=test-only', expires_in: 1 })))
    app(); await screen.findByText('Text extracted')
    await userEvent.click(screen.getByRole('button', { name: 'Download Policies.pdf' }))
    const link = await screen.findByRole('link', { name: 'Open private download' })
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
    await waitFor(() => expect(screen.queryByRole('link', { name: 'Open private download' })).not.toBeInTheDocument(), { timeout: 2500 })
    expect(JSON.stringify(sessionStorage)).not.toContain('private?token')
  })
  it('rejects unsafe signed URL schemes', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(json([knowledgeFile])).mockResolvedValueOnce(json({ download_url: 'javascript:alert(1)', expires_in: 60 })))
    app(); await screen.findByText('Text extracted'); await userEvent.click(screen.getByRole('button', { name: 'Download Policies.pdf' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('safe download link')
    expect(screen.queryByRole('link', { name: 'Open private download' })).not.toBeInTheDocument()
  })
  it('clears owner data on 401 without replaying a mutation', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(json([knowledgeFile])).mockResolvedValueOnce(json({}, 401))
    vi.stubGlobal('fetch', fetch); app(); await screen.findByText('Text extracted')
    await userEvent.click(screen.getByRole('button', { name: 'Download Policies.pdf' }))
    await screen.findByRole('heading', { name: 'Welcome back' })
    expect(screen.queryByText('Policies.pdf')).not.toBeInTheDocument()
    expect(fetch).toHaveBeenCalledTimes(2)
  })
  it('discards old-owner responses when switching accounts', async () => {
    let complete!: (value: Response) => void
    const auth = authPort(session()); const store = new AuthStore(auth.port); const stop = store.start()
    await waitFor(() => expect(store.snapshot().session).not.toBeNull())
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(resolve => { complete = resolve })))
    const response = knowledgeApi(store, 'example', new AbortController().signal).list()
    await waitFor(() => expect(complete).toBeDefined())
    act(() => auth.emit(session('owner-b'))); complete(json([knowledgeFile]))
    await expect(response).rejects.toThrow('Session changed'); stop()
  })
  it.each([404, 409, 413, 503])('reports HTTP %s without exposing server details', async status => {
    vi.stubGlobal('fetch', vi.fn(async () => json({ detail: 'DO NOT DISPLAY' }, status)))
    app()
    expect(await screen.findByRole('alert')).not.toHaveTextContent('DO NOT DISPLAY')
    expect(screen.getByRole('button', { name: 'Browse files' })).toBeDisabled()
  })
})
