import { expect, test, type Page } from '@playwright/test'
import { scanAfter } from './a11y'

// Client-side navigation never re-fires the document's networkidle; wait for our loading states instead.
const scan = scanAfter(/Loading|Checking/)

// Seeded demo data (docs/dev/demo-accounts.md): Morgan Member is M-1001; payments use the fake processor.
const ADMIN = { email: 'admin@courtside-demo.example.com', password: 'courtside-demo-2026' }

async function signIn(page: Page, path: string) {
  await page.goto(path)
  await page.getByRole('textbox', { name: 'Email' }).fill(ADMIN.email)
  await page.getByRole('textbox', { name: 'Password' }).fill(ADMIN.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('button', { name: /account menu/i })).toBeVisible()
}

async function openMorgan(page: Page) {
  await page.goto('/billing/clients')
  await page.getByRole('combobox', { name: 'Client' }).fill('m-1001')
  await page.getByRole('option', { name: /Morgan Member/ }).click()
  await expect(page.getByRole('heading', { level: 1, name: /Billing: Morgan Member/ })).toBeVisible()
}

async function addItem(page: Page, description: string, price: string) {
  await page.getByRole('tab', { name: 'Items' }).click()
  await page.getByRole('button', { name: 'Add item' }).click()
  const dialog = page.getByRole('dialog', { name: 'Add billing item' })
  await dialog.getByRole('textbox', { name: 'Description', exact: true }).fill(description)
  await dialog.getByRole('textbox', { name: 'Unit price' }).fill(price)
  await expect(dialog.getByRole('status')).toContainText('Net')
  await dialog.getByRole('button', { name: 'Add item' }).click()
  await expect(dialog).toBeHidden()
  await page.getByRole('combobox', { name: 'Show' }).selectOption('uninvoiced')
  await expect(page.getByRole('table', { name: 'Billing items' }).getByText(description)).toBeVisible()
}

async function invoiceItem(page: Page, description: string) {
  await page.getByRole('checkbox', { name: `Select ${description}` }).check()
  await page.getByRole('button', { name: /Invoice selected/ }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Create invoice' }).click()
  await expect(page).toHaveURL(/\/billing\/invoices\/[0-9a-f-]{36}$/)
  await expect(page.getByRole('heading', { level: 1, name: /Invoice #\d+/ })).toBeVisible()
}

test('staff bill a client, take a split-tender payment and refund part of it', async ({ page }) => {
  const item = `Restring ${Date.now()}`
  await signIn(page, '/billing')
  await openMorgan(page)
  await addItem(page, item, '25.00')
  await invoiceItem(page, item)
  await expect(page.getByRole('table', { name: /Items on invoice/ }).getByText(item)).toBeVisible()

  // Split tender: 10.00 cash, the rest on the fake processor's approved test card (no card number typed).
  await page.getByRole('button', { name: 'Take payment' }).click()
  const pay = page.getByRole('dialog', { name: 'Take payment' })
  await pay.getByRole('combobox', { name: 'Tender' }).selectOption({ label: 'Cash' })
  const total = await pay.getByRole('textbox', { name: 'Amount' }).inputValue()
  await pay.getByRole('textbox', { name: 'Amount' }).fill('10.00')
  await pay.getByRole('button', { name: 'Add tender' }).click()
  const second = pay.getByRole('group', { name: 'Tender 2' })
  await second.getByRole('combobox', { name: 'Tender' }).selectOption({ label: 'Card' })
  await expect(second.getByRole('textbox', { name: 'Amount' })).toHaveValue((Number(total) - 10).toFixed(2))
  await second.getByRole('textbox', { name: 'Amount' }).fill((Number(total) - 8).toFixed(2)) // 2.00 over: account credit
  await expect(pay.getByText(/goes to account credit/)).toBeVisible()
  await expect(second.getByText('Test processor: development only')).toBeVisible()
  await second.getByRole('combobox', { name: 'New payment method' }).selectOption('tok_card_ok')
  await scan(page, 'take payment dialog')
  await pay.getByRole('button', { name: 'Take payment' }).click()
  await expect(pay).toBeHidden()
  await expect(page.getByText('Paid', { exact: true }).first()).toBeVisible() // the status badge in the header

  // Refund part of the overpayment back to the card.
  await page.goBack()
  await page.getByRole('tab', { name: 'Payments' }).click()
  await page.getByRole('table', { name: 'Payments' }).getByRole('row', { name: /Card/ }).first().getByRole('link').click()
  await expect(page.getByRole('heading', { level: 1, name: /Payment #\d+/ })).toBeVisible()
  await page.getByRole('button', { name: 'Refund' }).click()
  const refund = page.getByRole('dialog', { name: /Refund payment/ })
  await expect(refund.getByRole('textbox', { name: 'Amount' })).toHaveValue('2.00') // only unapplied money
  await refund.getByRole('textbox', { name: 'Amount' }).fill('1.00')
  await refund.getByRole('textbox', { name: 'Reason' }).fill('Goodwill')
  await refund.getByRole('button', { name: 'Refund' }).click()
  await expect(refund).toBeHidden()
  await expect(page.getByRole('table', { name: 'Refunds' }).getByText('Goodwill')).toBeVisible()
})

test('a declined test card says so and leaves the invoice open; voiding needs a reason', async ({ page }) => {
  const item = `Locker ${Date.now()}`
  await signIn(page, '/billing')
  await openMorgan(page)
  await addItem(page, item, '5.00')
  await invoiceItem(page, item)
  await page.getByRole('button', { name: 'Take payment' }).click()
  const pay = page.getByRole('dialog', { name: 'Take payment' })
  await pay.getByRole('combobox', { name: 'Tender' }).selectOption({ label: 'Card' })
  await pay.getByRole('combobox', { name: 'New payment method' }).selectOption('tok_card_declined')
  await pay.getByRole('button', { name: 'Take payment' }).click()
  await expect(pay.getByRole('alert')).toBeVisible()
  await pay.getByRole('button', { name: 'Cancel' }).click()

  await page.getByRole('button', { name: 'Void invoice' }).click()
  const dialog = page.getByRole('dialog', { name: /Void invoice/ })
  await dialog.getByRole('button', { name: 'Void invoice' }).click()
  await expect(dialog.getByText('A reason is required.')).toBeVisible()
  await dialog.getByRole('textbox', { name: 'Reason' }).fill('Entered twice')
  await dialog.getByRole('button', { name: 'Void invoice' }).click()
  await expect(page.getByText('Voided: Entered twice')).toBeVisible()
})

test('bulk invoicing previews before it creates', async ({ page }) => {
  const item = `Guest pass ${Date.now()}`
  await signIn(page, '/billing')
  await openMorgan(page)
  await addItem(page, item, '8.00')
  await page.goto('/billing')
  await page.getByRole('searchbox', { name: 'Search' }).fill(item)
  await page.getByRole('checkbox', { name: `Select ${item}` }).check()
  await page.getByRole('button', { name: /Invoice selected \(1\)/ }).click()
  const dialog = page.getByRole('dialog', { name: 'Invoice items in bulk' })
  await dialog.getByRole('button', { name: 'Preview' }).click()
  await expect(dialog.getByRole('table', { name: 'Invoices that would be created' })).toContainText('Will be invoiced')
  await dialog.getByRole('button', { name: 'Create invoices' }).click()
  await expect(dialog.getByRole('link', { name: 'Invoice created' })).toBeVisible()
})

test('bulk reverse takes one reason for the selected items', async ({ page }) => {
  const item = `Locker fee ${Date.now()}`
  await signIn(page, '/billing')
  await openMorgan(page)
  await addItem(page, item, '5.00')
  await page.goto('/billing')
  await page.getByRole('searchbox', { name: 'Search' }).fill(item)
  await page.getByRole('checkbox', { name: `Select ${item}` }).check()
  await page.getByRole('button', { name: /Reverse selected \(1\)/ }).click()
  const dialog = page.getByRole('dialog', { name: 'Reverse items in bulk' })
  await scan(page, 'bulk reverse dialog')
  await dialog.getByRole('textbox', { name: 'Reason' }).fill('Entered twice')
  await dialog.getByRole('button', { name: 'Reverse items' }).click()
  await expect(page.getByText('1 reversed.')).toBeVisible()
})

test('every billing screen passes the axe WCAG 2.1 AA scan', async ({ page }) => {
  test.setTimeout(180_000) // about forty scans
  await signIn(page, '/billing')
  for (const colorScheme of ['light', 'dark'] as const) {
    await page.emulateMedia({ colorScheme })
    for (const path of ['/billing', '/billing/clients', '/billing/autopay', '/billing/receivables', '/billing/coupons', '/billing/setup', '/billing/settings']) {
      await page.goto(path)
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
      await scan(page, `${colorScheme} ${path}`)
    }
  }
  // Tabs and detail pages, reached the way a person reaches them.
  await openMorgan(page)
  for (const tab of ['Items', 'Invoices', 'Payments', 'Account history', 'Payment methods & autopay', 'Account credit', 'Statement']) {
    await page.getByRole('tab', { name: tab }).click()
    await scan(page, `client tab ${tab}`)
  }
  await page.getByRole('tab', { name: 'Invoices' }).click()
  await page.getByRole('table', { name: 'Invoices' }).getByRole('link').first().click()
  await expect(page.getByRole('heading', { level: 1, name: /Invoice #/ })).toBeVisible()
  await scan(page, '/billing/invoices/:id')
  await page.getByRole('link', { name: 'Print view' }).click()
  await expect(page.getByRole('heading', { level: 1, name: /Invoice #/ })).toBeVisible()
  await scan(page, '/billing/invoices/:id/document')
  await page.goto('/billing')
  await page.getByRole('tab', { name: 'Payments', exact: true }).click()
  await page.getByRole('table', { name: 'Payments' }).getByRole('link').first().click()
  await expect(page.getByRole('heading', { level: 1, name: /Payment #/ })).toBeVisible()
  await scan(page, '/billing/payments/:id')
  await page.getByRole('link', { name: 'Receipt' }).click()
  await expect(page.getByRole('heading', { level: 1, name: /Receipt #/ })).toBeVisible()
  await scan(page, '/billing/payments/:id/receipt')
  await page.goto('/billing/setup')
  for (const tab of ['Revenue categories', 'Tenders', 'Processor']) {
    await page.getByRole('tab', { name: tab }).click()
    await scan(page, `setup tab ${tab}`)
  }
  await page.goto('/billing/autopay')
  await page.getByRole('button', { name: 'Run autopay now' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Preview' }).click()
  await expect(page.getByRole('dialog').getByRole('status')).toContainText('invoices')
  await scan(page, 'autopay preview dialog')
  await page.getByRole('dialog').getByRole('button', { name: 'Cancel' }).click()
  await page.getByRole('tab', { name: 'Error queue' }).click()
  await scan(page, 'autopay error queue')
  await page.goto('/pay#token=not-a-real-token') // the public pay page, in its expired-link state
  await expect(page.getByRole('heading', { level: 1, name: 'Pay your invoice' })).toBeVisible()
  await expect(page.getByText(/expired or was already used/)).toBeVisible()
  await scan(page, '/pay')
})
