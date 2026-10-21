import { expect, test } from '@playwright/test'
import { signedIn } from './auth-helpers'
import { assistant } from '../assistant-fixture'

test('Playground responds with evidence, supports reset, Arabic direction and narrow layouts', async ({ page }) => {
  await signedIn(page)
  let requests = 0
  await page.route('**/api/assistants/example', route => route.fulfill({ json: assistant }))
  await page.route('**/api/assistants/example/playground/messages', async route => {
    expect(route.request().headers().authorization).toBe('Bearer test-only-access-token')
    expect(route.request().postDataJSON()).toEqual({ message: 'ما سياسة الإرجاع؟' })
    requests++
    await route.fulfill({ json: { answer: 'يمكنك الإرجاع خلال 14 يومًا.', outcome: 'grounded', citations: [
      { file_id: 'f1', chunk_id: 'c1', filename: 'Returns.pdf', excerpt: 'تقبل الإرجاعات خلال 14 يومًا.' },
    ] } })
  })
  for (const width of [390, 1440]) {
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/assistants/example/playground')
    await expect(page.getByRole('heading', { name: 'Meet Support' })).toBeVisible()
    await expect(page.getByRole('navigation', { name: 'Primary' }).getByRole('link', { name: 'Playground' })).toHaveAttribute('href', '/assistants/example/playground')
    if (width < 768) await expect(page.getByRole('navigation', { name: 'Mobile primary' }).getByRole('link', { name: 'Playground' })).toHaveAttribute('href', '/assistants/example/playground')
    await page.getByRole('textbox', { name: 'Ask Support a question' }).fill('ما سياسة الإرجاع؟')
    await page.getByRole('button', { name: 'Send question' }).click()
    await expect(page.getByText('يمكنك الإرجاع خلال 14 يومًا.')).toBeVisible()
    await expect(page.getByText('Returns.pdf')).toBeVisible()
    await expect(page.getByTestId('playground-turn')).toHaveCount(1)
    await expect(page.getByTestId('playground-answer')).toHaveAttribute('dir', 'auto')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: `test-results/playground-${width}.png`, fullPage: true })
    await page.getByRole('button', { name: /Reset conversation/ }).click()
    await expect(page.getByText(/Ask a question to test/)).toBeVisible()
    await page.goto('/assistants/example/configuration')
  }
  expect(requests).toBe(2)
})

test('readiness failure is explained safely and the question remains retryable', async ({ page }) => {
  await signedIn(page)
  await page.route('**/api/assistants/example', route => route.fulfill({ json: assistant }))
  await page.route('**/api/assistants/example/playground/messages', route => route.fulfill({ status: 409, json: {
    detail: { code: 'knowledge_not_ready', message: 'internal text must not be displayed' },
  } }))
  await page.goto('/assistants/example/playground')
  await page.getByRole('textbox', { name: 'Ask Support a question' }).fill('Question')
  await page.getByRole('button', { name: 'Send question' }).click()
  await expect(page.getByRole('alert')).toContainText('still being prepared')
  await expect(page.getByRole('alert')).not.toContainText('internal text')
  await expect(page.getByRole('textbox')).toHaveValue('Question')
})
