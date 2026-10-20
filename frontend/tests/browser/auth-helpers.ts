import type { Page } from '@playwright/test'
import { assistant } from '../assistant-fixture'
export const key = 'assistant-builder-auth.example.test-auth'
export function browserSession(id = '00000000-0000-4000-8000-000000000001') {
  return { access_token: 'test-only-access-token', refresh_token: 'test-only-refresh-token', token_type: 'bearer', expires_in: 3600, expires_at: Math.floor(Date.now() / 1000) + 3600,
    user: { id, email: 'test@example.test', aud: 'authenticated', role: 'authenticated', app_metadata: {}, user_metadata: {}, created_at: '2026-01-01T00:00:00Z' } }
}
export async function signedIn(page: Page) {
  await page.route('**/api/assistants**', route => route.fulfill({ json: /\/(assistants|knowledge-files)$/.test(route.request().url()) ? [] : assistant }))
  await page.addInitScript(({ key, session }) => {
    if (!sessionStorage.getItem('test-initialized')) { sessionStorage.setItem(key, JSON.stringify(session)); sessionStorage.setItem('test-initialized', '1') }
  }, { key, session: browserSession() })
  await page.route('https://auth.example.test/**', route => route.fulfill({ json: browserSession() }))
}
