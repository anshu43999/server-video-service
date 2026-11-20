import { defineConfig } from '@playwright/test'
import base from './playwright.scene-layout.config'

// All business HTTP/WebSocket requests are intercepted by this suite.
export default defineConfig({
  ...base,
  testMatch: 'project-model-duplicates.spec.ts',
  outputDir: '../.tmp/m36-t46-assignment-duplicates',
  use: { ...base.use, baseURL: 'http://127.0.0.1:5193' },
  webServer: {
    command: 'npm run preview -- --host 127.0.0.1 --port 5193',
    url: 'http://127.0.0.1:5193/admin/',
    reuseExistingServer: false,
  },
})
