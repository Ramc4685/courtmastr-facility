import AxeBuilder from '@axe-core/playwright'
import { expect as baseExpect, test, type Page } from '@playwright/test'

// Generous waits: the API and Vite share a busy development machine with other lanes.
const expect = baseExpect.configure({ timeout: 30_000 })

// Seeded demo data (docs/dev/demo-accounts.md): Morgan Member signs in to the portal, acts for Mia, holds a
// stored test card, has open invoices, and "Ten private lessons" and "Court rental" are sold online.
const MEMBER = { email: 'member@courtside-demo.example.com', password: 'courtside-demo-2026' }

async function scan(page: Page, label: string) {
  // Every LoadingState has role=status and ends in an ellipsis; scan once none is left.
  await expect(page.getByRole('status').filter({ hasText: /…$/ })).toHaveCount(0)
  const axe = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  expect(axe.violations.map((v) => `${label} ${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`)).toEqual([])
}

async function signIn(page: Page) {
  await page.goto('/portal')
  await expect(page).toHaveURL(/\/sign-in\?as=member/)
  await expect(page.getByRole('heading', { name: 'Member sign in' })).toBeVisible()
  await page.getByRole('textbox', { name: 'Email' }).fill(MEMBER.email)
  await page.getByRole('textbox', { name: 'Password' }).fill(MEMBER.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page).toHaveURL(/\/portal$/)
  await expect(page.getByRole('heading', { level: 1, name: 'Hello, Morgan' })).toBeVisible()
}

const nav = (page: Page, name: string) => page.getByRole('navigation', { name: 'Portal' }).getByRole('link', { name }).click()

test('every portal screen and dialog passes the axe WCAG 2.1 AA scan', async ({ page }) => {
  test.setTimeout(600_000)
  await page.goto('/sign-in?as=member')
  await scan(page, '/sign-in?as=member')
  await signIn(page)
  for (const colorScheme of ['light', 'dark'] as const) {
    await page.emulateMedia({ colorScheme })
    for (const [name, heading] of [
      ['Home', 'Hello, Morgan'],
      ['Bookings', 'Bookings'],
      ['Memberships', 'Memberships'],
      ['Packages', 'Packages'],
      ['Invoices', 'Invoices'],
      ['Profile', 'Profile'],
    ] as const) {
      await nav(page, name)
      await expect(page.getByRole('heading', { level: 1, name: heading })).toBeVisible()
      await scan(page, `${colorScheme} ${name}`)
    }
    await nav(page, 'Invoices')
    await page.getByRole('tab', { name: 'Payment history' }).click()
    await expect(page.getByRole('table', { name: 'Payments' })).toBeVisible()
    await scan(page, `${colorScheme} payment history`)

    // Dialogs, opened the way a member opens them.
    await page.getByRole('tab', { name: 'Invoices' }).click()
    await page.getByRole('button', { name: /^View invoice/ }).first().click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await scan(page, `${colorScheme} invoice dialog`)
    await page.getByRole('button', { name: 'Close', exact: true }).first().click()

    await nav(page, 'Bookings')
    await page.getByRole('button', { name: 'Book a rental' }).click()
    await expect(page.getByRole('dialog', { name: 'Book a rental' })).toBeVisible()
    await scan(page, `${colorScheme} book rental`)
    await page.getByRole('button', { name: 'Cancel', exact: true }).click()

    await nav(page, 'Memberships')
    await page.getByRole('button', { name: /^Buy / }).first().click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await expect(page.getByText('Due now')).toBeVisible()
    await scan(page, `${colorScheme} buy membership`)
    await page.getByRole('button', { name: 'Cancel', exact: true }).click()

    await nav(page, 'Packages')
    await page.getByRole('button', { name: /^History of/ }).first().click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await scan(page, `${colorScheme} package history`)
    await page.getByRole('button', { name: 'Close', exact: true }).first().click()
  }
})

test('member views invoices, buys a package, books and cancels a rental, and acts for a dependent', async ({ page }) => {
  test.setTimeout(300_000)
  await signIn(page)
  await expect(page.getByText('Adult monthly')).toBeVisible()

  // Invoices: the list, a document, and the pay dialog offering the stored card.
  await nav(page, 'Invoices')
  const invoices = page.getByRole('table', { name: 'Invoices' })
  await expect(invoices.getByText('#1', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'View invoice 1', exact: true }).click()
  await expect(page.getByRole('dialog', { name: 'Invoice #1' }).getByRole('table', { name: 'Invoice lines' })).toBeVisible()
  await page.getByRole('button', { name: 'Close', exact: true }).first().click()
  const payButton = page.getByRole('button', { name: /^Pay invoice/ }).first()
  if (await payButton.count()) {
    await payButton.click()
    const pay = page.getByRole('dialog', { name: /^Pay invoice/ })
    await expect(pay.getByRole('combobox', { name: 'Pay with' })).toContainText('ending 4242')
    await pay.getByRole('button', { name: 'Cancel' }).click()
    await expect(payButton).toBeFocused() // focus returns to the opener
  }

  // Packages: buy the online ten-pack with the test processor's approved card.
  await nav(page, 'Packages')
  await page.getByRole('button', { name: 'Buy Ten private lessons' }).click()
  const buy = page.getByRole('dialog', { name: 'Buy Ten private lessons' })
  await buy.getByRole('combobox', { name: 'Card' }).selectOption('tok_card_ok')
  await buy.getByRole('button', { name: /^Pay / }).click()
  await expect(buy.getByRole('status')).toContainText('Ten private lessons is ready: 10 left')
  await buy.getByRole('button', { name: 'Done' }).click()
  await expect(page.getByRole('table', { name: 'Packages' }).getByText('Ten private lessons').first()).toBeVisible()

  // Bookings: hold a court three days out (outside the late-cancel window), pay, then cancel it again.
  await nav(page, 'Bookings')
  await page.getByRole('button', { name: 'Book a rental' }).click()
  const book = page.getByRole('dialog', { name: 'Book a rental' })
  const date = await book.getByLabel('Date').inputValue()
  const [y, m, d] = date.split('-').map(Number)
  await book.getByLabel('Date').fill(new Date(Date.UTC(y ?? 0, (m ?? 1) - 1, (d ?? 1) + 2)).toISOString().slice(0, 10))
  const slot = book.getByRole('group', { name: /Available times/ }).getByRole('button').last()
  await expect(slot).toBeVisible()
  await slot.click()
  await expect(book.getByText(/Due now/)).toBeVisible()
  await book.getByRole('combobox', { name: 'Card' }).selectOption('tok_card_ok')
  await book.getByRole('button', { name: /^Pay / }).click()
  await expect(book.getByRole('status')).toContainText('Booked: Court rental')
  const when = /Booked: Court rental on (.+)\.$/.exec((await book.getByRole('status').textContent()) ?? '')?.[1]
  await book.getByRole('button', { name: 'Done' }).click()
  await page.getByRole('button', { name: `Cancel Court rental on ${when}` }).click()
  await page.getByRole('dialog', { name: 'Cancel this rental?' }).getByRole('button', { name: 'Cancel rental' }).click()
  await expect(page.getByText(/Rental cancelled/)).toBeVisible()

  // Acting for a dependent switches every screen to that person.
  await page.getByRole('combobox', { name: 'Acting for' }).selectOption({ label: 'Mia Member' })
  await nav(page, 'Profile')
  await expect(page.getByText('Details and communication choices for Mia Member.')).toBeVisible()
  await nav(page, 'Home')
  await expect(page.getByRole('heading', { level: 1, name: 'Hello, Mia' })).toBeVisible()

  await page.getByRole('button', { name: 'Sign out' }).click()
  await expect(page).toHaveURL(/\/sign-in/)
})
