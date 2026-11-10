import { defineConfig, devices } from '@playwright/test'

// Dedicated local Vite process; all /aiyoloapi requests are intercepted by test
// fixtures. No app.main, environment database, live server, or Docker is used.
export default defineConfig({
  testDir: './tests-e2e',
  testMatch: 'request-optimization.spec.ts',
  outputDir: './test-results-m32-t22',
  reporter: 'line',
  timeout: 45_000,
  workers: 1,
  use: {
    baseURL: 'http://127.0.0.1:5192',
    trace: 'retain-on-failure',
    ...devices['Desktop Chrome'],
    launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined },
  },
  projects: [{ name: 'request-chromium' }],
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 5192',
    url: 'http://127.0.0.1:5192/admin-next/',
    reuseExistingServer: false,
    stdout: 'ignore',
    stderr: 'ignore',
  },
})
