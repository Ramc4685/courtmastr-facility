import AxeBuilder from '@axe-core/playwright'
import { expect as baseExpect, test, type Page } from '@playwright/test'
import { ADMIN, PASSWORD } from './a11y'

// Phase 11 chip A: the public facility pages under /f/:slug (SSP-01, 05, 15, REG-12) and the staff settings
// behind them (SSP-13, 07). Seeded demo tenant: courtside-demo (docs/dev/demo-accounts.md).
const expect = baseExpect.configure({ timeout: 30_000 })
const SLUG = 'courtside-demo'

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
