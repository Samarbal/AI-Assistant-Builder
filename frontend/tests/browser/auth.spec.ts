import { test, expect } from '@playwright/test'
import { browserSession, key } from './auth-helpers'

// Auth checks must not depend on a running local FastAPI server.
test.beforeEach(async ({ page }) => {
  await page.route('**/api/assistants', route => route.fulfill({ json: [] }))
})

test('real SDK login, reload, logout and protected history with controlled Auth responses', async ({ page }) => {
  const paths: string[] = []
  await page.route('https://auth.example.test/**', async route => {
    const url = new URL(route.request().url()); paths.push(url.pathname)
    if (url.pathname.endsWith('/logout')) return route.fulfill({ status: 204 })
    if (url.pathname.endsWith('/token')) return route.fulfill({ json: browserSession() })
    return route.abort()
  })
  await page.goto('/assistants/example/knowledge')
  await expect(page).toHaveURL(/\/login$/)
  await page.getByLabel('Work email').fill('test@example.test')
  await page.getByLabel('Password', { exact: true }).fill('test-only-password')
  await page.getByRole('button', { name: 'Log in', exact: true }).click()
  await expect(page).toHaveURL(/\/assistants$/)
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Your assistants' })).toBeVisible()
  await page.getByRole('button', { name: 'Log out', exact: true }).first().click()
  await expect(page).toHaveURL(/\/login$/)
  await expect.poll(() => page.evaluate(key => sessionStorage.getItem(key), key)).toBeNull()
  await page.goto('/assistants')
  await expect(page).toHaveURL(/\/login$/)
  expect(paths).toContain('/auth/v1/token')
  expect(paths).toContain('/auth/v1/logout')
  expect(paths.every(path => path.startsWith('/auth/v1/'))).toBe(true)
})

test('failed sign-out clears this tab and cannot restore on reload', async ({ page }) => {
  await page.route('https://auth.example.test/**', route => route.request().url().includes('/logout')
    ? route.fulfill({ status: 500, json: { code: 'unexpected_failure', msg: 'unavailable' } })
    : route.fulfill({ json: browserSession() }))
  await page.goto('/login')
  await page.getByLabel('Work email').fill('test@example.test')
  await page.getByLabel('Password', { exact: true }).fill('test-only-password')
  await page.getByRole('button', { name: 'Log in', exact: true }).click()
  await expect(page).toHaveURL(/\/assistants$/)
  await page.getByRole('button', { name: 'Log out', exact: true }).first().click()
  await expect(page.getByRole('alert')).toContainText('revocation could not be confirmed')
  await page.reload()
  await page.goto('/assistants')
  await expect(page).toHaveURL(/\/login$/)
})

test('registration confirmation and invalid-login errors are honest', async ({ page }) => {
  await page.route('https://auth.example.test/**', route => route.request().url().includes('/signup')
    ? route.fulfill({ json: { user: browserSession().user, session: null } })
    : route.fulfill({ status: 400, headers: { 'x-supabase-api-version': '2024-01-01', 'access-control-expose-headers': 'x-supabase-api-version' }, json: { code: 'invalid_credentials', msg: 'provider internal details' } }))
  await page.goto('/register')
  await page.getByLabel('Work email').fill('test@example.test')
  await page.getByLabel('Password', { exact: true }).fill('test-only-password')
  await page.getByRole('button', { name: 'Create account', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('No signed-in session was created')
  await page.getByRole('link', { name: 'Return to log in' }).click()
  await page.getByLabel('Work email').fill('test@example.test')
  await page.getByLabel('Password', { exact: true }).fill('wrong-test-password')
  await page.getByRole('button', { name: 'Log in', exact: true }).click()
  await expect(page.getByRole('alert')).toHaveText('Email or password is incorrect.')
  await expect(page.getByLabel('Password', { exact: true })).toHaveValue('')
})

for (const width of [320, 390, 1440]) {
  test(`auth screens fit ${width}px and retain local icons`, async ({ page }) => {
    await page.setViewportSize({ width, height: 960 })
    for (const path of ['/login', '/register']) {
      await page.goto(path)
      await expect(page.getByLabel('Work email')).toBeVisible()
      await page.evaluate(() => document.fonts.ready)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
      expect(await page.locator('img').evaluateAll(images => images.every(img => img instanceof HTMLImageElement && img.complete && img.naturalWidth > 0))).toBe(true)
      await page.screenshot({ path: `test-results/auth-${path.slice(1)}-${width}.png`, fullPage: true })
    }
  })
}

test('root is reserved and development preview is independent of authentication', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByText('Public landing page coming later.')).toBeVisible()
  await expect(page.getByRole('navigation')).toHaveCount(0)
  await page.goto('/dev/dashboard')
  await expect(page.getByRole('heading', { name: 'Dashboard', exact: true })).toBeVisible()
  await page.getByRole('link', { name: 'Create assistant' }).first().click()
  await expect(page).toHaveURL(/\/login$/)
})
