import { defineConfig, devices } from '@playwright/test'

const python = process.env.ADMIN_TEST_PYTHON || (process.platform === 'win32' ? '../.venv/Scripts/python.exe' : '../.venv/bin/python')
export default defineConfig({
  testDir: './tests-e2e',
  testIgnore: 'legacy-approval.spec.ts',
  outputDir: './test-results-production',
  reporter: 'line',
  timeout: 30_000,
  use: { baseURL: 'http://127.0.0.1:4174', trace: 'retain-on-failure' },
  projects: [{
    name: 'production-chromium',
    use: { ...devices['Desktop Chrome'], launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined } },
  }],
  webServer: [
    {
      command: `"${python}" ../tests/admin_frontend_server.py --mode vue --port 4174`,
      url: 'http://127.0.0.1:4174/admin/',
      reuseExistingServer: false,
    },
  ],
})
