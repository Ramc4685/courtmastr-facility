import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

// Seeded demo account and rentals (docs/dev/demo-accounts.md, "Demo rentals (build module 3)").
const ADMIN = { email: 'admin@courtside-demo.example.com', password: 'courtside-demo-2026' }

async function scan(page: Page, label: string) {
  const axe = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  expect(axe.violations.map((v) => `${label} ${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`)).toEqual([])
}

// A date far enough ahead that the seed and other runs leave it empty; each run picks its own hour.
const day = new Date(Date.now() + (300 + Math.floor(Math.random() * 300)) * 86400000).toISOString().slice(0, 10)
const hour = String(7 + Math.floor(Math.random() * 12)).padStart(2, '0')

test('a rental is booked unbilled, priced, then billed from the queue, all screens pass axe', async ({ page }) => {
  await page.goto('/rentals')
  await page.getByRole('textbox', { name: 'Email' }).fill(ADMIN.email)
  await page.getByRole('textbox', { name: 'Password' }).fill(ADMIN.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Rentals' })).toBeVisible()
  await expect(page.getByRole('table', { name: 'Upcoming rentals' })).toBeVisible()
  await scan(page, 'rentals list')

  await page.getByRole('button', { name: 'New rental' }).click()
  const dialog = page.getByRole('dialog', { name: 'New rental' })
  await dialog.getByRole('combobox', { name: 'Client' }).fill('Reyes')
  await page.getByRole('option', { name: /Reyes/ }).first().click()
  await dialog.getByRole('combobox', { name: 'Resource' }).selectOption({ label: 'Court 1' })
  await dialog.getByLabel('Date').fill(day)
  await dialog.getByLabel('Start').fill(`${hour}:00`)
  await dialog.getByLabel('End').fill(`${hour}:30`)
  await dialog.getByRole('combobox', { name: 'Rate' }).selectOption({ label: 'Standard' })
  await dialog.getByRole('button', { name: 'Preview price' }).click()
  await expect(dialog.getByRole('table', { name: 'Price quote' })).toBeVisible()
  await expect(dialog.getByRole('status')).toHaveText('1 of 1 time is free.')
  await scan(page, 'new rental dialog')

  await dialog.getByRole('combobox', { name: 'Charge' }).selectOption('unbilled')
  const created = page.waitForResponse((r) => r.url().endsWith('/api/v1/rentals') && r.request().method() === 'POST')
  await dialog.getByRole('button', { name: 'Book rental' }).click()
  const { rental } = (await (await created).json()) as { rental: { booking_number: number } }
  await expect(dialog).toBeHidden()

  await page.getByRole('tab', { name: 'Unbilled queue' }).click()
  await page.getByRole('checkbox', { name: `Select rental #${rental.booking_number}` }).check()
  await scan(page, 'unbilled queue')
  await page.getByRole('button', { name: 'Bill selected (1)' }).click()
  const bill = page.getByRole('dialog', { name: 'Bill 1 rental' })
  await bill.getByRole('combobox', { name: 'Rate' }).selectOption({ label: 'Standard' })
  await bill.getByRole('button', { name: 'Bill', exact: true }).click()
  await expect(page.getByText('1 rental billed.')).toBeVisible()
  await expect(page.getByRole('checkbox', { name: `Select rental #${rental.booking_number}` })).toHaveCount(0)

  await page.goto('/rentals/setup')
  await expect(page.getByRole('heading', { level: 1, name: 'Rental setup' })).toBeVisible()
  await expect(page.getByText('Standard ·', { exact: false }).first()).toBeVisible()
  await scan(page, 'rental setup')
  await page.getByRole('tab', { name: 'Rental plans' }).click()
  await expect(page.getByRole('table', { name: 'Rental plans' })).toContainText('10-hour court pack')
  await scan(page, 'rental plans')
  await page.getByRole('tab', { name: 'Plans sold' }).click()
  await expect(page.getByRole('table', { name: 'Rental plans sold' })).toBeVisible()
  await scan(page, 'plans sold')
})
