import { defineConfig } from '@playwright/test'
import config from './playwright.requests.config'
export default defineConfig({
  ...config,
  testMatch:['media-optimization.spec.ts','shared-queries.spec.ts','request-optimization.spec.ts','polling-optimization.spec.ts','alert-sync-optimization.spec.ts'],
  outputDir:'./test-results-m32-t26',
  reporter:[['line'],['json',{outputFile:'../evidence/M32-T26-browser-results.json'}]],
  use:{...config.use,baseURL:'http://127.0.0.1:5196'},
  webServer:{command:'npm run dev -- --host 127.0.0.1 --port 5196',url:'http://127.0.0.1:5196/admin-next/',reuseExistingServer:false,stdout:'ignore',stderr:'ignore'},
})
