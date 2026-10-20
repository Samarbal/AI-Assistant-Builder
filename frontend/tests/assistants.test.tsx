import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { AuthStore } from '../src/auth/store'
import { AuthProvider } from '../src/auth/AuthProvider'
import { AppRoutes } from '../src/app/routes'
import { assistantApi } from '../src/assistants/api'
import { authPort, session } from './auth-fixtures'
import { assistant } from './assistant-fixture'
afterEach(() => vi.unstubAllGlobals())
function app(path = '/assistants/example/configuration') {
  render(<AuthProvider store={new AuthStore(authPort(session()).port)}><MemoryRouter initialEntries={[path]}><AppRoutes /></MemoryRouter></AuthProvider>)
}
describe('UI-04 assistant integration', () => {
  it('signs out on unauthorized response without replaying a write', async () => {
    const auth = authPort(session()); const store = new AuthStore(auth.port); const stop = store.start()
    await waitFor(() => expect(store.snapshot().session).not.toBeNull())
    const fetch = vi.fn(async () => new Response('', { status: 401 })); vi.stubGlobal('fetch', fetch)
    await expect(assistantApi(store, new AbortController().signal).update('example', { name: 'Changed' })).rejects.toThrow('sign in')
    expect(fetch).toHaveBeenCalledOnce(); expect(store.snapshot().session).toBeNull(); stop()
  })
  it('shows missing assistants safely and does not render an editable record', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 404 }))); app()
    expect(await screen.findByRole('alert')).toHaveTextContent('Assistant not found.')
    expect(screen.queryByLabelText('Assistant name')).not.toBeInTheDocument()
  })
  it('requires fields and uses the backend length limits', async () => {
    const fetch = vi.fn(); vi.stubGlobal('fetch', fetch); app('/assistants/new')
    expect(await screen.findByLabelText('Assistant name')).toHaveAttribute('maxlength', '120')
    expect(screen.getByLabelText('Role')).toHaveAttribute('maxlength', '500')
    expect(screen.getByLabelText('Tone of voice')).toHaveAttribute('maxlength', '100')
    await userEvent.click(screen.getByRole('button', { name: 'Create assistant' }))
    expect(fetch).not.toHaveBeenCalled()
  })
  it('lists independent assistants', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify([assistant, { ...assistant, id: 'second', name: 'Sales' }]))))
    app('/assistants')
    expect(await screen.findByRole('link', { name: 'Configure Sales' })).toHaveAttribute('href', '/assistants/second/configuration')
    expect(screen.getByRole('link', { name: 'Configure Support' })).toHaveAttribute('href', '/assistants/example/configuration')
  })
  it('patches only changes and preserves unfamiliar colors', async () => {
    const fetch = vi.fn(async () => new Response(JSON.stringify(assistant)))
    vi.stubGlobal('fetch', fetch); app()
    const name = await screen.findByLabelText('Assistant name')
    await userEvent.clear(name); await userEvent.type(name, 'Changed')
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    await screen.findByText('Draft saved.')
    const options = (fetch.mock.calls as unknown as [string, RequestInit][])[1][1]
    expect(JSON.parse(options.body as string)).toEqual({ name: 'Changed' })
    expect(screen.getByLabelText('Primary color')).toHaveValue('#635bff')
  })
  it('retains input after a failed save', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(assistant))).mockResolvedValue(new Response('', { status: 503 }))
    vi.stubGlobal('fetch', fetch); app()
    await userEvent.type(await screen.findByLabelText('Assistant name'), ' edited')
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not complete')
    expect(screen.getByLabelText('Assistant name')).toHaveValue('Support edited')
    expect(fetch).toHaveBeenCalledTimes(2)
  })
  it('rejects a delayed response after owner switches', async () => {
    const auth = authPort(session()); const store = new AuthStore(auth.port); const stop = store.start()
    await waitFor(() => expect(store.snapshot().session).not.toBeNull())
    let finish!: (value: Response) => void
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(resolve => { finish = resolve })))
    const result = assistantApi(store, new AbortController().signal).list()
    await waitFor(() => expect(finish).toBeDefined())
    auth.emit(session('owner-b')); finish(new Response('[]'))
    await expect(result).rejects.toThrow('Session changed'); stop()
  })
})
