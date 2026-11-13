import { expect as baseExpect, test, type Page } from '@playwright/test'
import { scan } from './a11y'

const expect = baseExpect.configure({ timeout: 30_000 })

// Seeded demo data (docs/dev/demo-accounts.md): Morgan Member (M-1001) has invoices at the demo location and
// signs in to the portal; emails go to Mailpit, so sending statements reaches no real inbox.
const ADMIN = { email: 'admin@courtside-demo.example.com', password: 'courtside-demo-2026' }
const MEMBER = { email: 'member@courtside-demo.example.com', password: 'courtside-demo-2026' }

// Statements cover at most 366 days.
const FROM = new Date(Date.now() - 300 * 86_400_000).toISOString().slice(0, 10)

async function signIn(page: Page, path: string, who: typeof ADMIN) {
  await page.goto(path)
  await page.getByRole('textbox', { name: 'Email' }).fill(who.email)
  await page.getByRole('textbox', { name: 'Password' }).fill(who.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
}

async function pdf(page: Page, button: ReturnType<Page['getByRole']>) {
  const [download] = await Promise.all([page.waitForEvent('download'), button.click()])
  expect(download.suggestedFilename()).toMatch(/\.pdf$/)
  const path = await download.path()
  const fs = await import('node:fs')
  expect(fs.readFileSync(path).subarray(0, 5).toString()).toBe('%PDF-')
}

test('staff send a statement batch, follow each recipient and download a statement PDF', async ({ page }) => {
  test.setTimeout(120_000)
  await signIn(page, '/billing/statements', ADMIN)
  await expect(page.getByRole('heading', { level: 1, name: 'Statements' })).toBeVisible()
  await scan(page, '/billing/statements')

  await page.getByRole('button', { name: 'Send statements' }).click()
  const dialog = page.getByRole('dialog', { name: 'Send statements' })
  await dialog.getByLabel('From').fill(FROM)
  await scan(page, '/billing/statements dialog')
  await dialog.getByRole('button', { name: 'Send statements' }).click()
  await expect(dialog).toBeHidden()

  const recipients = page.getByRole('table', { name: 'Statement recipients' })
  await expect(recipients.getByText('Morgan Member')).toBeVisible()
  await expect(recipients.getByText('Sent').first()).toBeVisible()
  await scan(page, '/billing/statements detail')
  await page.getByRole('button', { name: 'Resend to Morgan Member' }).click()
  await expect(page.getByText(/^Resent:/)).toBeVisible()

  await page.goto('/billing/clients')
  await page.getByRole('combobox', { name: 'Client' }).fill('m-1001')
  await page.getByRole('option', { name: /Morgan Member/ }).click()
  await page.getByRole('tab', { name: 'Statement' }).click()
  await pdf(page, page.getByRole('button', { name: 'Download PDF' }))
})

test('a member reads their statement and downloads it and an invoice as PDF', async ({ page }) => {
  test.setTimeout(120_000)
  await signIn(page, '/sign-in?as=member', MEMBER)
  await expect(page).toHaveURL(/\/portal$/)
  await page.goto(`/portal/statement?from_on=${FROM}`)
  await expect(page.getByRole('heading', { level: 1, name: 'Statement' })).toBeVisible()
  await expect(page.getByRole('table', { name: 'Invoices in the period' })).toBeVisible()
  await scan(page, '/portal/statement')
  await pdf(page, page.getByRole('button', { name: 'Download PDF' }))

  await page.getByRole('navigation', { name: 'Portal' }).getByRole('link', { name: 'Invoices' }).click()
  await page.getByRole('button', { name: /^View invoice/ }).first().click()
  await scan(page, '/portal/invoices dialog')
  await pdf(page, page.getByRole('dialog').getByRole('button', { name: 'Download PDF' }))
})
