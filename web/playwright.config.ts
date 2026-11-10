import { defineConfig, devices } from '@playwright/test'

// Runs against the live API (make api) through the Vite dev server's proxy.
export default defineConfig({
  testDir: 'e2e',
  timeout: 30_000,
  retries: 0,
  reporter: [['list']],
  use: { baseURL: 'http://localhost:5183', trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: { command: 'pnpm dev', url: 'http://localhost:5183', reuseExistingServer: true, timeout: 60_000 },
})
