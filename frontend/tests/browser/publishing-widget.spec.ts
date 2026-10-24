import { expect, test } from '@playwright/test'
import { signedIn } from './auth-helpers'

test('copyable publication snippet contains only the public ID', async ({ page }) => {
  await signedIn(page)
  let published = false
  await page.route('**/api/assistants/example/publication', async route => {
    if (route.request().method() === 'POST') { published = true; return route.fulfill({ status: 201, json: { public_id: 'public-id', version: 1, published_at: new Date().toISOString(), draft_fingerprint: 'a'.repeat(64), replayed: false } }) }
    return route.fulfill({ json: { published, public_id: published ? 'public-id' : null, version: published ? 1 : null, published_at: published ? new Date().toISOString() : null, draft_fingerprint: 'a'.repeat(64), has_changes: published ? false : true, readiness: 'fallback_only' } })
  })
  await page.route('**/api/assistants/example/embed', route => route.fulfill({ json: { public_id: 'public-id', snippet: '<script async src="http://127.0.0.1:4173/widget.js" data-assistant-id="public-id"></script>' } }))
  await page.goto('/assistants/example/publish')
  await page.getByRole('button', { name: 'Publish assistant' }).click()
  await expect(page.getByRole('heading', { name: 'Website embed' })).toBeVisible()
  const snippet = await page.getByLabel('Embed code').inputValue()
  expect(snippet).toContain('data-assistant-id="public-id"')
  expect(snippet).not.toContain('test-only-access-token')
  expect(snippet).not.toContain('X-Demo-Access')
})

test('loader embeds on another origin; iframe chat keeps demo and visitor tokens private', async ({ context }) => {
  const parent = await context.newPage()
  await parent.goto('http://localhost:4173/tests/browser/widget-host.html')
  await expect(parent.getByRole('heading', { name: 'External site' })).toBeVisible()
  await expect.poll(() => parent.locator('iframe').count()).toBe(1)
  await expect(parent.locator('iframe')).toHaveAttribute('src', /\/widget\?public_id=/)
  expect(await parent.evaluate(() => document.querySelector('iframe')?.contentDocument)).toBeNull()
  const launcher = parent.getByRole('button', { name: 'Open assistant chat' })
  await launcher.click()
  await expect(parent.locator('iframe')).toBeVisible()
  expect(await launcher.getAttribute('aria-expanded')).toBe('true')
  // A host-origin message cannot close or inspect the cross-origin frame.
  await parent.evaluate(() => window.postMessage({ type: 'assistant-widget-close' }, '*'))
  await expect(parent.locator('iframe')).toBeVisible()
  const frameUrl = await parent.locator('iframe').getAttribute('src')
  expect(frameUrl).toMatch(/public_id=00000000-0000-0000-0000-000000000001/)
  expect(frameUrl).not.toMatch(/token|access/i)
  expect(await parent.evaluate(() => document.body.innerText)).not.toMatch(/visitor-token|demo-code/i)
})

test('loader refuses same-origin hosts so they cannot inspect the tester iframe', async ({ page }) => {
  await page.goto('/tests/browser/widget-host.html')
  await expect.poll(() => page.locator('script[src*="/widget.js"]').getAttribute('data-widget-state')).toBe('same-origin-host-disallowed')
  await expect(page.getByRole('button', { name: 'Open assistant chat' })).toHaveCount(0)
})

test('widget displays disabled chat safely when server gate is off', async ({ page }) => {
  await page.goto('/widget?public_id=00000000-0000-0000-0000-000000000001')
  await page.route('**/public/assistants/*', route => route.fulfill({ status: 503, json: { detail: { code: 'public_chat_disabled', message: 'private server detail' } } }))
  await page.getByLabel('Demo access code').fill('tester-code')
  await page.getByRole('button', { name: 'Start chat' }).click()
  await expect(page.getByRole('alert')).toContainText('temporarily unavailable')
  await expect(page.getByRole('alert')).not.toContainText('private server detail')
})
