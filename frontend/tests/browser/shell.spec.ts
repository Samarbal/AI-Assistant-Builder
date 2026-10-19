import { test, expect } from '@playwright/test'
import { signedIn } from './auth-helpers'

test.beforeEach(async ({ page }) => signedIn(page))

for (const width of [320, 390, 768, 1440]) {
  test(`shell fits ${width}px with local assets and no API requests`, async ({ page }) => {
    const errors: string[] = []
    const external: string[] = []
    page.on('pageerror', error => errors.push(error.message))
    page.on('request', request => { if (!request.url().startsWith('http://127.0.0.1:4173/') && !request.url().startsWith('data:')) external.push(request.url()) })
    await page.setViewportSize({ width, height: 1000 })
    await page.goto('/assistants')
    await expect(page.getByRole('heading', { name: 'Your assistants', exact: true })).toBeVisible()
    await page.evaluate(() => document.fonts.ready)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    expect(await page.locator('img').evaluateAll(images => images.every(img => img instanceof HTMLImageElement && img.complete && img.naturalWidth > 0))).toBe(true)
    await expect(page.getByRole('navigation', { name: 'Mobile primary' })).toBeVisible({ visible: width < 768 })
    await page.screenshot({ path: `test-results/shell-${width}.png`, fullPage: true })
    await page.getByRole('link', { name: 'Create assistant' }).first().click()
    await expect(page.getByRole('heading', { name: 'Create an assistant', exact: true })).toBeVisible()
    await page.reload()
    await expect(page.getByRole('heading', { name: 'Create an assistant', exact: true })).toBeVisible()
    expect(errors).toEqual([])
    expect(external).toEqual([])
  })
}

test('mobile dialog traps focus, closes with Escape, and navigates', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/assistants')
  const trigger = page.getByRole('button', { name: 'Open navigation' })
  await trigger.click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await page.keyboard.press('Shift+Tab')
  expect(await dialog.evaluate(element => element.contains(document.activeElement))).toBe(true)
  await page.keyboard.press('Escape')
  await expect(dialog).not.toBeVisible()
  await expect(trigger).toBeFocused()
  await trigger.click()
  await dialog.getByRole('link', { name: 'New assistant', exact: true }).click()
  await expect(dialog).not.toBeVisible()
  await expect(page.getByRole('heading', { name: 'Create an assistant', exact: true })).toBeVisible()
  await expect(page.getByRole('main')).toBeFocused()
  await trigger.click()
  await page.setViewportSize({ width: 1440, height: 1000 })
  await expect(dialog).not.toBeVisible()
})

test('keyboard skip link and nested placeholder sections', async ({ page }) => {
  await page.goto('/assistants/example/configuration')
  await expect(page.getByRole('heading', { name: 'Assistant configuration' })).toBeVisible()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('link', { name: 'Skip to content' })).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('main')).toBeFocused()
  await page.getByRole('link', { name: 'Knowledge', exact: true }).click()
  await expect(page).toHaveURL(/\/assistants\/example\/knowledge$/)
  await expect(page.getByRole('heading', { name: 'Knowledge files' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Publish Planned' })).toBeDisabled()
})
