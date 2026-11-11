import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

// Seeded demo data (docs/dev/demo-accounts.md): the owner sees every client screen; Morgan Member (M-1001)
// has a household (Mia, a dependent; Riley, a spouse) and an alert.
const OWNER = { email: 'owner@courtside-demo.example.com', password: 'courtside-demo-2026' }

async function scan(page: Page, label: string) {
  const axe = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  expect(axe.violations.map((v) => `${label} ${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`)).toEqual([])
}

test('client list, profile tabs and merge flow pass the axe WCAG 2.1 AA scan', async ({ page }) => {
  await page.goto('/clients')
  await page.getByRole('textbox', { name: 'Email' }).fill(OWNER.email)
  await page.getByRole('textbox', { name: 'Password' }).fill(OWNER.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Clients' })).toBeVisible()

  for (const colorScheme of ['light', 'dark'] as const) {
    await page.emulateMedia({ colorScheme })
    await page.goto('/clients')
    await page.getByRole('searchbox', { name: 'Search' }).fill('M-1001')
    await expect(page.getByRole('link', { name: 'Morgan Member' })).toBeVisible()
    await scan(page, `${colorScheme} list`)
    await page.getByRole('link', { name: 'Morgan Member' }).click()
    await expect(page.getByRole('heading', { level: 1, name: 'Morgan Member' })).toBeVisible()
    await expect(page.getByRole('note')).toContainText('Asthma')
    await scan(page, `${colorScheme} overview`)
    await page.getByRole('tab', { name: 'Family' }).click()
    await expect(page.getByRole('link', { name: 'Mia Member' })).toBeVisible()
    await scan(page, `${colorScheme} family`)
    await page.getByRole('tab', { name: 'Notes' }).click()
    await expect(page.getByText('Welcome call')).toBeVisible()
    await scan(page, `${colorScheme} notes`)
    await page.getByRole('tab', { name: 'Documents' }).click()
    await scan(page, `${colorScheme} documents`)
    await page.goto('/clients/merge')
    await expect(page.getByRole('heading', { level: 1, name: 'Merge duplicates' })).toBeVisible()
    await scan(page, `${colorScheme} merge`)
  }
})
