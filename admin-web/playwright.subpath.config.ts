import { defineConfig, devices } from '@playwright/test'

const python = process.env.ADMIN_TEST_PYTHON || (process.platform === 'win32' ? '../.venv/Scripts/python.exe' : '../.venv/bin/python')
export default defineConfig({
  testDir: './tests-e2e',
  testMatch: 'subpath.spec.ts',
  outputDir: './test-results-subpath',
  reporter: 'line',
  timeout: 60_000,
  workers: 1,
  use: {
    baseURL: 'http://127.0.0.1:4175',
    trace: 'retain-on-failure',
    ...devices['Desktop Chrome'],
    launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined },
  },
  projects: [
    { name: 'subpath-chromium' },
    { name: 'direct-chromium', use: { baseURL: 'http://127.0.0.1:4176' } },
  ],
  webServer: [{
    command: `"${python}" ../tests/admin_subpath_server.py --port 4175`,
    url: 'http://127.0.0.1:4175/video/admin/',
    reuseExistingServer: false,
  }, {
    command: `"${python}" ../tests/admin_subpath_server.py --port 4176 --direct`,
    url: 'http://127.0.0.1:4176/admin/',
    reuseExistingServer: false,
  }],
})
