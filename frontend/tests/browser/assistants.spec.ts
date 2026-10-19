import { test, expect } from '@playwright/test'
import { signedIn } from './auth-helpers'
import { assistant } from '../assistant-fixture'

test('create, reopen and edit draft through authenticated HTTP contracts', async ({ page }) => {
  await signedIn(page)
  let stored = { ...assistant }
  await page.route('**/api/assistants**', async route => {
    expect(route.request().headers().authorization).toBe('Bearer test-only-access-token')
    const method = route.request().method()
    if (method === 'POST' || method === 'PATCH') {
      const body = route.request().postDataJSON()
      expect(body).not.toHaveProperty('owner_id')
      stored = { ...stored, ...body }
    }
    await route.fulfill({ status: method === 'POST' ? 201 : 200, json: method === 'GET' && route.request().url().endsWith('/assistants') ? [stored] : stored })
  })
  await page.setViewportSize({ width: 390, height: 900 })
  await page.goto('/assistants/new')
  for (const [label, value] of [['Assistant name', 'Shop support'], ['Role', 'Customer service'], ['Response style', 'Concise'], ['Tone of voice', 'Friendly'], ['Fallback message', 'I do not know.']]) await page.getByLabel(label, { exact: true }).fill(value)
  await page.getByRole('button', { name: 'Create assistant', exact: true }).click()
  await expect(page).toHaveURL(/example\/configuration$/)
  await expect(page.getByLabel('Assistant name')).toHaveValue('Shop support')
  await page.getByLabel('Tone of voice').fill('Professional')
  await page.getByRole('button', { name: 'Save changes' }).click()
  await expect(page.getByText('Draft saved.')).toBeVisible()
  await page.reload()
  await expect(page.getByLabel('Tone of voice')).toHaveValue('Professional')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: 'test-results/assistant-editor-mobile.png', fullPage: true })
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.screenshot({ path: 'test-results/assistant-editor-desktop.png', fullPage: true })
})
