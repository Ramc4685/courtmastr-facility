import { expect, test } from '@playwright/test'
import { scan } from './a11y'

// Seeded demo account, client and kiosk (docs/dev/demo-accounts.md, "Demo check-in (build module 10)").
const DESK = { email: 'front-desk@courtside-demo.example.com', password: 'courtside-demo-2026' }

test('front desk checks a client in by card, exports history, launches the kiosk and self check-in works, all screens pass axe', async ({ page, browser }) => {
  test.setTimeout(120_000) // eight axe scans and a second browser context
  await page.goto('/check-in')
  await page.getByRole('textbox', { name: 'Email' }).fill(DESK.email)
  await page.getByRole('textbox', { name: 'Password' }).fill(DESK.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Check-in' })).toBeVisible()
  await expect(page.getByRole('table', { name: 'Recent check-ins' })).toBeVisible()
  await scan(page, 'check-in window')

  await page.getByLabel('Card or member number').fill('DEMO-CARD-0001')
  await page.getByRole('button', { name: 'Look up' }).click()
  await expect(page.getByRole('heading', { level: 3, name: 'Morgan Member' })).toBeVisible()
  await scan(page, 'status card')
  const created = page.waitForResponse((r) => r.url().endsWith('/api/v1/check-ins') && r.request().method() === 'POST')
  await page.getByRole('button', { name: /^(Check in|Record denied entry)$/ }).click()
  const response = await created
  expect(response.status()).toBe(201)
  const clientId: string = (await response.json()).check_in.client_id
  await expect(page.getByRole('table', { name: 'Recent check-ins' })).toContainText('Morgan Member')

  await page.goto('/check-in/history')
  await page.getByRole('combobox', { name: 'Client' }).fill('Member')
  await page.getByRole('option', { name: /Morgan Member/ }).first().click()
  await expect(page.getByRole('table', { name: 'Check-ins of Morgan Member' })).toBeVisible()
  await scan(page, 'client history')
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Export CSV' }).click()
  expect((await download).suggestedFilename()).toBe('check-ins-morgan-member.csv')

  // CHK-03: the same check-in from the client's profile, at the working location.
  await page.goto(`/clients/${clientId}`)
  const fromProfile = page.waitForResponse((r) => r.url().endsWith('/api/v1/check-ins') && r.request().method() === 'POST')
  await page.getByRole('button', { name: 'Check in', exact: true }).click()
  expect((await fromProfile).status()).toBe(201)
  await expect(page.getByText(/^(Checked in at|Entry denied at) /)).toBeVisible()
  await page.getByRole('tab', { name: 'Check-ins' }).click()
  await expect(page.getByRole('table', { name: 'Check-ins of Morgan Member' })).toBeVisible()
  await scan(page, 'client profile check-ins')

  await page.goto('/check-in/kiosks')
  await expect(page.getByRole('heading', { level: 1, name: 'Kiosks' })).toBeVisible()
  await page.getByRole('button', { name: 'New pairing code for Front door kiosk' }).click()
  const code = (await page.getByRole('status').filter({ hasText: 'Pairing code for' }).locator('p.font-mono').textContent())?.trim() ?? ''
  expect(code).toMatch(/^[A-Z2-9]{8}$/)
  await scan(page, 'kiosk setup')

  // The kiosk is another device: no staff session, only its own cookie after pairing.
  const device = await browser.newContext()
  const kiosk = await device.newPage()
  await kiosk.goto('/kiosk')
  await kiosk.getByLabel('Pairing code').fill(code)
  await kiosk.getByRole('button', { name: 'Pair' }).click()
  await expect(kiosk.getByRole('heading', { name: 'Welcome to Courtside Downtown' })).toBeVisible()
  await scan(kiosk, 'kiosk start')
  await kiosk.getByLabel(/first letters of your last name/).fill('Mem')
  await kiosk.getByRole('button', { name: 'Find me' }).click()
  await kiosk.getByRole('button', { name: 'Morgan M.' }).click()
  await expect(kiosk.getByText(/You're checked in, Morgan!|Please see the front desk, Morgan\./)).toBeVisible()
  await scan(kiosk, 'kiosk result')
  await device.close()
})

test('a manager reviews access rules, check-in settings, access hours and membership locations, and the screen passes axe', async ({ page }) => {
  await page.goto('/check-in/access')
  await page.getByRole('textbox', { name: 'Email' }).fill('manager@courtside-demo.example.com')
  await page.getByRole('textbox', { name: 'Password' }).fill(DESK.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Access rules' })).toBeVisible()
  await expect(page.getByLabel('No visits left')).toHaveValue('deny') // owner question 12: used-up visits are refused
  await expect(page.getByRole('list', { name: 'Access schedules' })).toBeVisible()
  await scan(page, 'access rules')
  const saved = page.waitForResponse((r) => r.url().includes('/api/v1/access-rules') && r.request().method() === 'PUT')
  await page.getByRole('button', { name: 'Save rules' }).click() // unchanged values: saving is a no-op
  expect((await saved).status()).toBe(200)
})
