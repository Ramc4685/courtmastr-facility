import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

// Seeded demo data (docs/dev/demo-accounts.md): Chloe Coach is a paid trainer; Frank on the front desk has shifts.
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

test('trainer pay dialogs: session pay, rates by type and bonuses pass axe', async ({ page }) => {
  await signIn(page, '/staff-time/payees')
  await expect(page.getByRole('cell', { name: 'Chloe Coach', exact: true }).first()).toBeVisible()
  await page.getByRole('button', { name: 'Session pay for Chloe Coach' }).click()
  await expect(page.getByLabel('Floor shift rate per hour')).toBeVisible()
  await expect(page.getByLabel('Complimentary session rate')).toBeVisible()
  await scan(page, 'session pay dialog')
  await page.keyboard.press('Escape')

  await page.getByRole('button', { name: 'Rates by type for Chloe Coach' }).click()
  await expect(page.getByRole('dialog', { name: /Rates by type/ })).toBeVisible()
  await scan(page, 'rates by type dialog')
  await page.keyboard.press('Escape')

  await page.getByRole('button', { name: 'Bonuses for Chloe Coach' }).click()
  await page.getByRole('button', { name: 'Add bonus' }).click()
  await page.getByLabel('Kind').selectOption('off_hours')
  await expect(page.getByLabel('Extra pay per hour')).toBeVisible()
  await scan(page, 'bonuses dialog')
  await page.keyboard.press('Escape')
})

test('shifts: the variance table and the copy-week dialog pass axe', async ({ page }) => {
  await signIn(page, '/staff-time/shifts')
  await expect(page.getByRole('heading', { level: 1, name: 'Shifts' })).toBeVisible()
  await expect(page.getByRole('heading', { level: 2, name: 'Scheduled against worked' })).toBeVisible()
  await scan(page, 'shifts and variance')
  await page.getByRole('button', { name: 'Copy a week' }).click()
  await expect(page.getByRole('dialog', { name: 'Copy a week of shifts' })).toBeVisible()
  await scan(page, 'copy week dialog')
  await page.keyboard.press('Escape')
})
