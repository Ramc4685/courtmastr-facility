import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

// Seeded demo data (docs/dev/demo-accounts.md): Chloe Coach is a paid trainer, Frank on the front desk has an hourly
// rate and published shifts, and Morgan Member (M-1001) has three Fitness assessments shared on the portal.
const PASSWORD = 'courtside-demo-2026'
const ADMIN = 'admin@courtside-demo.example.com'
const MEMBER = 'member@courtside-demo.example.com'

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

test('staff time and pay screens render and pass axe', async ({ page }) => {
  await signIn(page, '/staff-time')
  await expect(page.getByRole('heading', { level: 1, name: 'Time clock' })).toBeVisible()
  await scan(page, 'clock')
  const screens: [string, string][] = [
    ['Time entries', 'Time entries'], ['Shifts', 'Shifts'], ['Trainers & salespeople', 'Trainers & salespeople'],
    ['Payroll', 'Payroll'], ['Set-up', 'Staff set-up'],
  ]
  const nav = page.getByRole('navigation', { name: 'Staff time and pay' })
  for (const [link, heading] of screens) {
    await nav.getByRole('link', { name: link }).click()
    await expect(page.getByRole('heading', { level: 1, name: heading })).toBeVisible()
    await scan(page, heading)
  }
  await nav.getByRole('link', { name: 'Trainers & salespeople' }).click()
  await expect(page.getByRole('cell', { name: 'Chloe Coach', exact: true }).first()).toBeVisible()
  await page.getByRole('button', { name: 'Session pay for Chloe Coach' }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await scan(page, 'session pay dialog')
  await page.keyboard.press('Escape')

  await nav.getByRole('link', { name: 'Payroll' }).click()
  await page.getByRole('button', { name: 'New payroll run' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Calculate' }).click()
  await expect(page.getByRole('heading', { level: 2, name: /^Run / })).toBeVisible()
  await scan(page, 'payroll run')
  // Void it so reruns do not pile up open runs.
  await page.getByRole('button', { name: 'Void', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Void run' }).click()
  await expect(page.getByRole('dialog')).toBeHidden()
  await expect(page.getByRole('button', { name: 'Void', exact: true })).toBeHidden()
})

test('assessments: set-up and a client profile tab pass axe', async ({ page }) => {
  await signIn(page, '/assessments/setup')
  await expect(page.getByRole('heading', { level: 1, name: 'Assessment setup' })).toBeVisible()
  await expect(page.getByText('Plank hold').first()).toBeVisible()
  await scan(page, 'setup')

  await page.goto('/clients')
  await page.getByRole('searchbox', { name: 'Search' }).fill('M-1001')
  await page.getByRole('link', { name: 'Morgan Member' }).click()
  await page.getByRole('tab', { name: 'Assessments' }).click()
  await expect(page.getByRole('table', { name: 'Assessment progress' })).toContainText('Weight')
  await expect(page.getByRole('img', { name: /^Weight from / })).toBeVisible() // FIT-03 trend chart
  await scan(page, 'client tab')
  await page.getByRole('button', { name: 'Record assessment' }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await scan(page, 'record dialog')
  await page.keyboard.press('Escape')
  await page.getByRole('link', { name: /Assessment history report/ }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Assessment history' })).toBeVisible()
  await page.getByRole('button', { name: /^Run/ }).click()
  await expect(page.getByRole('table').first()).toContainText('Weight')
  await scan(page, 'assessment history report')
})

test('the member portal shows progress', async ({ page }) => {
  // The web app's sign-in form is staff-only; a member signs in through the API (the portal app's call) first.
  const out = await page.request.post('/api/v1/auth/sign-in', { headers: { 'x-tenant-slug': 'courtside-demo' }, data: { email: MEMBER, password: PASSWORD, audience: 'client', client_kind: 'web' } })
  expect(out.ok()).toBe(true)
  await page.goto('/portal')
  await expect(page.getByRole('heading', { name: 'Your progress' })).toBeVisible()
  await expect(page.getByRole('table', { name: 'Personal bests' })).toContainText('Plank hold')
  await scan(page, 'portal')
})
