import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { AuthStore } from '../src/auth/store'
import { AuthProvider } from '../src/auth/AuthProvider'
import { AppRoutes } from '../src/app/routes'
import { authPort, session } from './auth-fixtures'
afterEach(() => vi.unstubAllGlobals())

const state = { published: false, public_id: null, version: null, published_at: null, draft_fingerprint: 'a'.repeat(64), has_changes: true, readiness: 'fallback_only' }
const result = { public_id: 'public-opaque-id', version: 1, published_at: '2026-10-23T10:00:00Z', draft_fingerprint: 'a'.repeat(64), replayed: false }
function app(path: string) {
  const store = new AuthStore(authPort(session()).port)
  const stop = store.start()
  render(<AuthProvider store={store}><MemoryRouter initialEntries={[path]}><AppRoutes /></MemoryRouter></AuthProvider>)
  return stop
}

describe('P4-06 publishing UI', () => {
  it('publishes with server fingerprint and idempotency, then shows the safe embed snippet', async () => {
    let published = false
    const fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const path = String(input)
      if (path.endsWith('/publication') && init?.method === 'POST') { published = true; return new Response(JSON.stringify(result), { status: 201 }) }
      if (path.endsWith('/publication')) return new Response(JSON.stringify({ ...state, published, public_id: published ? result.public_id : null, version: published ? 1 : null, has_changes: !published }))
      return new Response(JSON.stringify({ public_id: 'public-opaque-id', snippet: '<script src="https://assets.test/widget.js" data-assistant-id="public-opaque-id"></script>' }))
    })
    vi.stubGlobal('fetch', fetch)
    const stop = app('/assistants/example/publish')
    try {
      const user = userEvent.setup()
      await user.click(await screen.findByRole('button', { name: 'Publish assistant' }))
      expect(await screen.findByRole('heading', { name: 'Website embed' })).toBeInTheDocument()
      const snippet = (screen.getByLabelText('Embed code') as HTMLTextAreaElement).value
      expect(snippet).toContain('public-opaque-id')
      expect(snippet).not.toContain('token')
      const [, init] = fetch.mock.calls[1] as unknown as [string, RequestInit]
      expect(init.headers).toMatchObject({ Authorization: 'Bearer test-token-owner-a', 'Idempotency-Key': expect.any(String) })
      expect(JSON.parse(init.body as string)).toEqual({ expected_draft_fingerprint: 'a'.repeat(64), expected_published_version: null })
    } finally { stop() }
  })

  it('explains publish conflicts without exposing backend internals', async () => {
    vi.stubGlobal('fetch', vi.fn(async (_input: string | URL | Request, init?: RequestInit) => init?.method === 'POST'
      ? new Response(JSON.stringify({ detail: { code: 'draft_changed', message: 'database details' } }), { status: 409 })
      : new Response(JSON.stringify(state))))
    const stop = app('/assistants/example/publish')
    try {
      await userEvent.click(await screen.findByRole('button', { name: 'Publish assistant' }))
      expect(await screen.findByRole('alert')).toHaveTextContent('draft changed')
      expect(screen.getByRole('alert')).not.toHaveTextContent('database details')
    } finally { stop() }
  })
})

describe('P4-06 conversation history UI', () => {
  it('lists safe summaries without exposing visitor capabilities', async () => {
    const fetch = vi.fn(async (input: string | URL | Request) => String(input).endsWith('/conversations?limit=20')
      ? new Response(JSON.stringify({ items: [{ conversation_id: 'conversation-1', created_at: '2026-10-23T10:00:00Z', last_activity_at: null, latest_status: 'pending', latest_outcome: null, latest_published_version: 2 }], next_cursor: null, limit: 20 }))
      : new Response(JSON.stringify({ conversation_id: 'conversation-1', created_at: '2026-10-23T10:00:00Z', turns: [
        { user_message: 'Question?', user_created_at: '2026-10-23T10:00:00Z', assistant_message: null, assistant_created_at: null, status: 'pending', outcome: null, published_version: 2 },
        { user_message: 'Another question', user_created_at: '2026-10-23T10:01:00Z', assistant_message: null, assistant_created_at: null, status: 'failed', outcome: null, published_version: 2 },
      ], next_cursor: null, limit: 20 })))
    vi.stubGlobal('fetch', fetch)
    const stop = app('/assistants/example/conversations')
    try {
      expect(await screen.findByRole('link', { name: /Conversation.*Waiting for response/ })).toHaveAttribute('href', '/assistants/example/conversations/conversation-1')
      expect(fetch).toHaveBeenCalledOnce()
      expect((fetch.mock.calls as unknown as [string, RequestInit][])[0][1].headers).toEqual({ Authorization: 'Bearer test-token-owner-a' })
    } finally { stop() }
  })

  it('displays safe pending and failed details', async () => {
    const fetch = vi.fn(async () => new Response(JSON.stringify({ conversation_id: 'conversation-1', created_at: '2026-10-23T10:00:00Z', turns: [
      { user_message: 'Question?', user_created_at: '2026-10-23T10:00:00Z', assistant_message: null, assistant_created_at: null, status: 'pending', outcome: null, published_version: 2 },
      { user_message: 'Another question', user_created_at: '2026-10-23T10:01:00Z', assistant_message: null, assistant_created_at: null, status: 'failed', outcome: null, published_version: 2 },
    ], next_cursor: null, limit: 20 })))
    vi.stubGlobal('fetch', fetch)
    const stop = app('/assistants/example/conversations/conversation-1')
    try {
      expect(await screen.findByRole('heading', { name: 'Conversation details' })).toBeInTheDocument()
      expect(fetch).toHaveBeenCalledOnce()
      expect(await screen.findByText(/This response is still pending/)).toBeInTheDocument()
      expect(screen.getByText(/The assistant response was not saved/)).toBeInTheDocument()
      expect(fetch).toHaveBeenCalledOnce()
    } finally { stop() }
  })
})
