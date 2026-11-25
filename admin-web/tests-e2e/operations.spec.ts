import { adminPath, selectElementOption, toggleElementSwitch } from './helpers/navigation'
import { fixtureUser, fixtureProjects, fixtureProject, unscopedPath } from './helpers/project-fixture'
import {expect,test,type BrowserContext} from '@playwright/test'
const initialRule={ruleId:'helmet-rule',name:'未戴安全帽告警',ruleVersion:2,enabled:true,operator:'PRESENCE',subjectKind:'track',requires:['BOX'],targetLabels:['head'],thresholds:{minimumConfidence:.55},severityBands:[]}
async function service(context:BrowserContext,options:{conflict?:boolean;reject?:boolean;healthFailure?:boolean;verificationFailure?:boolean;role?:string}={}){
  const writes:{path:string;method:string;body:any}[]=[]
  const state={rule:{...initialRule},bindings:[] as any[],verification:{revision:0,enabled:false,imageEgressAuthorized:false,dailyLimit:100,callsToday:4,modelId:'review-v1',providerConfigured:true},deliveryReads:0,receipts:[] as any[]}
  await context.route('**/aiyoloapi/**',async route=>{
    const req=route.request(),path=unscopedPath(new URL(req.url()).pathname),method=req.method()
    const reply=(body:unknown,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)})
    if(path.endsWith('/auth/status'))return reply({authenticated:true,setupRequired:false,user:{username:'test-admin',role:options.role||'admin'}})
    if(path.endsWith('/auth/me'))return reply(fixtureUser(options.role))
    if(path.endsWith('/auth/projects'))return reply(fixtureProjects(options.role))
    if(path==='/aiyoloapi')return reply(fixtureProject)
    if(path.endsWith('/streams'))return reply([])
    if(path.endsWith('/alerts'))return reply({events:[]})
    const body=method==='GET'||method==='DELETE'?null:req.postDataJSON()
    if(method!=='GET')writes.push({path,method,body})
    if(path.endsWith('/capabilities/sources'))return reply({sources:[{sourceId:'gate',modelId:'helmet',capabilities:['BOX','TRACK']}]})
    if(path.endsWith('/rules/audit'))return reply({audit:[{action:'create',ruleId:'helmet-rule',ruleVersion:1,actor:'admin',timestamp:'2026-10-09T01:00:00Z'}]})
    if(path.endsWith('/rules')){if(method==='POST'){state.rule={...body,ruleVersion:1};return reply(state.rule,201)}return reply({rules:[state.rule]})}
    if(path.endsWith('/rules/helmet-rule')){if(method==='PUT'){if(options.conflict)return reply({detail:'规则版本已变化'},409);state.rule={...body,ruleVersion:3};return reply(state.rule)}if(method==='DELETE')return route.fulfill({status:204});return reply({...state.rule,ruleVersion:options.conflict?3:state.rule.ruleVersion})}
    if(path.endsWith('/validate'))return reply(options.reject?{accepted:false,code:'OPERATOR_NOT_IMPLEMENTED',message:'算子尚未实现'}:{accepted:true,...body,ruleId:'helmet-rule',ruleVersion:2})
    if(path.endsWith('/bindings')){if(method==='POST'){state.bindings=[{accepted:true,...body,ruleId:'helmet-rule',ruleVersion:2}];return reply(state.bindings[0])}return reply({bindings:state.bindings})}
    if(path.endsWith('/verification/config')){if(method==='POST'){if(options.verificationFailure)return reply({detail:'配置保存失败'},503);state.verification={...body,callsToday:4}}return reply(state.verification)}
    if(path.endsWith('/delivery/policy'))return reply({revision:0,enabled:true,channels:['management','email'],minimumSeverity:'MINOR'})
    if(path.endsWith('/alerts/delivery/status')){state.deliveryReads++;return reply({channels:{management:{enabled:true,subscribers:2},email:{enabled:true,subscribers:0}},pending:0,recent:state.receipts})}
    if(path.endsWith('/alerts/test-delivery')){state.receipts=[{delivery_id:'test-id',channel:'management',status:'delivered',attempts:1,error_code:null}];return reply({accepted:true,deliveryIds:['test-id']},202)}
    if(path.endsWith('/metrics'))return reply({system:{cpu_percent:0,memory_percent:20,disk_percent:30,gpu:null},scope:'platform',streams:{total:1,framesReceived:100,framesProcessed:50,framesDropped:50}})
    return reply({detail:'missing'},404)
  })
  await context.route('**/healthz',route=>route.fulfill({status:options.healthFailure?503:200,contentType:'application/json',body:JSON.stringify({status:options.healthFailure?'degraded':'ok',streams:1,database:{configured:false,status:'fallback'}})}))
  return {writes,state}
}
test('verification restores persisted config and requires consent for image egress',async({context,page})=>{
  const {writes}=await service(context);await page.goto(adminPath('/verification'))
  await expect(page.getByLabel('复核模型 ID')).toHaveValue('review-v1')
  await toggleElementSwitch(page, '允许证据图片发送至复核服务');await toggleElementSwitch(page, '启用智能复核');await page.getByLabel('每日调用限额').fill('50')
  await page.getByRole('button',{name:'保存复核配置'}).click();await expect(page.getByRole('alertdialog')).toBeVisible()
  await page.getByRole('button',{name:'取消',exact:true}).click();expect(writes).toEqual([])
  await page.getByRole('button',{name:'保存复核配置'}).click();await page.getByRole('button',{name:'授权并保存'}).click()
  await expect(page.getByText('复核配置已保存。实际复核结果请在告警详情查看。')).toBeVisible()
  expect(writes[0]?.body).toEqual({enabled:true,imageEgressAuthorized:true,dailyLimit:50,modelId:'review-v1',expectedRevision:0})
  await expect(page.locator('input[type=password]')).toHaveCount(0)
})
test('failed verification writes preserve form and never announce saved',async({context,page})=>{
  await service(context,{verificationFailure:true});await page.goto(adminPath('/verification'));await page.getByLabel('每日调用限额').fill('23');await page.getByRole('button',{name:'保存复核配置'}).click()
  await expect(page.getByText('配置保存失败',{exact:false})).toBeVisible();await expect(page.getByLabel('每日调用限额')).toHaveValue('23');await expect(page.getByText('复核配置已保存。实际复核结果请在告警详情查看。')).toHaveCount(0)
})
test('push distinguishes enqueue from receipts and releases polling',async({context,page})=>{
  const {writes,state}=await service(context);await page.goto(adminPath('/push'));await page.getByRole('button',{name:'测试 管理后台'}).click();await page.getByRole('button',{name:'取消',exact:true}).click();expect(writes).toEqual([])
  await page.getByRole('button',{name:'测试 管理后台'}).click();await page.getByRole('button',{name:'确认发送测试'}).click()
  await expect(page.getByRole('status')).toContainText('最终状态以回执为准');await expect(page.getByText('管理后台 · delivered')).toBeVisible()
  expect(writes[0]?.body.channels).toEqual(['management']);expect(writes[0]?.body.event.test).toBe(true)
  await page.getByRole('link',{name:'规则配置',exact:true}).click();const reads=state.deliveryReads;await page.waitForTimeout(5200);expect(state.deliveryReads).toBe(reads)
})
test('diagnostics treats failed health as unavailable and preserves missing GPU semantics',async({context,page})=>{
  await service(context,{healthFailure:true});await page.goto(adminPath('/diagnostics'))
  await expect(page.getByText('健康状态不可用')).toBeVisible();await expect(page.locator('.model-readiness').first()).toContainText('0.0%');await expect(page.locator('.model-readiness').first()).toContainText('不可用')
  await expect(page.getByText('健康检查通过',{exact:true})).toHaveCount(0)
})
test('narrow operations remain readable and operator cannot enter configuration',async({context,page})=>{
  await service(context);await page.setViewportSize({width:390,height:844});await page.goto(adminPath('/verification'));await expect(page.getByLabel('复核模型 ID')).toBeVisible()
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
  await page.screenshot({path:'../evidence/M32/M32-T08-verification-mobile.png',fullPage:true})
  await context.unroute('**/aiyoloapi/**');const {writes}=await service(context,{role:'operator'});await page.goto(adminPath('/push'));await expect(page).toHaveURL(/projects/);expect(writes).toEqual([])
})
