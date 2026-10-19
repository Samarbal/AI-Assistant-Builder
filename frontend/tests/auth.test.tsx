import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { useState } from 'react'
import { AuthStore } from '../src/auth/store'
import { AuthProvider, RequireOwner } from '../src/auth/AuthProvider'
import { AppRoutes } from '../src/app/routes'
import { authPort, session } from './auth-fixtures'
import { publicAuthConfig } from '../src/auth/config'
import { authError } from '../src/auth/errors'

afterEach(() => vi.useRealTimers())
describe('session boundary', () => {
  it('ignores stale bootstrap after owner event', async () => {
    const fake = authPort()
    let resolve!: (value: ReturnType<typeof session>) => void
    fake.port.session = () => new Promise(r => { resolve = r })
    const store = new AuthStore(fake.port); const stop = store.start()
    fake.emit(session('b')); resolve(session('a')); await Promise.resolve()
    expect(store.snapshot().session?.user.id).toBe('b'); stop()
  })
  it('clears owner immediately and ignores late refresh after failed logout', async () => {
    const fake = authPort(session()); const store = new AuthStore(fake.port); const stop = store.start()
    await Promise.resolve()
    fake.port.logout = vi.fn(async () => { throw new Error('private provider detail') })
    const pending = store.logout()
    expect(store.snapshot().session).toBeNull()
    fake.emit(session()); await pending
    expect(store.snapshot().session).toBeNull()
    expect(store.snapshot().error).toContain('revocation could not be confirmed')
    expect(store.snapshot().error).not.toContain('private provider'); stop()
  })
  it('expires a session and accepts a later valid refreshed session', async () => {
    vi.useFakeTimers()
    const value = session(); value.expires_at = Math.floor(Date.now() / 1000) + 1
    const fake = authPort(value); const store = new AuthStore(fake.port); const stop = store.start()
    await Promise.resolve(); vi.advanceTimersByTime(1100)
    expect(store.snapshot().session).toBeNull()
    fake.emit(session()); expect(store.snapshot().session).not.toBeNull(); stop()
  })
  it('shows loading until restoration and fails closed after timeout', async () => {
    vi.useFakeTimers()
    const fake = authPort(); fake.port.session = () => new Promise(() => {})
    const store = new AuthStore(fake.port); const stop = store.start()
    expect(store.snapshot().status).toBe('loading')
    vi.advanceTimersByTime(15000)
    expect(store.snapshot().session).toBeNull(); expect(store.snapshot().error).toContain('restore'); stop()
  })
  it('does not accept an already expired session', async () => {
    const value = session(); value.expires_at = 1
    const store = new AuthStore(authPort(value).port); const stop = store.start()
    await Promise.resolve(); expect(store.snapshot().session).toBeNull(); stop()
  })
  it('accepts auto-confirmed registration and prevents duplicate submissions', async () => {
    const fake = authPort(); let finish!: (value: ReturnType<typeof session>) => void
    fake.port.register = vi.fn(() => new Promise<ReturnType<typeof session>>(resolve => { finish = resolve }))
    const store = new AuthStore(fake.port)
    const request = store.authenticate('register', 'a@example.test', 'test-password')
    await store.authenticate('register', 'a@example.test', 'test-password')
    expect(fake.port.register).toHaveBeenCalledOnce()
    finish(session()); expect(await request).toEqual({ ok: true, confirmation: false })
    expect(store.snapshot().session?.user.id).toBe('owner-a')
    await store.logout()
  })
  it('unmounts owner-local state on switch and sign-out', async () => {
    const fake = authPort(session('a')); const store = new AuthStore(fake.port)
    function Owner() { const [text, setText] = useState(''); return <input aria-label="Draft" value={text} onChange={e => setText(e.target.value)} /> }
    render(<AuthProvider store={store}><MemoryRouter initialEntries={['/assistants']}><Routes><Route element={<RequireOwner />}><Route path="assistants" element={<Owner />} /></Route><Route path="login" element={<p>Sign in</p>} /></Routes></MemoryRouter></AuthProvider>)
    await userEvent.type(await screen.findByLabelText('Draft'), 'owner a private input')
    act(() => fake.emit(session('b')))
    expect(screen.getByLabelText('Draft')).toHaveValue('')
    act(() => fake.emit(null)); expect(screen.queryByLabelText('Draft')).not.toBeInTheDocument()
  })
})
describe('auth screens', () => {
  function setup(path = '/login') {
    const fake = authPort(); const store = new AuthStore(fake.port)
    render(<AuthProvider store={store}><MemoryRouter initialEntries={[path]}><AppRoutes /></MemoryRouter></AuthProvider>)
    return fake
  }
  it('redirects unauthenticated owner routes to login without showing owner content', async () => {
    setup('/assistants/example/knowledge')
    expect(await screen.findByRole('heading', { name: 'Welcome back' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Knowledge files' })).not.toBeInTheDocument()
  })
  it('validates fields without sending credentials and toggles password visibility', async () => {
    const fake = setup(); await screen.findByLabelText('Work email')
    await userEvent.click(screen.getByRole('button', { name: 'Log in' }))
    expect(fake.port.login).not.toHaveBeenCalled()
    expect(screen.getByLabelText('Password')).toBeInvalid()
    await userEvent.click(screen.getByRole('button', { name: 'Show password' }))
    expect(screen.getByLabelText('Password')).toHaveAttribute('type', 'text')
  })
  it('handles registration without session without falsely signing in', async () => {
    const fake = setup('/register')
    await userEvent.type(await screen.findByLabelText('Work email'), 'test@example.test')
    await userEvent.type(screen.getByLabelText('Password'), 'test-only-password')
    await userEvent.click(screen.getByRole('button', { name: 'Create account' }))
    expect(await screen.findByText(/No signed-in session was created/)).toBeInTheDocument()
    expect(fake.port.register).toHaveBeenCalledOnce()
    expect(screen.queryByLabelText('Password')).not.toBeInTheDocument()
  })
  it('logs in, then logs out and protects back navigation', async () => {
    setup()
    await userEvent.type(await screen.findByLabelText('Work email'), 'test@example.test')
    await userEvent.type(screen.getByLabelText('Password'), 'test-only-password')
    await userEvent.click(screen.getByRole('button', { name: 'Log in' }))
    expect(await screen.findByRole('heading', { name: 'Your assistants' })).toBeInTheDocument()
    await userEvent.click(screen.getAllByRole('button', { name: 'Log out' })[0])
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Welcome back' })).toBeInTheDocument())
  })
})
describe('safe configuration and errors', () => {
  it('rejects privileged keys and non-HTTPS URLs without echoing values', () => {
    expect(() => publicAuthConfig({ VITE_SUPABASE_URL: 'https://auth.example.test', VITE_SUPABASE_PUBLISHABLE_KEY: 'sb_secret_test-only' })).toThrow('Invalid public')
    expect(() => publicAuthConfig({ VITE_SUPABASE_URL: 'http://auth.example.test', VITE_SUPABASE_PUBLISHABLE_KEY: 'sb_publishable_test' })).toThrow('Invalid public')
    expect(publicAuthConfig({})).toBeNull()
  })
  it.each(['invalid_credentials', 'email_not_confirmed', 'weak_password', 'signup_disabled', 'email_exists', 'over_request_rate_limit'])('classifies %s without raw details', code => {
    expect(authError({ code, message: 'private-secret-value' })).not.toContain('private-secret-value')
    expect(authError({ code })).not.toBe(authError(null))
  })
})
