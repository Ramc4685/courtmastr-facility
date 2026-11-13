import { expect, test } from '@playwright/test'
import { PASSWORD, scan } from './a11y'

// Seeded demo data (docs/dev/demo-accounts.md): Mia Member's birth date was typed in, so it waits for the one-time
// staff age check. The spec opens the confirm dialog but never confirms, so the queue stays as seeded.
const OWNER = 'owner@courtside-demo.example.com'

test('age-check queue, the client mark and the confirm dialog pass the axe WCAG 2.1 AA scan', async ({ page }) => {
  test.setTimeout(120_000)
  await page.goto('/clients/age-checks')
  await page.getByRole('textbox', { name: 'Email' }).fill(OWNER)
  await page.getByRole('textbox', { name: 'Password' }).fill(PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()

  for (const colorScheme of ['light', 'dark'] as const) {
    await page.emulateMedia({ colorScheme })
    await page.goto('/clients/age-checks')
    await expect(page.getByRole('heading', { level: 1, name: 'Age checks' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Mia Member' })).toBeVisible()
    await scan(page, `${colorScheme} queue`)
    await page.getByRole('link', { name: 'Mia Member' }).click()
    await expect(page.getByText('Age not confirmed')).toBeVisible()
    await page.getByRole('button', { name: 'Confirm age' }).click()
    await expect(page.getByRole('dialog', { name: 'Confirm age' })).toBeVisible()
    await scan(page, `${colorScheme} confirm dialog`)
    await page.keyboard.press('Escape')
  }
})
