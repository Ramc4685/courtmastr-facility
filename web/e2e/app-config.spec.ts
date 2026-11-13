import { expect as baseExpect, test } from '@playwright/test'
import { scan } from './a11y'

test.use({ actionTimeout: 30_000 })

// Generous waits: the API and Vite share a busy development machine with other lanes.
const expect = baseExpect.configure({ timeout: 30_000 })

// Seeded demo owner (docs/dev/demo-accounts.md); the member app settings are tenant-wide (APP-04, APP-05, APP-18).
const OWNER = { email: 'owner@courtside-demo.example.com', password: 'courtside-demo-2026' }

test('staff edit the member app home with a live preview, save it, and the screen passes axe', async ({ page }) => {
  test.setTimeout(300_000)
  await page.goto('/engagement/app')
  await page.getByRole('textbox', { name: 'Email' }).fill(OWNER.email)
  await page.getByRole('textbox', { name: 'Password' }).fill(OWNER.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Member app' })).toBeVisible()
  const preview = page.getByRole('list', { name: 'Home tiles' })
  await expect(preview).toBeVisible()

  const custom = page.getByLabel('Use a custom home layout')
  if (!(await custom.isChecked())) await custom.check()
  const caption = `Book ${Date.now() % 100000}`
  await page.getByLabel('Tile 1 caption').fill(caption)
  await expect(preview.getByText(caption)).toBeVisible() // the preview follows the form before saving

  for (const colorScheme of ['light', 'dark'] as const) {
    await page.emulateMedia({ colorScheme, reducedMotion: 'reduce' })
    await scan(page, `${colorScheme} member app settings`)
  }

  await page.getByRole('button', { name: 'Save app settings' }).click()
  await expect(page.getByText('App settings saved.')).toBeVisible()
  await page.reload()
  await expect(page.getByLabel('Tile 1 caption')).toHaveValue(caption)
})
