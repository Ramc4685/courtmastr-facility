import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

// Phase 14 C2: post-billed rates and the period close (PKG-11, BIL-18), opening a post-billed package and binding
// a membership agreement (DOC-11) from the client profile, and the public direct-link page (SCH-16).
// Seeded demo data (docs/dev/demo-accounts.md): Morgan Member (M-1001) holds a membership; Downtown has
// "Private Lesson" sessions.
const OWNER = { email: 'owner@courtside-demo.example.com', password: 'courtside-demo-2026' }

async function scan(page: Page, label: string) {
  await expect(page.getByRole('status').filter({ hasText: /^(Loading|Checking)/ })).toHaveCount(0)
  const axe = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  expect(axe.violations.map((v) => `${label} ${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`)).toEqual([])
}

async function signIn(page: Page, path: string) {
  await page.goto(path)
  await page.getByRole('textbox', { name: 'Email' }).fill(OWNER.email)
  await page.getByRole('textbox', { name: 'Password' }).fill(OWNER.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
}

test('post-billed rates, the period close, and the client dialogs pass axe', async ({ page }) => {
  test.setTimeout(120_000)
  await signIn(page, '/packages')
  await expect(page.getByRole('heading', { level: 1, name: 'Packages' })).toBeVisible()

  await page.getByRole('tab', { name: 'Post-billed rates' }).click()
  const type = page.getByRole('combobox', { name: 'Reservation type' })
  await expect(type.locator('option')).not.toHaveCount(1)
  await type.selectOption({ index: 1 })
  const sessions = page.getByRole('spinbutton', { name: 'From sessions' })
  const price = page.getByRole('textbox', { name: 'Price per session' })
  const table = page.getByRole('table', { name: 'Post-billed rates' })
  await sessions.fill('1') // tiers start at one session (on a reused database this tier exists and is refused)
  await price.fill('20')
  await page.getByRole('button', { name: 'Add rate' }).click()
  await expect(table).toBeVisible()
  await sessions.fill(String(2 + (Date.now() % 500))) // a fresh higher tier
  await price.fill('25')
  await page.getByRole('button', { name: 'Add rate' }).click()
  await expect(table).toContainText('$25.00')
  await scan(page, 'post-billed rates')

  await page.getByRole('tab', { name: 'Period close' }).click()
  await page.getByRole('button', { name: 'Preview' }).click()
  await expect(page.getByRole('heading', { name: 'What this close bills' })).toBeVisible()
  await scan(page, 'period close preview')

  await page.goto('/clients')
  await page.getByRole('searchbox', { name: 'Search' }).fill('M-1001')
  await page.getByRole('link', { name: 'Morgan Member' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Morgan Member' })).toBeVisible()
  await page.getByRole('tab', { name: 'Packages' }).click()
  await page.getByRole('button', { name: 'Open post-billed' }).click()
  await expect(page.getByRole('dialog', { name: 'Open a post-billed package' })).toBeVisible()
  await scan(page, 'open post-billed dialog')
  await page.getByRole('dialog').getByRole('button', { name: 'Cancel' }).click()

  await page.getByRole('tab', { name: 'Memberships' }).click()
  await page.getByRole('button', { name: /^Agreement: / }).first().click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await scan(page, 'membership agreement dialog')
})

test('a session drawer shows its direct link and merge controls, and passes axe', async ({ page }) => {
  await signIn(page, '/schedule')
  await page.getByRole('button', { name: 'week', exact: true }).click()
  await page.getByRole('button', { name: /^Private Lesson.*full/ }).first().click()
  await expect(page.getByRole('heading', { name: 'Shared with' })).toHaveCount(0) // a class session has no organiser
  await expect(page.getByRole('button', { name: 'Link into series' })).toBeVisible()
  await page.getByRole('button', { name: /^(Create|New) link$/ }).click()
  const link = page.getByRole('textbox', { name: 'Registration link' })
  await expect(link).toHaveValue(/\/direct-link#token=/)
  expect(await link.inputValue()).not.toContain('?')
  await scan(page, 'session drawer with a direct link')
  await page.getByRole('button', { name: 'Turn off link' }).click() // leave the seeded session as it was
  await expect(link).toBeHidden()
})

test('a direct link that is not valid says so, and the token leaves the address bar', async ({ page }) => {
  await page.goto('/direct-link#token=not-a-real-link-token')
  await expect(page.getByRole('alert')).toContainText('This link is not valid any more.')
  await expect(page).not.toHaveURL(/token/)
  await scan(page, 'direct link page')
})
