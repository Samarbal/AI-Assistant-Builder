import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { AuthProvider } from '../src/auth/AuthProvider'
import { AuthStore } from '../src/auth/store'
import { AppRoutes } from '../src/app/routes'
import { authPort, session } from './auth-fixtures'
import { assistant } from './assistant-fixture'

afterEach(() => vi.unstubAllGlobals())
const citation = { file_id: 'file-1', chunk_id: 'chunk-1', filename: 'Returns.pdf', excerpt: 'Returns are accepted within 14 days.' }
const reply = { answer: 'يمكنك إرجاع المنتج خلال 14 يومًا.', outcome: 'grounded', citations: [citation] }

function app(path = '/assistants/example/playground') {
  const store = new AuthStore(authPort(session()).port)
  const stop = store.start()
  render(<AuthProvider store={store}><MemoryRouter initialEntries={[path]}><AppRoutes /></MemoryRouter></AuthProvider>)
  return stop
}

describe('Playground screen', () => {
  it('sends one authenticated independent turn and renders server-validated citations', async () => {
    const fetch = vi.fn(async (input: string | URL | Request) => {
      const url = String(input)
      if (url.endsWith('/assistants/example')) return new Response(JSON.stringify(assistant))
      return new Response(JSON.stringify(reply))
    })
    vi.stubGlobal('fetch', fetch)
    const stop = app()
    const user = userEvent.setup()
    try {
      const textbox = await screen.findByRole('textbox', { name: 'Ask Support a question' })
      await user.type(textbox, 'ما سياسة الإرجاع؟')
      await user.click(screen.getByRole('button', { name: 'Send question' }))
      expect(await screen.findByText(reply.answer)).toBeInTheDocument()
      expect(screen.getByText('Returns.pdf')).toBeInTheDocument()
      expect(screen.getByText(citation.excerpt)).toBeInTheDocument()
      expect(screen.getByText(reply.answer)).toHaveAttribute('dir', 'auto')
      expect(fetch).toHaveBeenCalledTimes(2)
      const [url, init] = fetch.mock.calls[1] as unknown as [string, RequestInit]
      expect(url).toBe('/api/assistants/example/playground/messages')
      expect(init.method).toBe('POST')
      expect(init.headers).toEqual({ Authorization: 'Bearer test-token-owner-a', 'Content-Type': 'application/json' })
      expect(JSON.parse(init.body as string)).toEqual({ message: 'ما سياسة الإرجاع؟' })
      expect(screen.queryByText(/Page \d/)).not.toBeInTheDocument()
    } finally { stop() }
  })

  it('shows exact fallback as a distinct outcome without citations', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request) => String(input).endsWith('/assistants/example')
      ? new Response(JSON.stringify(assistant))
      : new Response(JSON.stringify({ answer: 'No answer in the knowledge.', outcome: 'fallback', citations: [] }))))
    const stop = app()
    try {
      const user = userEvent.setup()
      await user.type(await screen.findByRole('textbox'), 'Unsupported question')
      await user.keyboard('{Enter}')
      expect(await screen.findByText('No answer in the knowledge.')).toBeInTheDocument()
      expect(screen.getByText(/No relevant answer was found/)).toBeInTheDocument()
      expect(screen.queryByRole('list', { name: 'Answer sources' })).not.toBeInTheDocument()
    } finally { stop() }
  })

  it('maps readiness and provider errors to actionable copy without exposing server details', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request) => String(input).endsWith('/assistants/example')
      ? new Response(JSON.stringify(assistant))
      : new Response(JSON.stringify({ detail: { code: 'knowledge_not_ready', message: 'secret database detail' } }), { status: 409 })))
    const stop = app()
    try {
      const user = userEvent.setup()
      await user.type(await screen.findByRole('textbox'), 'Question')
      await user.click(screen.getByRole('button', { name: 'Send question' }))
      expect(await screen.findByRole('alert')).toHaveTextContent('still being prepared')
      expect(screen.getByRole('alert')).not.toHaveTextContent('secret database detail')
      expect(screen.getByRole('textbox')).toHaveValue('Question')
    } finally { stop() }
  })

  it('logs out on an expired session and removes the protected playground', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request) => String(input).endsWith('/assistants/example')
      ? new Response(JSON.stringify(assistant))
      : new Response('{}', { status: 401 })))
    const stop = app()
    try {
      const user = userEvent.setup()
      await user.type(await screen.findByRole('textbox'), 'Question')
      await user.click(screen.getByRole('button', { name: 'Send question' }))
      expect(await screen.findByRole('heading', { name: 'Welcome back' })).toBeInTheDocument()
      expect(screen.queryByText('Question')).not.toBeInTheDocument()
    } finally { stop() }
  })

  it('offers reset and handles empty assistant load errors', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 404 })))
    const stop = app()
    try {
      expect(await screen.findByRole('alert')).toHaveTextContent('Assistant not found')
      expect(screen.getByRole('link', { name: 'Back to configuration' })).toHaveAttribute('href', '/assistants/example/configuration')
    } finally { stop() }
  })
})
