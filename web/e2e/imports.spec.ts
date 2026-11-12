import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

// Seeded demo data (docs/dev/demo-accounts.md). A lane runs no worker, so the spec finishes each queued chunk run
// itself with `app.cli run-import` against the lane database (the same code path the worker's actor runs).
const ADMIN = { email: 'admin@courtside-demo.example.com', password: 'courtside-demo-2026' }
const BACKEND = fileURLToPath(new URL('../../backend', import.meta.url))

async function scan(page: Page, label: string) {
  for (const colorScheme of ['light', 'dark'] as const) {
    await page.emulateMedia({ colorScheme, reducedMotion: 'reduce' })
    const axe = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
    expect(axe.violations.map((v) => `${label} ${colorScheme} ${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`)).toEqual([])
  }
  await page.emulateMedia({ colorScheme: 'light' })
}

function runJob(tenantId: string, jobId: string) {
  execFileSync('uv', ['run', 'python', '-m', 'app.cli', 'run-import', '--tenant', tenantId, '--job', jobId], { cwd: BACKEND, stdio: 'pipe' })
}

test('an admin checks and imports a clients file, and every step passes the axe WCAG 2.1 AA scan', async ({ page }) => {
  test.setTimeout(120_000)
  await page.goto('/settings/import')
  await page.getByRole('textbox', { name: 'Email' }).fill(ADMIN.email)
  await page.getByRole('textbox', { name: 'Password' }).fill(ADMIN.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Import data' })).toBeVisible()
  await expect(page.getByText(/One row per person/)).toBeVisible()
  await scan(page, 'start')

  const run = Date.now().toString(36)
  const csv = ['Member no,First Name,Last Name,Email', `E2E-${run}-1,Avery,Import${run},avery-${run}@example.com`,
    `E2E-${run}-2,Blake,Import${run},not-an-email`, `E2E-${run}-3,Casey,Import${run},`].join('\r\n')  // prettier-ignore
  await page.getByLabel('CSV file').setInputFiles({ name: 'members.csv', mimeType: 'text/csv', buffer: Buffer.from(csv) })
  await page.getByRole('button', { name: 'Upload' }).click()
  await expect(page.getByRole('heading', { name: 'Match your columns' })).toBeVisible()
  await expect(page.getByRole('combobox', { name: 'First name (required)' })).toHaveValue('First Name')
  await page.getByRole('combobox', { name: 'Member number' }).selectOption('Member no')
  await scan(page, 'mapping')

  const jobId = new URL(page.url()).searchParams.get('job') ?? ''
  const me = await (await page.request.get('/api/v1/me', { headers: { 'x-tenant-slug': 'courtside-demo' } })).json()
  await page.getByRole('button', { name: 'Check the file' }).click()
  runJob(me.tenant.id, jobId)
  await expect(page.getByRole('heading', { name: 'Check results' })).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText('With problems', { exact: true }).locator('..')).toContainText('1')
  await expect(page.getByRole('button', { name: 'Download the problem report' })).toBeVisible()
  await scan(page, 'results')

  await page.getByRole('button', { name: 'Import 2 rows' }).click()
  await page.getByRole('group', { name: 'Confirm the import' }).getByRole('button', { name: 'Confirm import' }).click()
  runJob(me.tenant.id, jobId)
  await expect(page.getByRole('heading', { name: 'Import finished' })).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText('Created', { exact: true }).locator('..')).toContainText('2')
  await expect(page.getByText('Failed', { exact: true }).locator('..')).toContainText('1')
  await scan(page, 'finished')
  await expect(page.getByRole('table', { name: 'Import history' }).getByRole('row').nth(1)).toContainText('Completed')
})
