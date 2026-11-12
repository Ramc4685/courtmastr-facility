import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

// Client photo (CLI-12) and note attachments (CLI-09) on seeded Morgan Member (M-1001, card DEMO-CARD-0001).
// The test removes what it adds, so the demo data is left as it was.
const OWNER = { email: 'owner@courtside-demo.example.com', password: 'courtside-demo-2026' }
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAQAAAAECAIAAAAmkwkpAAAAE0lEQVR4nGM8oaHBAANMcBZeDgA4VAEgH8AvGgAAAABJRU5ErkJggg==', 'base64')
const PDF = Buffer.from('%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n')

async function scan(page: Page, label: string) {
  const axe = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  expect(axe.violations.map((v) => `${label} ${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`)).toEqual([])
}

test('staff add, show and remove a client photo and a note attachment', async ({ page }) => {
  test.setTimeout(120_000)
  await page.goto('/clients')
  await page.getByRole('textbox', { name: 'Email' }).fill(OWNER.email)
  await page.getByRole('textbox', { name: 'Password' }).fill(OWNER.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await page.getByRole('searchbox', { name: 'Search' }).fill('M-1001')
  await page.getByRole('link', { name: 'Morgan Member' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Morgan Member' })).toBeVisible()

  // photo: upload on the profile, then it shows on the profile, the client list and the check-in status card
  await page.getByLabel(/^(Upload|Replace) photo/).setInputFiles({ name: 'face.png', mimeType: 'image/png', buffer: PNG })
  const photo = page.getByRole('img', { name: 'Morgan Member' })
  await expect(photo).toBeVisible()
  await expect.poll(() => photo.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0)
  await scan(page, 'profile with photo')
  const profileUrl = page.url()

  await page.goto('/clients')
  await page.getByRole('searchbox', { name: 'Search' }).fill('M-1001')
  await expect(page.getByRole('img', { name: 'Morgan Member' })).toBeVisible()
  await scan(page, 'list with photo')

  await page.goto('/check-in')
  await page.getByLabel('Card or member number').fill('DEMO-CARD-0001')
  await page.getByRole('button', { name: 'Look up' }).click()
  await expect(page.getByRole('heading', { level: 3, name: 'Morgan Member' })).toBeVisible({ timeout: 20_000 })
  await expect(page.getByRole('img', { name: 'Morgan Member' })).toBeVisible()
  await scan(page, 'check-in status card with photo')

  // attachment: on the newest note, download it, then remove it
  await page.goto(profileUrl)
  await page.getByRole('tab', { name: 'Notes' }).click()
  const firstNote = page.getByRole('tabpanel').locator('li').first()
  await firstNote.getByLabel(/^Attach a file/).setInputFiles({ name: 'intake form.pdf', mimeType: 'application/pdf', buffer: PDF })
  const download = firstNote.getByRole('button', { name: 'Download intake form.pdf' })
  await expect(download).toBeVisible()
  await scan(page, 'notes with attachment')
  const file = page.waitForEvent('download')
  await download.click()
  expect((await file).suggestedFilename()).toBe('intake form.pdf')
  await firstNote.getByRole('button', { name: 'Remove intake form.pdf' }).click()
  await expect(download).toBeHidden()

  await page.getByRole('tab', { name: 'Overview' }).click()
  await page.getByRole('button', { name: 'Remove photo' }).click()
  await expect(page.getByText('No photo yet.')).toBeVisible()
})
