import { defineConfig } from '@playwright/test'
import details from './playwright.parameter-details.config'

export default defineConfig({
  ...details,
  testMatch: ['platform-parameter-editor.spec.ts', 'project-parameter-details.spec.ts', 'platform-parameter-state.spec.ts'],
  outputDir: '../.tmp/m36-t44-parameter-editor',
  use: { ...details.use, baseURL: 'http://127.0.0.1:5191' },
  webServer: {
    command: 'npm run preview -- --host 127.0.0.1 --port 5191',
    url: 'http://127.0.0.1:5191/admin/',
    reuseExistingServer: false,
  },
})
