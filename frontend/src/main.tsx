import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import { AppRoutes } from './app/routes'
import '@fontsource-variable/inter'
import './styles/tokens.css'
import './styles/global.css'
import { createAuthPort } from './auth/client'
import { AuthStore } from './auth/store'
import { AuthProvider } from './auth/AuthProvider'

function initializeAuth() {
  try { return new AuthStore(createAuthPort(import.meta.env, window.sessionStorage)) }
  catch { return new AuthStore(null, 'Authentication could not initialize. Allow browser session storage and check the public Auth configuration.') }
}
const authStore = initializeAuth()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AuthProvider store={authStore}><BrowserRouter><AppRoutes /></BrowserRouter></AuthProvider>
  </StrictMode>,
)
