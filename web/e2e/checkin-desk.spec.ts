import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

// Seeded demo manager (docs/dev/demo-accounts.md, "Demo check-in (build module 10)"); the client is the spec's own.
const MANAGER = { email: 'manager@courtside-demo.example.com', password: 'courtside-demo-2026' }

async function scan(page: Page, label: string) {
  const axe = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  expect(axe.violations.map((v) => `${label} ${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`)).toEqual([])
}

test('the desk sets up a station, checks in on it, books, checks out, sees who is in and prints a member card, all screens pass axe', async ({ page }) => {
  test.setTimeout(180_000) // eight axe scans on a shared machine
  const tag = Date.now().toString(36).slice(-5).toUpperCase()
  await page.goto('/check-in/desk-setup')
  await page.getByRole('textbox', { name: 'Email' }).fill(MANAGER.email)
  await page.getByRole('textbox', { name: 'Password' }).fill(MANAGER.password)
  const signedIn = page.waitForResponse((r) => r.url().endsWith('/api/v1/auth/sign-in') && r.ok())
  await page.getByRole('button', { name: 'Sign in' }).click()
  const { csrf_token } = await (await signedIn).json()
  await expect(page.getByRole('heading', { level: 1, name: 'Stations and member cards' })).toBeVisible()

  // A client of its own: the board shows each client's latest open visit, and checkin.spec checks the seeded
  // Morgan Member in without a station, in parallel with this spec.
  const headers = { 'x-tenant-slug': 'courtside-demo', 'x-csrf-token': csrf_token, 'idempotency-key': crypto.randomUUID() }
  const locations = await (await page.request.get('/api/v1/locations', { headers })).json()
  const downtown = locations.data.find((l: { name: string }) => l.name === 'Courtside Downtown')
  const member = `DESK-${tag}`
  const who = `Dana Desk${tag}`
  const made = await page.request.post('/api/v1/clients', {
    headers, data: { first_name: 'Dana', last_name: `Desk${tag}`, home_location_id: downtown.id, member_number: member },
  })
  expect(made.status()).toBe(201)

  // CHK-07 and CHK-12: a station and a card layout for this location.
  await page.getByLabel('New station name').fill(`Desk ${tag}`)
  await page.getByRole('button', { name: 'Add station' }).click()
  await expect(page.getByRole('list', { name: 'Stations' })).toContainText(`Desk ${tag}`, { timeout: 20_000 })
  await page.getByLabel('Layout name').fill(`Card ${tag}`)
  await page.getByRole('checkbox', { name: 'Valid until' }).check()
  await page.getByRole('button', { name: 'Save layout' }).click()
  await expect(page.getByRole('list', { name: 'Card layouts' })).toContainText(`Card ${tag}`, { timeout: 20_000 })
  await scan(page, 'desk setup')

  await page.goto('/check-in')
  await page.getByLabel('Check-in station').selectOption({ label: `Desk ${tag}` })
  await page.getByLabel('Card or member number').fill(member)
  await page.getByRole('button', { name: 'Look up' }).click()
  await expect(page.getByRole('heading', { level: 3, name: who })).toBeVisible()
  await scan(page, 'status card')

  // CHK-21: an alert with a remedy at the desk opens its own screen; the status card is read again on close.
  const sign = page.getByRole('button', { name: 'Collect waiver signature' })
  if (await sign.isVisible()) {
    await sign.click()
    await expect(page.getByRole('dialog', { name: 'Waiver and documents' })).toBeVisible()
    await scan(page, 'waiver at the desk')
    await page.keyboard.press('Escape')
  }

  const created = page.waitForResponse((r) => r.url().endsWith('/api/v1/check-ins') && r.request().method() === 'POST')
  if (await page.getByRole('button', { name: 'Check in', exact: true }).isVisible()) {
    await page.getByRole('button', { name: 'Check in', exact: true }).click()
  } else {
    await page.getByLabel('Override reason').fill('Desk test')
    await page.getByRole('button', { name: 'Override and check in' }).click()
  }
  const done = await (await created).json()
  expect(done.check_in.check_in_station_id).toBeTruthy()
  const last = page.getByRole('region', { name: new RegExp(`Just checked in: ${who}`) })
  await expect(page.getByRole('heading', { name: `Just checked in: ${who}` })).toBeVisible()
  await scan(page, 'after check-in')

  // CHK-04: the booking dialog lists sessions starting soon.
  await page.getByRole('button', { name: 'Book a session' }).click()
  await expect(page.getByRole('dialog', { name: 'Book a session' })).toBeVisible()
  await scan(page, 'book a session')
  await page.keyboard.press('Escape')

  // CHK-07: the live count, in a second tab of the same session, while the panel stays open here.
  const board = await page.context().newPage()
  await board.goto('/check-in/occupancy')
  await expect(board.getByRole('heading', { level: 1, name: 'Who is in' })).toBeVisible()
  await expect(board.getByRole('row', { name: new RegExp(`${who}.*Desk ${tag}`) })).toBeVisible()
  await expect(board.getByRole('list', { name: 'By station' })).toContainText(`Desk ${tag}`, { timeout: 20_000 })
  await scan(board, 'occupancy')
  await board.close()

  const checkedOut = page.waitForResponse((r) => r.url().endsWith('/check-out') && r.request().method() === 'POST')
  await last.getByRole('button', { name: 'Check out' }).click()
  expect((await checkedOut).status()).toBe(200)
  await expect(last.getByRole('button', { name: 'Check out' })).toHaveCount(0)

  // MEM-19: the printable card, with its barcode.
  await page.goto(`/check-in/card/${done.check_in.client_id}`)
  await expect(page.getByRole('region', { name: new RegExp(`Member card for ${who}`) })).toBeVisible()
  await expect(page.getByRole('img', { name: /^Barcode / })).toBeVisible()
  await scan(page, 'member card')
})
