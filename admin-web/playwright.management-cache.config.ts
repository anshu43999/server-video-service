import { defineConfig } from '@playwright/test'
import config from './playwright.acceptance.config'
const run = process.env.ADMIN_MANAGEMENT_RUN || 'initial'
if (!/^[a-z0-9-]+$/.test(run)) throw new Error('Invalid run label')
export default defineConfig({
  ...config, testMatch: [...config.testMatch as string[], 'management-cache.spec.ts'],
  outputDir: `./test-results-m32-t31-${run}`,
  reporter: [['line'], ['json', { outputFile: `../evidence/M32-T31-browser-${run}-results.json` }]],
  use: { ...config.use, baseURL: 'http://127.0.0.1:5213' },
  webServer: { command: 'npm run dev -- --host 127.0.0.1 --port 5213',
    url: 'http://127.0.0.1:5213/admin-next/', reuseExistingServer: false, stdout: 'ignore', stderr: 'pipe',
    env: { ADMIN_API_TARGET: 'http://127.0.0.1:1', DATABASE_URL: '', APP_APK_WORKER_ENABLED: 'false', APP_APK_EXTERNAL_ENABLED: 'false' } },
})
