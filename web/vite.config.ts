/// <reference types="vitest/config" />
import { readFileSync } from 'node:fs'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import { API_PORT, WEB_PORT } from './lane'

// The display name lives once, in config/app.yaml. shortcut: regex instead of a YAML parser; swap for one
// if the web build ever needs more than this single scalar.
const appYaml = readFileSync(new URL('../config/app.yaml', import.meta.url), 'utf8')
const displayName = /display_name:\s*([^#\n]+)/.exec(appYaml)?.[1]?.trim() ?? 'FacilityHub'

const API = process.env.FH_API_URL ?? `http://127.0.0.1:${API_PORT}`

export default defineConfig({
  plugins: [react()],
  define: { __APP_NAME__: JSON.stringify(displayName) },
  // CHANGELOG.md sits one level above the web root and is imported as raw text (the What's new page).
  server: { fs: { allow: ['..'] }, port: WEB_PORT, strictPort: true, proxy: { '/api': { target: API } } },
  preview: { port: WEB_PORT, strictPort: true, proxy: { '/api': { target: API } } },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    css: false,
  },
})
