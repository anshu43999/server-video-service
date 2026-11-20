import { defineConfig } from '@playwright/test'
import layout from './playwright.scene-layout.config'

// Serve the production build with isolated HTTP/WebSocket fixtures.
export default defineConfig({
  ...layout,
  testMatch: ['project-parameter-details.spec.ts', 'platform-parameter-state.spec.ts'],
  outputDir: '../.tmp/m36-t43-parameter-details',
  use: { ...layout.use, baseURL: 'http://127.0.0.1:5190' },
  webServer: {
    command: 'npm run preview -- --host 127.0.0.1 --port 5190',
    url: 'http://127.0.0.1:5190/admin/',
    reuseExistingServer: false,
  },
})
