import { defineConfig } from '@playwright/test'
import config from './playwright.requests.config'
export default defineConfig({
  ...config,
  testMatch: ['shared-queries.spec.ts','request-optimization.spec.ts','polling-optimization.spec.ts','alert-sync-optimization.spec.ts'],
  outputDir: './test-results-m32-t25',
  reporter: [['line'],['json',{outputFile:'../evidence/M32-T25-browser-results.json'}]],
  use:{...config.use,baseURL:'http://127.0.0.1:5195'},
  webServer:{command:'npm run dev -- --host 127.0.0.1 --port 5195',url:'http://127.0.0.1:5195/admin-next/',reuseExistingServer:false,stdout:'ignore',stderr:'ignore'},
})
