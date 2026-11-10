import { defineConfig } from '@playwright/test'
import config from './playwright.subpath.config'
const python = process.env.ADMIN_TEST_PYTHON || (process.platform === 'win32' ? '../.venv/Scripts/python.exe' : '../.venv/bin/python')
export default defineConfig({
  ...config,
  outputDir: './test-results-m32-t24-subpath',
  projects: [
    { name: 'subpath-chromium', use: { baseURL: 'http://127.0.0.1:4199' } },
    { name: 'direct-chromium', use: { baseURL: 'http://127.0.0.1:4200' } },
  ],
  webServer: [
    { command: `"${python}" ../tests/admin_subpath_server.py --port 4199 --build-dir ../.tmp/m32-t24/dist --preview-dir ../.tmp/m32-t24/dist-preview`, url: 'http://127.0.0.1:4199/video/admin/', reuseExistingServer: false },
    { command: `"${python}" ../tests/admin_subpath_server.py --port 4200 --direct --build-dir ../.tmp/m32-t24/dist --preview-dir ../.tmp/m32-t24/dist-preview`, url: 'http://127.0.0.1:4200/admin/', reuseExistingServer: false },
  ],
})
