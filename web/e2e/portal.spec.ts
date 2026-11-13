import { expect as baseExpect, test, type Page } from '@playwright/test'
import { scanAfter } from './a11y'

// Every LoadingState has role=status and ends in an ellipsis; scan once none is left.
const scan = scanAfter(/…$/, 30_000)

// Generous waits: the API and Vite share a busy development machine with other lanes.
const expect = baseExpect.configure({ timeout: 30_000 })

// Seeded demo data (docs/dev/demo-accounts.md): Morgan Member signs in to the portal, acts for Mia, holds a
// stored test card, has open invoices, and "Ten private lessons" and "Court rental" are sold online.
const MEMBER = { email: 'member@courtside-demo.example.com', password: 'courtside-demo-2026' }
const OWNER = { email: 'owner@courtside-demo.example.com', password: 'courtside-demo-2026' }

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
  await buy.getByRole('radio', { name: 'New card' }).check() // the seeded saved card is offered first
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
  await book.getByRole('radio', { name: 'New card' }).check()
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

test('a booked online session offers Join online, the early click is refused, and the screen passes axe', async ({ browser }) => {
  test.setTimeout(180_000)
  // Staff side through the API: a session of its own two hours out with a pasted meeting, and Morgan booked in.
  const staff = await (await browser.newContext()).newPage()
  await staff.goto('/integrations')
  await staff.getByRole('textbox', { name: 'Email' }).fill(OWNER.email)
  await staff.getByRole('textbox', { name: 'Password' }).fill(OWNER.password)
  const signedIn = staff.waitForResponse((r) => r.url().endsWith('/api/v1/auth/sign-in') && r.ok())
  await staff.getByRole('button', { name: 'Sign in' }).click()
  const { csrf_token } = await (await signedIn).json()
  const headers = () => ({ 'x-tenant-slug': 'courtside-demo', 'x-csrf-token': csrf_token, 'idempotency-key': crypto.randomUUID() })
  const call = async (method: 'get' | 'post' | 'put', url: string, data?: object) => {
    const response = await staff.request[method](url, { headers: headers(), data })
    expect(response.ok(), `${method} ${url}: ${await response.text()}`).toBe(true)
    return response.json()
  }
  const tag = Date.now().toString(36)
  const downtown = (await call('get', '/api/v1/locations')).data.find((l: { name: string }) => l.name === 'Courtside Downtown')
  const group = await call('post', '/api/v1/resource-groups', { location_id: downtown.id, name: `Online ${tag}` })
  const room = await call('post', '/api/v1/resources', { location_id: downtown.id, resource_group_id: group.id, name: `Studio ${tag}` })
  const kind = await call('post', '/api/v1/reservation-types', { location_id: downtown.id, name: `Online class ${tag}`, default_capacity: 4, default_allows_free_booking: true, color: '#22aa66' })
  const starts = new Date(Date.now() + 2 * 3_600_000)
  starts.setUTCSeconds(0, 0)
  const made = await call('post', '/api/v1/bookings', {
    location_id: downtown.id, kind: 'session', reservation_type_id: kind.id, public_title: `Online yoga ${tag}`,
    starts_at: starts.toISOString(), ends_at: new Date(starts.getTime() + 3_600_000).toISOString(), resources: [{ resource_id: room.id }],
  })
  const seat = (made.booking ?? made).session.id
  await call('put', `/api/v1/sessions/${seat}/video-meeting`, { provider: 'manual', join_url: 'https://meet.example.com/yoga' })
  const morgan = (await call('get', '/api/v1/clients?q=Morgan')).data.find((c: { first_name: string; last_name: string }) => c.first_name === 'Morgan' && c.last_name === 'Member')
  await call('post', '/api/v1/enrollments', { session_id: seat, client_id: morgan.id })
  await staff.context().close()

  const page = await (await browser.newContext()).newPage()
  await signIn(page)
  await page.goto('/portal/sessions')
  // the title comes from the listings, which may not show a new class, so any online place will do (all are early)
  const join = page.getByRole('list', { name: 'Your bookings' }).getByRole('button', { name: /^Join online/ }).first()
  await expect(join).toBeVisible()
  await scan(page, 'portal sessions with an online booking')
  await join.click() // two hours early: the API refuses and the screen says why
  await expect(page.getByText('The session opens 10 minutes before it starts')).toBeVisible()
  await page.context().close()
})

// The join itself depends on the clock (10 minutes before a start), so the Vitest suite covers the opened link.
test('a member gets a calendar address and stops the feed, and the dialogs pass axe', async ({ page }) => {
  await signIn(page)
  const listed = page.waitForResponse((r) => r.url().endsWith('/api/v1/portal/calendar-feeds') && r.request().method() === 'GET')
  await page.goto('/portal/sessions')
  await expect(page.getByRole('heading', { name: 'Your calendar' })).toBeVisible()
  if (((await (await listed).json()) as unknown[]).length > 0) {
    // a feed left by an earlier run: stop it first, so the button is shown only while a feed exists
    await page.getByRole('button', { name: 'Stop my calendar feed' }).click()
    await page.getByRole('dialog', { name: 'Stop your calendar feed?' }).getByRole('button', { name: 'Stop feed' }).click()
  }
  await expect(page.getByRole('button', { name: 'Stop my calendar feed' })).toHaveCount(0)
  await page.getByRole('button', { name: 'Get my calendar address' }).click()
  const address = page.getByRole('dialog', { name: 'Your calendar address' }).getByRole('textbox', { name: 'Secret' })
  const url = await address.inputValue()
  expect((await page.request.get(url)).headers()['content-type']).toContain('text/calendar')
  await scan(page, 'calendar address dialog')
  await page.getByRole('button', { name: 'I have copied it' }).click()

  await page.getByRole('button', { name: 'Stop my calendar feed' }).click() // shown now that a feed exists
  await page.emulateMedia({ colorScheme: 'dark' })
  await scan(page, 'stop feed dialog dark')
  await page.getByRole('dialog', { name: 'Stop your calendar feed?' }).getByRole('button', { name: 'Stop feed' }).click()
  await expect(page.getByText(/Your calendar feed is stopped/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Stop my calendar feed' })).toHaveCount(0)
  expect((await page.request.get(url)).status()).toBe(404)
  await page.emulateMedia({ colorScheme: 'light' })
  await scan(page, 'portal sessions')
})
