import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

// Seeded demo account and league (docs/dev/demo-accounts.md, "Demo leagues (build module 11)").
const LEAGUE_ADMIN = { email: 'league-admin@courtside-demo.example.com', password: 'courtside-demo-2026' }

async function scan(page: Page, label: string) {
  const axe = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  expect(axe.violations.map((v) => `${label} ${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`)).toEqual([])
}

const starts = new Date(Date.now() + (400 + Math.floor(Math.random() * 300)) * 86400000).toISOString().slice(0, 10)
const name = `E2E league ${Math.random().toString(36).slice(2, 7)}`

test('a league is created, scored and shown publicly, all screens pass axe', async ({ page }) => {
  test.setTimeout(120_000) // sign-in hashing alone can take 10s on a loaded machine
  await page.goto('/leagues')
  await page.getByRole('textbox', { name: 'Email' }).fill(LEAGUE_ADMIN.email)
  await page.getByRole('textbox', { name: 'Password' }).fill(LEAGUE_ADMIN.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Leagues & tournaments' })).toBeVisible({ timeout: 30_000 })
  await expect(page.getByRole('table', { name: 'Competitions' })).toContainText('Wednesday Futsal')
  await scan(page, 'competitions')

  await page.getByRole('button', { name: 'New competition' }).click()
  const dialog = page.getByRole('dialog', { name: 'New competition' })
  await dialog.getByLabel('Name').fill(name)
  await dialog.getByRole('combobox', { name: 'Sport' }).selectOption({ label: 'Futsal' })
  await dialog.getByLabel('Starts on').fill(starts)
  await scan(page, 'new competition dialog')
  await dialog.getByRole('button', { name: 'Create competition' }).click()
  await expect(dialog).toBeHidden()
  await page.getByRole('link', { name }).click()
  await expect(page.getByRole('heading', { level: 1, name })).toBeVisible()
  await page.getByRole('button', { name: 'Activate' }).click()
  await expect(page.getByText(`${name} is active.`)).toBeVisible()
  await page.getByRole('textbox', { name: 'Team name' }).fill('Night Owls')
  await page.getByRole('button', { name: 'Add team' }).click()
  await expect(page.getByRole('table', { name: 'Teams' })).toContainText('Night Owls')
  await scan(page, 'teams tab')

  await page.goto('/leagues')
  await page.getByRole('link', { name: 'Wednesday Futsal' }).click()
  await page.getByRole('tab', { name: 'Schedule & results' }).click()
  await expect(page.getByRole('table', { name: 'Games' })).toBeVisible()
  await page.getByRole('button', { name: /^Enter the score of / }).last().click()
  const score = page.getByRole('dialog', { name: /^Score: / })
  await score.getByRole('spinbutton').first().fill('2')
  await score.getByRole('spinbutton').last().fill('1')
  await scan(page, 'score dialog')
  await score.getByRole('button', { name: 'Save result' }).click()
  await expect(page.getByText('Result saved; the standings are updated.')).toBeVisible()
  await scan(page, 'schedule tab')
  await page.getByRole('tab', { name: 'Standings' }).click()
  await expect(page.getByRole('table', { name: 'Standings' })).toContainText('Downtown Strikers')
  await scan(page, 'standings tab')

  await page.goto('/leagues/public')
  await page.getByRole('link', { name: 'Wednesday Futsal' }).click()
  await expect(page.getByRole('table', { name: 'Standings' })).toBeVisible()
  await expect(page.getByRole('heading', { level: 2, name: 'Schedule' })).toBeVisible()
  await scan(page, 'public league')
})
