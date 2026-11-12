import AxeBuilder from '@axe-core/playwright'
import { expect as baseExpect, test, type Page } from '@playwright/test'

// PAY-11 and PAY-18 on the fake processor: a card that needs 3-D Secure at the desk, and a member paying
// part of an invoice in the portal through the bank check. Seeded data: docs/dev/demo-accounts.md.
const expect = baseExpect.configure({ timeout: 30_000 })
const PASSWORD = 'courtside-demo-2026'
const ADMIN = 'admin@courtside-demo.example.com'
const MEMBER = 'member@courtside-demo.example.com'

async function scan(page: Page, label: string) {
  await expect(page.getByRole('status').filter({ hasText: /Loading|Checking|Preparing|…$/ })).toHaveCount(0)
  const axe = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  expect(axe.violations.map((v) => `${label} ${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`)).toEqual([])
}

/** Staff bill Morgan Member one item and open its invoice; returns the invoice number. */
async function billMorgan(page: Page, description: string, price: string) {
  await page.goto('/billing/clients')
  await page.getByRole('textbox', { name: 'Email' }).fill(ADMIN)
  await page.getByRole('textbox', { name: 'Password' }).fill(PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('button', { name: /account menu/i })).toBeVisible()
  await page.getByRole('combobox', { name: 'Client' }).fill('m-1001')
  await page.getByRole('option', { name: /Morgan Member/ }).click()
  await page.getByRole('tab', { name: 'Items' }).click()
  await page.getByRole('button', { name: 'Add item' }).click()
  const add = page.getByRole('dialog', { name: 'Add billing item' })
  await add.getByRole('textbox', { name: 'Description', exact: true }).fill(description)
  await add.getByRole('textbox', { name: 'Unit price' }).fill(price)
  await expect(add.getByRole('status')).toContainText('Net')
  await add.getByRole('button', { name: 'Add item' }).click()
  await expect(add).toBeHidden()
  await page.getByRole('combobox', { name: 'Show' }).selectOption('uninvoiced')
  await page.getByRole('checkbox', { name: `Select ${description}` }).check()
  await page.getByRole('button', { name: /Invoice selected/ }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Create invoice' }).click()
  const heading = page.getByRole('heading', { level: 1, name: /Invoice #\d+/ })
  await expect(heading).toBeVisible()
  return (await heading.textContent())?.match(/#(\d+)/)?.[1] ?? ''
}

test('desk: a card that needs authentication goes through the bank check and pays the invoice', async ({ page }) => {
  test.setTimeout(180_000)
  await billMorgan(page, `Grip ${Date.now()}`, '6.00')
  await page.getByRole('button', { name: 'Take payment' }).click()
  const pay = page.getByRole('dialog', { name: 'Take payment' })
  await pay.getByRole('combobox', { name: 'Tender' }).selectOption({ label: 'Card' })
  await pay.getByRole('combobox', { name: 'New payment method' }).selectOption('tok_card_auth')
  await pay.getByRole('button', { name: 'Take payment' }).click()
  await expect(pay.getByRole('button', { name: 'Approve as the bank (test)' })).toBeVisible()
  await scan(page, 'take payment bank check')
  await pay.getByRole('button', { name: 'Approve as the bank (test)' }).click()
  await expect(pay.getByRole('button', { name: 'Approve as the bank (test)' })).toBeHidden() // confirmed and applied
  await pay.getByRole('button', { name: 'Continue' }).click()
  await expect(pay).toBeHidden()
  await expect(page.getByText('Paid', { exact: true }).first()).toBeVisible()
})

test('portal: a member pays part of an invoice through the bank check and gets a receipt', async ({ browser }) => {
  test.setTimeout(240_000)
  const staff = await browser.newContext()
  const number = await billMorgan(await staff.newPage(), `Balls ${Date.now()}`, '9.00')
  await staff.close()

  const member = await browser.newContext()
  const page = await member.newPage()
  await page.goto('/portal')
  await page.getByRole('textbox', { name: 'Email' }).fill(MEMBER)
  await page.getByRole('textbox', { name: 'Password' }).fill(PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Hello, Morgan' })).toBeVisible()
  await page.getByRole('navigation', { name: 'Portal' }).getByRole('link', { name: 'Invoices' }).click()
  await page.getByRole('button', { name: `Pay invoice ${number}`, exact: true }).click()
  const pay = page.getByRole('dialog', { name: `Pay invoice #${number}` })
  await pay.getByRole('textbox', { name: /Amount/ }).fill('20.00')
  await expect(pay.getByText(/is owed/)).toBeVisible() // never more than the balance
  await pay.getByRole('textbox', { name: /Amount/ }).fill('4.00')
  await pay.getByRole('combobox', { name: 'Pay with' }).selectOption('new')
  await pay.getByRole('combobox', { name: 'Card' }).selectOption('tok_card_auth')
  await scan(page, 'portal pay dialog')
  await pay.getByRole('button', { name: 'Pay $4.00' }).click()
  await expect(pay.getByRole('button', { name: 'Approve as the bank (test)' })).toBeVisible()
  await scan(page, 'portal bank check')
  await pay.getByRole('button', { name: 'Approve as the bank (test)' }).click()
  await expect(pay.getByRole('status')).toContainText('$4.00 paid')
  await expect(pay.getByRole('button', { name: 'Download receipt' })).toBeVisible()
  await pay.getByRole('button', { name: 'Done' }).click()
  await expect(page.getByRole('table', { name: 'Invoices' }).getByRole('row', { name: new RegExp(`#${number}\\b`) })).toContainText('$5.00')
  await member.close()
})
