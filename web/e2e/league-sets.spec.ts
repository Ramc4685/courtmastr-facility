import { expect, test } from '@playwright/test'
import { scan } from './a11y'

// Seeded demo league admin (docs/dev/demo-accounts.md, "Demo leagues (build module 11)"); the competition, its two
// teams and its one game are the spec's own, made through the API (there is no add-game screen).
const LEAGUE_ADMIN = { email: 'league-admin@courtside-demo.example.com', password: 'courtside-demo-2026' }

test('a competition switches to set scoring, scores a game set by set and holds a league night, all dialogs pass axe', async ({ page }) => {
  test.setTimeout(150_000) // sign-in hashing and four axe scans on a shared machine
  const tag = Math.random().toString(36).slice(2, 7)
  const day = new Date(Date.now() + (700 + Math.floor(Math.random() * 300)) * 86400000)
  const on = day.toISOString().slice(0, 10)
  await page.goto('/leagues')
  await page.getByRole('textbox', { name: 'Email' }).fill(LEAGUE_ADMIN.email)
  await page.getByRole('textbox', { name: 'Password' }).fill(LEAGUE_ADMIN.password)
  const signedIn = page.waitForResponse((r) => r.url().endsWith('/api/v1/auth/sign-in') && r.ok())
  await page.getByRole('button', { name: 'Sign in' }).click()
  const { csrf_token } = await (await signedIn).json()
  await expect(page.getByRole('heading', { level: 1, name: 'Leagues & tournaments' })).toBeVisible({ timeout: 30_000 })

  const headers = () => ({ 'x-tenant-slug': 'courtside-demo', 'x-csrf-token': csrf_token, 'idempotency-key': crypto.randomUUID() })
  const call = async (method: 'get' | 'post', path: string, data?: object) => {
    const response = await page.request[method](`/api/v1${path}`, { headers: headers(), data })
    expect(response.ok(), `${method} ${path}: ${await response.text()}`).toBe(true)
    return response.json()
  }
  const downtown = (await call('get', '/locations')).data.find((l: { name: string }) => l.name === 'Courtside Downtown')
  const futsal = (await call('get', '/sports')).data.find((s: { name: string }) => s.name === 'Futsal')
  const court = (await call('get', `/resources?location_id=${downtown.id}`)).data.find((r: { kind: string }) => r.kind === 'venue')
  const name = `E2E sets ${tag}`
  const competition = await call('post', '/competitions', {
    location_id: downtown.id, kind: 'league', name, sport_id: futsal.id, starts_on: on, ends_on: on,
  })
  await call('post', `/competitions/${competition.id}/activate`)
  const [home, away] = await call('post', `/competitions/${competition.id}/teams/generate`, { count: 2 })
  await call('post', '/games', {
    competition_id: competition.id, home_team_id: home.id, away_team_id: away.id, resource_id: court.id, starts_at: `${on}T18:00:00Z`,
  })

  await page.goto(`/leagues/${competition.id}`)
  await expect(page.getByRole('heading', { level: 1, name })).toBeVisible()
  await page.getByRole('tab', { name: 'Standings' }).click()
  await page.getByRole('button', { name: 'Scoring format' }).click()
  const format = page.getByRole('dialog', { name: 'Scoring format' })
  await format.getByRole('button', { name: 'Badminton' }).click()
  await expect(format.getByLabel('Points to win a set')).toHaveValue('21')
  await scan(page, 'scoring format dialog')
  await format.getByRole('button', { name: 'Save format' }).click()
  await expect(page.getByText('Scoring format saved.')).toBeVisible()

  await page.getByRole('tab', { name: 'Schedule & results' }).click()
  await page.getByRole('button', { name: /^Enter the score of / }).click()
  const score = page.getByRole('dialog', { name: /^Score: / })
  for (const [n, h, a] of [[1, '21', '18'], [2, '19', '21'], [3, '21', '15']] as const) {
    await score.getByLabel(new RegExp(`^Set ${n}: `)).first().fill(h)
    await score.getByLabel(new RegExp(`^Set ${n}: `)).last().fill(a)
  }
  await scan(page, 'set score dialog')
  await score.getByRole('button', { name: 'Save result' }).click()
  await expect(page.getByText('Result saved; the standings are updated.')).toBeVisible()

  await page.getByRole('button', { name: 'Hold a league night' }).click()
  const night = page.getByRole('dialog', { name: 'Hold a league night' })
  await expect(night).toContainText('If you move or postpone a game, re-block its old slot.')
  await night.getByLabel('From').fill(`${on}T18:00`)
  await night.getByLabel('Until').fill(`${on}T20:00`)
  await night.getByRole('checkbox', { name: court.name }).check()
  await scan(page, 'league night dialog')
  await night.getByRole('button', { name: 'Hold courts' }).click()
  await expect(page.getByText('Courts held for the league.', { exact: false })).toBeVisible()
})
