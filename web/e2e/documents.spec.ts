import { expect, test } from '@playwright/test'
import { scan } from './a11y'

// Seeded demo data (seeds/documents.py): a published "Liability waiver" signed by Morgan Member.
const OWNER = { email: 'owner@courtside-demo.example.com', password: 'courtside-demo-2026' }

test('templates, the editor, the documents tab, in-person signing and the public page pass axe WCAG 2.1 AA', async ({ page }) => {
  test.slow() // eight axe scans plus signing: ~24 s warm, over the 30 s default on a cold dev server
  await page.goto('/documents')
  await page.getByRole('textbox', { name: 'Email' }).fill(OWNER.email)
  await page.getByRole('textbox', { name: 'Password' }).fill(OWNER.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Documents' })).toBeVisible()

  // Issue a fresh waiver to Riley so the run is repeatable.
  await page.goto('/clients')
  await page.getByRole('searchbox', { name: 'Search' }).fill('Riley')
  await page.getByRole('link', { name: 'Riley Reyes' }).click()
  await page.getByRole('tab', { name: 'Documents' }).click()
  await page.getByRole('button', { name: 'Issue document' }).click()
  await page.getByLabel('Template').selectOption({ label: 'Liability waiver' })
  await scan(page, 'issue dialog')
  await page.getByRole('button', { name: 'Issue', exact: true }).click()
  await expect(page.getByText('Document ready to sign')).toBeVisible()

  for (const colorScheme of ['light', 'dark'] as const) {
    await page.emulateMedia({ colorScheme })
    await page.goto('/documents')
    await expect(page.getByRole('link', { name: 'Liability waiver' })).toBeVisible()
    await scan(page, `${colorScheme} templates`)
    await page.getByRole('link', { name: 'Liability waiver' }).click()
    await expect(page.getByRole('heading', { level: 1, name: 'Liability waiver' })).toBeVisible()
    await expect(page.getByText('Assumption of risk').first()).toBeVisible()
    await scan(page, `${colorScheme} editor`)

    await page.goto('/clients')
    await page.getByRole('searchbox', { name: 'Search' }).fill('Riley')
    await page.getByRole('link', { name: 'Riley Reyes' }).click()
    await page.getByRole('tab', { name: 'Documents' }).click()
    await expect(page.getByText('Awaiting signature').first()).toBeVisible()
    await scan(page, `${colorScheme} documents tab`)
    await page.getByRole('button', { name: 'Sign now' }).first().click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await scan(page, `${colorScheme} signing dialog`)
    await page.getByRole('button', { name: 'Close' }).click()

    await page.goto('/sign#token=fhd_not-a-real-token')
    await expect(page.getByRole('alert')).toBeVisible()
    await scan(page, `${colorScheme} public sign page`)
  }

  // Sign one in person, typed, and see the indicator flip.
  await page.goto('/clients')
  await page.getByRole('searchbox', { name: 'Search' }).fill('Riley')
  await page.getByRole('link', { name: 'Riley Reyes' }).click()
  await page.getByRole('tab', { name: 'Documents' }).click()
  await page.getByRole('button', { name: 'Sign now' }).first().click()
  await page.getByLabel('Typed signature').fill('Riley Reyes')
  await page.getByRole('checkbox', { name: /agree to its terms/ }).check()
  await page.getByRole('button', { name: 'Sign document' }).click()
  await expect(page.getByText(/^Waiver on file/)).toBeVisible()
})
