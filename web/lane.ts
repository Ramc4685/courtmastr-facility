import { existsSync, readFileSync } from 'node:fs'

// Lane isolation (parallel checkouts): FH_API_PORT / FH_WEB_PORT from the environment, else the repo's .env,
// else the defaults. Shared by vite.config.ts and playwright.config.ts.
const dotenv = new URL('../.env', import.meta.url)
const file = existsSync(dotenv) ? readFileSync(dotenv, 'utf8') : ''
const read = (key: string, fallback: number) =>
  Number(process.env[key] ?? new RegExp(`^${key}=(\\d+)\\s*$`, 'm').exec(file)?.[1] ?? fallback)

export const API_PORT = read('FH_API_PORT', 8100)
export const WEB_PORT = read('FH_WEB_PORT', 5183)
