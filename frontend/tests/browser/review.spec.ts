import { test, expect } from '@playwright/test'
import { signedIn } from './auth-helpers'
import { knowledgeFile } from '../knowledge-fixture'

test.beforeEach(async ({ page }) => signedIn(page))

test('assistant parent URL opens configuration instead of an empty shell', async ({ page }) => {
  await page.goto('/assistants/example')
  await expect(page).toHaveURL(/\/assistants\/example\/configuration$/)
  await expect(page.getByRole('heading', { level: 1, name: 'Assistant configuration' })).toBeVisible()
})

test('loading copy has intact punctuation', async ({ page }) => {
  let release!: () => void
  const pending = new Promise<void>(resolve => { release = resolve })
  await page.route('**/api/assistants', async route => { await pending; await route.fulfill({ json: [] }) })
  await page.goto('/assistants')
  try { await expect(page.getByRole('status')).toHaveText('Loading assistants…') }
  finally { release() }
})

test('knowledge navigation and controls work with keyboard at narrow width', async ({ page }) => {
  let removed = false
  await page.route('**/knowledge-files**', route => {
    if (route.request().method() === 'DELETE') { removed = true; return route.fulfill({ status: 204 }) }
    return route.fulfill({ json: removed ? [] : [{ ...knowledgeFile, original_filename: `${'Long-business-document-'.repeat(5)}.pdf` }] })
  })
  await page.setViewportSize({ width: 320, height: 700 })
  await page.goto('/assistants/example/knowledge')
  await expect(page.getByText('Text extracted', { exact: true })).toBeVisible()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('link', { name: 'Skip to content' })).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('main')).toBeFocused()
  await expect(page.getByRole('main')).toHaveCount(1)
  await expect(page.getByRole('heading', { level: 1 })).toHaveCount(1)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.getByRole('button', { name: /^Remove / }).focus()
  await page.keyboard.press('Enter')
  await page.getByRole('button', { name: 'Cancel', exact: true }).focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('group', { name: /^Confirm removal/ })).toHaveCount(0)
  await expect(page.getByRole('button', { name: /^Remove / })).toBeFocused()
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.screenshot({ path: 'test-results/ui06-knowledge-320.png', fullPage: true })
  await page.keyboard.press('Enter')
  await page.getByRole('button', { name: 'Confirm removal', exact: true }).focus()
  await page.keyboard.press('Enter')
  await expect(page.getByText(/No knowledge files yet/)).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Attached files' })).toBeFocused()
})
