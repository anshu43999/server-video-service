import { defineConfig } from '@playwright/test'
import config from './playwright.management-cache.config'
const run=process.env.ADMIN_ACCOUNTS_RUN || 'initial'
if(!/^[a-z0-9-]+$/.test(run))throw new Error('Invalid run label')
export default defineConfig({
  ...config,testMatch:[...config.testMatch as string[],'accounts-cache.spec.ts'],
  outputDir:'./test-results-m32-t32-'+run,
  reporter:[['line'],['json',{outputFile:'../evidence/M32-T32-browser-'+run+'-results.json'}]],
  use:{...config.use,baseURL:'http://127.0.0.1:5215',trace:'off'},
  webServer:{command:'npm run dev -- --host 127.0.0.1 --port 5215',url:'http://127.0.0.1:5215/admin-next/',
    reuseExistingServer:false,stdout:'ignore',stderr:'pipe',
    env:{ADMIN_API_TARGET:'http://127.0.0.1:1',DATABASE_URL:'',RUN_POSTGRES_TESTS:'0',APP_APK_WORKER_ENABLED:'false',APP_APK_EXTERNAL_ENABLED:'false'}},
})
