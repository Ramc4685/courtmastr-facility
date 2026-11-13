import { expect as baseExpect, test } from '@playwright/test'
import { MEMBER, PASSWORD, scanAfter } from './a11y'

const scan = scanAfter(/…$/, 30_000)

test.use({ actionTimeout: 30_000 })

// Generous waits: the API and Vite share a busy development machine with other lanes.
const expect = baseExpect.configure({ timeout: 30_000 })

// Seeded demo owner and member (docs/dev/demo-accounts.md). The seed has no app inquiries, so the member sends
// feedback through the portal API first; the staff then create a content item and handle that feedback.
const OWNER = { email: 'owner@courtside-demo.example.com', password: PASSWORD }
const SLUG = { 'x-tenant-slug': 'courtside-demo' }

test('staff create app content, change a feedback status in the inbox, and every tab passes axe', async ({ page, browser }) => {
  test.setTimeout(300_000)
  const tag = Date.now().toString(36).slice(-6)

  // The member's feedback, from a context of their own (the web sign-in form is staff-only).
  const member = await browser.newContext()
  const memberRequest = member.request
  const out = await memberRequest.post('/api/v1/auth/sign-in', {
    headers: { ...SLUG, 'idempotency-key': crypto.randomUUID() }, data: { email: MEMBER, password: PASSWORD, audience: 'client', client_kind: 'web' },
  })
  expect(out.ok()).toBe(true)
  const { csrf_token } = await out.json()
  const self = (await (await memberRequest.get('/api/v1/portal/clients', { headers: SLUG })).json()).data.find((c: { authority: string }) => c.authority === 'self')
  const message = `E2E feedback ${tag}: the new courts are great.`
  const sent = await memberRequest.post('/api/v1/portal/feedback', {
    headers: { ...SLUG, 'x-csrf-token': csrf_token, 'idempotency-key': crypto.randomUUID() }, data: { client_id: self.id, message, rating: 5 },
  })
  expect(sent.status()).toBe(201)
  await member.close()

  await page.goto('/engagement/app-content')
  await page.getByRole('textbox', { name: 'Email' }).fill(OWNER.email)
  await page.getByRole('textbox', { name: 'Password' }).fill(OWNER.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Member app content' })).toBeVisible()

  // Content: create an item for every location and find it in the list.
  const title = `E2E news ${tag}`
  await page.getByRole('button', { name: 'New content' }).click()
  const dialog = page.getByRole('dialog', { name: 'New content' })
  await dialog.getByLabel('Kind').selectOption('news')
  await dialog.getByLabel('Title').fill(title)
  await dialog.getByLabel('Text').fill('Courts 1 to 4 have new surfaces.')
  await dialog.getByLabel('Link').fill('https://example.com/courts')
  await scan(page, 'new content dialog')
  await dialog.getByRole('button', { name: 'Create content' }).click()
  await expect(dialog).toBeHidden()
  const contentRow = page.getByRole('row').filter({ hasText: title })
  await expect(contentRow).toBeVisible()
  await expect(contentRow.getByText('Every location')).toBeVisible()

  for (const colorScheme of ['light', 'dark'] as const) {
    await page.emulateMedia({ colorScheme, reducedMotion: 'reduce' })
    for (const tab of ['Content', 'Contacts', 'Inbox', 'Usage']) {
      await page.getByRole('tab', { name: tab }).click()
      await expect(page.getByRole('tabpanel', { name: tab })).toBeVisible()
      await scan(page, `${colorScheme} ${tab}`)
    }
  }

  // Inbox: the member's feedback arrives as new; move it to in progress.
  await page.getByRole('tab', { name: 'Inbox' }).click()
  await page.getByLabel('Kind').selectOption('feedback')
  const inquiryRow = page.getByRole('row').filter({ hasText: message })
  await expect(inquiryRow).toBeVisible()
  await expect(inquiryRow.getByText('5 of 5')).toBeVisible()
  const status = inquiryRow.getByLabel(/^Status for /)
  await expect(status).toHaveValue('new')
  await status.selectOption('in_progress')
  await expect(page.getByText('Status changed.')).toBeVisible()
  await page.reload()
  await page.getByRole('tab', { name: 'Inbox' }).click()
  await expect(page.getByRole('row').filter({ hasText: message }).getByLabel(/^Status for /)).toHaveValue('in_progress')

  // Put the content back so repeated runs leave the demo tenant as it was.
  await page.getByRole('tab', { name: 'Content' }).click()
  await page.getByRole('button', { name: `Delete ${title}` }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Delete' }).click()
  await expect(page.getByRole('row').filter({ hasText: title })).toHaveCount(0)
})
