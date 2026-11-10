import { expect, test, type BrowserContext, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { fixtureProject as sourceFixtureProject, fixtureUser } from './helpers/project-fixture'
import type { AccessibleProject } from '../src/api/projects'

const fixtureProject: AccessibleProject = { ...sourceFixtureProject, lifecycleState: 'ACTIVE' }
const png=readFileSync(resolve(process.cwd(),'tests-e2e/fixtures/evidence_helmet_violation.png'))
const events=Array.from({length:10},(_,i)=>({eventId:'media-'+i,projectId:fixtureProject.projectId,displayName:'证据事件 '+i,origin:'SERVER_STREAM',ruleId:'RULE',severity:'MAJOR',state:'CONFIRMED',confirmedAtUs:1_750_000_000_000_000-i,disposition:{status:'OPEN'},evidence:{thumbnail:{contentVersion:1},snapshotUri:'fixture-only',displayOverlay:{version:1,bakedIn:false,coordinateSpace:'normalized',detections:[]}}}))
async function service(context:BrowserContext,page:Page){
  const jpeg=Buffer.from(await page.evaluate(()=>{const canvas=document.createElement('canvas');canvas.width=160;canvas.height=90;const ctx=canvas.getContext('2d')!;ctx.fillStyle='#267441';ctx.fillRect(0,0,160,90);ctx.fillStyle='#ffffff';ctx.fillText('LOCAL FRAME',12,45);return canvas.toDataURL('image/jpeg').split(',')[1]!}),'base64')
  const state={reads:[] as string[],writes:[] as string[],events:structuredClone(events),projects:[{...fixtureProject}] as AccessibleProject[],
    imageGate:undefined as Promise<void>|undefined,previewGate:undefined as Promise<void>|undefined,previewStatus:200,invalidJpeg:false,
    activeImages:0,maxImages:0,previewTimes:[] as number[],failed:[] as string[]}
  page.on('requestfailed',r=>state.failed.push(new URL(r.url()).pathname))
  await context.route('**/aiyoloapi/**',async route=>{
    const path=new URL(route.request().url()).pathname
    ;(route.request().method()==='GET'?state.reads:state.writes).push(path)
    const json=(value:unknown,status=200)=>route.fulfill({json:value,status}).catch(()=>{})
    if(path.endsWith('/auth/status'))return json({authenticated:true,setupRequired:false})
    if(path.endsWith('/auth/me'))return json(fixtureUser())
    if(path.endsWith('/auth/projects'))return json({contractVersion:'m33-v1',projects:state.projects})
    const project=state.projects.find(p=>path==='/aiyoloapi/projects/'+p.projectId);if(project)return json(project)
    if(path.endsWith('/alerts'))return json({events:state.events})
    if(path.includes('/evidence')){
      state.maxImages=Math.max(state.maxImages,++state.activeImages)
      try{if(state.imageGate)await state.imageGate;await route.fulfill({body:png,contentType:'image/png'}).catch(()=>{})}finally{state.activeImages--}
      return
    }
    if(path.endsWith('/advice-generations/latest'))return json({detail:{code:'ADVICE_GENERATION_NOT_FOUND'}},404)
    const event=state.events.find(e=>path.endsWith('/alerts/'+e.eventId));if(event)return json(event)
    if(path.endsWith('/streams'))return json([{stream_id:'gate',display_name:'隔离视频源',source_type:'rtsp',enabled:true,runtime_available:true,yolo_enabled:true,overlay_enabled:true,received_fps:5,processed_fps:5,model_id:'fixture',model:{modelId:'fixture',name:'测试模型'}}])
    if(path.endsWith('/scenes'))return json({scenes:[]})
    if(path.endsWith('/models'))return json({models:[]})
    if(path.endsWith('/preview')){
      state.previewTimes.push(Date.now());if(state.previewGate)await state.previewGate
      await route.fulfill(state.previewStatus===200?{body:state.invalidJpeg?Buffer.from('not-a-jpeg'):jpeg,contentType:'image/jpeg',headers:{'X-Preview-Mode':'yolo'}}:{status:state.previewStatus}).catch(()=>{});return
    }
    return json({detail:'isolated fixture unknown'},404)
  })
  await context.routeWebSocket('**/aiyoloapi/**',socket=>socket.onMessage(()=>{}))
  return state
}
const images=(s:Awaited<ReturnType<typeof service>>)=>s.reads.filter(p=>p.endsWith('/evidence'))
async function visibility(page:Page,hidden:boolean){await page.evaluate(hidden=>{Object.defineProperty(document,'visibilityState',{configurable:true,value:hidden?'hidden':'visible'});document.dispatchEvent(new Event('visibilitychange'))},hidden)}
async function record(state:Awaited<ReturnType<typeof service>>,scenario:string,extra:object={}){
  const evidence={scenario,environment:'real local Chromium and synthetic PNG/JPEG/API fixtures; not real camera or production benchmark',counts:Object.fromEntries([...new Set(state.reads)].map(p=>[p,state.reads.filter(v=>v===p).length])),maxImageHandlers:state.maxImages,cancelled:state.failed,writes:state.writes,...extra}
  console.log(JSON.stringify(evidence));await test.info().attach(scenario,{body:JSON.stringify(evidence),contentType:'application/json'})
}

test('visible evidence requests are lazy, at most three concurrent, and scroll loads new images',async({context,page})=>{
  await page.setViewportSize({width:1400,height:1000});const state=await service(context,page)
  let release!:()=>void;state.imageGate=new Promise(r=>{release=r})
  await page.goto('/admin-next/alerts?project='+fixtureProject.projectId)
  await expect(page.locator('.alert-event-row')).toHaveCount(10);await expect.poll(()=>images(state).length).toBe(3)
  await page.waitForTimeout(300);expect(images(state)).toHaveLength(3);expect(state.maxImages).toBe(3)
  state.imageGate=undefined;release();await expect(page.locator('.evidence-indicator img').first()).toBeVisible()
  await page.waitForTimeout(400);const initial=images(state).length;expect(initial).toBeLessThan(10)
  await page.locator('.alert-event-row').last().scrollIntoViewIfNeeded();await expect(page.locator('.alert-event-row').last().locator('img')).toBeVisible()
  expect(images(state).length).toBeGreaterThan(initial);expect(state.maxImages).toBeLessThanOrEqual(3)
  await record(state,'visible-evidence-concurrency',{initialImageReads:initial})
})

test('same-event thumbnail revision reloads and hidden tab releases image data',async({context,page})=>{
  const state=await service(context,page);state.events=state.events.slice(0,1)
  await page.goto('/admin-next/alerts?project='+fixtureProject.projectId);const img=page.locator('.evidence-indicator img')
  await expect(img).toBeVisible();const first=await img.getAttribute('src');expect(images(state)).toHaveLength(1)
  state.events[0]!.evidence.thumbnail.contentVersion=2;await page.getByRole('button',{name:'刷新告警',exact:true}).click()
  await expect.poll(()=>images(state).length).toBe(2);await expect(img).not.toHaveAttribute('src',first!)
  await visibility(page,true);await expect(img).toHaveCount(0);const before=images(state).length;await page.waitForTimeout(400);expect(images(state)).toHaveLength(before)
  await visibility(page,false);await expect(img).toBeVisible();expect(images(state)).toHaveLength(before+1)
  await record(state,'evidence-revision-and-tab-visibility')
})

test('leaving alerts cancels pending and queued images without late private thumbnails',async({context,page})=>{
  const state=await service(context,page);let release!:()=>void;state.imageGate=new Promise(r=>{release=r})
  await page.goto('/admin-next/alerts?project='+fixtureProject.projectId);await expect.poll(()=>images(state).length).toBe(3)
  await page.getByRole('link',{name:'项目空间',exact:true}).click();await expect(page.locator('.alert-event-row')).toHaveCount(0)
  await expect.poll(()=>state.failed.filter(p=>p.endsWith('/evidence')).length).toBe(3)
  state.imageGate=undefined;release();await page.waitForTimeout(250);expect(images(state)).toHaveLength(3);await expect(page.locator('.evidence-indicator img')).toHaveCount(0)
  await record(state,'navigation-cancels-evidence')
})

test('permission loss cancels evidence and removes decoded thumbnails and open detail',async({context,page})=>{
  const state=await service(context,page);state.events=state.events.slice(0,1)
  await page.goto('/admin-next/alerts?project='+fixtureProject.projectId);await expect(page.locator('.evidence-indicator img')).toBeVisible()
  let release!:()=>void;state.imageGate=new Promise(r=>{release=r});await page.locator('.alert-event-row').click();await expect.poll(()=>images(state).length).toBe(2)
  state.projects=[{...fixtureProject,membershipRevision:2}];await page.evaluate(()=>window.dispatchEvent(new Event('focus')))
  // A subsequent authoritative recheck may replace the transient revocation
  // notice with the project chooser. Verify the durable security outcome.
  await expect(page.getByRole('region',{name:'当前项目上下文'})).toContainText('尚未进入项目')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.locator('.alert-event-row')).toHaveCount(0)
  await expect.poll(()=>state.failed.filter(p=>p.endsWith('/evidence')).length).toBe(1);release();await expect(page.locator('.evidence-image')).toHaveCount(0)
  await record(state,'revocation-cancels-evidence-detail')
})

test('real ten-second preview stays bounded then clears and backs off on missing frames',async({context,page})=>{
  const state=await service(context,page);await page.goto('/admin-next/streams?project='+fixtureProject.projectId)
  const img=page.locator('.stream-preview img');await expect(img).toBeVisible();await expect.poll(()=>img.evaluate(el=>(el as HTMLImageElement).naturalWidth)).toBe(160)
  const start=state.previewTimes.length;await page.waitForTimeout(10_100);const good=state.previewTimes.length-start
  expect(good).toBeGreaterThanOrEqual(30);expect(good).toBeLessThanOrEqual(51)
  state.previewStatus=204;await expect(img).toHaveCount(0);await expect(page.locator('.preview-state')).toContainText('等待视频帧')
  const waiting=state.previewTimes.length;await page.waitForTimeout(10_100);const empty=state.previewTimes.length-waiting
  expect(empty).toBeLessThanOrEqual(4);expect(empty).toBeGreaterThanOrEqual(3)
  state.previewStatus=200;await expect(img).toBeVisible({timeout:7000});await expect(page.locator('.preview-state')).toContainText('实时预览')
  await record(state,'real-preview-10s',{validFrameReadDelta:good,emptyFrameReadDelta:empty})
})

test('preview cancels while hidden and resumes once, then stops on forbidden response',async({context,page})=>{
  const state=await service(context,page);await page.goto('/admin-next/streams?project='+fixtureProject.projectId);await expect(page.locator('.stream-preview img')).toBeVisible()
  let release!:()=>void;state.previewGate=new Promise(r=>{release=r});const before=state.previewTimes.length;await expect.poll(()=>state.previewTimes.length).toBeGreaterThan(before)
  await visibility(page,true);await expect(page.locator('.stream-preview img')).toHaveCount(0);await expect.poll(()=>state.failed.filter(p=>p.endsWith('/preview')).length).toBe(1)
  const paused=state.previewTimes.length;await page.waitForTimeout(500);expect(state.previewTimes).toHaveLength(paused)
  state.previewGate=undefined;release();await visibility(page,false);await expect(page.locator('.stream-preview img')).toBeVisible()
  state.previewStatus=403;await expect(page.locator('.preview-state')).toContainText('预览不可用');const denied=state.previewTimes.length
  await page.waitForTimeout(700);expect(state.previewTimes).toHaveLength(denied);await expect(page.locator('.stream-preview img')).toHaveCount(0)
  await record(state,'preview-hidden-and-permission-denial')
})

test('preview leaves the viewport without continuing frame requests',async({context,page})=>{
  await page.setViewportSize({width:390,height:844});const state=await service(context,page)
  await page.goto('/admin-next/streams?project='+fixtureProject.projectId);await page.locator('.stream-preview').scrollIntoViewIfNeeded();await expect(page.locator('.stream-preview img')).toBeVisible()
  await page.evaluate(()=>window.scrollTo(0,document.documentElement.scrollHeight));await expect(page.locator('.stream-preview img')).toHaveCount(0)
  const before=state.previewTimes.length;await page.waitForTimeout(500);expect(state.previewTimes).toHaveLength(before)
  await page.locator('.stream-preview').scrollIntoViewIfNeeded();await expect(page.locator('.stream-preview img')).toBeVisible()
  await record(state,'preview-viewport-pause')
})

test('detail shares the three-read budget and preserves capture overlays and original version selection',async({context,page})=>{
  const state=await service(context,page)
  const overlay={version:1,bakedIn:false,coordinateSpace:'normalized',capturedAtUs:123,detections:[{label:'安全帽',confidence:.91,box:{left:.1,top:.2,right:.6,bottom:.8}}]}
  Object.assign(state.events[0]!.evidence,{original:{'1':{contentVersion:1}},displayOverlay:overlay})
  let release!:()=>void;state.imageGate=new Promise(r=>{release=r})
  await page.goto('/admin-next/alerts?project='+fixtureProject.projectId);await expect.poll(()=>images(state).length).toBe(3)
  await page.locator('.alert-event-row').filter({hasText:'证据事件 0'}).click();await expect(page.getByRole('dialog')).toBeVisible()
  await page.waitForTimeout(250);expect(images(state)).toHaveLength(3);expect(state.maxImages).toBe(3)
  state.imageGate=undefined;release();const detail=page.getByRole('dialog');await expect(detail.locator('.evidence-image img')).toBeVisible()
  await expect(detail.locator('.evidence-box-label')).toHaveText('安全帽 91%')
  await detail.getByRole('button',{name:'查看原图',exact:true}).click();await expect.poll(()=>state.reads.filter(p=>p.endsWith('/evidence/original/1')).length).toBe(1)
  await expect(detail.locator('.evidence-image img')).toBeVisible();expect(state.maxImages).toBeLessThanOrEqual(3)
  await page.screenshot({path:test.info().outputPath('detail-desktop.png')})
  await page.setViewportSize({width:390,height:844});await detail.locator('.evidence-section').scrollIntoViewIfNeeded();await expect(detail.locator('.evidence-image img')).toBeVisible()
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
  await page.screenshot({path:test.info().outputPath('detail-narrow.png')})
  await record(state,'detail-budget-overlay-original')
})

test('failed and undecodable preview frames recover without manual reconnect or stale live labels',async({context,page})=>{
  const state=await service(context,page);state.previewStatus=503
  await page.goto('/admin-next/streams?project='+fixtureProject.projectId);await expect(page.locator('.preview-state')).toContainText('预览不可用')
  await page.waitForTimeout(3600);expect(state.previewTimes.length).toBeLessThanOrEqual(4)
  state.previewStatus=200;state.invalidJpeg=true;await expect(page.locator('.preview-placeholder')).toContainText('现场预览不可用')
  await page.waitForTimeout(5200);await expect(page.locator('.stream-preview img')).toHaveCount(0)
  state.invalidJpeg=false;await expect(page.locator('.stream-preview img')).toBeVisible({timeout:7000});await expect(page.locator('.preview-state')).toContainText('实时预览')
  await record(state,'transient-and-decode-recovery')
})

test('project switch cancels pending old preview and renders only the new project frame',async({context,page})=>{
  const state=await service(context,page);state.projects=['a','b'].map(id=>({...fixtureProject,projectId:id,projectCode:id,displayName:'项目 '+id}))
  let release!:()=>void;state.previewGate=new Promise(r=>{release=r})
  await page.goto('/admin-next/streams?project=a');await expect.poll(()=>state.previewTimes.length).toBe(1)
  state.previewGate=undefined
  await page.evaluate(()=>{history.pushState({},'', '/admin-next/streams?project=b');dispatchEvent(new PopStateEvent('popstate'))})
  await expect(page.locator('.stream-preview img')).toBeVisible();await expect(page.getByRole('region',{name:'当前项目上下文'})).toContainText('项目 b')
  const image=await page.locator('.stream-preview img').getAttribute('src');release();await expect(page.locator('.stream-preview img')).not.toHaveAttribute('src','')
  expect(state.reads.filter(p=>p.includes('/projects/a/')&&p.endsWith('/preview'))).toHaveLength(1)
  expect(state.failed.some(p=>p.includes('/projects/a/')&&p.endsWith('/preview'))).toBe(true);expect(image).toMatch(/^blob:/)
  await record(state,'preview-cross-project-cancel')
})
