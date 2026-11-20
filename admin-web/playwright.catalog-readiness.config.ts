import { defineConfig } from '@playwright/test'
import base from './playwright.scene-layout.config'

// This suite intercepts every business request and never contacts a real backend.
export default defineConfig({
  ...base,
  testMatch: 'catalog-readiness.spec.ts',
  outputDir: '../.tmp/m36-t49-compact-catalog',
  use: { ...base.use, baseURL: 'http://127.0.0.1:5194' },
  webServer: {
    command: 'npm run preview -- --host 127.0.0.1 --port 5194',
    url: 'http://127.0.0.1:5194/admin/',
    reuseExistingServer: false,
  },
})
