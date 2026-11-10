import { defineConfig } from '@playwright/test'
import config from './playwright.subpath.config'
const python = process.env.ADMIN_TEST_PYTHON || (process.platform === 'win32' ? '../.venv/Scripts/python.exe' : '../.venv/bin/python')
export default defineConfig({
  ...config,
  outputDir: './test-results-m32-t25-subpath',
  projects: [
    { name: 'subpath-chromium', use: { baseURL: 'http://127.0.0.1:4201' } },
    { name: 'direct-chromium', use: { baseURL: 'http://127.0.0.1:4202' } },
  ],
  webServer: [
    { command: `"${python}" ../tests/admin_subpath_server.py --port 4201 --build-dir ../.tmp/m32-t25/dist --preview-dir ../.tmp/m32-t25/dist-preview`, url: 'http://127.0.0.1:4201/video/admin/', reuseExistingServer: false },
    { command: `"${python}" ../tests/admin_subpath_server.py --port 4202 --direct --build-dir ../.tmp/m32-t25/dist --preview-dir ../.tmp/m32-t25/dist-preview`, url: 'http://127.0.0.1:4202/admin/', reuseExistingServer: false },
  ],
})
