import { defineConfig } from '@playwright/test'
import config from './playwright.requests.config'

export default defineConfig({
  ...config,
  testMatch: ['request-optimization.spec.ts', 'polling-optimization.spec.ts'],
  outputDir: './test-results-m32-t23',
  reporter: [['line'], ['json', { outputFile: '../evidence/M32-T23-browser-results.json' }]],
  use: { ...config.use, baseURL: 'http://127.0.0.1:5193' },
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 5193',
    url: 'http://127.0.0.1:5193/admin-next/',
    reuseExistingServer: false,
    stdout: 'ignore', stderr: 'ignore',
  },
})
