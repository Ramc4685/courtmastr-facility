import { expect, test, type Page } from '@playwright/test'
import { scan } from './a11y'

// Seeded demo owner (docs/dev/demo-accounts.md). Phase 8 T2: setup checklist, logos, support requests.
const OWNER = { email: 'owner@courtside-demo.example.com', password: 'courtside-demo-2026' }
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==', 'base64')

async function signIn(page: Page, path: string, heading: string | RegExp) {
  await page.goto(path)
  await page.getByRole('textbox', { name: 'Email' }).fill(OWNER.email)
  await page.getByRole('textbox', { name: 'Password' }).fill(OWNER.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { level: 1, name: heading })).toBeVisible()
}

test('the setup checklist, logos and support screens work and pass axe', async ({ page }) => {
  test.setTimeout(120_000)
  await page.emulateMedia({ colorScheme: 'dark' })
  await signIn(page, '/', /Welcome/)
  await page.waitForLoadState('networkidle') // the checklist loads after the page; it hides itself once complete
  await scan(page, 'dark dashboard')
  await page.emulateMedia({ colorScheme: 'light' })
  await page.reload()
  await page.waitForLoadState('networkidle')
  await scan(page, 'light dashboard')

  await page.goto('/settings')
  await page.getByLabel('Account logo').setInputFiles({ name: 'logo.png', mimeType: 'image/png', buffer: PNG })
  await expect(page.getByText('Account logo saved.')).toBeVisible()
  await expect(page.getByRole('img', { name: 'Current logo for the account' })).toBeVisible()
  await expect(page.locator('nav[aria-label="Main"]').locator('..').locator('img').first()).toBeVisible() // sidebar logo
  await scan(page, 'settings with logo')
  await page.getByRole('button', { name: 'Remove logo', exact: true }).click()
  await expect(page.getByText('Logo removed from the account.')).toBeVisible()

  await page.goto('/support')
  await expect(page.getByRole('heading', { level: 1, name: 'Help and support' })).toBeVisible()
  await page.getByLabel('What is it about?').selectOption('question')
  await page.getByLabel('Message').fill(`E2E question ${Date.now()}`)
  await page.getByRole('button', { name: 'Send request' }).click()
  await expect(page.getByText('Request sent. We reply by email.')).toBeVisible()
  const table = page.getByRole('table', { name: 'Your support requests' })
  await expect(table.getByText('A question').first()).toBeVisible()
  await scan(page, 'light support')
  await page.emulateMedia({ colorScheme: 'dark' })
  await page.reload() // a fresh render: scanning mid colour transition reads half-faded buttons
  await expect(table.getByText('A question').first()).toBeVisible()
  await scan(page, 'dark support')
  await page.emulateMedia({ colorScheme: 'light' })
  await table.getByRole('button', { name: /Close/ }).first().click()

  await page.goto('/settings/privacy')
  await expect(page.getByRole('checkbox', { name: /Apply GDPR rules/ })).toBeVisible()
  await scan(page, 'privacy')
})
