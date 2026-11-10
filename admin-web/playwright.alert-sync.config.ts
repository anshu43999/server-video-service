import { defineConfig } from '@playwright/test'
import config from './playwright.requests.config'

export default defineConfig({
  ...config,
  testMatch: ['alert-sync-optimization.spec.ts', 'request-optimization.spec.ts', 'polling-optimization.spec.ts'],
  outputDir: './test-results-m32-t24',
  reporter: [['line'], ['json', { outputFile: '../evidence/M32-T24-browser-results.json' }]],
  use: { ...config.use, baseURL: 'http://127.0.0.1:5194' },
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 5194',
    url: 'http://127.0.0.1:5194/admin-next/',
    reuseExistingServer: false, stdout: 'ignore', stderr: 'ignore',
  },
})
