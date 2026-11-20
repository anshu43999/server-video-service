import { defineConfig } from '@playwright/test'
import layout from './playwright.scene-layout.config'

// Serve local artifacts; both HTTP and WebSocket are intercepted by test fixtures.
export default defineConfig({
  ...layout,
  testMatch: ['scene-create-simple.spec.ts', 'scene-parameter-layout.spec.ts'],
  outputDir: '../.tmp/m36-t50-scene-joint-default',
})
