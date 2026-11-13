import { expect, test, type Page } from '@playwright/test'
import { scanAfter } from './a11y'

const scan = scanAfter(/Loading|Checking/)

// Seeded demo data (docs/dev/demo-accounts.md): the Front desk register at Courtside Downtown and a stocked
// "Water 500 ml" with barcode 0001000500.
const ADMIN = { email: 'admin@courtside-demo.example.com', password: 'courtside-demo-2026' }

async function signIn(page: Page, path: string) {
  await page.goto(path)
  await page.getByRole('textbox', { name: 'Email' }).fill(ADMIN.email)
  await page.getByRole('textbox', { name: 'Password' }).fill(ADMIN.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('button', { name: /account menu/i })).toBeVisible()
}

async function openRegister(page: Page) {
  await signIn(page, '/pos')
  await expect(page.getByRole('heading', { level: 1, name: 'Front desk' })).toBeVisible()
  const open = page.getByRole('button', { name: 'Open drawer' })
  if (await open.isVisible()) {
    await open.click()
    await expect(open).toBeHidden()
  }
  // A cart left by an earlier failed run would block the flow below: abandon it.
  const abandon = page.getByRole('button', { name: 'Abandon sale' })
  if (await abandon.isEnabled({ timeout: 1000 }).catch(() => false)) {
    await abandon.click()
    await expect(page.getByText('Scan an item or pick one to start a sale.')).toBeVisible()
  }
}

test('a walk-in sale by barcode scan, paid in cash, printed and partly returned', async ({ page }) => {
  await openRegister(page)
  const barcode = page.getByRole('textbox', { name: 'Scan or type a barcode' })
  await barcode.fill('0001000500')
  await barcode.press('Enter') // what a keyboard-wedge scanner sends
  const cart = page.getByRole('table', { name: 'Items in the cart' })
  await expect(cart.getByRole('cell', { name: 'Water 500 ml', exact: true })).toBeVisible()
  await expect(barcode).toHaveValue('')
  await barcode.fill('0001000500')
  await barcode.press('Enter')
  await expect(cart.getByRole('textbox', { name: 'Quantity of Water 500 ml' })).toHaveValue('2')
  await scan(page, 'register with a cart')

  await page.getByRole('textbox', { name: 'Cash handed over' }).fill('20')
  await expect(page.getByText(/Change due/)).toBeVisible()
  await page.getByRole('button', { name: /^Take / }).click()
  await expect(page.getByRole('list', { name: 'Tenders' })).toContainText('Taken')
  await page.getByRole('button', { name: 'Complete sale' }).click()
  const done = page.getByRole('status').filter({ hasText: /Sale #\d+ complete/ })
  await expect(done).toBeVisible()
  await scan(page, 'register after a sale')

  await done.getByRole('link', { name: 'Print receipt' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Courtside Downtown' })).toBeVisible()
  await expect(page.getByText(/2 × Water 500 ml/)).toBeVisible()
  await scan(page, 'printable receipt')

  await page.getByRole('link', { name: 'Back to the sale' }).click()
  await expect(page.getByRole('heading', { level: 1, name: /Sale #\d+/ })).toBeVisible()
  await page.getByRole('button', { name: 'Return items' }).click()
  const dialog = page.getByRole('dialog', { name: /Return items/ })
  await dialog.getByRole('textbox', { name: /Water 500 ml/ }).fill('1')
  await scan(page, 'return dialog')
  await dialog.getByRole('button', { name: 'Return items' }).click()
  await expect(dialog).toBeHidden()
  await expect(page.getByRole('table', { name: 'Returns' })).toBeVisible()
  await expect(page.getByText('Part returned').first()).toBeVisible()
})

test('every POS screen passes the axe WCAG 2.1 AA scan', async ({ page }) => {
  test.setTimeout(180_000)
  await openRegister(page)
  for (const colorScheme of ['light', 'dark'] as const) {
    await page.emulateMedia({ colorScheme })
    for (const path of ['/pos', '/pos/sales', '/pos/products', '/pos/equipment', '/pos/drawers', '/pos/reports', '/pos/setup']) {
      await page.goto(path)
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
      await scan(page, `${colorScheme} ${path}`)
    }
  }
  await page.emulateMedia({ colorScheme: 'light' })
  await page.goto('/pos/setup')
  for (const tab of ['Settings', 'Categories', 'Brands', 'Suppliers', 'Discount presets']) {
    await page.getByRole('tab', { name: tab }).click()
    await scan(page, `setup tab ${tab}`)
  }
  await page.goto('/pos/reports')
  for (const tab of ['Daily register', 'Reorder', 'Returns']) {
    await page.getByRole('tab', { name: tab }).click()
    await scan(page, `report tab ${tab}`)
  }
  await page.goto('/pos/products')
  await page.getByRole('button', { name: 'New product' }).click()
  await scan(page, 'new product dialog')
  await page.getByRole('button', { name: 'Cancel' }).click()
  await page.getByRole('button', { name: 'Stock of Water 500 ml' }).click()
  await expect(page.getByRole('table', { name: 'Stock by location' })).toBeVisible()
  await scan(page, 'stock dialog')
  await page.getByRole('button', { name: 'Cancel' }).click()
  await page.goto('/pos/equipment')
  await page.getByRole('tab', { name: 'Items' }).click()
  await expect(page.getByText('Demo racket (RKT-01)')).toBeVisible()
  await scan(page, 'equipment items')
})
