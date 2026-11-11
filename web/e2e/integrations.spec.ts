import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import { createServer } from 'node:http'
import type { AddressInfo } from 'node:net'

// Seeded demo owner (docs/dev/demo-accounts.md). Needs `make api` in dev, where webhooks may target loopback.
const OWNER = { email: 'owner@courtside-demo.example.com', password: 'courtside-demo-2026' }

async function scan(page: Page, label: string) {
  const axe = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  expect(axe.violations.map((v) => `${label} ${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`)).toEqual([])
}

async function signIn(page: Page) {
  await page.goto('/integrations')
  await page.getByRole('textbox', { name: 'Email' }).fill(OWNER.email)
  await page.getByRole('textbox', { name: 'Password' }).fill(OWNER.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Integrations' })).toBeVisible()
}

test('an API key created in the UI calls a platform endpoint, and the screens pass axe', async ({ page, request }) => {
  await signIn(page)
  await scan(page, 'directory')
  await page.emulateMedia({ colorScheme: 'dark' })
  await scan(page, 'directory dark')
  await page.getByRole('tab', { name: 'Webhooks' }).click()
  await scan(page, 'webhooks dark')
  await page.emulateMedia({ colorScheme: 'light' })
  await page.getByRole('tab', { name: 'API keys' }).click()
  await page.getByRole('button', { name: 'New API key' }).click()
  const dialog = page.getByRole('dialog', { name: 'New API key' })
  await dialog.getByRole('textbox', { name: 'Name' }).fill(`E2E ${Date.now()}`)
  await dialog.getByLabel(/\(clients\.client\.read\)/).check()
  await scan(page, 'create key dialog')
  await dialog.getByRole('button', { name: 'Create key' }).click()

  const secretBox = page.getByRole('dialog', { name: 'Your API key' }).getByRole('textbox', { name: 'Secret' })
  const secret = await secretBox.inputValue()
  expect(secret).toMatch(/^fhk_/)
  await scan(page, 'secret dialog')
  await page.getByRole('button', { name: 'I have copied it' }).click()
  await expect(page.getByText(secret)).toHaveCount(0)

  const bearer = { Authorization: `Bearer ${secret}` }
  const locations = await request.get('/api/v1/locations', { headers: bearer })
  expect(locations.status()).toBe(403) // keyless routes refuse API keys (13b12dd); only scoped routes accept them
  expect((await locations.json()).code).toBe('api-key-not-allowed')
  expect((await request.get('/api/v1/clients', { headers: bearer })).status()).toBe(200)
  expect((await request.get('/api/v1/charges', { headers: bearer })).status()).toBe(403) // outside its scopes
})

test('a webhook endpoint receives a signed test delivery that shows in the log', async ({ page }) => {
  const received: { signature: string | undefined; body: string }[] = []
  const receiver = createServer((req, res) => {
    let body = ''
    req.on('data', (chunk) => (body += chunk))
    req.on('end', () => {
      received.push({ signature: req.headers['fh-signature'] as string | undefined, body })
      res.writeHead(200).end('ok')
    })
  })
  await new Promise<void>((resolve) => receiver.listen(0, '127.0.0.1', resolve))
  const url = `http://127.0.0.1:${(receiver.address() as AddressInfo).port}/hook`
  try {
    await signIn(page)
    await page.getByRole('tab', { name: 'Webhooks' }).click()
    await page.getByRole('button', { name: 'New endpoint' }).click()
    const dialog = page.getByRole('dialog', { name: 'New webhook endpoint' })
    await dialog.getByRole('textbox', { name: 'URL' }).fill(url)
    await dialog.getByLabel('clients.client.created').check()
    await scan(page, 'endpoint dialog')
    await dialog.getByRole('button', { name: 'Create endpoint' }).click()
    await expect(page.getByRole('dialog', { name: 'Signing secret' }).getByRole('textbox', { name: 'Secret' })).toHaveValue(/^whsec_/)
    await page.getByRole('button', { name: 'I have copied it' }).click()

    await page.getByRole('button', { name: `Test ${url}` }).click()
    await expect(page.getByText(/Test delivered \(HTTP 200\)/)).toBeVisible()
    expect(received).toHaveLength(1)
    expect(received[0]?.signature).toMatch(/^t=\d+,v1=[0-9a-f]{64}$/)
    expect(JSON.parse(received[0]?.body ?? '{}').type).toBe('integrations.webhook.tested')
    await expect(page.getByRole('table', { name: 'Webhook deliveries' }).getByText('Delivered').first()).toBeVisible()
    await scan(page, 'webhooks with log')

    // Leave nothing active behind for the next run.
    await page.getByRole('button', { name: `Delete ${url}` }).click()
    await page.getByRole('button', { name: 'Delete endpoint' }).click()
  } finally {
    receiver.close()
  }
})
