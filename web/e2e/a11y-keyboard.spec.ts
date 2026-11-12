import { expect, test, type Locator, type Page } from '@playwright/test'
import { ADMIN, auditRoute, dialogKeyboard, focused, MEMBER, PASSWORD, settled, signIn, tabWalk } from './a11y'

// The manual WCAG 2.1 AA pass, kept as assertions (docs/status/phase8-o2-accessibility.md). axe runs in every
// other spec; this one checks what axe cannot: keyboard reach and order, focus visibility and handling, target
// size, reflow, reduced motion. Problems left open are listed in KNOWN with their finding number; fixing one
// means deleting its line, and a new problem fails the spec.
const KNOWN: string[] = []

function expectOnlyKnown(found: string[]) {
  if (found.length) console.log(found.join('\n'))
  expect(found.filter((p) => !KNOWN.includes(p))).toEqual([])
}

async function openInvoice(page: Page) {
  await page.goto('/billing/clients')
  await page.getByRole('combobox', { name: 'Client' }).fill('m-1001')
  await page.getByRole('option', { name: /Morgan Member/ }).click()
  await page.getByRole('tab', { name: 'Invoices' }).click()
  await page.getByRole('table', { name: 'Invoices' }).getByRole('link').first().click()
  await expect(page.getByRole('heading', { level: 1, name: /Invoice #/ })).toBeVisible()
}

/** A field error is linked to its field (aria-describedby, aria-invalid) and sits in a live region (3.3.1, 4.1.3). */
async function expectLinkedError(page: Page, field: Locator, text: string) {
  await expect(field).toHaveAttribute('aria-invalid', 'true')
  const ids = ((await field.getAttribute('aria-describedby')) ?? '').split(' ').filter(Boolean)
  const error = page.locator(ids.map((id) => `[id="${id}"]`).join(', ')).filter({ hasText: text })
  await expect(error).toHaveCount(1)
  await expect(error).toHaveAttribute('aria-live', 'polite')
}

async function staffRoute(page: Page, path: string) {
  await page.goto(path)
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  return auditRoute(page, path)
}

test.describe('keyboard and focus, staff', () => {
  test.setTimeout(180_000)

  test('sign-in: order, error announced, MFA step and its error linked to the field', async ({ page }) => {
    await page.goto('/sign-in')
    await expect(page.getByRole('heading', { level: 1, name: 'Sign in' })).toBeVisible()
    expectOnlyKnown(await auditRoute(page, '/sign-in', { skip: false }))

    // Tab order follows the form: email, password, then the submit button after them.
    await page.getByRole('textbox', { name: 'Email' }).focus()
    await page.keyboard.press('Tab')
    expect((await focused(page))?.tag).toBe('input[password]')
    await page.getByRole('textbox', { name: 'Email' }).fill(ADMIN)
    await page.getByRole('textbox', { name: 'Password' }).fill('not-the-password')
    await page.keyboard.press('Enter')
    await expect(page.getByRole('alert')).toContainText('do not match')

    // The second factor (the demo tenant keeps MFA optional, so the API's answer is stubbed here).
    await page.route('**/api/v1/auth/sign-in', (route) =>
      route.fulfill({ json: { mfa_token: 'stub', enrolment_required: false, methods: ['totp'], expires_at: new Date(Date.now() + 300_000).toISOString() } }),
    )
    await page.route('**/api/v1/auth/mfa/verify', (route) =>
      route.fulfill({ status: 422, json: { status: 422, code: 'mfa-code-invalid', title: 'Invalid code' } }),
    )
    await page.getByRole('textbox', { name: 'Password' }).fill(PASSWORD)
    await page.getByRole('button', { name: 'Sign in' }).click()
    const code = page.getByRole('textbox', { name: 'Verification code' })
    await expect(code).toBeFocused()
    await code.fill('000000')
    await page.keyboard.press('Enter')
    await expect(code).toHaveAttribute('aria-invalid', 'true')
    await expectLinkedError(page, code, 'That did not match. Try again.')
  })

  test('main staff screens: structure, targets, skip link, tab walk, reflow', async ({ page }) => {
    test.setTimeout(300_000)
    await signIn(page, '/')
    await expect(page.getByRole('button', { name: /account menu/i })).toBeVisible()
    const found: string[] = []
    for (const path of ['/', '/schedule', '/clients', '/billing', '/pos', '/check-in', '/settings/security', '/settings/plan', '/settings/privacy'])
      found.push(...(await staffRoute(page, path)))
    // Detail pages, reached the way a person reaches them.
    await page.goto('/clients')
    await page.getByRole('table').getByRole('link').first().click()
    await expect(page).toHaveURL(/\/clients\/[0-9a-f-]{36}/)
    found.push(...(await auditRoute(page, '/clients/:id')))
    await openInvoice(page)
    found.push(...(await auditRoute(page, '/billing/invoices/:id')))
    expectOnlyKnown(found)
  })

  test('dialogs: booking, take payment, check-in booking; focus in, Tab kept, Escape, focus back', async ({ page }) => {
    await signIn(page, '/schedule')
    await expect(page.getByRole('button', { name: 'New booking' })).toBeVisible()
    await settled(page)
    const found = (await dialogKeyboard(page, page.getByRole('button', { name: 'New booking' }), page.getByRole('dialog', { name: 'New booking' }))).map((p) => `booking: ${p}`)

    await openInvoice(page)
    await settled(page)
    const take = page.getByRole('button', { name: 'Take payment' })
    if (await take.isVisible()) found.push(...(await dialogKeyboard(page, take, page.getByRole('dialog', { name: 'Take payment' }))).map((p) => `take payment: ${p}`))
    expectOnlyKnown(found)
  })

  test('step-up dialog: focus on the field, error linked, Escape cancels', async ({ page }) => {
    await signIn(page, '/')
    await expect(page.getByRole('button', { name: /account menu/i })).toBeVisible()
    let refused = false
    await page.route('**/api/v1/roles**', (route) => {
      if (refused || route.request().method() !== 'GET') return route.continue()
      refused = true
      return route.fulfill({ status: 403, json: { status: 403, code: 'step-up-required', title: 'Confirm it is you' } })
    })
    await page.route('**/api/v1/auth/step-up', (route) =>
      route.fulfill({ status: 422, json: { status: 422, code: 'reauthentication-failed', title: 'No match' } }),
    )
    await page.goto('/roles')
    const dialog = page.getByRole('dialog', { name: 'Confirm it is you' })
    await expect(dialog).toBeVisible()
    const field = dialog.getByRole('textbox')
    await expect(field).toBeFocused()
    await field.fill('wrong')
    await page.keyboard.press('Enter')
    await expectLinkedError(page, field, 'That did not match. Try again.')
    await page.keyboard.press('Escape')
    await expect(dialog).toBeHidden()
  })

  test('reduced motion is honoured and focus rings keep 3:1 in both themes', async ({ page }) => {
    await signIn(page, '/clients')
    await expect(page.getByRole('heading', { level: 1, name: 'Clients' })).toBeVisible() // not the sign-in h1
    await settled(page)
    await page.emulateMedia({ reducedMotion: 'reduce' })
    const longest = await page.evaluate(() =>
      Math.max(...[...document.querySelectorAll('*')].map((el) => parseFloat(getComputedStyle(el).transitionDuration) || 0)),
    )
    expect(longest).toBeLessThanOrEqual(0.01)
    const found: string[] = []
    for (const colorScheme of ['light', 'dark'] as const) {
      await page.emulateMedia({ colorScheme, reducedMotion: 'reduce' })
      found.push(...(await tabWalk(page, 25)).map((p) => `${colorScheme} /clients: ${p}`))
    }
    expectOnlyKnown(found)
  })
})

test.describe('keyboard and focus, member portal', () => {
  test.setTimeout(180_000)

  test('portal home and booking dialog', async ({ page }) => {
    await signIn(page, '/sign-in?as=member', MEMBER)
    await expect(page).toHaveURL(/\/portal/)
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    const found = await auditRoute(page, '/portal')
    const book = page.getByRole('button', { name: 'Book a rental' })
    if (await book.isVisible()) found.push(...(await dialogKeyboard(page, book, page.getByRole('dialog', { name: 'Book a rental' }))).map((p) => `portal booking: ${p}`))
    expectOnlyKnown(found)
  })
})
