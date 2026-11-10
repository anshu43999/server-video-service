import { defineConfig } from '@playwright/test'
import config from './playwright.requests.config'
// Reuse only scenarios without legacy screenshot paths; preserve prior evidence.
export default defineConfig({
  ...config,testMatch:['streams.spec.ts','alerts.spec.ts'],
  grep:/switching streams cancels|preview failure has|no source frame clears|polling preserves unsaved|concurrent disposition conflict|empty alert storage|list failure stays/,
  outputDir:'./test-results-m32-t26-regression',
  use:{...config.use,baseURL:'http://127.0.0.1:5198'},
  webServer:{command:'npm run dev -- --host 127.0.0.1 --port 5198',url:'http://127.0.0.1:5198/admin-next/',reuseExistingServer:false,stdout:'ignore',stderr:'ignore'},
})
