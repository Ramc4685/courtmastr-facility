import AxeBuilder from '@axe-core/playwright'
import { expect as baseExpect, test, type Page } from '@playwright/test'

const expect = baseExpect.configure({ timeout: 30_000 })

// Seeded demo data (docs/dev/demo-accounts.md): Morgan Member signs in to the portal; the "10-hour court pack"
// rental plan is sold online and renews automatically.
const MEMBER = { email: 'member@courtside-demo.example.com', password: 'courtside-demo-2026' }

async function scan(page: Page, label: string) {
  await expect(page.getByRole('status').filter({ hasText: /…$/ })).toHaveCount(0)
  const axe = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  expect(axe.violations.map((v) => `${label} ${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`)).toEqual([])
}

test('a member buys a rental plan online with the test card and stops its renewal', async ({ page }) => {
  test.setTimeout(120_000)
  await page.goto('/portal')
  await page.getByRole('textbox', { name: 'Email' }).fill(MEMBER.email)
  await page.getByRole('textbox', { name: 'Password' }).fill(MEMBER.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page).toHaveURL(/\/portal$/)
  await page.getByRole('navigation', { name: 'Portal' }).getByRole('link', { name: 'Rental plans' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Rental plans' })).toBeVisible()
  await scan(page, 'portal rental plans')

  await page.getByRole('button', { name: 'Buy 10-hour court pack' }).click()
  const buy = page.getByRole('dialog', { name: 'Buy 10-hour court pack' })
  await buy.getByRole('combobox', { name: 'Card' }).selectOption('tok_card_ok')
  await scan(page, 'buy rental plan dialog')
  await buy.getByRole('button', { name: /^Pay / }).click()
  await expect(buy.getByText(/10-hour court pack is ready/)).toBeVisible()
  await buy.getByRole('button', { name: 'Done' }).click()

  const owned = page.getByRole('table', { name: 'Your rental plans' })
  await expect(owned).toContainText('10-hour court pack')
  await page.getByRole('button', { name: 'Stop renewal of 10-hour court pack' }).first().click()
  await scan(page, 'stop renewal dialog')
  await page.getByRole('dialog', { name: 'Stop automatic renewal?' }).getByRole('button', { name: 'Stop renewal' }).click()
  await expect(page.getByText('Automatic renewal is off.')).toBeVisible()
})
