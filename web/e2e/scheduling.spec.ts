import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

// Seeded demo account and facility (docs/dev/demo-accounts.md, "Demo facility (build module 2)").
const ADMIN = { email: 'admin@courtside-demo.example.com', password: 'courtside-demo-2026' }

async function scan(page: Page, label: string) {
  const axe = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  expect(axe.violations.map((v) => `${label} ${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`)).toEqual([])
}

async function signIn(page: Page, path: string) {
  await page.goto(path)
  await page.getByRole('textbox', { name: 'Email' }).fill(ADMIN.email)
  await page.getByRole('textbox', { name: 'Password' }).fill(ADMIN.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
}

// A date far enough ahead that the seed and other runs leave it empty; each run picks its own hour.
const day = new Date(Date.now() + (300 + Math.floor(Math.random() * 300)) * 86400000).toISOString().slice(0, 10)
const hour = String(6 + Math.floor(Math.random() * 12)).padStart(2, '0')

test('a time block is booked, conflicts are named, and it is cancelled, all by keyboard', async ({ page }) => {
  await signIn(page, '/schedule')
  await expect(page.getByRole('heading', { level: 1, name: 'Schedule' })).toBeVisible()
  await expect(page.getByText(/Times are in America\/Chicago/)).toBeVisible()

  const book = async () => {
    await page.getByRole('button', { name: 'New booking' }).click()
    const drawer = page.getByRole('dialog', { name: 'New booking' })
    await drawer.getByRole('combobox', { name: 'What' }).selectOption('block')
    await drawer.getByRole('textbox', { name: 'Title' }).fill('E2E hold')
    await drawer.getByLabel('Date').fill(day)
    await drawer.getByLabel('Start').fill(`${hour}:00`)
    await drawer.getByLabel('End').fill(`${hour}:30`)
    await drawer.getByRole('combobox', { name: 'Resource' }).selectOption({ label: 'Court 3 (Venue)' })
    return drawer
  }

  let drawer = await book()
  await scan(page, 'new booking drawer')
  await drawer.getByRole('button', { name: 'Create booking' }).click()
  await expect(drawer).toBeHidden()

  // The same slot again: the server refuses and the drawer names the booking holding it.
  drawer = await book()
  await drawer.getByRole('button', { name: 'Create booking' }).click()
  await expect(drawer.getByRole('alert')).toContainText('That time is already taken.')
  await expect(drawer.getByRole('alert')).toContainText('Court 3 is held by #')
  await drawer.getByRole('button', { name: 'Cancel', exact: true }).click()

  await page.getByLabel('Go to date').fill(day)
  const entry = page.getByRole('button', { name: /^E2E hold/ })
  await entry.focus()
  await page.keyboard.press('Enter')
  const detail = page.getByRole('dialog', { name: 'E2E hold' })
  await expect(detail.getByRole('heading', { name: 'When and where' })).toBeVisible({ timeout: 20_000 })
  await scan(page, 'booking drawer')
  await detail.getByRole('button', { name: 'Cancel booking' }).click()
  await page.getByRole('dialog', { name: 'Cancel E2E hold?' }).getByRole('button', { name: 'Cancel booking' }).click()
  await expect(entry).toBeHidden()
})

test('dragging across a resource column opens a prefilled booking', async ({ page }) => {
  await signIn(page, '/schedule')
  await page.getByLabel('Go to date').fill(day)
  await expect(page.getByRole('heading', { level: 2, name: new RegExp(`\\b${Number(day.slice(8))}, ${day.slice(0, 4)}`) })).toBeVisible()
  const grid = page.locator('[data-grid]')
  const column = grid.locator('div.relative.cursor-crosshair').first()
  const box = await column.boundingBox()
  if (!box) throw new Error('no column')
  await page.mouse.move(box.x + 20, box.y + 72 * 3 + 2) // three hours below the top of the grid
  await page.mouse.down()
  await page.mouse.move(box.x + 20, box.y + 72 * 4 + 2, { steps: 5 })
  await page.mouse.up()
  const drawer = page.getByRole('dialog', { name: 'New booking' })
  await expect(drawer).toBeVisible()
  await expect(drawer.getByLabel('Date')).toHaveValue(day)
  const start = await drawer.getByLabel('Start').inputValue()
  const end = await drawer.getByLabel('End').inputValue()
  expect(Number(end.slice(0, 2)) * 60 + Number(end.slice(3)) - (Number(start.slice(0, 2)) * 60 + Number(start.slice(3)))).toBe(60)
})

// Definition of done: WCAG 2.1 AA on every module 2 screen, both themes.
test('every module 2 screen passes the axe WCAG 2.1 AA scan', async ({ page }) => {
  test.setTimeout(120_000)
  await signIn(page, '/schedule')
  await expect(page.getByRole('heading', { level: 1, name: 'Schedule' })).toBeVisible()
  for (const colorScheme of ['light', 'dark'] as const) {
    await page.emulateMedia({ colorScheme })
    await page.goto('/schedule')
    for (const view of ['day', 'week', 'month']) {
      await page.getByRole('button', { name: view, exact: true }).click()
      // the previous view stays dimmed (and so below contrast) until the new range arrives
      await expect(page.locator('[data-calendar]')).toHaveAttribute('aria-busy', 'false', { timeout: 20_000 })
      await page.waitForLoadState('networkidle')
      await scan(page, `${colorScheme} /schedule ${view}`)
    }
    await page.goto('/resources')
    await expect(page.getByRole('heading', { level: 2, name: 'Courts' })).toBeVisible()
    await scan(page, `${colorScheme} /resources`)
    await page.getByRole('button', { name: 'Availability of Chloe Coach' }).click()
    await expect(page.getByRole('dialog', { name: 'Availability of Chloe Coach' })).toBeVisible()
    await page.waitForLoadState('networkidle')
    await scan(page, `${colorScheme} availability dialog`)
    await page.keyboard.press('Escape')

    await page.goto('/scheduling/setup')
    for (const tab of ['Reservation types', 'Categories', 'Closures', 'Calendar settings']) {
      await page.getByRole('tab', { name: tab }).click()
      await page.waitForLoadState('networkidle')
      await scan(page, `${colorScheme} /scheduling/setup ${tab}`)
    }
  }
  // A session with participants and a waitlist (the seeded private lesson).
  await page.goto('/schedule')
  await page.getByRole('button', { name: 'week', exact: true }).click()
  await page.getByRole('button', { name: /^Private Lesson.*full/ }).first().click()
  await expect(page.getByRole('heading', { name: 'Participants' })).toBeVisible()
  await page.waitForLoadState('networkidle')
  await scan(page, 'session roster')
})

// Phase 10 chip A: slot offers, per-staff type grants, select-to-cancel and changing a series pattern.
test('a trainer window is offered as slots, and the grants dialog opens', async ({ page }) => {
  test.setTimeout(120_000)
  const note = `E2E slots ${Math.random().toString(36).slice(2, 8)}`
  await signIn(page, '/resources')
  await page.getByRole('button', { name: 'Availability of Chloe Coach' }).click()
  const dialog = page.getByRole('dialog', { name: 'Availability of Chloe Coach' })
  await dialog.getByLabel('From', { exact: true }).fill('05:00')
  await dialog.getByLabel('Until', { exact: true }).fill('06:00')
  await dialog.getByRole('textbox', { name: 'Note' }).fill(note)
  await dialog.getByRole('button', { name: 'Add availability' }).click()
  const row = dialog.getByRole('listitem').filter({ hasText: note })
  await row.getByRole('button', { name: /^Offer as slots/ }).click()
  await row.getByRole('combobox', { name: 'Type' }).selectOption({ index: 1 })
  await row.getByRole('button', { name: 'Offer slots' }).click()
  await expect(row).toContainText('Slots:')
  await scan(page, 'availability dialog with a slot offer')
  await row.getByRole('button', { name: /^Show slots/ }).click()
  const slots = page.getByRole('dialog', { name: / slots$/ })
  await expect(slots.getByRole('list', { name: 'Slots' })).toBeVisible()
  await scan(page, 'slots dialog')
  await slots.getByRole('button', { name: 'Close' }).click()
  await row.getByRole('button', { name: /^Remove / }).click() // the offer goes with its window
  await expect(row).toBeHidden()

  await page.goto('/scheduling/setup')
  await page.getByRole('button', { name: /^Who can book / }).first().click()
  const grants = page.getByRole('dialog', { name: /^Who can book / })
  await expect(grants.getByRole('checkbox').first()).toBeVisible()
  await scan(page, 'who can book dialog')
  await grants.getByRole('button', { name: 'Cancel' }).click()
})

test('bookings are picked on the calendar and cancelled together; a series pattern changes with a preview', async ({ page }) => {
  test.setTimeout(120_000)
  const later = new Date(Date.parse(`${day}T00:00:00Z`) + 86400000).toISOString().slice(0, 10)
  await signIn(page, '/schedule')
  const block = async (title: string, date: string, repeat: boolean) => {
    await page.getByRole('button', { name: 'New booking' }).click()
    const drawer = page.getByRole('dialog', { name: 'New booking' })
    await drawer.getByRole('combobox', { name: 'What' }).selectOption('block')
    await drawer.getByRole('textbox', { name: 'Title' }).fill(title)
    await drawer.getByLabel('Date').fill(date)
    await drawer.getByLabel('Start').fill(`${hour}:30`)
    await drawer.getByLabel('End').fill(`${hour}:45`)
    await drawer.getByRole('combobox', { name: 'Resource' }).selectOption({ label: 'Court 3 (Venue)' })
    if (repeat) await drawer.getByRole('checkbox', { name: 'Repeats' }).check()
    await drawer.getByRole('button', { name: 'Create booking' }).click()
    await expect(drawer).toBeHidden()
  }

  await block('E2E pick', day, false)
  await page.getByLabel('Go to date').fill(day)
  await page.getByRole('button', { name: 'Select to cancel' }).click()
  const entry = page.getByRole('button', { name: /^E2E pick/ })
  await entry.click()
  await expect(entry).toHaveAttribute('aria-pressed', 'true')
  await scan(page, 'calendar select mode')
  await page.getByRole('button', { name: 'Cancel selected' }).click()
  await page.getByRole('dialog', { name: 'Cancel 1 booking?' }).getByRole('button', { name: 'Cancel bookings' }).click()
  await expect(entry).toBeHidden()

  await block('E2E pattern', later, true)
  await page.getByLabel('Go to date').fill(later)
  await page.getByRole('button', { name: /^E2E pattern/ }).click()
  const detail = page.getByRole('dialog', { name: 'E2E pattern' })
  await detail.getByRole('button', { name: 'Change pattern' }).click()
  const change = page.getByRole('dialog', { name: 'Change the pattern' })
  await change.getByLabel('End', { exact: true }).fill(`${hour}:50`)
  await change.getByRole('button', { name: 'Check availability' }).click()
  await expect(change.getByText(/^Preview: \d+ cancelled/)).toBeVisible()
  await scan(page, 'change pattern dialog')
  await change.getByRole('button', { name: 'Change pattern' }).click()
  await expect(page.getByText(/Pattern changed: \d+ cancelled, \d+ booked\./)).toBeVisible()
})
