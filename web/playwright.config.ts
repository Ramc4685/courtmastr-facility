import { defineConfig, devices } from '@playwright/test'
import { WEB_PORT } from './lane'

const WEB = `http://localhost:${WEB_PORT}`

// The browser's zone is pinned, never the machine's, so the suite gives the same result at any hour. `chromium` sits
// in the demo locations' zone (FH_E2E_BROWSER_TZ overrides it for a one-off run). `browser-ahead` re-runs the
// date-sensitive specs with the browser on a different date from Chicago's, where screens that default a date from
// the browser's clock break: Kiritimati (UTC+14) is a day ahead from 05:00 in Chicago; before then no zone is ahead,
// so it takes one a day behind (UTC-12) instead.
const chicagoHour = Number(new Intl.DateTimeFormat('en-US', { timeZone: 'America/Chicago', hour: 'numeric', hourCycle: 'h23' }).format(new Date()))
const OFF_DATE_ZONE = chicagoHour >= 5 ? 'Pacific/Kiritimati' : 'Etc/GMT+12'
const DATE_SENSITIVE = /(billing|statements|collections|catalog|pos|staff-pay|staff-assessments|shared-post-billed|memberships|scheduling|rentals|leagues|league-sets|reporting|portal-booking|lockers)\.spec\.ts$/

// Runs against the live API (make api) through the Vite dev server's proxy.
export default defineConfig({
  testDir: 'e2e',
  timeout: 30_000,
  retries: 0,
  reporter: [['list']],
  // A click or fill on a missing or disabled control fails here instead of waiting out the whole test timeout.
  use: { baseURL: WEB, trace: 'retain-on-failure', actionTimeout: 15_000, navigationTimeout: 30_000 },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'], timezoneId: process.env.FH_E2E_BROWSER_TZ ?? 'America/Chicago' } },
    { name: 'browser-ahead', testMatch: DATE_SENSITIVE, use: { ...devices['Desktop Chrome'], timezoneId: OFF_DATE_ZONE } },
  ],
  webServer: { command: 'pnpm dev', url: WEB, reuseExistingServer: true, timeout: 60_000 },
})
