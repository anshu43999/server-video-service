import { expect, test, type BrowserContext, type Page } from '@playwright/test'
import { fixtureProject,fixtureUser } from './helpers/project-fixture'
import { statsFixture } from '../tests/fixtures/dashboard'
import type { StatsRange } from '../src/features/dashboard/types'
import type { AccessibleProject } from '../src/api/projects'

const project:AccessibleProject={...fixtureProject,lifecycleState:'ACTIVE',capabilities:[...fixtureProject.capabilities,'project.members.manage','project.scenes.manage','project.scenes.approve']}
const assignment={projectModelId:'pm-disabled',modelId:'fixture-model',modelName:'保留停用模型',modelVersion:'1',target:'pc',parameterPlatform:'server',parameterRevision:1,enabled:false,revision:2}
const available={modelId:'fixture-model',name:'完整模型候选',version:'1',status:'PUBLISHED',serverBindable:true,artifacts:[],parameterProfiles:{server:{revision:1,detection:{confidenceThreshold:.5,iouThreshold:.5,maxDetections:100},alertRules:[]}}}
const scene={projectId:project.projectId,sceneId:'scene-one',name:'独立场景列表',revision:1,inputTypes:['image'],models:[],plans:[],enabled:true,approved:false}
async function service(context:BrowserContext){
  const state={reads:[] as string[],writes:[] as string[],projects:[{...project}],user:fixtureUser(),
    gate:undefined as Promise<void>|undefined,gatePath:'',failPath:'',assignments:[] as typeof assignment[],statsTotal:12}
  await context.route('**/aiyoloapi/**',async route=>{
    const url=new URL(route.request().url()),path=url.pathname,key=path+url.search
    ;(route.request().method()==='GET'?state.reads:state.writes).push(key)
    const reply=(json:unknown,status=200)=>route.fulfill({json,status}).catch(()=>{})
    if(path.endsWith('/auth/status'))return reply({authenticated:true,setupRequired:false})
    if(path.endsWith('/auth/me'))return reply(state.user)
    if(path.endsWith('/auth/projects'))return reply({contractVersion:'m33-v1',projects:state.projects})
    if(path==='/aiyoloapi/platform/projects')return reply({projects:state.projects})
    const detail=state.projects.find(p=>path==='/aiyoloapi/projects/'+p.projectId);if(detail)return reply(detail)
    const total=state.statsTotal
    if(state.gatePath&&path.endsWith(state.gatePath))await state.gate
    if(state.failPath&&path.endsWith(state.failPath))return reply({detail:'隔离候选暂不可用'},503)
    if(path.endsWith('/platform/accounts'))return reply({accounts:[{accountId:'owner-one',username:'候选负责人',enabled:true,platformRole:'NORMAL_USER',revision:1}]})
    if(path.endsWith('/members'))return reply({members:[{projectId:project.projectId,accountId:'member-one',username:'已有成员',accountEnabled:true,projectRole:'PROJECT_USER',enabled:true,revision:1}]})
    if(path.endsWith('/dashboard/stats'))return reply(statsFixture(url.searchParams.get('range') as StatsRange,total))
    if(path.endsWith('/streams'))return reply([])
    if(path.endsWith('/alerts'))return reply({events:[]})
    if(path.endsWith('/rules/audit'))return reply({audit:[]})
    if(path.endsWith('/rules'))return reply({rules:[{ruleId:'rule-one',name:'测试规则',ruleVersion:1,operator:'PRESENCE',subjectKind:'track',enabled:true,requires:[],targetLabels:[],thresholds:{}}]})
    if(path.endsWith('/bindings'))return reply({bindings:[]})
    if(path.endsWith('/capabilities/sources'))return reply({sources:[{sourceId:'camera-one',modelId:'fixture-model',capabilities:['BOX']}]})
    if(path.endsWith('/scenes/scene-one')&&route.request().method()==='PATCH'){state.statsTotal=44;return reply({...scene,enabled:false,revision:2})}
    if(path.endsWith('/scenes'))return reply({scenes:[scene]})
    if(path.endsWith('/model-assignments'))return reply({assignments:state.assignments})
    if(path.endsWith('/models/available'))return reply({models:[available]})
    if(path.endsWith('/models'))return reply({models:[]})
    return reply({detail:'isolated unknown endpoint'},404)
  })
  await context.routeWebSocket('**/aiyoloapi/**',socket=>{socket.onMessage(()=>{})})
  return state
}
const count=(state:Awaited<ReturnType<typeof service>>,suffix:string)=>state.reads.filter(p=>p.endsWith(suffix)).length
async function clock(page:Page){const time=new Date('2026-11-09T11:00:00Z');await page.clock.install({time});await page.clock.pauseAt(time)}
async function navigate(page:Page,path:string){
  await page.evaluate(path=>{window.history.pushState({},'',path);window.dispatchEvent(new PopStateEvent('popstate'))},'/admin-next/'+path)
  await expect(page.locator('#main-content')).not.toHaveAttribute('inert','')
}
async function record(page:Page,state:Awaited<ReturnType<typeof service>>,scenario:string){
  const timing=await page.evaluate(()=>performance.getEntriesByType('resource').filter(r=>new URL(r.name).pathname.startsWith('/aiyoloapi/')).map(r=>({path:new URL(r.name).pathname+new URL(r.name).search,startMs:r.startTime,durationMs:r.duration})))
  const result={scenario,environment:'local real Chromium with isolated API fixtures; not production measurement',counts:Object.fromEntries([...new Set(state.reads)].map(p=>[p,state.reads.filter(q=>p===q).length])),writes:state.writes}
  console.log(JSON.stringify(result));await test.info().attach(scenario,{body:JSON.stringify({...result,timing}),contentType:'application/json'})
}

test('overview and dashboard reuse ten-second reads while period changes fetch only statistics',async({context,page})=>{
  const state=await service(context);await clock(page);await page.goto('/admin-next/overview?project='+project.projectId)
  await expect(page.locator('.board-kpis')).toContainText('12')
  await expect.poll(()=>count(state,'/alerts?limit=20')).toBe(1)
  await navigate(page,'dashboard?project='+project.projectId);await expect(page.getByRole('region',{name:'数据看板工作区'})).toBeVisible()
  await expect(page.locator('.board-kpis')).toContainText('12')
  expect(count(state,'/dashboard/stats?range=today')).toBe(1);expect(count(state,'/streams')).toBe(1)
  await navigate(page,'dashboard?project='+project.projectId+'&range=7d')
  await expect.poll(()=>count(state,'/dashboard/stats?range=7d')).toBe(1)
  await expect(page.getByRole('button',{name:'刷新看板',exact:true})).toBeEnabled()
  expect(count(state,'/streams')).toBe(1);expect(count(state,'/alerts?limit=20')).toBe(1)
  await navigate(page,'overview?project='+project.projectId);await expect(page.getByRole('region',{name:'总览工作区'})).toBeVisible()
  await expect(page.locator('.board-kpis')).toContainText('12');expect(count(state,'/dashboard/stats?range=today')).toBe(1)
  await page.getByRole('button',{name:'刷新看板',exact:true}).click();await expect.poll(()=>count(state,'/streams')).toBe(2)
  await expect(page.getByRole('button',{name:'刷新看板',exact:true})).toBeEnabled()
  expect(count(state,'/alerts?limit=20')).toBe(2);expect(count(state,'/dashboard/stats?range=today')).toBe(2)
  await record(page,state,'shared-dashboard-period-navigation')
})

test('real 60.5 second dashboard retains six fresh cycles and permission monitoring',async({context,page})=>{
  test.setTimeout(90_000);const state=await service(context)
  await page.goto('/admin-next/overview?project='+project.projectId);await expect(page.locator('.board-kpis')).toContainText('12')
  const keys=['/dashboard/stats?range=today','/streams','/alerts?limit=20','/auth/me','/auth/projects']
  const before=keys.map(k=>count(state,k));await page.waitForTimeout(60_500)
  expect(keys.map((k,i)=>count(state,k)-before[i]!)).toEqual([6,6,6,4,4]);await record(page,state,'real-dashboard-60s')
})

test('platform projects do not fetch accounts until create, with cancellation and retry',async({context,page})=>{
  const state=await service(context);await page.goto('/admin-next/platform/projects')
  await expect(page.getByRole('heading',{name:'验收项目',exact:true})).toBeVisible();expect(count(state,'/platform/accounts')).toBe(0)
  await page.getByRole('button',{name:'编辑项目',exact:true}).click();expect(count(state,'/platform/accounts')).toBe(0)
  await page.getByRole('button',{name:'取消',exact:true}).click()
  let release!:()=>void;state.gatePath='/platform/accounts';state.gate=new Promise(r=>{release=r})
  const cancelled:string[]=[];page.on('requestfailed',r=>{if(r.url().endsWith('/platform/accounts'))cancelled.push(r.failure()?.errorText??'')})
  await page.getByRole('button',{name:'创建项目',exact:true}).click();await expect.poll(()=>count(state,'/platform/accounts')).toBe(1)
  await expect(page.getByRole('button',{name:'确认创建项目',exact:true})).toBeDisabled()
  await page.getByRole('button',{name:'取消',exact:true}).click();await expect.poll(()=>cancelled.length).toBe(1)
  state.gate=undefined;state.gatePath='';release();state.failPath='/platform/accounts'
  await page.getByRole('button',{name:'创建项目',exact:true}).click();await expect(page.getByRole('dialog')).toContainText('隔离候选暂不可用')
  state.failPath='';await page.getByRole('button',{name:'重试账号候选'}).click()
  await expect(page.getByLabel('初始负责人').locator('option')).toHaveCount(2)
  expect(state.writes).toEqual([]);await record(page,state,'lazy-platform-accounts-cancel-retry')
})

test('members show required names without fetching account candidates before adding',async({context,page})=>{
  const state=await service(context);await page.goto('/admin-next/members?project='+project.projectId)
  await expect(page.getByRole('heading',{name:'已有成员',exact:true})).toBeVisible();expect(count(state,'/platform/accounts')).toBe(0)
  await page.getByRole('button',{name:'编辑成员',exact:true}).click();expect(count(state,'/platform/accounts')).toBe(0)
  await page.getByRole('button',{name:'取消',exact:true}).click();await page.getByRole('button',{name:'添加项目成员',exact:true}).click()
  await expect(page.getByLabel('选择账号').locator('option')).toHaveCount(2);expect(count(state,'/platform/accounts')).toBe(1)
  await record(page,state,'lazy-member-accounts')
})

test('rules keep visible audit but load source candidates only in binding dialog',async({context,page})=>{
  const state=await service(context);await page.goto('/admin-next/rules?project='+project.projectId)
  await expect(page.getByRole('heading',{name:'测试规则',exact:true})).toBeVisible();expect(count(state,'/capabilities/sources')).toBe(0)
  await page.getByRole('button',{name:'校验与绑定',exact:true}).click()
  await expect.poll(()=>count(state,'/capabilities/sources')).toBe(1);await expect(page.getByRole('dialog')).toContainText('实际来源')
  expect(count(state,'/rules/audit')).toBe(1);expect(state.writes).toEqual([]);await record(page,state,'lazy-rule-sources')
})

test('scene lists and empty inventory avoid models until editors need them',async({context,page})=>{
  const state=await service(context);await clock(page);await page.goto('/admin-next/scenes?project='+project.projectId)
  await expect(page.locator('.scene-list')).toContainText('独立场景列表');expect(count(state,'/models')).toBe(0)
  await page.getByRole('button',{name:'创建场景',exact:true}).click();await expect.poll(()=>count(state,'/models')).toBe(1)
  await page.getByRole('button',{name:'取消',exact:true}).click();await navigate(page,'project-models?project='+project.projectId)
  await expect(page.getByText('PC 端尚未分配模型',{exact:true})).toBeVisible();expect(count(state,'/models/available')).toBe(0)
  await page.getByRole('button',{name:'添加 PC 模型',exact:true}).click();await expect.poll(()=>count(state,'/models/available')).toBe(1)
  await expect(page.getByRole('dialog')).not.toContainText('当前没有满足项目授权条件')
  await record(page,state,'lazy-scene-model-candidates')
})

test('disabled assignment preserves required fallback metadata instead of hiding it',async({context,page})=>{
  const state=await service(context);state.assignments=[assignment];await page.goto('/admin-next/project-models?project='+project.projectId)
  await expect(page.locator('.inventory-row')).toContainText('保留停用模型');await expect(page.locator('.inventory-row')).toContainText('已停用')
  expect(count(state,'/models/available')).toBe(1);await expect(page.locator('.inventory-row')).not.toContainText('状态未知')
  await record(page,state,'disabled-assignment-required-metadata')
})

test('account permission change clears cached dashboard before explicit project reentry',async({context,page})=>{
  const state=await service(context);await clock(page);await page.goto('/admin-next/overview?project='+project.projectId)
  await expect(page.locator('.board-kpis')).toContainText('12')
  state.projects=[{...project,membershipRevision:2}]
  await page.evaluate(()=>window.dispatchEvent(new Event('focus')))
  await expect(page.getByRole('alert')).toContainText('项目状态或成员权限已变化');await expect(page.locator('.board-kpis')).toHaveCount(0)
  state.statsTotal=77
  await page.getByRole('link',{name:'项目空间',exact:true}).click()
  await page.getByRole('button',{name:'重新验证项目',exact:true}).click()
  await page.getByRole('button',{name:'进入 验收项目',exact:true}).click()
  await expect(page.locator('.board-kpis')).toContainText('77');expect(count(state,'/dashboard/stats?range=today')).toBe(2)
  await record(page,state,'cache-revocation-fresh-entry')
})

test('a confirmed scene write invalidates statistics and streams but retains unrelated recent window',async({context,page})=>{
  const state=await service(context);await clock(page);await page.goto('/admin-next/overview?project='+project.projectId)
  await expect(page.locator('.board-kpis')).toContainText('12');await expect.poll(()=>count(state,'/alerts?limit=20')).toBe(1)
  await navigate(page,'scenes?project='+project.projectId)
  await page.getByRole('button',{name:'停用场景 独立场景列表',exact:true}).click()
  await expect(page.getByRole('status')).toContainText('操作已由服务器确认')
  await navigate(page,'overview?project='+project.projectId);await expect(page.locator('.board-kpis')).toContainText('44')
  expect(count(state,'/dashboard/stats?range=today')).toBe(2);expect(count(state,'/streams')).toBe(2);expect(count(state,'/alerts?limit=20')).toBe(1)
  expect(state.writes).toEqual(['/aiyoloapi/projects/'+project.projectId+'/scenes/scene-one']);await record(page,state,'targeted-write-invalidation')
})

test('pending account candidates are cancelled and removed on membership revision change',async({context,page})=>{
  const state=await service(context);await page.goto('/admin-next/members?project='+project.projectId)
  await expect(page.getByRole('heading',{name:'已有成员',exact:true})).toBeVisible()
  let release!:()=>void;state.gatePath='/platform/accounts';state.gate=new Promise(r=>{release=r})
  const cancelled:string[]=[];page.on('requestfailed',r=>{if(r.url().endsWith('/platform/accounts'))cancelled.push(r.failure()?.errorText??'')})
  await page.getByRole('button',{name:'添加项目成员',exact:true}).click();await expect.poll(()=>count(state,'/platform/accounts')).toBe(1)
  await expect(page.getByRole('dialog')).not.toContainText('暂无可添加账号');await expect(page.getByRole('button',{name:'确认添加项目成员',exact:true})).toBeDisabled()
  state.projects=[{...project,membershipRevision:2}];await page.evaluate(()=>window.dispatchEvent(new Event('focus')))
  await expect(page.getByRole('alert')).toContainText('项目状态或成员权限已变化');await expect.poll(()=>cancelled.length).toBe(1)
  release();await expect(page.getByRole('dialog')).toHaveCount(0);await expect(page.getByText('候选负责人',{exact:true})).toHaveCount(0)
  expect(state.writes).toEqual([]);await record(page,state,'candidate-permission-cancellation')
})

test('cross-project dashboard navigation rejects a late old snapshot and does not reuse it on reentry',async({context,page})=>{
  const state=await service(context);state.projects=['a','b'].map(id=>({...project,projectId:id,projectCode:id,displayName:'项目 '+id}))
  let release!:()=>void;state.gatePath='/projects/a/dashboard/stats';state.gate=new Promise(r=>{release=r})
  await clock(page);await page.goto('/admin-next/overview?project=a');await expect.poll(()=>count(state,'/projects/a/dashboard/stats?range=today')).toBe(1)
  state.statsTotal=88;await navigate(page,'overview?project=b');await expect(page.locator('.board-kpis')).toContainText('88')
  release();state.gatePath='';state.gate=undefined;await expect(page.locator('.board-kpis')).not.toContainText('12')
  state.statsTotal=66;await navigate(page,'overview?project=a');await expect(page.locator('.board-kpis')).toContainText('66')
  expect(count(state,'/projects/a/dashboard/stats?range=today')).toBe(2);await record(page,state,'cache-cross-project-late-response')
})
