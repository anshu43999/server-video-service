import { defineConfig } from '@playwright/test'

// Read-only route fixtures: this layout suite never needs a live backend.
export default defineConfig({
  testDir: './tests-e2e',
  testMatch: 'scene-parameter-layout.spec.ts',
  outputDir: '../.tmp/m36-t38-scene-layout',
  reporter: 'line',
  workers: 1,
  timeout: 30_000,
  use: {
    baseURL: 'http://127.0.0.1:5188',
    trace: 'off',
    launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined },
  },
  projects: [{ name: 'production-chromium', use: { browserName: 'chromium' } }],
  webServer: {
    command: 'npm run preview -- --host 127.0.0.1 --port 5188',
    url: 'http://127.0.0.1:5188/admin/',
    reuseExistingServer: false,
  },
})
