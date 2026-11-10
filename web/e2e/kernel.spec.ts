import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'

// Seeded demo data (docs/dev/demo-accounts.md): front desk may read clients; Morgan Member is M-1001.
const DESK = { email: 'front-desk@courtside-demo.example.com', password: 'courtside-demo-2026' }

// Kernel slices have one web surface: the shared client picker, previewed on a development-only page.
test('client picker finds a client by keyboard and passes the axe WCAG 2.1 AA scan', async ({ page }) => {
  const scan = async (label: string) => {
    const axe = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
    expect(axe.violations.map((v) => `${label} ${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`)).toEqual([])
  }
  await page.goto('/dev/client-picker')
  await page.getByRole('textbox', { name: 'Email' }).fill(DESK.email)
  await page.getByRole('textbox', { name: 'Password' }).fill(DESK.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Client picker' })).toBeVisible()

  for (const colorScheme of ['light', 'dark'] as const) {
    await page.emulateMedia({ colorScheme })
    const picker = page.getByRole('combobox', { name: 'Client' })
    await scan(`${colorScheme} empty`)
    await picker.fill('m-1001') // member number, case-insensitive
    await expect(page.getByRole('option', { name: /Morgan Member/ })).toBeVisible()
    await expect(page.getByRole('status')).toHaveText('1 client found.')
    await scan(`${colorScheme} open list`)
    await picker.press('Enter')
    await expect(page.getByRole('group', { name: 'Client' })).toContainText('Morgan Member')
    await scan(`${colorScheme} selected`)
    await page.getByRole('button', { name: /Change client/ }).click()
    await picker.fill('zzzz')
    await expect(page.getByRole('status')).toHaveText('No clients match.')
    await scan(`${colorScheme} no match`)
    await picker.fill('')
  }
})
