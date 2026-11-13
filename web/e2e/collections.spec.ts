import { expect as baseExpect, test, type Page } from '@playwright/test'
import { scanAfter } from './a11y'

const scan = scanAfter(/Loading|…$/, 30_000)

const expect = baseExpect.configure({ timeout: 30_000 })

// Seeded demo data (docs/dev/demo-accounts.md): Morgan Member (M-1001) at the demo location.
const ADMIN = { email: 'admin@courtside-demo.example.com', password: 'courtside-demo-2026' }

async function signIn(page: Page, path: string) {
  await page.goto(path)
  await page.getByRole('textbox', { name: 'Email' }).fill(ADMIN.email)
  await page.getByRole('textbox', { name: 'Password' }).fill(ADMIN.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
}

test('staff tag a client for collections, see them on the report, and read notices and expiring cards', async ({ page }) => {
  test.setTimeout(120_000)
  const tag = `Payment plan ${Date.now()}` // tag names are unique per tenant, and the seed is reused across runs
  await signIn(page, '/billing/collections')
  await expect(page.getByRole('heading', { level: 1, name: 'Collections' })).toBeVisible()
  await page.getByRole('button', { name: 'New tag' }).click()
  const tagDialog = page.getByRole('dialog', { name: 'New collections tag' })
  await tagDialog.getByLabel(/Name/).fill(tag)
  await scan(page, '/billing/collections tag dialog')
  await tagDialog.getByRole('button', { name: 'Save tag' }).click()
  await expect(tagDialog).toBeHidden()
  await scan(page, '/billing/collections')

  await page.goto('/billing/clients')
  await page.getByRole('combobox', { name: 'Client' }).fill('m-1001')
  await page.getByRole('option', { name: /Morgan Member/ }).click()
  await page.getByRole('tab', { name: 'Collections' }).click()
  await page.getByRole('button', { name: /Place in collections|Change/ }).click()
  const profile = page.getByRole('dialog', { name: 'Collections profile' })
  await profile.getByLabel(/Tag/).selectOption({ label: tag })
  await profile.getByLabel('Notes').fill('Agreed to pay in two parts')
  await scan(page, 'collections profile dialog')
  await profile.getByRole('button', { name: 'Save' }).click()
  await expect(profile).toBeHidden()
  await expect(page.getByText('Agreed to pay in two parts')).toBeVisible()

  await page.goto('/billing/collections')
  const report = page.getByRole('table', { name: 'Clients in collections' })
  await expect(report.getByText(tag)).toBeVisible()
  await expect(report.getByText('Morgan Member')).toBeVisible()

  await page.goto('/billing/notices')
  await expect(page.getByRole('heading', { level: 1, name: 'Notices' })).toBeVisible()
  await scan(page, '/billing/notices')
  await page.goto('/billing/expiring-cards')
  await expect(page.getByRole('heading', { level: 1, name: 'Expiring cards' })).toBeVisible()
  await page.getByRole('checkbox', { name: 'Autopay cards only' }).check()
  await scan(page, '/billing/expiring-cards')
})
