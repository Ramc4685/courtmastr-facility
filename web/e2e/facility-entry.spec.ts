import { expect as baseExpect, test } from '@playwright/test'
import { ADMIN, PASSWORD, scanAfter } from './a11y'

// Phase 11 chip A: the public facility pages under /f/:slug (SSP-01, 05, 15, REG-12) and the staff settings
// behind them (SSP-13, 07). Seeded demo tenant: courtside-demo (docs/dev/demo-accounts.md).
const expect = baseExpect.configure({ timeout: 30_000 })
const SLUG = 'courtside-demo'
const TENANT = { 'x-tenant-slug': SLUG }
const scan = scanAfter(/…$/, 30_000)

test('the public facility pages pass the axe WCAG 2.1 AA scan', async ({ page }) => {
  test.setTimeout(300_000)
  for (const colorScheme of ['light', 'dark'] as const) {
    await page.emulateMedia({ colorScheme })
    await page.goto(`/f/${SLUG}`)
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Programs' })).toBeVisible()
    await scan(page, `${colorScheme} landing`)
    await page.goto(`/f/${SLUG}/signup`)
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    await scan(page, `${colorScheme} signup`)
    await page.goto(`/f/${SLUG}/signup/confirm`)
    await expect(page.getByRole('alert')).toContainText('not valid')
    await scan(page, `${colorScheme} signup confirm without a token`)
  }
  await page.goto('/f/no-such-facility')
  await expect(page.getByText('We could not find that facility')).toBeVisible()
  await scan(page, 'unknown facility')
})

test('staff settings for the portal entry pass the scan', async ({ page }) => {
  test.setTimeout(300_000)
  await page.goto('/sign-in')
  await page.getByRole('textbox', { name: 'Email' }).fill(ADMIN)
  await page.getByRole('textbox', { name: 'Password' }).fill(PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await page.waitForURL((url) => !url.pathname.startsWith('/sign-in'))
  await page.goto('/engagement/portal')
  await expect(page.getByRole('group', { name: 'Portal menu' })).toBeVisible()
  await expect(page.getByRole('checkbox', { name: /create their own account/ })).not.toBeChecked()
  await scan(page, 'portal settings')
  await page.goto('/settings')
  await expect(page.getByRole('textbox', { name: 'Portal main colour' })).toBeVisible()
  await page.getByRole('textbox', { name: 'Portal main colour' }).fill('#ffeb3b')
  await expect(page.getByText(/Too light for readable contrast/)).toBeVisible()
  await scan(page, 'account settings')
})

test('guest checkout for a program passes the scan, with and without field errors (REG-12)', async ({ page }) => {
  test.setTimeout(300_000)
  await page.goto('/sign-in')
  await page.getByRole('textbox', { name: 'Email' }).fill(ADMIN)
  await page.getByRole('textbox', { name: 'Password' }).fill(PASSWORD)
  const signedIn = page.waitForResponse((r) => r.url().endsWith('/api/v1/auth/sign-in') && r.ok())
  await page.getByRole('button', { name: 'Sign in' }).click()
  const { csrf_token } = await (await signedIn).json()
  const staff = () => ({ ...TENANT, 'x-csrf-token': csrf_token, 'idempotency-key': crypto.randomUUID() })

  // Its own program each run (no capacity limit, guest checkout on), so the paid place never fills a seeded one;
  // archived at the end, cancelling any guest basket still holding a place, so it leaves the public listing.
  const groups: { id: string; registration_state: string }[] = await (await page.request.get('/api/v1/public/program-groups', { headers: TENANT })).json()
  const seeded = groups.find((g) => g.registration_state === 'open')
  if (!seeded) throw new Error('the demo seed publishes an open program group')
  const { location_id }: { location_id: string } = await (await page.request.get(`/api/v1/program-groups/${seeded.id}`, { headers: TENANT })).json()
  const made = await page.request.post('/api/v1/program-groups', { headers: staff(), data: { location_id, name: `E2E guest camp ${Date.now()}` } })
  expect(made.ok(), await made.text()).toBe(true)
  const camp: { id: string } = await made.json()
  try {
    const steps = [
      page.request.post(`/api/v1/program-groups/${camp.id}/fees`, { headers: staff(), data: { description: 'Camp', amount_minor: 9000 } }),
      page.request.put(`/api/v1/program-groups/${camp.id}/registration-config`, {
        headers: staff(),
        data: { is_enabled: true, payment_requirement: 'immediate_card_payment', allows_guest_checkout: true },
      }),
      // The seed's program-default waiver blocks guests (409 guest-documents-required); this camp's own rules are desk-only.
      page.request.put('/api/v1/document-bindings', {
        headers: staff(),
        data: { scope_type: 'program_group', scope_id: camp.id, custom_text: 'Camp rules', is_enforced_online: false },
      }),
    ]
    for (const step of await Promise.all(steps)) expect(step.ok(), await step.text()).toBe(true)
    const published = await page.request.post(`/api/v1/program-groups/${camp.id}/publish`, { headers: staff() })
    expect(published.ok(), await published.text()).toBe(true)
    for (const colorScheme of ['light', 'dark'] as const) {
      await page.emulateMedia({ colorScheme })
      await page.goto(`/f/${SLUG}/programs/${camp.id}/guest`)
      await expect(page.getByRole('heading', { level: 1, name: /^Register for/ })).toBeVisible()
      await scan(page, `${colorScheme} guest checkout`)
      // Nothing filled and the declaration unticked: one submit marks every missing field and the declaration inline.
      await page.getByRole('button', { name: 'Continue to payment' }).click()
      await expect(page.getByRole('textbox', { name: 'Email', exact: true })).toHaveAttribute('aria-invalid', 'true')
      await expect(page.getByLabel('Date of birth', { exact: true })).toHaveAttribute('aria-invalid', 'true')
      const declaration = page.getByRole('checkbox', { name: /dates of birth I entered are true/ })
      await expect(declaration).toHaveAttribute('aria-invalid', 'true')
      await expect(declaration).toHaveAccessibleDescription(/Tick this box/)
      await scan(page, `${colorScheme} guest checkout with field errors`)
    }

    // Through the payment step once (a place in this run's own program): scan it, decline, then pay on retry.
    // The fake processor's scripted test cards pick the outcome (PaymentMethodField FAKE_CARDS).
    const detail: { confirmation_message: string | null } = await (await page.request.get(`/api/v1/public/program-groups/${camp.id}?guest=true`, { headers: TENANT })).json()
    await page.emulateMedia({ colorScheme: 'light' })
    await page.goto(`/f/${SLUG}/programs/${camp.id}/guest`)
    await expect(page.getByRole('heading', { level: 1, name: /^Register for/ })).toBeVisible()
    await page.getByRole('textbox', { name: 'First name', exact: true }).fill('Gale')
    await page.getByRole('textbox', { name: 'Last name', exact: true }).fill('Guest')
    await page.getByRole('textbox', { name: 'Email', exact: true }).fill(`guest-${crypto.randomUUID()}@example.com`)
    await page.getByLabel('Date of birth', { exact: true }).fill('1990-04-12')
    await page.getByRole('checkbox', { name: /dates of birth I entered are true/ }).check()
    await page.getByRole('button', { name: 'Continue to payment' }).click()
    await expect(page.getByText(/Total to pay now/)).toBeVisible()
    const card = page.getByRole('combobox', { name: 'Card' })
    await expect(card).toBeVisible()
    const terms = page.getByRole('checkbox', { name: /agree to these terms/ })
    if (await terms.count()) await terms.check()
    await scan(page, 'guest checkout payment step')

    const payButton = page.getByRole('button', { name: 'Pay and register' })
    await card.selectOption('tok_card_declined')
    await payButton.click()
    await expect(page.locator('form').getByRole('alert')).toBeVisible() // the decline, shown on the form
    await expect(payButton).toBeVisible() // still on the payment step, the place still held
    await scan(page, 'guest checkout after a decline')

    await card.selectOption('tok_card_ok')
    await payButton.click()
    await expect(page.getByRole('status').filter({ hasText: detail.confirmation_message || 'You are registered' })).toBeVisible()
    await expect(payButton).toHaveCount(0)
  } finally {
    await page.request.post(`/api/v1/program-groups/${camp.id}/archive?cancel_guest_holds=true`, { headers: staff() })
  }
})
