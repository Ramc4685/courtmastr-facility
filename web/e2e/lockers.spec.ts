import { expect as baseExpect, test, type Page } from '@playwright/test'
import { scanAfter } from './a11y'

const scan = scanAfter(/…$/, 30_000)

const expect = baseExpect.configure({ timeout: 30_000 })

// Seeded demo data (docs/dev/demo-accounts.md, "Demo lockers"): a 20-locker room at Downtown with two leases,
// padlock PL-01 on locker 1, and the "10-hour court pack" rental plan sold to Okafor.
const ADMIN = { email: 'admin@courtside-demo.example.com', password: 'courtside-demo-2026' }

async function signIn(page: Page, path: string) {
  await page.goto(path)
  await page.getByRole('textbox', { name: 'Email' }).fill(ADMIN.email)
  await page.getByRole('textbox', { name: 'Password' }).fill(ADMIN.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
}

test('a locker is rented and cleared, a padlock combination is revealed, and every screen passes axe', async ({ page }) => {
  test.setTimeout(180_000)
  await signIn(page, '/lockers')
  await expect(page.getByRole('heading', { level: 1, name: 'Lockers' })).toBeVisible()
  const board = page.getByRole('table', { name: 'Lockers' })
  await expect(board).toContainText('PL-01')
  await scan(page, 'locker board')

  const rent = page.getByRole('button', { name: /^Rent locker \d+$/ }).first()
  const number = ((await rent.getAttribute('aria-label')) ?? '').replace('Rent locker ', '')
  await rent.click()
  const dialog = page.getByRole('dialog', { name: `Rent locker ${number}` })
  await dialog.getByRole('combobox', { name: 'Client' }).fill('Reyes')
  await page.getByRole('option', { name: /Reyes/ }).first().click()
  await dialog.getByRole('combobox', { name: 'Term', exact: true }).selectOption('day')
  await scan(page, 'rent locker dialog')
  await dialog.getByRole('button', { name: 'Rent locker' }).click()
  await expect(dialog).toBeHidden()
  await expect(page.getByRole('button', { name: `Renew locker ${number}` })).toBeVisible()

  await page.getByRole('button', { name: `Renew locker ${number}` }).click()
  await scan(page, 'renew locker dialog')
  await page.getByRole('dialog', { name: `Renew locker ${number}` }).getByRole('button', { name: 'Cancel' }).click()

  await page.getByRole('button', { name: `Clear locker ${number}` }).click()
  await scan(page, 'clear locker dialog')
  await page.getByRole('dialog', { name: `Clear locker ${number}?` }).getByRole('button', { name: 'Clear locker' }).click()
  await expect(page.getByRole('button', { name: `Rent locker ${number}` })).toBeVisible()

  await page.getByRole('tab', { name: 'Setup' }).click()
  await expect(page.getByRole('table', { name: 'Locker rooms' })).toContainText('Main locker room')
  await scan(page, 'locker setup')
  await page.getByRole('button', { name: 'Reveal combination of padlock PL-01' }).click()
  await expect(page.getByRole('table', { name: 'Padlocks' })).toContainText('12-24-36')
  await page.getByRole('button', { name: 'New padlock' }).click()
  await scan(page, 'new padlock dialog')
  await page.getByRole('dialog', { name: 'New padlock' }).getByRole('button', { name: 'Cancel' }).click()
  await page.getByRole('button', { name: 'New locker term' }).click()
  await scan(page, 'new locker term dialog')
  await page.getByRole('dialog', { name: 'New locker term' }).getByRole('button', { name: 'Cancel' }).click()
  await page.getByRole('button', { name: 'New locker room' }).click()
  await scan(page, 'new locker room dialog')
})

test('a sold rental plan is managed: renewal, autopay and sharing', async ({ page }) => {
  await signIn(page, '/rentals/setup')
  await expect(page.getByRole('heading', { level: 1, name: 'Rental setup' })).toBeVisible()
  await page.getByRole('tab', { name: 'Rental plans' }).click()
  await page.getByRole('button', { name: 'Edit 10-hour court pack' }).click()
  const edit = page.getByRole('dialog', { name: 'Edit 10-hour court pack' })
  await expect(edit.getByRole('checkbox', { name: 'Shareable with related clients' })).toBeChecked()
  await scan(page, 'plan dialog with renewal options')
  await edit.getByRole('button', { name: 'Cancel' }).click()
  await page.getByRole('tab', { name: 'Plans sold' }).click()
  await page.getByRole('button', { name: /^Manage 10-hour court pack/ }).first().click()
  const manage = page.getByRole('dialog', { name: 'Manage 10-hour court pack' })
  await expect(manage.getByRole('checkbox', { name: 'Renews automatically' })).toBeVisible()
  await expect(manage.getByRole('group', { name: 'Shared with' })).toBeVisible()
  await scan(page, 'manage sold plan dialog')
  await manage.getByRole('button', { name: 'Save' }).click()
  await expect(manage).toBeHidden()
})
