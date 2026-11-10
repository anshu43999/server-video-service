import { expect, test, type BrowserContext, type Page } from '@playwright/test'
import { fixtureProject, fixtureUser } from './helpers/project-fixture'
import type { AccountRecord } from '../src/features/management/api'
const account = (accountId='other',username='fixture-account'):AccountRecord => ({accountId,username,platformRole:'NORMAL_USER',enabled:true,revision:1})
async function service(context:BrowserContext){
  const s={reads:[] as string[],writes:[] as string[],unexpected:[] as string[],user:fixtureUser(),meStatus:200,
    accounts:[account()],writeStatus:200,abortWrite:false,revokeOnWrite:false,gate:undefined as Promise<void>|undefined}
  await context.route('**/aiyoloapi/**',async route=>{
    const path=new URL(route.request().url()).pathname,method=route.request().method()
    ;(method==='GET'?s.reads:s.writes).push(path)
    const reply=(json:unknown,status=200)=>route.fulfill({json,status}).catch(()=>{})
    if(path.endsWith('/auth/status'))return reply({authenticated:true,setupRequired:false})
    if(path.endsWith('/auth/me'))return reply(s.user,s.meStatus)
    if(path.endsWith('/auth/projects'))return reply({contractVersion:'m33-v1',projects:[fixtureProject]})
    if(path==='/aiyoloapi/platform/projects')return reply({projects:[fixtureProject]})
    if(path==='/aiyoloapi/platform/accounts'&&method==='GET'){
      const snapshot=structuredClone(s.accounts);if(s.gate)await s.gate;return reply({accounts:snapshot})
    }
    if(path.startsWith('/aiyoloapi/platform/accounts')&&method!=='GET'){
      // Fixture-only body use: never attach, log or persist passwords/request bodies.
      const body=route.request().postDataJSON()
      if(method==='POST')s.accounts.push(account('created',body.username))
      else {
        const id=path.split('/').at(-1),index=s.accounts.findIndex(a=>a.accountId===id)
        s.accounts[index]={...s.accounts[index]!,platformRole:body.platformRole,enabled:body.enabled,revision:2}
        if(s.revokeOnWrite){if(!body.enabled)s.meStatus=401;else s.user={...s.user,role:'operator',platformRole:'NORMAL_USER'}}
      }
      // 409/503 intentionally allow a changed server snapshot: only a fresh GET establishes fact.
      if(s.abortWrite)return route.abort('failed')
      return reply({accepted:true},s.writeStatus)
    }
    s.unexpected.push(path);return reply({detail:'unknown isolated endpoint'},404)
  })
  await context.routeWebSocket('**/aiyoloapi/**',socket=>{socket.onMessage(()=>{})})
  return s
}
type State=Awaited<ReturnType<typeof service>>
const count=(s:State,suffix:string)=>s.reads.filter(p=>p.endsWith(suffix)).length
async function navigate(page:Page,path:string){
  await page.evaluate(path=>{history.pushState({},'',path);dispatchEvent(new PopStateEvent('popstate'))},'/admin-next/'+path)
  await expect(page.locator('#main-content')).not.toHaveAttribute('inert','')
}
async function record(s:State,scenario:string,extra:Record<string,unknown>={}){
  expect(s.unexpected).toEqual([])
  const result={scenario,environment:'real local Chromium, synthetic API/WS only; not production',
    counts:Object.fromEntries([...new Set(s.reads)].map(p=>[p,s.reads.filter(q=>q===p).length])),writes:s.writes,...extra}
  console.log(JSON.stringify(result));await test.info().attach(scenario,{body:JSON.stringify(result),contentType:'application/json'})
}
async function openAccounts(page:Page){await page.goto('/admin-next/platform/accounts');await expect(page.getByRole('heading',{name:'fixture-account',exact:true})).toBeVisible()}
async function create(page:Page){
  await page.getByRole('button',{name:'创建账号',exact:true}).click()
  await page.getByLabel('账号名称').fill('new-fixture');await page.getByLabel('初始密码').fill('synthetic-only-password')
  await page.getByRole('button',{name:'确认创建账号',exact:true}).click()
}
test('account A-B-A under five seconds reuses one read, search stays local and refresh is authoritative',async({context,page})=>{
  const s=await service(context);await openAccounts(page);const me=count(s,'/auth/me'),start=Date.now()
  await page.getByLabel('搜索账号').fill('not-matched');await expect(page.getByText('暂无匹配账号。')).toBeVisible();expect(count(s,'/platform/accounts')).toBe(1)
  await navigate(page,'platform/projects');await expect(page.getByRole('button',{name:'创建项目',exact:true})).toBeVisible()
  await navigate(page,'platform/accounts');await expect(page.getByRole('heading',{name:'fixture-account',exact:true})).toBeVisible()
  const elapsedMs=Date.now()-start;expect(elapsedMs).toBeLessThan(5000);expect(count(s,'/platform/accounts')).toBe(1);expect(count(s,'/auth/me')).toBe(me)
  await page.evaluate(()=>dispatchEvent(new Event('focus')));await expect.poll(()=>count(s,'/auth/me')).toBe(me+1)
  await expect(page.locator('#main-content')).not.toHaveAttribute('inert','');expect(count(s,'/platform/accounts')).toBe(1)
  s.accounts=[account('other','fresh-account')];await page.getByRole('button',{name:'刷新账号列表'}).click()
  await expect(page.getByRole('heading',{name:'fresh-account',exact:true})).toBeVisible();expect(count(s,'/platform/accounts')).toBe(2)
  await record(s,'accounts-A-B-A',{elapsedMs,returnExtraReads:0,manualExtraReads:1})
})
test('account TTL expires on return after real ten seconds with no extra background list timer',async({context,page})=>{
  const s=await service(context);await openAccounts(page);await navigate(page,'platform/projects');await page.waitForTimeout(10100)
  expect(count(s,'/platform/accounts')).toBe(1);s.accounts=[account('other','expired-fresh')]
  await navigate(page,'platform/accounts');await expect(page.getByRole('heading',{name:'expired-fresh',exact:true})).toBeVisible()
  expect(count(s,'/platform/accounts')).toBe(2);await record(s,'accounts-real-TTL')
})
for(const result of ['200','409','503','network'])test('account create '+result+' invalidates without replay and clears password',async({context,page})=>{
  const s=await service(context);s.writeStatus=result==='network'?200:Number(result);s.abortWrite=result==='network';await openAccounts(page);await create(page)
  if(result!=='200'){
    await expect(page.getByRole('dialog')).toContainText('不会自动重试');await expect(page.getByLabel('初始密码')).toHaveValue('')
    await expect(page.getByRole('button',{name:'确认创建账号',exact:true})).toBeDisabled()
    await page.getByRole('button',{name:'取消',exact:true}).click();await page.getByRole('button',{name:'刷新账号列表'}).click()
  }
  await expect(page.getByRole('heading',{name:'new-fixture',exact:true})).toBeVisible();expect(s.writes).toHaveLength(1);expect(count(s,'/platform/accounts')).toBe(2)
  await page.getByRole('button',{name:'创建账号',exact:true}).click();await expect(page.getByLabel('初始密码')).toHaveValue('')
  await page.getByLabel('初始密码').fill('discarded-fixture-password');await page.getByRole('button',{name:'取消',exact:true}).click()
  await page.getByRole('button',{name:'创建账号',exact:true}).click();await expect(page.getByLabel('初始密码')).toHaveValue('');await page.getByRole('button',{name:'取消',exact:true}).click()
  await navigate(page,'platform/projects');await navigate(page,'platform/accounts');await expect(page.getByRole('heading',{name:'new-fixture',exact:true})).toBeVisible()
  expect(count(s,'/platform/accounts')).toBe(2);expect(s.writes).toHaveLength(1)
  const persisted=await page.evaluate(()=>JSON.stringify([Object.entries(localStorage),Object.entries(sessionStorage)]))
  expect(persisted.includes('synthetic-only-password')).toBe(false);expect(persisted.includes('discarded-fixture-password')).toBe(false)
  await record(s,'accounts-create-'+result)
})
for(const field of ['role','enabled'])test('account '+field+' edit invalidates cached list',async({context,page})=>{
  const s=await service(context);await openAccounts(page);await page.getByRole('button',{name:'管理账号',exact:true}).click()
  if(field==='role')await page.getByRole('dialog').locator('select').nth(0).selectOption('PLATFORM_ADMIN')
  else await page.getByRole('dialog').locator('select').nth(1).selectOption('false')
  await page.getByRole('button',{name:'确认更新账号',exact:true}).click();await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByRole('article')).toContainText(field==='role'?'平台超级管理员':'已停用');await expect(page.getByRole('article')).toContainText('版本 2')
  expect(count(s,'/platform/accounts')).toBe(2);expect(s.writes).toHaveLength(1)
  await navigate(page,'platform/projects');await navigate(page,'platform/accounts');await expect(page.getByRole('article')).toContainText('版本 2')
  expect(count(s,'/platform/accounts')).toBe(2);await record(s,'accounts-edit-'+field)
})
test('leaving a pending account list aborts it and reentry never displays the late response',async({context,page})=>{
  const s=await service(context);let release!:()=>void;s.gate=new Promise(r=>{release=r})
  let cancelled=0;page.on('requestfailed',r=>{if(new URL(r.url()).pathname==='/aiyoloapi/platform/accounts')cancelled++})
  await page.goto('/admin-next/platform/accounts');await expect.poll(()=>count(s,'/platform/accounts')).toBe(1)
  await navigate(page,'platform/projects');await expect(page.getByRole('button',{name:'创建项目',exact:true})).toBeVisible();await expect.poll(()=>cancelled).toBe(1)
  release();s.gate=undefined;s.accounts=[account('other','fresh-return')];await navigate(page,'platform/accounts')
  await expect(page.getByRole('heading',{name:'fresh-return',exact:true})).toBeVisible();expect(count(s,'/platform/accounts')).toBe(2)
  await record(s,'accounts-navigation-cancel',{cancelled})
})
for(const action of ['demote','disable'])test('current account '+action+' clears cache through authoritative revalidation',async({context,page})=>{
  const s=await service(context);s.accounts=[{...account(s.user.accountId),platformRole:'PLATFORM_ADMIN'}];s.revokeOnWrite=true
  await page.goto('/admin-next/platform/accounts');await expect(page.getByRole('article')).toContainText('当前账号')
  await page.getByRole('button',{name:'管理账号',exact:true}).click()
  if(action==='demote')await page.getByRole('dialog').locator('select').nth(0).selectOption('NORMAL_USER')
  else await page.getByRole('dialog').locator('select').nth(1).selectOption('false')
  await page.getByRole('button',{name:'确认更新账号',exact:true}).click()
  await expect(page.getByRole('button',{name:'刷新账号列表'})).toHaveCount(0);await expect(page.getByRole('article')).toHaveCount(0)
  expect(s.writes).toHaveLength(1);expect(count(s,'/auth/me')).toBeGreaterThan(2)
  await record(s,'accounts-self-'+action)
})
test('cached account list never replaces freshly opened owner candidates',async({context,page})=>{
  const s=await service(context);await openAccounts(page);await navigate(page,'platform/projects');expect(count(s,'/platform/accounts')).toBe(1)
  await page.getByRole('button',{name:'创建项目',exact:true}).click();await expect(page.getByLabel('初始负责人')).toContainText('fixture-account');expect(count(s,'/platform/accounts')).toBe(2)
  await page.getByRole('button',{name:'取消',exact:true}).click();s.accounts=[account('other','new-candidate')]
  await page.getByRole('button',{name:'创建项目',exact:true}).click();await expect(page.getByLabel('初始负责人')).toContainText('new-candidate');expect(count(s,'/platform/accounts')).toBe(3)
  await record(s,'accounts-candidates-remain-fresh')
})
test('real minute on accounts retains permission checks but no repeated list loading',async({context,page})=>{
  test.setTimeout(80000);const s=await service(context);await openAccounts(page)
  const before={accounts:count(s,'/platform/accounts'),me:count(s,'/auth/me'),projects:count(s,'/auth/projects')},start=Date.now()
  await page.waitForTimeout(60500)
  const delta={accounts:count(s,'/platform/accounts')-before.accounts,me:count(s,'/auth/me')-before.me,projects:count(s,'/auth/projects')-before.projects}
  expect(delta.accounts).toBe(0);expect(delta.me).toBe(4);expect(delta.projects).toBe(4)
  await record(s,'accounts-real-60s',{elapsedMs:Date.now()-start,delta})
})
