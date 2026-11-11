import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

// One client through four modules, as front-desk staff would do it: create the client, sell a membership that
// needs a waiver, sign the waiver, book a court, take the payment and find it on the invoice. Seeded demo data
// (docs/dev/demo-accounts.md): the "Court club monthly" plan is bound to the Liability waiver; Court 1 at
// Courtside Downtown rents on the Standard rate.
const OWNER = { email: 'owner@courtside-demo.example.com', password: 'courtside-demo-2026' }

async function scan(page: Page, label: string) {
  const axe = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  expect(axe.violations.map((v) => `${label} ${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`)).toEqual([])
}

test.use({ actionTimeout: 10_000 }) // a missing control fails at its own line, not at the test timeout

// A fresh client and a free court hour on every run.
const stamp = Date.now().toString(36)
const person = { first: 'Jordan', last: `Journey-${stamp}` }
const day = new Date(Date.now() + (700 + Math.floor(Math.random() * 300)) * 86400000).toISOString().slice(0, 10)
const hour = String(7 + Math.floor(Math.random() * 12)).padStart(2, '0')

test('a new client buys a membership with a waiver, books a court, pays, and the invoice shows it', async ({ page }) => {
  test.setTimeout(120_000)
  await page.goto('/clients')
  await page.getByRole('textbox', { name: 'Email' }).fill(OWNER.email)
  await page.getByRole('textbox', { name: 'Password' }).fill(OWNER.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Clients' })).toBeVisible()

  // 1. Create the client.
  await page.getByRole('button', { name: 'Add client' }).click()
  const add = page.getByRole('dialog', { name: 'Add a client' })
  await add.getByLabel('First name').fill(person.first)
  await add.getByLabel('Last name').fill(person.last)
  await add.getByLabel('Home location').selectOption({ label: 'Courtside Downtown' })
  await add.getByRole('button', { name: 'Add client' }).click()
  await expect(page.getByRole('heading', { level: 1, name: `${person.first} ${person.last}` })).toBeVisible()

  // 2. Sell the membership: it is billed at once and waits for the waiver.
  await page.getByRole('tab', { name: 'Memberships' }).click()
  await page.getByRole('button', { name: 'Sell membership' }).click()
  const sell = page.getByRole('dialog')
  await sell.getByLabel('Plan').selectOption({ label: 'Court club monthly · $45.00' })
  await expect(sell.getByRole('region', { name: 'Quote' })).toContainText('Liability waiver')
  await sell.getByRole('button', { name: 'Sell membership' }).click()
  await expect(sell).toBeHidden()
  await expect(page.getByText('Waiting for document')).toBeVisible()
  await scan(page, 'membership waiting for its waiver')

  // 3. The client signs the waiver at the desk.
  await page.getByRole('tab', { name: 'Documents' }).click()
  await page.getByRole('button', { name: 'Sign now' }).first().click()
  await page.getByLabel('Typed signature').fill(`${person.first} ${person.last}`)
  await page.getByRole('checkbox', { name: /agree to its terms/ }).check()
  await page.getByRole('button', { name: 'Sign document' }).click()
  await expect(page.getByText(/^Waiver on file/)).toBeVisible()

  // 4. Book a court for them, billed on a new invoice.
  await page.goto('/rentals')
  await page.getByRole('button', { name: 'New rental' }).click()
  const rent = page.getByRole('dialog', { name: 'New rental' })
  await rent.getByRole('combobox', { name: 'Client' }).fill(person.last)
  await page.getByRole('option', { name: new RegExp(person.last) }).first().click()
  await rent.getByRole('combobox', { name: 'Resource' }).selectOption({ label: 'Court 1' })
  await rent.getByLabel('Date').fill(day)
  await rent.getByLabel('Start').fill(`${hour}:00`)
  await rent.getByLabel('End').fill(`${hour}:30`)
  await rent.getByRole('combobox', { name: 'Rate' }).selectOption({ label: 'Standard' })
  await rent.getByRole('button', { name: 'Preview price' }).click()
  await expect(rent.getByRole('status')).toHaveText('1 of 1 time is free.')
  const booked = page.waitForResponse((r) => r.url().endsWith('/api/v1/rentals') && r.request().method() === 'POST')
  await rent.getByRole('button', { name: 'Book rental' }).click()
  const { invoice_ids } = (await (await booked).json()) as { invoice_ids: string[] }
  await expect(rent).toBeHidden()
  expect(invoice_ids).toHaveLength(1)

  // 5. Their profile now lists two invoices: the membership and the court. Open the court's and take payment.
  await page.goto('/clients')
  await page.getByRole('searchbox', { name: 'Search' }).fill(person.last)
  await page.getByRole('link', { name: `${person.first} ${person.last}` }).click()
  await page.getByRole('tab', { name: 'Billing' }).click()
  const invoices = page.getByRole('table', { name: 'Invoices' })
  await expect(invoices.getByRole('row')).toHaveCount(3) // header + membership + court
  await scan(page, 'client billing tab')
  await page.goto(`/billing/invoices/${invoice_ids[0]}`)
  await expect(page.getByRole('table', { name: /Items on invoice/ })).toContainText('Court rental: Standard')
  await page.getByRole('button', { name: 'Take payment' }).click()
  const pay = page.getByRole('dialog', { name: 'Take payment' })
  await pay.getByRole('combobox', { name: 'Tender' }).selectOption({ label: 'Cash' })
  const due = await pay.getByRole('textbox', { name: 'Amount' }).inputValue()
  expect(Number(due)).toBeGreaterThan(0)
  await pay.getByRole('button', { name: 'Take payment' }).click()
  await expect(pay).toBeHidden()

  // 6. The invoice shows it: paid in full, nothing left to pay.
  await expect(page.getByText('Paid', { exact: true }).first()).toBeVisible()
  await scan(page, 'paid court invoice')
  await page.goto('/clients')
  await page.getByRole('searchbox', { name: 'Search' }).fill(person.last)
  await page.getByRole('link', { name: `${person.first} ${person.last}` }).click()
  await page.getByRole('tab', { name: 'Billing' }).click()
  await expect(page.getByRole('table', { name: 'Payments' })).toContainText(due)
})
