import { defineConfig } from '@playwright/test'
import config from './playwright.acceptance.config'
export default defineConfig({
  ...config,
  testMatch: ['streams.spec.ts', 'alerts.spec.ts'],
  grep: /switching streams cancels|preview failure has|no source frame clears|polling preserves unsaved|concurrent disposition conflict|empty alert storage|list failure stays/,
  outputDir: './test-results-m32-t30-regression',
  reporter: [['line'], ['json', { outputFile: '../evidence/M32-T30-regression-results.json' }]],
  use: { ...config.use, baseURL: 'http://127.0.0.1:5212' },
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 5212',
    url: 'http://127.0.0.1:5212/admin-next/', reuseExistingServer: false,
    stdout: 'ignore', stderr: 'pipe',
    env: { ADMIN_API_TARGET: 'http://127.0.0.1:1', DATABASE_URL: '',
      APP_APK_WORKER_ENABLED: 'false', APP_APK_EXTERNAL_ENABLED: 'false' },
  },
})
