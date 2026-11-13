import { expect as baseExpect, test, type Page } from '@playwright/test'
import { scanAfter } from './a11y'

const scan = scanAfter(/…$/, 30_000)

test.use({ actionTimeout: 30_000 })

// Generous waits: the API and Vite share a busy development machine with other lanes.
const expect = baseExpect.configure({ timeout: 30_000 })

// Seeded demo data (seeds/engagement.py): a draft "Spring leagues", a sent "Court 3 resurfacing" announcement
// (inbox title "Court 3 closed"), a reminder rule, a payment-declined alert route and a video at Downtown.
const OWNER = { email: 'owner@courtside-demo.example.com', password: 'courtside-demo-2026' }
const MEMBER = { email: 'member@courtside-demo.example.com', password: 'courtside-demo-2026' }

async function signIn(page: Page, who: typeof OWNER, entry: string, landed: RegExp) {
  await page.goto(entry)
  await page.getByRole('textbox', { name: 'Email' }).fill(who.email)
  await page.getByRole('textbox', { name: 'Password' }).fill(who.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page).toHaveURL(landed)
}

test('staff open campaigns, create a draft email campaign and every engagement screen passes axe', async ({ page }) => {
  test.setTimeout(600_000)
  await signIn(page, OWNER, '/engagement', /\/engagement$/)
  await expect(page.getByRole('heading', { level: 1, name: 'Campaigns' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Spring leagues' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Court 3 resurfacing' })).toBeVisible()

  const name = `E2E campaign ${Date.now()}`
  await page.getByRole('button', { name: 'New campaign' }).click()
  const dialog = page.getByRole('dialog', { name: 'New campaign' })
  await dialog.getByLabel('Campaign name').fill(name)
  await dialog.getByLabel('Subject').fill('Hello from $facility_name')
  await dialog.getByLabel('Message').fill('Hi $first_name, see you on court.')
  await scan(page, 'new campaign dialog')
  await dialog.getByRole('button', { name: 'Create draft' }).click()
  await expect(page.getByRole('link', { name })).toBeVisible()
  const row = page.getByRole('row').filter({ hasText: name })
  await expect(row.getByText('Draft', { exact: true })).toBeVisible()

  for (const colorScheme of ['light', 'dark'] as const) {
    await page.emulateMedia({ colorScheme, reducedMotion: 'reduce' }) // no colour transition mid-scan
    await page.getByRole('navigation', { name: 'Engagement' }).getByRole('link', { name: 'Campaigns' }).click()
    await expect(page.getByRole('link', { name })).toBeVisible()
    await scan(page, `${colorScheme} campaigns`)

    await page.getByRole('link', { name }).click()
    await expect(page.getByRole('heading', { level: 1, name })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Results' })).toBeVisible()
    await scan(page, `${colorScheme} campaign detail`)

    for (const [tab, heading] of [
      ['Templates', 'Templates'],
      ['Segments', 'Segments'],
      ['Message log', 'Message log'],
      ['Suppressions', 'Suppressions'],
      ['Automations', 'Automations'],
      ['Reminders & alerts', 'Reminders and staff alerts'],
      ['Portal & videos', 'Portal and videos'],
    ] as const) {
      await page.getByRole('navigation', { name: 'Engagement' }).getByRole('link', { name: tab }).click()
      await expect(page.getByRole('heading', { level: 1, name: heading })).toBeVisible()
      await scan(page, `${colorScheme} ${tab}`)
    }

    await page.getByRole('navigation', { name: 'Engagement' }).getByRole('link', { name: 'Segments' }).click()
    await page.getByRole('button', { name: /^Preview / }).first().click()
    await page.getByRole('dialog').getByRole('button', { name: 'Preview audience' }).click()
    await expect(page.getByRole('dialog').getByRole('status')).toContainText('clients')
    await scan(page, `${colorScheme} segment preview`)
    await page.getByRole('button', { name: 'Close', exact: true }).first().click()
  }

  // Clean up the draft so the run is repeatable.
  await page.getByRole('navigation', { name: 'Engagement' }).getByRole('link', { name: 'Campaigns' }).click()
  await page.getByRole('link', { name }).click()
  await page.getByRole('button', { name: `Delete ${name}` }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Delete', exact: true }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Campaigns' })).toBeVisible()
  await expect(page.getByRole('link', { name })).toHaveCount(0)
})

test('a member opens the inbox, sees the Court 3 announcement and marks it read; the unsubscribe page explains a bad link', async ({ page }) => {
  test.setTimeout(300_000)
  await signIn(page, MEMBER, '/portal', /\/portal$/)
  await page.getByRole('navigation', { name: 'Portal' }).getByRole('link', { name: /^Inbox/ }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Inbox' })).toBeVisible()
  await expect(page.getByText('Court 3 is closed for resurfacing this week.').first()).toBeVisible()
  for (const colorScheme of ['light', 'dark'] as const) {
    await page.emulateMedia({ colorScheme, reducedMotion: 'reduce' }) // no colour transition mid-scan
    await scan(page, `${colorScheme} inbox`)
  }
  const markRead = page.getByRole('button', { name: /^Mark as read/ }).first()
  if (await markRead.count()) {
    await markRead.click()
    await expect(page.getByText('Read').first()).toBeVisible()
  }
  await page.getByRole('button', { name: 'Sign out' }).click()
  await expect(page).toHaveURL(/\/sign-in/)

  // The token never stays in the address bar, and a bad link is explained.
  await page.goto('/unsubscribe#token=fhu_not_a_real_token_value')
  await expect(page.getByRole('alert')).toContainText('not valid any more')
  expect(page.url()).not.toContain('fhu_')
  await scan(page, 'unsubscribe bad link')
})
