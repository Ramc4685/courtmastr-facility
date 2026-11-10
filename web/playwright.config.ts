import { defineConfig, devices } from '@playwright/test'
import { WEB_PORT } from './lane'

const WEB = `http://localhost:${WEB_PORT}`

// Runs against the live API (make api) through the Vite dev server's proxy.
export default defineConfig({
  testDir: 'e2e',
  timeout: 30_000,
  retries: 0,
  reporter: [['list']],
  use: { baseURL: WEB, trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: { command: 'pnpm dev', url: WEB, reuseExistingServer: true, timeout: 60_000 },
})
