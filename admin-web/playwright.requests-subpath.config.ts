import { defineConfig } from '@playwright/test'
import config from './playwright.subpath.config'
const python = process.env.ADMIN_TEST_PYTHON || '../.venv/Scripts/python.exe'
export default defineConfig({
  ...config,
  outputDir: './test-results-m32-t22-subpath',
  projects: [
    { name: 'subpath-chromium', use: { baseURL: 'http://127.0.0.1:4195' } },
    { name: 'direct-chromium', use: { baseURL: 'http://127.0.0.1:4196' } },
  ],
  webServer: [
    { command: `"${python}" ../tests/admin_subpath_server.py --port 4195 --build-dir ../.tmp/m32-t22/dist --preview-dir ../.tmp/m32-t22/dist-preview`, url: 'http://127.0.0.1:4195/video/admin/', reuseExistingServer: false },
    { command: `"${python}" ../tests/admin_subpath_server.py --port 4196 --direct --build-dir ../.tmp/m32-t22/dist --preview-dir ../.tmp/m32-t22/dist-preview`, url: 'http://127.0.0.1:4196/admin/', reuseExistingServer: false },
  ],
})
