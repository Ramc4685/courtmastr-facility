import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

// Phase 10 chip E front-desk screens over seeded demo data (docs/dev/demo-accounts.md): Morgan Member (M-1001)
// holds a membership and a lesson package; the Front desk register sells "Water 500 ml" (barcode 0001000500).
const ADMIN = { email: 'admin@courtside-demo.example.com', password: 'courtside-demo-2026' }

async function signIn(page: Page, path: string) {
  await page.goto(path)
  await page.getByRole('textbox', { name: 'Email' }).fill(ADMIN.email)
  await page.getByRole('textbox', { name: 'Password' }).fill(ADMIN.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('button', { name: /account menu/i })).toBeVisible({ timeout: 20_000 }) // cold password hash
}

async function scan(page: Page, label: string) {
  await expect(page.getByRole('status').filter({ hasText: /Loading|Checking/ })).toHaveCount(0)
  const axe = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  expect(axe.violations.map((v) => `${label} ${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`)).toEqual([])
}

test('front-desk screens: quick client, receipt footer, membership details and package removal', async ({ page }) => {
  test.setTimeout(120_000)
  await signIn(page, '/pos')
  await expect(page.getByRole('heading', { level: 1, name: 'Front desk' })).toBeVisible()
  const open = page.getByRole('button', { name: 'Open drawer' })
  if (await open.isVisible()) {
    await open.click()
    await expect(open).toBeHidden()
  }
  const barcode = page.getByRole('textbox', { name: 'Scan or type a barcode' })
  await barcode.fill('0001000500')
  await barcode.press('Enter')
  await page.getByRole('button', { name: 'New client' }).click()
  const quick = page.getByRole('dialog', { name: 'New client' })
  await expect(quick.getByRole('textbox', { name: /First name/ })).toBeVisible()
  await scan(page, 'quick client dialog')
  await quick.getByRole('button', { name: 'Cancel' }).click()
  await page.getByRole('button', { name: 'Abandon sale' }).click()

  await page.goto('/pos/setup')
  await page.getByRole('tab', { name: 'Settings' }).click()
  await expect(page.getByRole('textbox', { name: 'Receipt footer' })).toBeVisible()
  await scan(page, 'pos settings with the receipt footer')

  await page.goto('/clients')
  await page.getByRole('searchbox', { name: 'Search' }).fill('M-1001')
  await page.getByRole('link', { name: 'Morgan Member' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Morgan Member' })).toBeVisible()
  await scan(page, 'client profile with derived alerts')

  await page.getByRole('tab', { name: 'Memberships' }).click()
  await page.getByRole('button', { name: /^Details: / }).first().click()
  const details = page.getByRole('dialog')
  await expect(details.getByRole('heading', { name: 'Visits' })).toBeVisible()
  await expect(details.getByRole('button', { name: 'Reprice' })).toBeVisible()
  await scan(page, 'membership details')
  await page.keyboard.press('Escape')

  await page.getByRole('tab', { name: 'Packages' }).click()
  await page.getByRole('button', { name: /^Remove: / }).first().click()
  await expect(page.getByRole('dialog').getByRole('combobox', { name: 'Billing' })).toBeVisible()
  await scan(page, 'package removal')
  await page.keyboard.press('Escape')
})
