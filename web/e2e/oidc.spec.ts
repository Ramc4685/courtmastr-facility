import { expect, test } from '@playwright/test'
import { scan } from './a11y'

// Seeded demo account (docs/dev/demo-accounts.md); exists only in dev and test databases. Only the Owner may
// add a sign-in provider.
const OWNER = { email: 'owner@courtside-demo.example.com', password: 'courtside-demo-2026' }

// A real provider needs a public issuer (its discovery document is fetched when it is saved), so the sign-in
// buttons are shown from a stubbed provider list; the rest runs against the live API.
test('OIDC screens: sign-in buttons, callback refusal and the provider form pass axe', async ({ page }) => {
  test.setTimeout(90_000)
  await page.route('**/api/v1/auth/oidc/providers', (route) =>
    route.fulfill({ json: [{ id: '00000000-0000-7000-8000-000000000001', display_name: 'Google', preset: 'google' }] }),
  )
  for (const colorScheme of ['light', 'dark'] as const) {
    await page.emulateMedia({ colorScheme, reducedMotion: 'reduce' })
    await page.goto('/sign-in')
    await expect(page.getByRole('button', { name: 'Continue with Google' })).toBeVisible()
    await scan(page, `${colorScheme} /sign-in`)

    // The provider sent the browser back without a code: no API call, a plain explanation.
    await page.goto('/auth/oidc/callback?error=access_denied&state=fho_x')
    await expect(page.getByRole('alert')).toContainText('Sign-in was cancelled at the provider.')
    await expect(page).toHaveURL(/\/auth\/oidc\/callback$/)
    await scan(page, `${colorScheme} /auth/oidc/callback`)

    // The emailed link page waits for a deliberate click and strips the token from the address bar.
    await page.goto('/auth/oidc/link#token=fhl_x')
    await expect(page.getByRole('button', { name: 'Connect my account' })).toBeVisible()
    await expect(page).toHaveURL(/\/auth\/oidc\/link$/)
    await scan(page, `${colorScheme} /auth/oidc/link`)
  }

  // A forged state is refused by the API (the real round trip, not stubbed).
  await page.goto('/auth/oidc/callback?code=c&state=fho_00000000000000000000000000000000_forged')
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Back to sign in' })).toBeVisible()

  await page.goto('/sign-in?next=/settings/security')
  await page.getByRole('textbox', { name: 'Email' }).fill(OWNER.email)
  await page.getByRole('textbox', { name: 'Password' }).fill(OWNER.password)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Security' })).toBeVisible()
  await page.getByRole('button', { name: 'Add a sign-in provider' }).click()
  await page.getByRole('combobox', { name: 'Provider' }).selectOption('microsoft')
  await expect(page.getByRole('textbox', { name: /Directory \(tenant\) ID/ })).toBeVisible()
  await expect(page.getByText(/\/auth\/oidc\/callback$/)).toBeVisible()
  for (const colorScheme of ['light', 'dark'] as const) {
    await page.emulateMedia({ colorScheme, reducedMotion: 'reduce' })
    await scan(page, `${colorScheme} provider form`)
  }
})
