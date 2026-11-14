import { expect, test, type Page } from '@playwright/test'
import { scanAfter } from './a11y'

const scan = scanAfter(/Loading|Checking/)

// Seeded demo data (docs/dev/demo-accounts.md): Chloe Coach is a trainer; coach@ is linked to her column.
const PASSWORD = 'courtside-demo-2026'

async function signIn(page: Page, email: string, path: string) {
  await page.goto('/')
  await page.getByRole('textbox', { name: 'Email' }).fill(email)
  await page.getByRole('textbox', { name: 'Password' }).fill(PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { level: 1, name: /Welcome/ })).toBeVisible()
  await page.goto(path)
}

test('coach revenue share: terms, share rule and payout dialogs pass axe and say no money moves', async ({ page }) => {
  await signIn(page, 'admin@courtside-demo.example.com', '/staff-time/coach-share')
  await expect(page.getByRole('heading', { level: 1, name: 'Coach revenue share' })).toBeVisible()
  await expect(page.getByText(/does not move money/).first()).toBeVisible()
  await expect(page.getByRole('cell', { name: 'Chloe Coach', exact: true }).first()).toBeVisible()
  await scan(page, 'coach revenue share')

  await page.getByRole('button', { name: 'Terms for Chloe Coach' }).click()
  await expect(page.getByLabel('Tax form on file since')).toBeVisible()
  await scan(page, 'coach terms dialog')
  await page.keyboard.press('Escape')

  await page.getByRole('button', { name: 'Add share rule' }).click()
  await expect(page.getByLabel("Coach's share (percent)")).toBeVisible()
  await scan(page, 'share rule dialog')
  await page.keyboard.press('Escape')

  await page.getByRole('button', { name: 'New payout statements' }).click()
  await expect(page.getByRole('dialog', { name: 'New payout statements' })).toBeVisible()
  await scan(page, 'new payout statements dialog')
  await page.keyboard.press('Escape')
})

test("a coach's own earnings page passes axe and shows no share rule", async ({ page }) => {
  await signIn(page, 'coach@courtside-demo.example.com', '/staff-time/my-earnings')
  await expect(page.getByRole('heading', { level: 1, name: 'My earnings' })).toBeVisible()
  // The seed has no statements, so the list shows its empty state; a lane where statements were made shows the table.
  await expect(page.getByRole('table', { name: 'My payout statements' }).or(page.getByText('No statements yet'))).toBeVisible()
  await expect(page.getByText('Share rules')).toHaveCount(0)
  await scan(page, 'my earnings')
})
