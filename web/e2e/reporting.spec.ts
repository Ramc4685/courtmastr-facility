import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

// Seeded demo data (docs/dev/demo-accounts.md): Adam Admin has seven saved reports, two of them shared.
const PASSWORD = 'courtside-demo-2026'
const ADMIN = 'admin@courtside-demo.example.com'

async function signIn(page: Page, path: string) {
  await page.goto('/')
  await page.getByRole('textbox', { name: 'Email' }).fill(ADMIN)
  await page.getByRole('textbox', { name: 'Password' }).fill(PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { level: 1, name: /Welcome/ })).toBeVisible()
  await page.goto(path)
}

async function scan(page: Page, label: string) {
  await expect(page.getByRole('status').filter({ hasText: /Loading|Checking/ })).toHaveCount(0)
  const axe = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  expect(axe.violations.map((v) => `${label} ${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`)).toEqual([])
}

test('report centre: catalogue, run, drill-down, save and export pass axe', async ({ page }) => {
  await signIn(page, '/reports')
  await expect(page.getByRole('heading', { level: 1, name: 'Reports' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Revenue this month' })).toBeVisible()
  await scan(page, 'catalogue')

  await page.getByRole('link', { name: 'Deposits', exact: true }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Deposits' })).toBeVisible()
  await page.getByLabel('Period').selectOption('last_year')
  await page.getByRole('button', { name: 'Run report' }).click()
  await expect(page.getByRole('heading', { name: 'Totals' })).toBeVisible()
  await scan(page, 'results')

  await page.getByRole('button', { name: 'Save as…' }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await scan(page, 'save dialog')
  await page.keyboard.press('Escape')

  // Without a worker in a lane the job stays queued; the status line is what a person sees either way.
  await page.getByRole('button', { name: 'Export CSV' }).click()
  await expect(page.getByRole('status').filter({ hasText: /Preparing|failed/ }).or(page.getByRole('button', { name: /^Download/ }))).toBeVisible()
  await scan(page, 'export')
})
