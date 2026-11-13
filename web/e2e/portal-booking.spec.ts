import { expect as baseExpect, test, type APIRequestContext, type Browser, type Page } from '@playwright/test'
import { ADMIN, MEMBER, PASSWORD, scanAfter } from './a11y'

const scan = scanAfter(/…$/, 30_000)

// Phase 11 chip B (portal booking and buying). Seeded demo data (docs/dev/demo-accounts.md): Morgan Member holds a
// stored test card and a lesson package, "Summer Sports Camp" is published at Downtown, and Downtown has a
// schedule for this week and next. The spec makes what the seed lacks (a virtual session, a payment plan) through
// the staff API and puts it back afterwards. No fixed dates: sessions are picked from the live listing.
const expect = baseExpect.configure({ timeout: 30_000 })
const SLUG = { 'x-tenant-slug': 'courtside-demo' }

/** A signed-in member in a context of their own (the web sign-in form is staff-only; the portal app signs in by API). */
async function memberPage(browser: Browser) {
  const context = await browser.newContext()
  const page = await context.newPage()
  const out = await page.request.post('/api/v1/auth/sign-in', { headers: { ...SLUG, 'idempotency-key': crypto.randomUUID() }, data: { email: MEMBER, password: PASSWORD, audience: 'client', client_kind: 'web' } })
  expect(out.ok()).toBe(true)
  const { csrf_token } = await out.json()
  return { page, context, headers: () => ({ ...SLUG, 'x-csrf-token': csrf_token, 'idempotency-key': crypto.randomUUID() }) }
}

async function staffSignIn(page: Page, path: string) {
  await page.goto(path)
  await page.getByRole('textbox', { name: 'Email' }).fill(ADMIN)
  await page.getByRole('textbox', { name: 'Password' }).fill(PASSWORD)
  const signedIn = page.waitForResponse((r) => r.url().endsWith('/api/v1/auth/sign-in') && r.ok())
  await page.getByRole('button', { name: 'Sign in' }).click()
  const { csrf_token } = await (await signedIn).json()
  return () => ({ ...SLUG, 'x-csrf-token': csrf_token, 'idempotency-key': crypto.randomUUID() })
}

type Listing = { session_id: string; title: string | null; starts_at: string; location_id: string; is_bookable: boolean; reservation_type_id: string | null }

/** Book Morgan into a bookable session at least a day out (so its meeting is not open yet), with a held package
 * when the session needs one. Returns the session and the enrollment. */
async function bookSomething(request: APIRequestContext, headers: () => Record<string, string>) {
  const me = (await (await request.get('/api/v1/portal/clients', { headers: SLUG })).json()).data.find((c: { authority: string }) => c.authority === 'self')
  const listings: Listing[] = await (await request.get(`/api/v1/portal/session-listings?client_id=${me.id}`, { headers: SLUG })).json()
  const packages = (await (await request.get(`/api/v1/portal/client-packages?client_id=${me.id}&limit=100`, { headers: SLUG })).json()).data
  const dayOut = Date.now() + 24 * 3600_000
  for (const l of listings.filter((x) => x.is_bookable && new Date(x.starts_at).getTime() > dayOut).slice(0, 12)) {
    const pack = packages.find((p: { status: string; reservation_type_id: string; is_unlimited: boolean; sessions_available_count: number | null }) => p.status === 'active' && p.reservation_type_id === l.reservation_type_id && (p.is_unlimited || (p.sessions_available_count ?? 0) > 0))
    const res = await request.post('/api/v1/portal/enrollments', { headers: headers(), data: { client_id: me.id, session_id: l.session_id, client_package_id: pack?.id ?? null } })
    if (res.ok()) return { listing: l, enrollment: await res.json() }
  }
  throw new Error('no bookable session in the seeded listing; run make seed for this lane')
}

test('portal booking and buying: saved cards, calendar, virtual session, payment plan and progress pass axe', async ({ page, browser }) => {
  test.setTimeout(600_000)
  const tag = Date.now().toString(36).slice(-5)
  const staff = await staffSignIn(page, '/rentals/setup')
  await expect(page.getByRole('heading', { level: 1, name: 'Rental setup' })).toBeVisible()

  // SSP-04: the location's online booking defaults (saved unchanged, so other specs see the seed's values).
  await page.getByRole('tab', { name: 'Online booking' }).click()
  await expect(page.getByRole('checkbox', { name: 'Members can book rentals online here' })).toBeVisible()
  await scan(page, 'staff rental online booking')
  await page.getByRole('button', { name: 'Save online booking' }).click()
  await expect(page.getByText('Online booking saved.')).toBeVisible()

  // REG-10: the plan fields in a program's online registration form (shown, not saved).
  await page.goto('/programs')
  await page.getByRole('link', { name: 'Summer Sports Camp' }).click()
  await page.getByRole('tab', { name: 'Online registration' }).click()
  await page.getByRole('combobox', { name: 'Payment plan' }).selectOption('instalments')
  await expect(page.getByRole('spinbutton', { name: 'Number of instalments' })).toBeVisible()
  await scan(page, 'staff registration config with instalments')
  await page.getByRole('combobox', { name: 'Payment plan' }).selectOption('deposit')
  await expect(page.getByLabel('Balance due on')).toBeVisible()
  await scan(page, 'staff registration config with deposit')
  const camp = page.url().split('/').pop() ?? ''

  // The member books a session; staff make it virtual (CLS-08).
  const member = await memberPage(browser)
  const { listing, enrollment } = await bookSomething(member.page.request, member.headers)
  const made = await page.request.put(`/api/v1/sessions/${listing.session_id}/video-meeting`, { headers: staff(), data: { provider: 'manual', join_url: 'https://meet.example.com/e2e' } })
  // REG-10: a three-instalment plan on the camp, put back at the end.
  const config = await (await page.request.get(`/api/v1/program-groups/${camp}/registration-config`, { headers: SLUG })).json()
  const planned = await page.request.put(`/api/v1/program-groups/${camp}/registration-config`, {
    headers: staff(),
    data: { payment_requirement: 'immediate_card_payment', payment_plan: 'instalments', instalment_count: 3, instalment_unit: 'month', balance_due_on: new Date(Date.now() + 40 * 86400_000).toISOString().slice(0, 10) },
  })

  try {
    expect(made.ok(), await made.text()).toBe(true)
    expect(planned.ok(), await planned.text()).toBe(true)
    const m = member.page
    for (const colorScheme of ['light', 'dark'] as const) {
      await m.emulateMedia({ colorScheme })
      // SSP-12 and SSP-18: list, week and month; the booked virtual session with its Join button.
      await m.goto('/portal/sessions')
      await expect(m.getByRole('heading', { level: 1, name: 'Book a session' })).toBeVisible()
      const mine = m.getByRole('list', { name: 'Your bookings' })
      await expect(mine.getByRole('button', { name: /^Join online/ }).first()).toBeVisible() // the join itself: portal.spec.ts
      await scan(m, `${colorScheme} sessions list`)
      await m.getByRole('button', { name: 'Week', exact: true }).click()
      await expect(m.getByRole('table', { name: /^Sessions,/ })).toBeVisible()
      await scan(m, `${colorScheme} sessions week`)
      await m.getByRole('button', { name: 'Month', exact: true }).click()
      await expect(m.getByRole('columnheader', { name: 'Monday' })).toBeVisible()
      await scan(m, `${colorScheme} sessions month`)
      const any = m.getByRole('table', { name: /^Sessions,/ }).getByRole('button').first()
      if (await any.count()) {
        await any.focus()
        await m.keyboard.press('Enter')
        await expect(m.getByRole('dialog')).toBeVisible()
        await scan(m, `${colorScheme} session dialog`)
        await m.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).last().click()
      }
      await m.getByRole('button', { name: 'List', exact: true }).click()
      const offer = m.getByRole('button', { name: /^Buy a package and book/ }).first()
      if (await offer.count()) {
        await offer.click()
        await expect(m.getByRole('dialog', { name: 'Buy a package and book' })).toBeVisible()
        await scan(m, `${colorScheme} buy a package and book`)
        await m.getByRole('button', { name: 'Cancel', exact: true }).click()
      }

      // MEM-09 and PKG-09: the saved card is offered first.
      await m.goto('/portal/packages')
      await m.getByRole('button', { name: /^Buy / }).first().click()
      await expect(m.getByRole('dialog').getByRole('radio', { name: /^Saved card/ }).first()).toBeChecked()
      await scan(m, `${colorScheme} buy package`)
      await m.getByRole('button', { name: 'Cancel', exact: true }).click()
      await m.goto('/portal/memberships')
      await m.getByRole('button', { name: /^Buy / }).first().click()
      await expect(m.getByText('Due now')).toBeVisible()
      await scan(m, `${colorScheme} buy membership`)
      await m.getByRole('button', { name: 'Cancel', exact: true }).click()

      // RNT-06: the rental limits, and the saved-card choice at the pay step (the hold is given back on Cancel).
      await m.goto('/portal/bookings')
      await m.getByRole('button', { name: 'Book a rental' }).click()
      const rental = m.getByRole('dialog', { name: 'Book a rental' })
      await expect(rental.getByText(/^Book (up to|any date)/)).toBeVisible()
      const slot = rental.getByRole('listitem').getByRole('button').first()
      if (await slot.count()) {
        await slot.click()
        await expect(rental.getByRole('radio', { name: /^Saved card/ }).first()).toBeVisible()
      }
      await scan(m, `${colorScheme} rental pay step`)
      await rental.getByRole('button', { name: 'Cancel', exact: true }).click()

      // REG-10: the plan on the program card, and due today plus the schedule in the basket.
      await m.goto('/portal/programs')
      await expect(m.getByText(/in 3 instalments, one each month from/).first()).toBeVisible()
      await m.getByRole('button', { name: 'Register for Summer Sports Camp' }).click()
      const reg = m.getByRole('dialog', { name: 'Register for Summer Sports Camp' })
      await reg.getByRole('combobox', { name: 'Who is registering?' }).selectOption({ index: 1 })
      const option = reg.getByRole('combobox', { name: 'Option' })
      if (await option.count()) await option.selectOption({ index: 1 })
      await reg.getByRole('button', { name: 'Add to basket' }).click()
      const plan = m.getByRole('region', { name: 'Payment plan' })
      await expect(plan).toContainText('Due today')
      await expect(plan.getByRole('list', { name: 'Later payments' }).getByRole('listitem')).toHaveCount(3)
      await scan(m, `${colorScheme} basket with a payment plan`)
      await m.getByRole('button', { name: 'Empty basket' }).click()
      await expect(plan).toBeHidden()

      // FIT-05: progress, a share link shown once, the public page, then the link turned off.
      await m.goto('/portal/progress')
      await expect(m.getByRole('heading', { level: 1, name: 'Progress' })).toBeVisible()
      await expect(m.getByRole('table', { name: 'Personal bests' })).toBeVisible()
      await m.getByRole('textbox', { name: 'Label (optional)' }).fill(`E2E ${tag} ${colorScheme}`)
      await m.getByRole('button', { name: 'Create link' }).click()
      await expect(m.getByText('it will not be shown again')).toBeVisible()
      const url = await m.getByRole('textbox', { name: 'Share link' }).inputValue()
      expect(url).toContain('/progress#token=')
      await scan(m, `${colorScheme} progress`)
      const anonymousContext = await browser.newContext({ colorScheme })
      const anonymous = await anonymousContext.newPage()
      await anonymous.goto(`/progress${new URL(url).hash}`)
      await expect(anonymous.getByRole('heading', { level: 1, name: /'s progress$/ })).toBeVisible()
      expect(anonymous.url()).not.toContain('token')
      await scan(anonymous, `${colorScheme} public progress`)
      await m.getByRole('button', { name: `Turn off link E2E ${tag} ${colorScheme}` }).click()
      await expect(m.getByText('The link no longer works.')).toBeVisible()
      // Open the link afresh: from /progress, a goto that only adds the fragment is a same-document navigation and
      // the page (which reads the token once, on load) never sees it.
      await anonymous.goto('about:blank')
      await anonymous.goto(`/progress${new URL(url).hash}`)
      await expect(anonymous.getByText('This link has expired or was turned off.')).toBeVisible()
      await scan(anonymous, `${colorScheme} public progress expired`)
      await anonymousContext.close()
    }

  } finally {
    await page.request.delete(`/api/v1/sessions/${listing.session_id}/video-meeting`, { headers: staff() })
    await page.request.put(`/api/v1/program-groups/${camp}/registration-config`, {
      headers: staff(),
      data: { payment_requirement: config.payment_requirement, payment_plan: config.payment_plan, instalment_count: config.instalment_count, instalment_unit: config.instalment_unit, balance_due_on: config.balance_due_on },
    })
    await member.page.request.post(`/api/v1/portal/enrollments/${enrollment.id}/cancel`, { headers: member.headers() })
    await member.context.close()
  }
})
