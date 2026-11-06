import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './tests-e2e', testMatch: 'app-updates-live.spec.ts',
  outputDir: './test-results-app-updates-live', reporter: 'line',
  timeout: 120_000, workers: 1,
  expect: { timeout: 30_000 },
  use: { baseURL: process.env.APP_UPDATE_LIVE_URL, trace: 'retain-on-failure' },
  projects: [{ name: 'app-updates-live', use: { ...devices['Desktop Chrome'],
    launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined } } }],
})
