import { expect, test } from '@playwright/test'
import { scan } from './a11y'

// Seeded demo data (backend/seeds/programs.py): a published "Summer Sports Camp" at Downtown, and a client login.
const ADMIN = { email: 'admin@courtside-demo.example.com', password: 'courtside-demo-2026' }
const MEMBER = { email: 'member@courtside-demo.example.com', password: 'courtside-demo-2026' }

test('staff open the programs screens and every one passes axe', async ({ page }) => {
  test.setTimeout(120_000) // eleven axe scans on a shared machine
  await page.goto('/programs')
  await page.getByRole('textbox', { name: 'Email' }).fill(ADMIN.email)
  await page.getByRole('textbox', { name: 'Password' }).fill(ADMIN.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Programs' })).toBeVisible()
  await expect(page.getByRole('table', { name: 'Programs' })).toContainText('Summer Sports Camp')
  await scan(page, 'programs list')

  await page.getByRole('link', { name: 'Summer Sports Camp' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Summer Sports Camp' })).toBeVisible()
  await scan(page, 'program overview')
  for (const [tab, label] of [['Subgroups (2)', 'subgroups'], ['Sessions', 'sessions'], ['Fees', 'fees'], ['Online registration', 'online registration'], ['Roster', 'roster'], [/Waitlist/, 'waitlist']] as const) {
    await page.getByRole('tab', { name: tab }).click()
    await expect(page.getByRole('tabpanel')).toBeVisible()
    await expect(page.getByText(/^Loading/)).toHaveCount(0)
    await scan(page, label)
  }
  await page.getByRole('tab', { name: 'Fees' }).click()
  await expect(page.getByRole('table', { name: 'Program fees' })).toContainText('Camp week')
  await page.getByRole('button', { name: 'Add fee' }).click()
  await scan(page, 'new fee dialog')
  await page.getByRole('button', { name: 'Cancel', exact: true }).click()
  await page.getByRole('tab', { name: 'Roster' }).click()
  await page.getByRole('button', { name: 'Register a client' }).click()
  await expect(page.getByRole('dialog', { name: 'Register for Summer Sports Camp' })).toBeVisible()
  await scan(page, 'register dialog')
  await page.getByRole('button', { name: 'Cancel', exact: true }).click()

  await page.goto('/programs/register')
  await expect(page.getByRole('heading', { level: 1, name: 'Registration basket' })).toBeVisible()
  await scan(page, 'registration basket')

  await page.goto('/programs/booking-policies')
  await expect(page.getByRole('heading', { level: 1, name: 'Booking policies' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Save default' })).toBeVisible()
  await scan(page, 'booking policies')
})

test('a client sees published programs and session booking, both pass axe', async ({ page }) => {
  const signed = await page.request.post('/api/v1/auth/sign-in', {
    data: { ...MEMBER, audience: 'client', client_kind: 'web' },
    headers: { 'x-tenant-slug': 'courtside-demo', 'idempotency-key': crypto.randomUUID() },
  })
  expect(signed.ok()).toBe(true)
  await page.goto('/portal/programs')
  await expect(page.getByRole('heading', { level: 1, name: 'Programs' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Summer Sports Camp' }).first()).toBeVisible()
  await scan(page, 'portal programs')
  await page.goto('/portal/sessions')
  await expect(page.getByRole('heading', { level: 1, name: 'Book a session' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Your bookings' })).toBeVisible()
  await expect(page.getByText(/^Loading/)).toHaveCount(0)
  await scan(page, 'portal sessions')
})
