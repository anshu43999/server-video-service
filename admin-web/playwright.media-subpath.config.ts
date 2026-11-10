import { defineConfig } from '@playwright/test'
import config from './playwright.subpath.config'
const python=process.env.ADMIN_TEST_PYTHON||(process.platform==='win32'?'../.venv/Scripts/python.exe':'../.venv/bin/python')
export default defineConfig({
  ...config,outputDir:'./test-results-m32-t26-subpath',
  projects:[{name:'subpath-chromium',use:{baseURL:'http://127.0.0.1:4203'}},{name:'direct-chromium',use:{baseURL:'http://127.0.0.1:4204'}}],
  webServer:[
    {command:`"${python}" ../tests/admin_subpath_server.py --port 4203 --build-dir ../.tmp/m32-t26/dist --preview-dir ../.tmp/m32-t26/dist-preview`,url:'http://127.0.0.1:4203/video/admin/',reuseExistingServer:false},
    {command:`"${python}" ../tests/admin_subpath_server.py --port 4204 --direct --build-dir ../.tmp/m32-t26/dist --preview-dir ../.tmp/m32-t26/dist-preview`,url:'http://127.0.0.1:4204/admin/',reuseExistingServer:false},
  ],
})
