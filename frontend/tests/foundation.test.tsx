import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { assistant } from './assistant-fixture'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { AppRoutes } from '../src/app/routes'
import { Alert, Button, LoadingState, TextField } from '../src/components/ui'
import { AuthProvider } from '../src/auth/AuthProvider'
import { AuthStore } from '../src/auth/store'
import { authPort, session } from './auth-fixtures'

function App({ path }: { path: string }) {
  return <AuthProvider store={new AuthStore(authPort(session()).port)}><MemoryRouter initialEntries={[path]}><AppRoutes /></MemoryRouter></AuthProvider>
}

describe('UI-02 shell routes', () => {
  beforeEach(() => vi.stubGlobal('fetch', vi.fn(async (url: string) => new Response(JSON.stringify(url.endsWith('/assistants') ? [] : assistant)))))
  afterEach(() => vi.unstubAllGlobals())
  it.each([
    ['/', 'AI Assistant Builder'], ['/assistants', 'Your assistants'], ['/assistants/new', 'Create an assistant'],
    ['/assistants/example/configuration', 'Assistant configuration'], ['/assistants/example/knowledge', 'Knowledge files'],
    ['/dev/dashboard', 'Dashboard'], ['/not-a-route', 'Page not found'],
  ])('renders %s as an honest placeholder', async (path, heading) => {
    render(<App path={path} />)
    expect(await screen.findByRole('heading', { level: 1, name: heading })).toBeInTheDocument()
    expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument()
    expect(screen.queryAllByRole('button', { name: /planned/i }).every(button => button.hasAttribute('disabled'))).toBe(true)
  })
  it('navigates to create without claiming a saved assistant', async () => {
    render(<App path="/assistants" />)
    await userEvent.click((await screen.findAllByRole('link', { name: 'Create assistant' }))[0])
    expect(screen.getByRole('heading', { name: 'Create an assistant' })).toBeInTheDocument()
    expect(screen.getByLabelText('Assistant name')).toHaveValue('')
    expect(screen.getByRole('main')).toHaveFocus()
  })
  it('preserves assistant route context when changing sections', async () => {
    render(<App path="/assistants/example/configuration" />)
    const knowledge = await screen.findByRole('link', { name: 'Knowledge' })
    expect(knowledge).toHaveAttribute('href', '/assistants/example/knowledge')
    await userEvent.click(knowledge)
    expect(screen.getByRole('heading', { name: 'Knowledge files' })).toBeInTheDocument()
  })
})

describe('shared UI contracts', () => {
  it('prevents busy and disabled button actions', async () => {
    const click = vi.fn()
    render(<><Button busy onClick={click}>Saving</Button><Button disabled onClick={click}>Later</Button></>)
    await userEvent.click(screen.getByRole('button', { name: 'Saving' }))
    await userEvent.click(screen.getByRole('button', { name: 'Later' }))
    expect(click).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Saving' })).toHaveAttribute('aria-busy', 'true')
  })
  it('links labels and error text with unique field IDs', () => {
    render(<><TextField label="Name" error="Name is required" /><TextField label="Role" hint="Describe the role" /></>)
    expect(screen.getByLabelText('Name')).toHaveAccessibleDescription('Name is required')
    expect(screen.getByLabelText('Name')).toBeInvalid()
    expect(screen.getByLabelText('Role')).toHaveAccessibleDescription('Describe the role')
    expect(screen.getByLabelText('Name').id).not.toBe(screen.getByLabelText('Role').id)
  })
  it('announces loading and error states', () => {
    render(<><LoadingState label="Loading assistants" /><Alert kind="error">Unable to load</Alert></>)
    expect(screen.getByRole('status')).toHaveTextContent('Loading assistants')
    expect(screen.getByRole('alert')).toHaveTextContent('Unable to load')
  })
})
