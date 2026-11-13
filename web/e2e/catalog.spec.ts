import { expect, test, type Page } from '@playwright/test'
import { scanAfter } from './a11y'

const scan = scanAfter(/Loading|Checking/)

// Seeded demo data (docs/dev/demo-accounts.md): Morgan Member is M-1001; the seed adds three pre-defined items.
const ADMIN = { email: 'admin@courtside-demo.example.com', password: 'courtside-demo-2026' }

async function signIn(page: Page, path: string) {
  await page.goto(path)
  await page.getByRole('textbox', { name: 'Email' }).fill(ADMIN.email)
  await page.getByRole('textbox', { name: 'Password' }).fill(ADMIN.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('button', { name: /account menu/i })).toBeVisible()
}

test('staff define a pre-defined item, sell it from client billing and cancel the sale', async ({ page }) => {
  const name = `Ball hopper ${Date.now()}`
  await signIn(page, '/billing/catalog')
  await expect(page.getByRole('heading', { level: 1, name: 'Pre-defined items' })).toBeVisible()
  await expect(page.getByRole('table', { name: 'Pre-defined items' }).getByText('Locker, monthly')).toBeVisible()
  await scan(page, 'catalogue')

  await page.getByRole('button', { name: 'New item' }).click()
  const edit = page.getByRole('dialog', { name: 'New pre-defined item' })
  await edit.getByRole('textbox', { name: 'Description' }).fill(name)
  await edit.getByRole('textbox', { name: 'Fee per occurrence' }).fill('8.00')
  await edit.getByRole('combobox', { name: 'Revenue category' }).selectOption({ label: 'Pro shop' })
  await scan(page, 'item dialog')
  await edit.getByRole('button', { name: 'Save item' }).click()
  await expect(edit).toBeHidden()
  await expect(page.getByRole('table', { name: 'Pre-defined items' }).getByText(name)).toBeVisible()

  await page.goto('/billing/clients')
  await page.getByRole('combobox', { name: 'Client' }).fill('m-1001')
  await page.getByRole('option', { name: /Morgan Member/ }).click()
  await page.getByRole('tab', { name: 'Items' }).click()
  await page.getByRole('button', { name: 'Sell pre-defined item' }).click()
  const sell = page.getByRole('dialog', { name: 'Sell a pre-defined item' })
  await sell.getByRole('combobox', { name: 'Item' }).selectOption({ label: name })
  await expect(sell.getByText('$8.00 once')).toBeVisible()
  await scan(page, 'sell dialog')
  await sell.getByRole('button', { name: 'Sell item' }).click()
  await expect(sell).toBeHidden()

  const sold = page.getByRole('table', { name: 'Pre-defined items sold' })
  const row = sold.getByRole('row').filter({ hasText: name })
  await expect(row).toContainText('Active')
  await scan(page, 'client items')
  await row.getByRole('button', { name: `Cancel ${name}` }).click()
  const cancel = page.getByRole('dialog', { name: 'Cancel this sale?' })
  await cancel.getByRole('textbox', { name: 'Reason' }).fill('Sold by mistake')
  await cancel.getByRole('button', { name: 'Cancel sale' }).click()
  await expect(row).toContainText('Cancelled')
})
