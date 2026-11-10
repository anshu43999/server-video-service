import { expect, test, type BrowserContext, type Page } from '@playwright/test'
import { fixtureProject, fixtureUser } from './helpers/project-fixture'
const base = {...fixtureProject, capabilities:[...fixtureProject.capabilities,'project.members.manage']}
async function service(context:BrowserContext) {
  const state={reads:[] as string[],writes:[] as string[],unexpected:[] as string[],user:fixtureUser(),
    projects:[{...base}], names:{[base.projectId]:'原成员'} as Record<string,string>, platformName:'原项目',
    writeStatus:200, gatePath:'', gate:undefined as Promise<void>|undefined, meStatus:200}
  await context.route('**/aiyoloapi/**',async route=>{
    const path=new URL(route.request().url()).pathname, method=route.request().method()
    ;(method==='GET'?state.reads:state.writes).push(path)
    const reply=(json:unknown,status=200)=>route.fulfill({json,status}).catch(()=>{})
    if(path.endsWith('/auth/status'))return reply({authenticated:true,setupRequired:false})
    if(path.endsWith('/auth/me'))return reply(state.user,state.meStatus)
    if(path.endsWith('/auth/projects'))return reply({contractVersion:'m33-v1',projects:state.projects})
    if(path==='/aiyoloapi/platform/projects'&&method==='GET'){const data=state.projects.map(p=>({...p,displayName:state.platformName}));if(path===state.gatePath)await state.gate;return reply({projects:data})}
    if(path.startsWith('/aiyoloapi/platform/projects/')&&method==='PATCH'){state.platformName='更新项目';return reply({detail:'isolated write result'},state.writeStatus)}
    if(path==='/aiyoloapi/platform/accounts')return reply({accounts:[]})
    const match=new RegExp('^/aiyoloapi/projects/([^/]+)/members(?:/([^/]+))?$').exec(path)
    if(match){
      const projectId=match[1]!
      if(method!=='GET'){state.names[projectId]='更新成员';return reply({detail:'isolated write result'},state.writeStatus)}
      const member={projectId,accountId:'member-one',username:state.names[projectId],accountEnabled:true,projectRole:'PROJECT_USER',enabled:true,revision:1}
      if(path===state.gatePath)await state.gate
      return reply({members:[member]})
    }
    const detail=state.projects.find(p=>path==='/aiyoloapi/projects/'+p.projectId);if(detail)return reply(detail)
    if(path.endsWith('/alerts'))return reply({events:[]})
    if(path.endsWith('/metrics'))return reply({scope:'project',streams:{total:0,framesReceived:0,framesProcessed:0,framesDropped:0}})
    state.unexpected.push(path);return reply({detail:'isolated unknown endpoint'},404)
  })
  await context.routeWebSocket('**/aiyoloapi/**',socket=>{socket.onMessage(()=>{})})
  return state
}
const count=(state:Awaited<ReturnType<typeof service>>,suffix:string)=>state.reads.filter(p=>p.endsWith(suffix)).length
async function navigate(page:Page,path:string){
  await page.evaluate(path=>{history.pushState({},'',path);dispatchEvent(new PopStateEvent('popstate'))},'/admin-next/'+path)
  await expect(page.locator('#main-content')).not.toHaveAttribute('inert','')
}
async function record(state:Awaited<ReturnType<typeof service>>,scenario:string,extra:Record<string,unknown>={}) {
  expect(state.unexpected).toEqual([])
  const result={scenario,environment:'real local Chromium with synthetic API/WS; not production',
    counts:Object.fromEntries([...new Set(state.reads)].map(p=>[p,state.reads.filter(q=>q===p).length])),writes:state.writes,...extra}
  console.log(JSON.stringify(result));await test.info().attach(scenario,{body:JSON.stringify(result),contentType:'application/json'})
}
test('platform list real A-B-A within five seconds reuses reads and explicit refresh reloads',async({context,page})=>{
  const s=await service(context);await page.goto('/admin-next/platform/projects');await expect(page.getByRole('heading',{name:'原项目',exact:true})).toBeVisible()
  const before=count(s,'/platform/projects'),me=count(s,'/auth/me'),started=Date.now()
  await navigate(page,'platform/accounts');await expect(page.getByRole('button',{name:'刷新账号列表'})).toBeVisible()
  await navigate(page,'platform/projects');await expect(page.getByRole('heading',{name:'原项目',exact:true})).toBeVisible()
  const elapsedMs=Date.now()-started;expect(elapsedMs).toBeLessThan(5000);expect(count(s,'/platform/projects')).toBe(before);expect(count(s,'/auth/me')).toBe(me)
  await page.evaluate(()=>dispatchEvent(new Event('focus')));await expect.poll(()=>count(s,'/auth/me')).toBe(me+1)
  await expect(page.locator('#main-content')).not.toHaveAttribute('inert','');expect(count(s,'/platform/projects')).toBe(before)
  s.platformName='刷新项目';await page.getByRole('button',{name:'刷新项目列表'}).click();await expect(page.getByRole('heading',{name:'刷新项目',exact:true})).toBeVisible()
  expect(count(s,'/platform/projects')).toBe(before+1);await record(s,'platform-A-B-A',{elapsedMs,returnExtraReads:0,manualExtraReads:1})
})
test('member list real TTL expiration fetches once on return and adds no idle timer',async({context,page})=>{
  const s=await service(context);await page.goto('/admin-next/members?project='+base.projectId);await expect(page.getByRole('heading',{name:'原成员',exact:true})).toBeVisible()
  await navigate(page,'project-diagnostics?project='+base.projectId);await page.waitForTimeout(10_100);expect(count(s,'/members')).toBe(1)
  s.names[base.projectId]='到期新成员';await navigate(page,'members?project='+base.projectId);await expect(page.getByRole('heading',{name:'到期新成员',exact:true})).toBeVisible()
  expect(count(s,'/members')).toBe(2);expect(count(s,'/platform/accounts')).toBe(0);await record(s,'members-real-TTL')
})
for(const status of [200,409,503])test(`member write ${status} invalidates cache without replay`,async({context,page})=>{
  const s=await service(context);s.writeStatus=status
  await page.goto('/admin-next/members?project='+base.projectId);await expect(page.getByRole('heading',{name:'原成员',exact:true})).toBeVisible()
  await page.getByRole('button',{name:'编辑成员',exact:true}).click();await page.getByRole('button',{name:'确认编辑项目成员',exact:true}).click()
  if(status!==200){await expect(page.getByRole('dialog')).toContainText('不会自动重试');await page.getByRole('button',{name:'取消',exact:true}).click();await page.getByRole('button',{name:'刷新成员列表'}).click()}
  await expect(page.getByRole('heading',{name:'更新成员',exact:true})).toBeVisible();expect(count(s,'/members')).toBe(2);expect(s.writes).toHaveLength(1)
  await navigate(page,'project-diagnostics?project='+base.projectId);await navigate(page,'members?project='+base.projectId)
  await expect(page.getByRole('heading',{name:'更新成员',exact:true})).toBeVisible();expect(count(s,'/members')).toBe(2)
  await record(s,'member-write-'+status)
})
test('platform write reloads and permission-list revision discards cached snapshot',async({context,page})=>{
  const s=await service(context);await page.goto('/admin-next/platform/projects');await expect(page.getByRole('heading',{name:'原项目',exact:true})).toBeVisible()
  await page.getByRole('button',{name:'编辑项目',exact:true}).click();await page.getByLabel('项目名称').fill('更新项目');await page.getByRole('button',{name:'确认编辑项目',exact:true}).click()
  await expect(page.getByRole('heading',{name:'更新项目',exact:true})).toBeVisible();expect(count(s,'/platform/projects')).toBe(2)
  s.projects=[{...base,revision:2}];s.platformName='权限修订后项目';await page.evaluate(()=>dispatchEvent(new Event('focus')))
  await expect(page.getByRole('heading',{name:'权限修订后项目',exact:true})).toBeVisible();expect(count(s,'/platform/projects')).toBe(3);expect(s.writes).toHaveLength(1)
  await record(s,'platform-write-and-revision')
})
test('project switching cancels late member list and never reuses it on reentry',async({context,page})=>{
  const s=await service(context);s.projects=['a','b'].map(id=>({...base,projectId:id,projectCode:id,displayName:'项目'+id}));s.names={a:'旧A成员',b:'B成员'}
  let release!:()=>void;s.gatePath='/aiyoloapi/projects/a/members';s.gate=new Promise(r=>{release=r})
  const failures:string[]=[];page.on('requestfailed',r=>{if(new URL(r.url()).pathname===s.gatePath)failures.push('cancelled')})
  await page.goto('/admin-next/members?project=a');await expect.poll(()=>count(s,'/projects/a/members')).toBe(1)
  await navigate(page,'members?project=b');await expect(page.getByRole('heading',{name:'B成员',exact:true})).toBeVisible();await expect.poll(()=>failures.length).toBe(1)
  release();s.gate=undefined;s.names.a='新A成员';await navigate(page,'members?project=a');await expect(page.getByRole('heading',{name:'新A成员',exact:true})).toBeVisible()
  expect(count(s,'/projects/a/members')).toBe(2);await record(s,'members-project-cancel',{cancelled:failures.length})
})
test('failed platform write during permission refresh releases loading for manual recovery',async({context,page})=>{
  const s=await service(context);await page.goto('/admin-next/platform/projects');await expect(page.getByRole('heading',{name:'原项目',exact:true})).toBeVisible()
  await page.getByRole('button',{name:'编辑项目',exact:true}).click();s.writeStatus=503
  let release!:()=>void;s.gatePath='/aiyoloapi/platform/projects';s.gate=new Promise(r=>{release=r})
  s.projects=[{...base,revision:2}];await page.evaluate(()=>dispatchEvent(new Event('focus')))
  await expect.poll(()=>count(s,'/platform/projects')).toBe(2)
  await expect(page.locator('#main-content')).not.toHaveAttribute('inert','')
  await page.getByRole('button',{name:'确认编辑项目',exact:true}).click();await expect(page.getByRole('dialog')).toContainText('不会自动重试')
  release();s.gate=undefined;await page.getByRole('button',{name:'取消',exact:true}).click()
  const refresh=page.getByRole('button',{name:'刷新项目列表'});await expect(refresh).toBeEnabled();await refresh.click()
  await expect(page.getByRole('heading',{name:'更新项目',exact:true})).toBeVisible();expect(count(s,'/platform/projects')).toBe(3);expect(s.writes).toHaveLength(1)
  await record(s,'platform-pending-refresh-failed-write-recovery')
})

test('platform role revocation removes cached list and identity is not reused',async({context,page})=>{
  const s=await service(context);await page.goto('/admin-next/platform/projects');await expect(page.getByRole('heading',{name:'原项目',exact:true})).toBeVisible()
  s.user=fixtureUser('operator');await page.evaluate(()=>dispatchEvent(new Event('focus')))
  await expect(page.getByRole('heading',{name:'原项目',exact:true})).toHaveCount(0);await expect(page.getByRole('alert')).toContainText('账号会话已变化')
  expect(count(s,'/platform/projects')).toBe(1);await record(s,'platform-cache-revocation')
})
