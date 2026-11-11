import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

// Seeded demo data (docs/dev/demo-accounts.md): Morgan Member holds a membership and a lesson package; the
// "Ten private lessons" package plan is on sale.
const OWNER = { email: 'owner@courtside-demo.example.com', password: 'courtside-demo-2026' }

async function scan(page: Page, label: string) {
  const axe = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  expect(axe.violations.map((v) => `${label} ${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`)).toEqual([])
}

async function signIn(page: Page) {
  await page.goto('/memberships')
  await page.getByRole('textbox', { name: 'Email' }).fill(OWNER.email)
  await page.getByRole('textbox', { name: 'Password' }).fill(OWNER.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Memberships' })).toBeVisible()
}

async function openMorgan(page: Page) {
  await page.goto('/clients')
  await page.getByRole('searchbox', { name: 'Search' }).fill('M-1001')
  await page.getByRole('link', { name: 'Morgan Member' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Morgan Member' })).toBeVisible()
}

test('membership and package screens and dialogs pass the axe WCAG 2.1 AA scan', async ({ page }) => {
  test.setTimeout(120_000) // twenty axe scans across two colour schemes; over 30s on a loaded machine
  await signIn(page)
  for (const colorScheme of ['light', 'dark'] as const) {
    await page.emulateMedia({ colorScheme })
    await page.goto('/memberships')
    await expect(page.getByRole('table', { name: 'Membership contracts' })).toBeVisible()
    await scan(page, `${colorScheme} contracts`)
    for (const tab of ['Upcoming renewals', 'Types', 'Preferences', 'Plans']) {
      await page.getByRole('tab', { name: tab }).click()
      await scan(page, `${colorScheme} memberships ${tab}`)
    }
    await page.getByRole('button', { name: 'New plan' }).click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await scan(page, `${colorScheme} membership plan dialog`)
    await page.getByRole('button', { name: 'Close' }).click()

    await page.goto('/packages')
    await expect(page.getByRole('heading', { level: 1, name: 'Packages' })).toBeVisible()
    await scan(page, `${colorScheme} expiring`)
    for (const tab of ['Preferences', 'Plans']) {
      await page.getByRole('tab', { name: tab }).click()
      await scan(page, `${colorScheme} packages ${tab}`)
    }
    await expect(page.getByRole('table', { name: 'Package plans' })).toContainText('Ten private lessons')

    await openMorgan(page)
    await page.getByRole('tab', { name: 'Memberships' }).click()
    await page.getByRole('button', { name: 'Sell membership' }).click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await scan(page, `${colorScheme} sell membership`)
    await page.getByRole('button', { name: 'Close' }).click()
    await scan(page, `${colorScheme} client memberships`)

    await page.getByRole('tab', { name: 'Packages' }).click()
    await page.getByRole('button', { name: /^Ledger: / }).first().click()
    await expect(page.getByRole('table', { name: 'Credit ledger' })).toBeVisible()
    await scan(page, `${colorScheme} ledger`)
    await page.getByRole('button', { name: 'Close' }).click()
    await scan(page, `${colorScheme} client packages`)
  }
})

test('a package sells from the client profile with a cash payment', async ({ page }) => {
  await signIn(page)
  await openMorgan(page)
  await page.getByRole('tab', { name: 'Packages' }).click()
  await page.getByRole('button', { name: 'Sell package' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Package plan').selectOption({ label: 'Ten private lessons · 10 sessions' })
  await expect(dialog.getByRole('region', { name: 'Quote' })).toContainText('10 sessions')
  await dialog.getByLabel('Take payment').selectOption('cash')
  await scan(page, 'sell package with payment')
  await dialog.getByRole('button', { name: 'Sell package' }).click()
  await expect(page.getByText(/Sold Ten private lessons\. Payment succeeded/)).toBeVisible()
})
