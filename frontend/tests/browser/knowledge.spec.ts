/// <reference types="node" />
import { test, expect } from '@playwright/test'
import { readFile } from 'node:fs/promises'
import { signedIn } from './auth-helpers'
import { knowledgeFile } from '../knowledge-fixture'
import type { KnowledgeFile } from '../../src/knowledge/api'

const preparation = (readiness: 'needs_preparation' | 'preparing' | 'ready' = 'needs_preparation') => ({
  readiness, operation_id: readiness === 'preparing' ? 'operation-123' : null,
  completed_chunks: readiness === 'preparing' ? 1 : 0, total_chunks: 3,
  eligible_files: 1, next_action: readiness === 'preparing' ? 'continue' : readiness === 'ready' ? null : 'prepare', reason: null,
})

test('PDF/DOCX upload, private download, remove and replace on mobile', async ({ page }) => {
  await signedIn(page)
  await page.route('**/api/assistants/example/playground/status', route => route.fulfill({ json: preparation() }))
  let files: KnowledgeFile[] = []
  let uploads = 0
  const documentBytes = Buffer.from('controlled document bytes')
  await page.context().route('https://files.example.test/**', async route => {
    expect(route.request().headers().authorization).toBeUndefined()
    await route.fulfill({ body: documentBytes, contentType: 'application/octet-stream', headers: { 'Content-Disposition': 'attachment; filename="Policies.pdf"' } })
  })
  await page.route('**/api/assistants/example/knowledge-files**', async route => {
    const request = route.request()
    expect(request.headers().authorization).toBe('Bearer test-only-access-token')
    if (request.url().endsWith('/download-url')) return route.fulfill({ json: { download_url: 'https://files.example.test/signed/test-only', expires_in: 60 } })
    if (request.method() === 'DELETE') {
      files = files.filter(file => !request.url().endsWith(`/${file.id}`))
      return route.fulfill({ status: 204 })
    }
    if (request.method() === 'POST') {
      expect(request.headers()['content-type']).toContain('multipart/form-data; boundary=')
      expect(request.postData()).not.toContain('name="owner_id"')
      const name = /filename="([^"]+)"/.exec(request.postData() ?? '')![1]
      const file = { ...knowledgeFile, id: `file-${++uploads}`, original_filename: name, file_format: name.endsWith('.docx') ? 'docx' : 'pdf' }
      files.push(file)
      return route.fulfill({ status: 201, json: file })
    }
    return route.fulfill({ json: files })
  })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/assistants/example/knowledge')
  await expect(page.getByText(/No knowledge files yet/)).toBeVisible()
  for (const name of ['Policies.pdf', 'FAQ.docx']) {
    await page.getByLabel('Choose knowledge file').setInputFiles({ name, mimeType: name.endsWith('.pdf') ? 'application/pdf' : 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', buffer: documentBytes })
    await page.getByRole('button', { name: 'Upload file', exact: true }).click()
    await expect(page.getByRole('button', { name: `Download ${name}`, exact: true })).toBeEnabled()
  }
  await expect(page.getByText('2 of 5 files')).toBeVisible()
  await page.getByRole('button', { name: 'Download Policies.pdf', exact: true }).click()
  const downloadEvent = page.waitForEvent('download')
  await page.getByRole('link', { name: 'Open private download' }).click()
  const download = await downloadEvent
  expect(await readFile((await download.path())!)).toEqual(documentBytes)
  await page.getByRole('button', { name: 'Remove Policies.pdf', exact: true }).click()
  await page.getByRole('button', { name: 'Cancel', exact: true }).click()
  expect(files).toHaveLength(2)
  await page.getByRole('button', { name: 'Remove Policies.pdf', exact: true }).click()
  await page.getByRole('button', { name: 'Confirm removal', exact: true }).click()
  await expect(page.getByText('1 of 5 files')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Download Policies.pdf', exact: true })).toHaveCount(0)
  await page.getByLabel('Choose knowledge file').setInputFiles({ name: 'Replacement.pdf', mimeType: 'application/pdf', buffer: documentBytes })
  await page.getByRole('button', { name: 'Upload file', exact: true }).click()
  await expect(page.getByText('2 of 5 files')).toBeVisible()
  await page.reload()
  await expect(page.getByRole('button', { name: 'Download Replacement.pdf', exact: true })).toBeEnabled()
  expect(uploads).toBe(3)
  for (const width of [320, 1440]) {
    await page.setViewportSize({ width, height: 1000 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    expect(await page.locator('img').evaluateAll(images => images.every(img => img instanceof HTMLImageElement && img.complete && img.naturalWidth > 0))).toBe(true)
    await page.screenshot({ path: `test-results/knowledge-${width}.png`, fullPage: true })
  }
})

test('server limit wins over a stale four-file list', async ({ page }) => {
  await signedIn(page)
  await page.route('**/api/assistants/example/playground/status', route => route.fulfill({ json: preparation() }))
  const files = Array.from({ length: 4 }, (_, i) => ({ ...knowledgeFile, id: `${i}`, original_filename: `${i}.pdf` }))
  let posts = 0
  await page.route('**/knowledge-files', async route => {
    if (route.request().method() === 'POST') {
      posts++; files.push({ ...knowledgeFile, id: 'five', original_filename: 'Other-tab.pdf' })
      return route.fulfill({ status: 409, json: {} })
    }
    return route.fulfill({ json: files })
  })
  await page.goto('/assistants/example/knowledge')
  await expect(page.getByText('4 of 5 files')).toBeVisible()
  await page.getByLabel('Choose knowledge file').setInputFiles({ name: 'test.pdf', mimeType: 'application/pdf', buffer: Buffer.from('test') })
  await page.getByRole('button', { name: 'Upload file', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('five-file limit')
  await expect(page.getByText('5 of 5 files')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Browse files', exact: true })).toBeDisabled()
  expect(posts).toBe(1)
})

test('expired session redirects without exposing file data', async ({ page }) => {
  await signedIn(page)
  await page.route('**/knowledge-files', route => route.fulfill({ status: 401, json: {} }))
  await page.route('**/api/assistants/example/playground/status', route => route.fulfill({ status: 401, json: {} }))
  await page.goto('/assistants/example/knowledge')
  await expect(page).toHaveURL(/\/login$/)
  await expect(page.getByRole('heading', { name: 'Knowledge files' })).toHaveCount(0)
})

test('knowledge preparation is an explicit single-batch action with safe progress', async ({ page }) => {
  await signedIn(page)
  let prepareRequests = 0
  await page.route('**/api/assistants/example/knowledge-files', route => route.fulfill({ json: [knowledgeFile] }))
  await page.route('**/api/assistants/example/playground/status', route => route.fulfill({ json: preparation() }))
  await page.route('**/api/assistants/example/playground/prepare', async route => {
    prepareRequests++
    expect(route.request().method()).toBe('POST')
    expect(route.request().headers()['idempotency-key']).toMatch(/^[0-9a-f-]{36}$/i)
    expect(route.request().headers().authorization).toBe('Bearer test-only-access-token')
    expect(route.request().postDataJSON()).toEqual({})
    await route.fulfill({ status: 202, json: preparation('preparing') })
  })
  await page.goto('/assistants/example/knowledge')
  await expect(page.getByRole('button', { name: 'Prepare knowledge' })).toBeVisible()
  await expect(page.getByText(/uses AI embedding credits/i)).toBeVisible()
  await page.getByRole('button', { name: 'Prepare knowledge' }).click()
  await expect(page.getByText('Progress saved: 1 of 3 chunks. Select Continue to process the next batch.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Continue preparation' })).toBeVisible()
  expect(prepareRequests).toBe(1)
})
