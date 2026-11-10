import { defineConfig } from '@playwright/test'
import config from './playwright.subpath.config'
const python=process.env.ADMIN_TEST_PYTHON || '../.venv/Scripts/python.exe'
const run=process.env.ADMIN_ACCOUNTS_RUN || 'initial'
if(!/^[a-z0-9-]+$/.test(run))throw new Error('Invalid run label')
const env={DATABASE_URL:'',RUN_POSTGRES_TESTS:'0',APP_APK_WORKER_ENABLED:'false',APP_APK_EXTERNAL_ENABLED:'false'}
const build=' --build-dir ../.tmp/m32-t32-'+run+'/dist --preview-dir ../.tmp/m32-t32-'+run+'/dist-preview'
export default defineConfig({
  ...config,outputDir:'./test-results-m32-t32-subpath-'+run,
  reporter:[['line'],['json',{outputFile:'../evidence/M32-T32-subpath-'+run+'-results.json'}]],
  use:{...config.use,trace:'off'},
  projects:[
    {name:'subpath-chromium',use:{baseURL:'http://127.0.0.1:4215'}},
    {name:'direct-chromium',use:{baseURL:'http://127.0.0.1:4216'}},
  ],
  webServer:[
    {command:'"'+python+'" ../tests/admin_subpath_server.py --port 4215'+build,url:'http://127.0.0.1:4215/video/admin/',reuseExistingServer:false,env},
    {command:'"'+python+'" ../tests/admin_subpath_server.py --port 4216 --direct'+build,url:'http://127.0.0.1:4216/admin/',reuseExistingServer:false,env},
  ],
})
