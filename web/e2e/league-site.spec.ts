import { expect, test, type Page } from '@playwright/test'
import { scan } from './a11y'

// Phase 14 B2: the public league site, its staff screens, the TV board and moderated classifieds. Seeded demo
// accounts (docs/dev/demo-accounts.md). The member withdraws the post at the end so reruns stay under the limit.
const PASSWORD = 'courtside-demo-2026'
const ADMIN = 'admin@courtside-demo.example.com' // the site is tenant-wide: every location needed
const LEAGUE_ADMIN = 'league-admin@courtside-demo.example.com' // moderates at Downtown only
const MEMBER = 'member@courtside-demo.example.com'

async function signIn(page: Page, path: string, email: string) {
  await page.goto(path)
  await page.getByRole('textbox', { name: 'Email' }).fill(email)
  await page.getByRole('textbox', { name: 'Password' }).fill(PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()
}

const title = `E2E keeper ${Math.random().toString(36).slice(2, 7)}`

test('the league site is set up, a post is moderated and shown, every screen passes axe', async ({ browser }) => {
  test.setTimeout(240_000)
  const staff = await (await browser.newContext()).newPage()
  await signIn(staff, '/leagues/site', ADMIN)
  await expect(staff.getByRole('heading', { level: 1, name: 'League site' })).toBeVisible({ timeout: 30_000 })
  const publish = staff.getByLabel('Publish the league site')
  if (!(await publish.isChecked())) await publish.check()
  const classifieds = staff.getByLabel('Classifieds')
  if (!(await classifieds.isChecked())) await classifieds.check()
  await staff.getByRole('button', { name: 'Save' }).click()
  await expect(staff.getByText('League site saved.')).toBeVisible()
  await scan(staff, 'site options')
  for (const tab of ['News', 'Photos', 'Links', 'Sponsors']) {
    await staff.getByRole('tab', { name: tab }).click()
    await expect(staff.getByRole('tabpanel')).toBeVisible()
    await scan(staff, `${tab} tab`)
  }
  await staff.getByRole('tab', { name: 'News' }).click()
  await staff.getByRole('button', { name: 'Write a story' }).click()
  const story = staff.getByRole('dialog', { name: 'Write a story' })
  await story.getByLabel('Title').fill(`Season news ${title}`)
  await story.getByLabel('Story').fill('Games start next week.')
  await scan(staff, 'story dialog')
  await story.getByRole('button', { name: 'Save story' }).click()
  await expect(story).toBeHidden()
  await expect(staff.getByRole('table', { name: 'News stories' })).toContainText(`Season news ${title}`)

  const member = await (await browser.newContext()).newPage()
  await signIn(member, '/portal', MEMBER)
  await expect(member).toHaveURL(/\/portal$/, { timeout: 30_000 })
  await member.goto('/portal/league-posts')
  await expect(member.getByRole('heading', { level: 1, name: 'Classifieds and pickup games' })).toBeVisible()
  await member.getByLabel('Title').fill(title)
  await member.getByLabel('Details').fill('Our Sunday side needs a keeper for the spring.')
  await member.getByRole('button', { name: 'Post' }).click()
  await expect(member.getByText('Posted. The club checks it before it goes on the league site.')).toBeVisible()
  await scan(member, 'portal posts')

  const moderator = await (await browser.newContext()).newPage()
  await signIn(moderator, '/leagues/posts', LEAGUE_ADMIN)
  const row = moderator.getByRole('row', { name: new RegExp(title) })
  await expect(row).toContainText('Pending', { timeout: 30_000 })
  await scan(moderator, 'moderation queue')
  await row.getByRole('button', { name: `Approve ${title}` }).click()
  await expect(moderator.getByText(`"${title}" is now on the league site.`)).toBeVisible()

  const visitor = await (await browser.newContext()).newPage()
  await visitor.goto('/leagues/public')
  await expect(visitor.getByRole('heading', { name: title, exact: true })).toBeVisible({ timeout: 30_000 })
  await expect(visitor.getByRole('heading', { name: `Season news ${title}` })).toBeVisible()
  await scan(visitor, 'public site')
  await visitor.getByRole('link', { name: 'Wednesday Futsal' }).first().click()
  await expect(visitor.getByRole('heading', { name: 'Teams' })).toBeVisible()
  await scan(visitor, 'public competition')
  await visitor.goto('/leagues/public?embed=1')
  await expect(visitor.getByRole('search', { name: 'Filter competitions' })).toBeVisible()
  await scan(visitor, 'embedded list')
  await visitor.goto('/leagues/public')
  await visitor.getByRole('link', { name: "Today's games" }).first().click()
  await expect(visitor.getByRole('heading', { level: 1, name: /today's games/ })).toBeVisible()
  await scan(visitor, 'tv board')

  await member.reload()
  await member.getByRole('button', { name: `Withdraw ${title}` }).click()
  await expect(member.getByText('Post withdrawn.')).toBeVisible()
})
