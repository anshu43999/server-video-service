import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests-e2e',
  testMatch: 'project-model-lifecycle.spec.ts',
  outputDir: '../.tmp/m36-t39-model-lifecycle',
  reporter: 'line',
  workers: 1,
  timeout: 30_000,
  use: {
    baseURL: 'http://127.0.0.1:5189',
    trace: 'off',
    launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined },
  },
  projects: [{ name: 'production-chromium', use: { browserName: 'chromium' } }],
  webServer: {
    command: 'npm run preview -- --host 127.0.0.1 --port 5189',
    url: 'http://127.0.0.1:5189/admin/',
    reuseExistingServer: false,
  },
})
