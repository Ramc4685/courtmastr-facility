import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'

// Seeded demo account (docs/dev/demo-accounts.md); exists only in dev and test databases.
const ADMIN = { email: 'admin@courtside-demo.example.com', password: 'courtside-demo-2026' }

test('staff signs in and opens the staff users page', async ({ page }) => {
  await page.goto('/staff')
  await expect(page).toHaveURL(/\/sign-in\?next=%2Fstaff/)
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()

  await page.getByRole('textbox', { name: 'Email' }).fill(ADMIN.email)
  await page.getByRole('textbox', { name: 'Password' }).fill(ADMIN.password)
  await page.getByRole('button', { name: 'Sign in' }).click()

  await expect(page).toHaveURL(/\/staff$/)
  await expect(page.getByRole('heading', { level: 1, name: 'Staff users' })).toBeVisible()
  await expect(page.getByRole('table', { name: 'Staff users' }).getByText('owner@courtside-demo.example.com')).toBeVisible()

  const axe = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  expect(axe.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`)).toEqual([])

  // The session survives a reload (cookie session restore, CSRF token re-read from /auth/session).
  await page.reload()
  await expect(page.getByRole('heading', { level: 1, name: 'Staff users' })).toBeVisible()
  await page.getByRole('button', { name: /account menu/i }).click()
  await page.getByRole('button', { name: 'Sign out' }).click()
  await expect(page).toHaveURL(/\/sign-in/)
})

// Definition of done: WCAG 2.1 AA on every web screen. A new module adds its routes to its own spec.
test('every module 1 screen passes the axe WCAG 2.1 AA scan', async ({ page }) => {
  test.setTimeout(120_000) // fourteen axe scans; well over 30s on a loaded machine
  const scan = async (label: string) => {
    const axe = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
    expect(axe.violations.map((v) => `${label} ${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`)).toEqual([])
  }
  await page.goto('/sign-in')
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
  await scan('/sign-in')
  await page.getByRole('textbox', { name: 'Email' }).fill(ADMIN.email)
  await page.getByRole('textbox', { name: 'Password' }).fill(ADMIN.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('button', { name: /account menu/i })).toBeVisible()

  // Both themes: the default follows the system setting, and contrast differs per theme.
  for (const colorScheme of ['light', 'dark'] as const) {
    await page.emulateMedia({ colorScheme })
    for (const path of ['/', '/locations', '/staff', '/roles', '/audit', '/settings', '/settings/security']) {
      await page.goto(path)
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
      await page.waitForLoadState('networkidle')
      await scan(`${colorScheme} ${path}`)
    }
  }
  // Detail pages, reached the way a person reaches them.
  await page.goto('/staff')
  await page.getByRole('table', { name: 'Staff users' }).getByRole('link').first().click()
  await expect(page).toHaveURL(/\/staff\/[0-9a-f-]{36}$/)
  await page.waitForLoadState('networkidle')
  await scan('/staff/:id')
  await page.goto('/roles')
  await page.getByRole('table').getByRole('link').first().click()
  await expect(page).toHaveURL(/\/roles\/[0-9a-f-]{36}$/)
  await page.waitForLoadState('networkidle')
  await scan('/roles/:id')
})
