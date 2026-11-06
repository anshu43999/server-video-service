import { expect, test, type BrowserContext, type Page } from '@playwright/test'
import { statsFixture } from '../tests/fixtures/dashboard'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const prefix = () => test.info().project.name === 'production-chromium' ? '/admin' : '/admin-next'
const member = { accountId: 'member', username: 'project-user', role: 'operator', platformRole: 'NORMAL_USER', contractVersion: 'm33-v1' }
const project = (id: string) => ({ projectId: id, projectCode: id, displayName: `项目 ${id.toUpperCase()}`, lifecycleState: 'ACTIVE', revision: 1, membershipRevision: 1, projectRole: 'PROJECT_OWNER', platformEntry: false, capabilities: ['project.read', 'project.streams.view', 'project.alerts.read', 'project.rules.manage', 'project.settings.manage'] })
const png = readFileSync(resolve(process.cwd(), 'tests-e2e/fixtures/evidence_helmet_violation.png'))
async function service(context: BrowserContext) {
  const state = { user: { ...member }, projects: [project('a'), project('b')], authenticated: true, projectsStatus: 200, requests: [] as string[], sockets: [] as string[] }
  await context.addInitScript(() => {
    const sockets: { url: string; closed: boolean }[] = []; (window as any).__projectSockets = sockets
    class Socket {
      onopen: ((event: Event) => void) | null = null; onmessage = null; onclose = null; onerror = null; closed = false
      constructor(public url: string) { sockets.push(this); setTimeout(() => { if(!this.closed)this.onopen?.(new Event('open')) }, 0) }
      close() { this.closed = true }
    }
    ;(window as any).WebSocket = Socket
  })
  await context.route('**/aiyoloapi/**', route => {
    const path = new URL(route.request().url()).pathname; state.requests.push(path)
    if(path.endsWith('/auth/status'))return route.fulfill({ json: { authenticated: state.authenticated, setupRequired: false, user: state.user } })
    if(path.endsWith('/auth/me'))return route.fulfill({ status: state.authenticated ? 200 : 401, json: state.authenticated ? state.user : { detail: 'expired' } })
    if(path.endsWith('/auth/projects'))return route.fulfill({ status: state.projectsStatus, json: state.projectsStatus === 200 ? { contractVersion: 'm33-v1', projects: state.projects } : { detail: 'project directory unavailable' } })
    if(path.endsWith('/auth/logout')){ state.authenticated=false; return route.fulfill({ json: { ok: true } }) }
    const match = new RegExp('^/aiyoloapi/projects/([^/]+)(.*)$').exec(path)
    if(!match)return route.fulfill({ status: 400, json: { detail: 'missing project' } })
    const p = state.projects.find(p => p.projectId===match[1]); if(!p)return route.fulfill({ status:404,json:{detail:'not found'} })
    const suffix=match[2]
    if(!suffix)return route.fulfill({json:p})
    if(suffix==='/dashboard/stats')return route.fulfill({json:statsFixture('today',p.projectId==='a'?11:22)})
    if(suffix==='/models')return route.fulfill({json:{models:[]}})
    if(suffix==='/streams')return route.fulfill({json:[{stream_id:'same-camera',display_name:`${p.projectId}-private-camera`,enabled:true,runtime_available:true,yolo_enabled:true,received_fps:20,runtime_state:'running'}]})
    if(suffix.endsWith('/preview'))return route.fulfill({contentType:'image/jpeg',body:png})
    if(suffix.endsWith('/playback')||suffix.endsWith('/mjpeg'))return route.fulfill({status:410,json:{detail:{code:'live_video_retired'}}})
    if(suffix==='/alerts')return route.fulfill({json:{events:[{eventId:'same-event',projectId:p.projectId,displayName:`${p.projectId}-private-alert`,sourceId:'camera',confirmedAtUs:1791518400123456,state:'CONFIRMED',severity:'MAJOR',disposition:{status:'OPEN'}}]}})
    if(suffix.endsWith('/verification'))return route.fulfill({json:{status:'UNREVIEWED'}})
    if(suffix==='/alerts/same-event')return route.fulfill({json:{eventId:'same-event',projectId:p.projectId,displayName:`${p.projectId}-private-alert`,sourceId:'camera',confirmedAtUs:1791518400123456,state:'CONFIRMED',severity:'MAJOR',disposition:{status:'OPEN'}}})
    return route.fulfill({json:{rules:[],audit:[],sources:[]}})
  })
  return state
}
const contextBar = (page:Page)=>page.getByRole('region',{name:'当前项目上下文'})
for(const width of [1440,390]) {
  test(`explicit selection, role indicator and safe switch at ${width}px`,async({context,page})=>{
    const state=await service(context); await page.setViewportSize({width,height:900}); await page.goto(`${prefix()}/overview`)
    await expect(page.getByRole('heading',{name:'选择项目空间'})).toBeVisible()
    expect(state.requests.filter(p=>p.includes('/projects/'))).toEqual([])
    await page.getByRole('button',{name:'进入 项目 A'}).focus(); await page.keyboard.press('Enter')
    await expect(contextBar(page)).toContainText('项目 A'); await expect(contextBar(page)).toContainText('项目负责人')
    await expect(page.locator('.board-alert')).toContainText('a-private-alert')
    await page.getByRole('button',{name:'切换项目'}).click(); await expect(page.locator('body')).not.toContainText('a-private-alert')
    await page.getByRole('button',{name:'进入 项目 B'}).click(); await expect(page.locator('.board-alert')).toContainText('b-private-alert')
    await expect(contextBar(page)).toContainText('项目 B'); expect(new URL(page.url()).searchParams.get('project')).toBe('b')
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
    if (width === 1440) {
      const projectLink = page.getByRole('link', { name: '项目空间', exact: true })
      await expect(projectLink.locator('span')).toBeVisible()
      const bounds = await projectLink.boundingBox()
      expect(bounds?.height).toBeLessThan(60)
    }
    await page.screenshot({path:`../evidence/M34/M34-T03-project-${width}.png`,fullPage:true})
  })
}
test('member single project auto-enters but platform admin explicitly confirms',async({context,page})=>{
  const state=await service(context); state.projects=[project('a')]
  await page.goto(`${prefix()}/alerts`); await expect(page.locator('.alert-event-row')).toContainText('a-private-alert')
  state.user={...member,platformRole:'PLATFORM_ADMIN',role:'admin'}; state.projects=[{...project('a'),platformEntry:true}]
  await page.goto(`${prefix()}/overview`); await expect(page.getByRole('heading',{name:'选择项目空间'})).toBeVisible()
  await page.getByRole('button',{name:'进入 项目 A'}).click(); await expect(contextBar(page)).toContainText('平台超级管理员（管理全平台） · 显式进入')
})
test('no membership and invalid deep links never make business requests',async({context,page})=>{
  const state=await service(context); state.projects=[]
  await page.goto(`${prefix()}/overview`); await expect(page.getByRole('heading',{name:'暂无可访问项目'})).toBeVisible()
  state.projects=[project('a')]; await page.goto(`${prefix()}/alerts?project=private-other&event=secret`)
  await expect(page.getByRole('alert')).toContainText('项目不存在或当前账号已无访问权限')
  expect(state.requests.filter(p=>p.includes('/projects/'))).toEqual([])
})
test('refresh restores an explicit deep-link project without leaking another project',async({context,page})=>{
  await service(context); await page.goto(`${prefix()}/alerts?project=b&event=same-event`)
  await expect(page.getByRole('dialog')).toContainText('b-private-alert'); await page.reload()
  await expect(contextBar(page)).toContainText('项目 B'); await expect(page.getByRole('dialog')).toContainText('b-private-alert')
  await expect(page.locator('body')).not.toContainText('a-private-alert')
})
test('switch destroys sockets, media and polling before loading the next project',async({context,page})=>{
  const state=await service(context); await page.goto(`${prefix()}/streams?project=a`)
  await expect(page.locator('.stream-preview img')).toBeVisible()
  await page.getByRole('button',{name:'切换项目'}).click()
  await expect(page.locator('.stream-preview img')).toHaveCount(0)
  expect(await page.evaluate(()=>(window as any).__projectSockets.every((s:any)=>s.closed))).toBe(true)
  await page.getByRole('button',{name:'进入 项目 B'}).click(); await expect(page.locator('.board-alert')).toContainText('b-private-alert')
  const count=state.requests.filter(p=>p.includes('/projects/a/')).length
  await page.clock.install(); await page.clock.fastForward(11000)
  expect(state.requests.filter(p=>p.includes('/projects/a/')).length).toBe(count)
})
test('late prior-project responses cannot overwrite newly selected project',async({context,page})=>{
  await service(context); let release!:()=>void; const gate=new Promise<void>(r=>{release=r})
  await context.route('**/projects/a/alerts',async route=>{await gate;await route.fulfill({json:{events:[{eventId:'late',projectId:'a',displayName:'late-private-a',confirmedAtUs:1791518400123456,state:'CONFIRMED'}]}}).catch(()=>{})})
  await page.goto(`${prefix()}/overview?project=a`); await expect(contextBar(page)).toContainText('项目 A')
  await page.getByRole('button',{name:'切换项目'}).click(); await page.getByRole('button',{name:'进入 项目 B'}).click()
  await expect(page.locator('.board-alert')).toContainText('b-private-alert'); release()
  await expect(page.locator('body')).not.toContainText('late-private-a')
})
for(const change of ['removed','suspended','role'] as const) {
  test(`permission revalidation clears data after ${change}`,async({context,page})=>{
    const state=await service(context); await page.goto(`${prefix()}/alerts?project=a`); await expect(page.locator('.alert-event-row')).toContainText('a-private-alert')
    state.projects=change==='removed'?[project('b')]:[{...project('a'),revision:2,capabilities:change==='suspended'?['project.read','project.alerts.read','project.settings.manage']:project('a').capabilities,lifecycleState:change==='suspended'?'SUSPENDED':'ACTIVE',projectRole:change==='role'?'PROJECT_USER':'PROJECT_OWNER'}]
    await page.evaluate(()=>window.dispatchEvent(new Event('focus')))
    await expect(page.locator('body')).not.toContainText('a-private-alert'); await expect(page.getByRole('alert')).toContainText('项目状态或成员权限已变化')
    if(change==='suspended'){await page.getByRole('button',{name:'重新验证项目'}).click();await page.getByRole('button',{name:'进入 项目 A'}).click();await expect(page.locator('.shell-alert')).toContainText('项目已停用');await page.goto(`${prefix()}/alerts?project=a`);await expect(page.locator('.alert-event-row')).toContainText('a-private-alert');await expect(page.getByRole('button',{name:'确认告警',exact:true})).toHaveCount(0)}
  })
}
test('tabs never share project selection; logout clears the other tab',async({context,page})=>{
  await service(context); await page.goto(`${prefix()}/alerts?project=a`); await expect(contextBar(page)).toContainText('项目 A')
  const other=await context.newPage();await other.goto(`${prefix()}/alerts?project=b`);await expect(contextBar(other)).toContainText('项目 B')
  expect(new URL(page.url()).searchParams.get('project')).toBe('a')
  await other.getByRole('button',{name:'退出登录',exact:true}).click();await expect(other).toHaveURL(new RegExp('/login'))
  await page.bringToFront();await page.evaluate(()=>window.dispatchEvent(new Event('focus')))
  await expect(page).toHaveURL(new RegExp('/login'));await expect(page.locator('body')).not.toContainText('a-private-alert')
  expect(await page.evaluate(()=>Object.keys(localStorage))).toEqual(['aiyolo.session.changed'])
})

test('project directory failure clears old project data and recovers after retry',async({context,page})=>{
  const state=await service(context);await page.goto(`${prefix()}/alerts?project=a`)
  await expect(page.locator('.alert-event-row')).toContainText('a-private-alert')
  state.projectsStatus=503
  await page.getByRole('button',{name:'切换项目'}).click()
  await expect(page.getByRole('heading',{name:'暂时无法验证项目'})).toBeVisible()
  await expect(page.locator('body')).not.toContainText('a-private-alert')
  await expect(page.getByRole('alert')).toBeVisible()
  await page.screenshot({path:`../evidence/M33/M33-T16-project-directory-failure-${test.info().project.name==='production-chromium'?'production':'test'}.png`,fullPage:true,animations:'disabled'})
  state.projectsStatus=200
  await page.getByRole('button',{name:'重新验证项目'}).click()
  await expect(page.getByRole('heading',{name:'选择项目空间'})).toBeVisible()
  await page.getByRole('button',{name:'进入 项目 B'}).click()
  await expect(page.locator('.board-alert')).toContainText('b-private-alert')
  await expect(page.locator('body')).not.toContainText('a-private-alert')
})

test('expired session clears project data and redirects to login',async({context,page})=>{
  const state=await service(context);await page.goto(`${prefix()}/alerts?project=a`)
  await expect(page.locator('.alert-event-row')).toContainText('a-private-alert')
  state.authenticated=false
  // Recheck on focus, as when the operator returns to an open management tab.
  await page.evaluate(()=>window.dispatchEvent(new Event('focus')))
  await expect(page).toHaveURL(new RegExp('/login'))
  await expect(page.locator('body')).not.toContainText('a-private-alert')
  await page.screenshot({path:`../evidence/M33/M33-T16-session-expired-${test.info().project.name==='production-chromium'?'production':'test'}.png`,fullPage:true,animations:'disabled'})
})
