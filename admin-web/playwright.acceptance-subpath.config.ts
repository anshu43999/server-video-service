import { defineConfig } from '@playwright/test'
import config from './playwright.subpath.config'
const python = process.env.ADMIN_TEST_PYTHON || '../.venv/Scripts/python.exe'
const env = { DATABASE_URL: '', RUN_POSTGRES_TESTS: '0', APP_APK_WORKER_ENABLED: 'false', APP_APK_EXTERNAL_ENABLED: 'false' }
export default defineConfig({
  ...config,
  outputDir: './test-results-m32-t30-subpath',
  reporter: [['line'], ['json', { outputFile: '../evidence/M32-T30-subpath-results.json' }]],
  // Do not retain cookies/password-bearing traces, even for synthetic accounts.
  use: { ...config.use, trace: 'off' },
  projects: [
    { name: 'subpath-chromium', use: { baseURL: 'http://127.0.0.1:4210' } },
    { name: 'direct-chromium', use: { baseURL: 'http://127.0.0.1:4211' } },
  ],
  webServer: [
    { command: `"${python}" ../tests/admin_subpath_server.py --port 4210 --build-dir ../.tmp/m32-t30/dist --preview-dir ../.tmp/m32-t30/dist-preview`,
      url: 'http://127.0.0.1:4210/video/admin/', reuseExistingServer: false, env },
    { command: `"${python}" ../tests/admin_subpath_server.py --port 4211 --direct --build-dir ../.tmp/m32-t30/dist --preview-dir ../.tmp/m32-t30/dist-preview`,
      url: 'http://127.0.0.1:4211/admin/', reuseExistingServer: false, env },
  ],
})
