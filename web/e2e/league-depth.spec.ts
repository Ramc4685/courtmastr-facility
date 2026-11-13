import { expect, test } from '@playwright/test'
import { ADMIN, MEMBER, scan, signIn } from './a11y'

// Phase 14 B1 league depth screens on the seeded demo league (docs/dev/demo-accounts.md, "Demo leagues").
const LEAGUE_ADMIN = 'league-admin@courtside-demo.example.com'
const SCOREKEEPER = 'scorekeeper@courtside-demo.example.com'
const tag = Array.from({ length: 5 }, () => String.fromCharCode(65 + Math.floor(Math.random() * 26))).join('')

test('league depth screens work and pass axe: venues, stats, staff, generator, scores, captain roster', async ({ browser }) => {
  test.setTimeout(180_000) // three sign-ins; password hashing alone can take 10s on a loaded machine
  const admin = await (await browser.newContext()).newPage()
  await signIn(admin, '/leagues/venues', LEAGUE_ADMIN)
  await expect(admin.getByRole('heading', { level: 1, name: 'League venues' })).toBeVisible({ timeout: 30_000 })
  await admin.getByLabel('Venue name').fill(`E2E venue ${tag}`)
  const courts = admin.getByRole('group', { name: 'Courts' }).getByRole('checkbox')
  await courts.first().check()
  await courts.nth(1).check()
  await admin.getByRole('button', { name: 'Add venue' }).click()
  await expect(admin.getByRole('table', { name: 'Venues' })).toContainText(`E2E venue ${tag}`)
  await scan(admin, 'venues')

  // Stat tables are tenant-wide setup: a league admin at one location sees the refusal, the owner adds one.
  await admin.goto('/leagues/stats')
  await admin.getByLabel('New stat table').fill(`E2E stats ${tag}`)
  await admin.getByRole('button', { name: 'Add table' }).click()
  await expect(admin.getByRole('alert').filter({ hasText: /./ })).toBeVisible()
  const owner = await (await browser.newContext()).newPage()
  await signIn(owner, '/leagues/stats', ADMIN)
  await owner.getByLabel('New stat table').fill(`E2E stats ${tag}`)
  await owner.getByRole('button', { name: 'Add table' }).click()
  const form = owner.getByRole('form', { name: `Add a stat to E2E stats ${tag}` })
  await form.getByLabel('Code').fill(tag)
  await form.getByLabel('Stat name').fill('Goals')
  await form.getByRole('button', { name: 'Add stat' }).click()
  await expect(owner.getByRole('table', { name: `E2E stats ${tag} stats` })).toContainText('Goals')
  await scan(owner, 'stats')
  await owner.context().close()

  await admin.goto('/leagues')
  await admin.getByRole('link', { name: 'Wednesday Futsal' }).click()
  await admin.getByRole('tab', { name: 'Staff' }).click()
  const staff = admin.getByRole('table', { name: 'Competition staff' })
  const who = admin.getByRole('combobox', { name: 'Staff member' })
  const sam = who.locator('option', { hasText: /^Sam / })
  await expect(sam).toHaveCount(1) // staff and candidates loaded; the lane keeps Sam from an earlier run
  if (!(await staff.isVisible()) || !(await staff.textContent())?.includes('Sam ')) {
    await who.selectOption((await sam.getAttribute('value')) ?? '')
    await admin.getByRole('button', { name: 'Assign' }).click()
  }
  await expect(staff).toContainText('Sam ')
  await scan(admin, 'staff tab')

  await admin.getByRole('tab', { name: 'Teams' }).click()
  await admin.getByRole('button', { name: 'Scheduling preferences of Downtown Strikers' }).click()
  const prefs = admin.getByRole('dialog', { name: 'Scheduling preferences: Downtown Strikers' })
  await prefs.getByRole('button', { name: 'Add a preference' }).click()
  await scan(admin, 'preferences dialog')
  await prefs.getByRole('button', { name: 'Cancel' }).click()

  await admin.getByRole('tab', { name: 'Schedule & results' }).click()
  await admin.getByRole('button', { name: 'Generate schedule' }).click()
  const generate = admin.getByRole('dialog', { name: 'Generate the schedule' })
  await generate.getByRole('button', { name: 'Add a window' }).click()
  await expect(generate.getByRole('combobox', { name: 'Window 2 court or venue' })).toBeVisible()
  await scan(admin, 'generate dialog')
  await generate.getByRole('button', { name: 'Cancel' }).click()

  await admin.getByRole('tab', { name: 'Bracket' }).click()
  await expect(admin.getByRole('combobox', { name: 'Bracket' })).toBeVisible()
  await scan(admin, 'bracket tab')
  await admin.getByRole('tab', { name: 'Player stats' }).click()
  await scan(admin, 'player stats tab')
  await admin.context().close()

  const keeper = await (await browser.newContext()).newPage()
  await signIn(keeper, '/leagues/scores', SCOREKEEPER)
  await expect(keeper.getByRole('heading', { level: 1, name: 'Scores' })).toBeVisible({ timeout: 30_000 })
  await expect(keeper.getByRole('table', { name: 'Games to score' })).toBeVisible()
  await scan(keeper, 'scores')
  await keeper.getByRole('button', { name: /^Enter player stats of / }).first().click()
  await expect(keeper.getByRole('dialog', { name: /^Player stats: / })).toBeVisible()
  await scan(keeper, 'player stats dialog')
  await keeper.context().close()

  const member = await (await browser.newContext()).newPage()
  await signIn(member, '/sign-in?as=member', MEMBER)
  await expect(member).toHaveURL(/\/portal/, { timeout: 30_000 })
  await member.goto('/portal/teams')
  await expect(member.getByRole('table', { name: 'Downtown Strikers roster' })).toBeVisible()
  await scan(member, 'captain roster')
  await member.context().close()
})
