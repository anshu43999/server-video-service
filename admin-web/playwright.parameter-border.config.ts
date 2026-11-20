import { defineConfig } from '@playwright/test'
import layout from './playwright.scene-layout.config'

export default defineConfig({
  ...layout,
  testMatch: 'parameter-card-border.spec.ts',
  outputDir: '../.tmp/m36-t45-parameter-border',
  use: { ...layout.use, baseURL: 'http://127.0.0.1:5192' },
  webServer: {
    command: 'npm run preview -- --host 127.0.0.1 --port 5192',
    url: 'http://127.0.0.1:5192/admin/',
    reuseExistingServer: false,
  },
})
