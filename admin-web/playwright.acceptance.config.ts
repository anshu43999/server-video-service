import { defineConfig } from '@playwright/test'
import config from './playwright.media.config'
const run = process.env.ADMIN_ACCEPTANCE_RUN || 'initial'
if (!/^[a-z0-9-]+$/.test(run)) throw new Error('ADMIN_ACCEPTANCE_RUN must be a safe run label')
const suffix = run === 'initial' ? '' : `-${run}`

// Synthetic API/WS fixtures only. Never proxy a missed route to a live service.
export default defineConfig({
  ...config,
  testMatch: ['media-optimization.spec.ts', 'shared-queries.spec.ts', 'request-optimization.spec.ts',
    'polling-optimization.spec.ts', 'alert-sync-optimization.spec.ts', 'request-acceptance.spec.ts'],
  outputDir: `./test-results-m32-t30${suffix}`,
  reporter: [['line'], ['json', { outputFile: `../evidence/M32-T30-browser${suffix}-results.json` }]],
  use: { ...config.use, baseURL: 'http://127.0.0.1:5210', trace: 'off' },
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 5210',
    url: 'http://127.0.0.1:5210/admin-next/', reuseExistingServer: false,
    stdout: 'ignore', stderr: 'pipe',
    env: { ADMIN_API_TARGET: 'http://127.0.0.1:1', DATABASE_URL: '',
      APP_APK_WORKER_ENABLED: 'false', APP_APK_EXTERNAL_ENABLED: 'false' },
  },
})
