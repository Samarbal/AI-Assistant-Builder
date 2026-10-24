import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { WidgetPage } from '../src/widget/WidgetPage'
afterEach(() => vi.unstubAllGlobals())

describe('public widget iframe UI', () => {
  it('keeps the demo code in memory, obtains a visitor capability and sends only public headers', async () => {
    const fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const path = String(input)
      if (path.endsWith('/conversations') && init?.method === 'POST') return new Response(JSON.stringify({ conversation_id: 'conversation-id', conversation_token: 'visitor-capability' }), { status: 201 })
      if (path.endsWith('/messages')) return new Response(JSON.stringify({ message_id: 'message-id', answer: 'Your configured fallback.', outcome: 'fallback', version: 1 }))
      return new Response(JSON.stringify({ name: 'Support', colors: { primary: '#635bff' }, version: 1 }))
    })
    vi.stubGlobal('fetch', fetch)
    vi.stubGlobal('crypto', { randomUUID: () => 'request-id' })
    sessionStorage.clear(); localStorage.clear()
    render(<MemoryRouter initialEntries={['/widget?public_id=public-id']}><WidgetPage /></MemoryRouter>)
    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Demo access code'), 'test-demo-code')
    await user.click(screen.getByRole('button', { name: 'Start chat' }))
    await screen.findByText('Support', { selector: 'strong' })
    await user.type(screen.getByRole('textbox', { name: 'Message Support' }), 'Question')
    await user.click(screen.getByRole('button', { name: 'Send message' }))
    expect(await screen.findByText('Your configured fallback.')).toBeInTheDocument()
    expect(fetch).toHaveBeenCalledTimes(3)
    const [, profile] = fetch.mock.calls[0] as unknown as [string, RequestInit]
    const [, create] = fetch.mock.calls[1] as unknown as [string, RequestInit]
    const [, send] = fetch.mock.calls[2] as unknown as [string, RequestInit]
    expect(profile.headers).toEqual({ 'X-Demo-Access': 'test-demo-code' })
    expect(create.headers).toMatchObject({ 'X-Demo-Access': 'test-demo-code', 'Content-Type': 'application/json' })
    expect(send.headers).toMatchObject({ 'X-Demo-Access': 'test-demo-code', 'X-Visitor-Token': 'visitor-capability' })
    expect(JSON.parse(send.body as string)).toEqual({ message: 'Question', request_id: 'request-id' })
    expect(sessionStorage.length + localStorage.length).toBe(0)
  })

  it('shows a disabled-chat state without leaking API details', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: { code: 'public_chat_disabled', message: 'internal' } }), { status: 503 })))
    render(<MemoryRouter initialEntries={['/widget?public_id=public-id']}><WidgetPage /></MemoryRouter>)
    await userEvent.type(screen.getByLabelText('Demo access code'), 'bad-demo-code')
    await userEvent.click(screen.getByRole('button', { name: 'Start chat' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('temporarily unavailable')
    expect(screen.getByRole('alert')).not.toHaveTextContent('internal')
  })

  it('sends close messages only to the embedding origin', () => {
    const postMessage = vi.fn()
    Object.defineProperty(window, 'parent', { configurable: true, value: { postMessage } })
    Object.defineProperty(document, 'referrer', { configurable: true, value: 'https://embed.example.test/page' })
    render(<MemoryRouter initialEntries={['/widget?public_id=public-id']}><WidgetPage /></MemoryRouter>)
    fireEvent.click(screen.getByRole('button', { name: 'Close chat' }))
    expect(postMessage).toHaveBeenCalledWith({ type: 'assistant-widget-close' }, 'https://embed.example.test')
  })
})
