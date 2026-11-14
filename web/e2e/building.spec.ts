import { expect as baseExpect, test } from '@playwright/test'
import { MEMBER, scanAfter, signIn } from './a11y'

// Building control (CHK-15, CHK-16): the staff screen at /check-in/building and a member's door code on the
// portal Bookings page. Seeded demo tenant (docs/dev/demo-accounts.md): one front door and a lights zone per court.
const expect = baseExpect.configure({ timeout: 30_000 })
const scan = scanAfter(/^Loading/, 30_000)

test('the building control screen passes the axe WCAG 2.1 AA scan, with its hold and unlock dialogs', async ({ page }) => {
  test.setTimeout(240_000)
  await signIn(page, '/check-in/building')
  await expect(page.getByRole('heading', { level: 1, name: 'Building control' })).toBeVisible()
  await expect(page.getByRole('table', { name: /Lighting zones/ })).toBeVisible()
  for (const colorScheme of ['light', 'dark'] as const) {
    await page.emulateMedia({ colorScheme })
    await scan(page, `${colorScheme} building control`)
  }
  await page.getByRole('button', { name: /^Hold / }).first().click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await scan(page, 'hold dialog')
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: /^Unlock / }).first().click()
  await expect(page.getByRole('textbox', { name: 'Reason' })).toBeVisible()
  await scan(page, 'unlock dialog')
})

test('a member sees the door code on their booking and the page passes the scan', async ({ page }) => {
  test.setTimeout(240_000)
  const now = Date.now()
  // The code is the server's to issue (it needs a booking inside seven days); the screen is what is scanned here.
  await page.route('**/api/v1/portal/entry-codes', (route) =>
    route.fulfill({
      json: {
        data: [{
          booking_id: '01900000-0000-7000-8000-000000000001', location_id: '01900000-0000-7000-8000-000000000002',
          location_phone: '+1 309 555 0100', code: '48151623', held_reason: null, message: null, is_open_now: true,
          valid_from_at: new Date(now - 600_000).toISOString(), valid_until_at: new Date(now + 3_600_000).toISOString(),
        }],
        page: { next_cursor: null, has_more: false },
      },
    }),
  )
  await signIn(page, '/portal', MEMBER) // a portal sign-in lands on Home
  await expect(page.getByRole('heading', { level: 1, name: /^Hello/ })).toBeVisible()
  await page.goto('/portal/bookings')
  await expect(page.getByRole('heading', { level: 2, name: 'Door codes' })).toBeVisible()
  await expect(page.getByText('48151623', { exact: true })).toBeVisible()
  await expect(page.getByText('4 8 1 5 1 6 2 3', { exact: true })).toBeAttached() // what a screen reader reads
  await expect(page.getByRole('button', { name: 'Open the door' })).toBeVisible()
  for (const colorScheme of ['light', 'dark'] as const) {
    await page.emulateMedia({ colorScheme })
    await scan(page, `${colorScheme} portal door code`)
  }
})
