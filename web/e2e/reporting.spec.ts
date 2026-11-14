import { expect, test, type Page } from '@playwright/test'
import { scanAfter } from './a11y'

const scan = scanAfter(/Loading|Checking/)

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
  await page.getByLabel('Format').selectOption('pdf')
  await expect(page.getByLabel('Page size')).toBeVisible()
  const created = page.waitForResponse((r) => r.url().endsWith('/api/v1/export-jobs') && r.request().method() === 'POST')
  await page.getByRole('button', { name: 'Export', exact: true }).click()
  const job = (await (await created).json()) as { id: string }
  await expect(page.getByRole('status').filter({ hasText: /Preparing|failed/ }).or(page.getByRole('button', { name: /^Download/ }))).toBeVisible()
  await scan(page, 'export')

  // The page an emailed link opens.
  await page.goto(`/reports/exports/${job.id}`)
  await expect(page.getByRole('heading', { level: 1, name: 'Your export' })).toBeVisible()
  await scan(page, 'export link page')
})

test('dashboard tiles, revenue chart and schedule dialog pass axe', async ({ page }) => {
  await signIn(page, '/')
  await expect(page.getByRole('heading', { name: 'At a glance' })).toBeVisible()
  await scan(page, 'dashboard')

  await page.goto('/reports/revenue_summary')
  await page.getByLabel('Period').selectOption('last_year')
  await page.getByLabel(/^Goal/).fill('1000')
  await page.getByRole('button', { name: 'Run report' }).click()
  await expect(page.getByRole('img', { name: /against a goal of/ })).toBeVisible()
  await scan(page, 'revenue chart')

  await page.goto('/reports')
  await page.getByRole('table', { name: 'Saved reports' }).getByRole('link').first().click()
  await page.getByRole('button', { name: 'Schedule…' }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await scan(page, 'schedule dialog')
})

test('court use chart and heat map pass axe in light and dark', async ({ page }) => {
  await signIn(page, '/reports/court_use')
  await page.getByLabel('Period').selectOption('this_month')
  await page.getByRole('button', { name: 'Run report' }).click()
  await expect(page.getByRole('img', { name: /^Utilization .* available hours$/ })).toBeVisible()
  await expect(page.getByText(/^In all: played /)).toBeVisible()
  await scan(page, 'court use chart')

  await page.goto('/reports/court_use_heatmap')
  await page.getByLabel('Period').selectOption('this_month')
  await page.getByRole('button', { name: 'Run report' }).click()
  await expect(page.getByRole('table', { name: /^Average utilization by hour and weekday/ })).toBeVisible()
  await scan(page, 'heat map')
  await page.emulateMedia({ colorScheme: 'dark' })
  await scan(page, 'heat map, dark')
})
