import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import { MEMBER, signIn } from './a11y'

// Seeded demo data (backend/seeds/programs.py): a free "Open Day sign-up" form with a shirt cap, a priced
// "Awards night" form, three classifiers and the "Summer Sports Camp" program at Downtown.

async function scan(page: Page, label: string) {
  await expect(page.getByText(/^Loading/)).toHaveCount(0)
  const axe = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  expect(axe.violations.map((v) => `${label} ${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`)).toEqual([])
}

test('staff build event forms and use the group tools; every screen passes axe', async ({ page }) => {
  test.setTimeout(120_000) // eleven axe scans on a shared machine
  await signIn(page, '/programs/forms')
  await expect(page.getByRole('heading', { level: 1, name: 'Event forms' })).toBeVisible({ timeout: 20_000 })
  await expect(page.getByRole('table', { name: 'Event forms' })).toContainText('Open Day sign-up', { timeout: 20_000 })
  await scan(page, 'event forms list')
  await page.getByRole('button', { name: 'New form' }).click()
  await expect(page.getByRole('dialog', { name: 'New event form' })).toBeVisible()
  await scan(page, 'new form dialog')
  await page.getByRole('button', { name: 'Cancel', exact: true }).click()

  await page.getByRole('link', { name: 'Open Day sign-up' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Open Day sign-up' })).toBeVisible()
  await scan(page, 'form settings')
  for (const tab of ['Questions', 'Stock', 'Registrations', 'Summaries']) {
    await page.getByRole('tab', { name: tab }).click()
    await expect(page.getByRole('tabpanel')).toBeVisible()
    await scan(page, `form ${tab.toLowerCase()}`)
  }

  await page.goto('/programs/setup')
  await expect(page.getByRole('heading', { level: 1, name: 'Program setup' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Save defaults' })).toBeVisible()
  await scan(page, 'program setup')

  await page.goto('/programs')
  await expect(page.getByRole('combobox', { name: 'Season' })).toBeVisible()
  await page.getByRole('button', { name: 'Columns' }).click()
  await scan(page, 'programs list with tools')
  await page.getByRole('link', { name: 'Summer Sports Camp' }).click()
  await page.getByRole('tab', { name: 'Tools' }).click()
  await expect(page.getByRole('button', { name: 'Copy program' })).toBeVisible()
  await scan(page, 'program tools')
})

test('a visitor signs up for a free event without an account', async ({ page, browser }) => {
  await signIn(page, '/programs/forms')
  await page.getByRole('link', { name: 'Open Day sign-up' }).click({ timeout: 20_000 })
  const href = await page.getByRole('link', { name: 'Open the public page' }).getAttribute('href')
  expect(href).toMatch(/^\/forms\//)

  const context = await browser.newContext() // no staff or client session
  const visitor = await context.newPage()
  await visitor.goto(href ?? '')
  await expect(visitor.getByRole('heading', { level: 1, name: 'Club Open Day' })).toBeVisible()
  await scan(visitor, 'public form')
  await visitor.getByRole('textbox', { name: 'Your name' }).fill('Pat Visitor')
  await visitor.getByRole('textbox', { name: 'Email' }).fill('pat.visitor@example.com')
  for (const group of await visitor.getByRole('group').all()) await group.getByRole('radio').first().check()
  await visitor.getByRole('button', { name: 'Register' }).click()
  await expect(visitor.getByText(/^Confirmation number \d+\.$/)).toBeVisible()
  await scan(visitor, 'public form confirmation')
  await context.close()
})

test('a member opens a priced event form in the portal', async ({ page }) => {
  await signIn(page, '/programs/forms')
  await page.getByRole('link', { name: 'Awards night' }).click({ timeout: 20_000 })
  const href = await page.getByRole('link', { name: 'Open the public page' }).getAttribute('href')
  await page.context().clearCookies()

  // Client sign-in always lands on the portal home (SignInPage), so open the form once signed in.
  await signIn(page, '/portal', MEMBER)
  await expect(page.getByRole('heading', { level: 1, name: /^Hello/ })).toBeVisible({ timeout: 20_000 })
  await page.goto(`/portal${href}`)
  await expect(page.getByRole('heading', { level: 1, name: 'End of Season Awards Night' })).toBeVisible()
  await expect(page.getByRole('button', { name: /Register/ })).toBeVisible()
  await scan(page, 'portal priced form')
})
