import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'

// Seeded demo data (docs/dev/demo-accounts.md): the demo tenant is on the Complete plan (Phase 8 T1).
const ADMIN = { email: 'admin@courtside-demo.example.com', password: 'courtside-demo-2026' }
const DESK = { email: 'front-desk@courtside-demo.example.com', password: 'courtside-demo-2026' }

async function signIn(page: import('@playwright/test').Page, who: typeof ADMIN, path: string) {
  await page.goto(path)
  await page.getByRole('textbox', { name: 'Email' }).fill(who.email)
  await page.getByRole('textbox', { name: 'Password' }).fill(who.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
}

test('an admin sees the plan and its usage, and the page passes the axe WCAG 2.1 AA scan', async ({ page }) => {
  await signIn(page, ADMIN, '/settings/plan')
  await expect(page.getByRole('heading', { level: 1, name: 'Plan and usage' })).toBeVisible()
  await expect(page.getByText('Complete', { exact: true })).toBeVisible()
  const table = page.getByRole('table', { name: 'Plan limits and current use' })
  await expect(table.getByRole('row', { name: /Active locations/ })).toContainText('Unlimited')
  await expect(page.getByRole('listitem').filter({ hasText: 'Branded mobile app' })).toContainText('Included')
  for (const colorScheme of ['light', 'dark'] as const) {
    await page.emulateMedia({ colorScheme })
    const axe = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
    expect(axe.violations.map((v) => `${colorScheme} ${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`)).toEqual([])
  }
})

test('front desk has no Plan and usage entry', async ({ page }) => {
  await signIn(page, DESK, '/')
  await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Plan and usage' })).toHaveCount(0)
})
