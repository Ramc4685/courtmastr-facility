import AxeBuilder from '@axe-core/playwright'
import { expect as baseExpect, test, type Page } from '@playwright/test'
import { ADMIN, PASSWORD } from './a11y'

// Phase 11 chip A: the public facility pages under /f/:slug (SSP-01, 05, 15, REG-12) and the staff settings
// behind them (SSP-13, 07). Seeded demo tenant: courtside-demo (docs/dev/demo-accounts.md).
const expect = baseExpect.configure({ timeout: 30_000 })
const SLUG = 'courtside-demo'
const TENANT = { 'x-tenant-slug': SLUG }

async function scan(page: Page, label: string) {
  await expect(page.getByRole('status').filter({ hasText: /…$/ })).toHaveCount(0)
  const axe = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  expect(axe.violations.map((v) => `${label} ${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`)).toEqual([])
}

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

  // The seed publishes one open camp with guest checkout off (its default); switch it on here and back at the end.
  const groups: { id: string; registration_state: string }[] = await (await page.request.get('/api/v1/public/program-groups', { headers: TENANT })).json()
  const camp = groups.find((g) => g.registration_state === 'open')
  if (!camp) throw new Error('the demo seed publishes an open program group')
  const config = `/api/v1/program-groups/${camp.id}/registration-config`
  const before: { allows_guest_checkout: boolean } = await (await page.request.get(config, { headers: TENANT })).json()
  const allowed = await page.request.put(config, { headers: staff(), data: { allows_guest_checkout: true } })
  try {
    expect(allowed.ok(), await allowed.text()).toBe(true)
    for (const colorScheme of ['light', 'dark'] as const) {
      await page.emulateMedia({ colorScheme })
      await page.goto(`/f/${SLUG}/programs/${camp.id}/guest`)
      await expect(page.getByRole('heading', { level: 1, name: /^Register for/ })).toBeVisible()
      await scan(page, `${colorScheme} guest checkout`)
      await page.getByRole('button', { name: 'Continue to payment' }).click()
      await expect(page.getByRole('textbox', { name: 'Email', exact: true })).toHaveAttribute('aria-invalid', 'true')
      await scan(page, `${colorScheme} guest checkout with field errors`)
    }

    // Through the payment step once (each run holds a real place): scan it, decline, then pay on retry.
    // The fake processor's scripted test cards pick the outcome (PaymentMethodField FAKE_CARDS).
    const detail: { confirmation_message: string | null } = await (await page.request.get(`/api/v1/public/program-groups/${camp.id}?guest=true`, { headers: TENANT })).json()
    await page.emulateMedia({ colorScheme: 'light' })
    await page.goto(`/f/${SLUG}/programs/${camp.id}/guest`)
    await expect(page.getByRole('heading', { level: 1, name: /^Register for/ })).toBeVisible()
    await page.getByRole('textbox', { name: 'First name', exact: true }).fill('Gale')
    await page.getByRole('textbox', { name: 'Last name', exact: true }).fill('Guest')
    await page.getByRole('textbox', { name: 'Email', exact: true }).fill(`guest-${crypto.randomUUID()}@example.com`)
    await page.getByLabel('Date of birth', { exact: true }).fill('1990-04-12')
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
    await page.request.put(config, { headers: staff(), data: { allows_guest_checkout: before.allows_guest_checkout } })
  }
})
