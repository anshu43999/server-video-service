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
test('rules persist complete fields and validate actual capabilities before binding',async({context,page})=>{
  const {writes}=await service(context);await page.goto(adminPath('/rules'));await expect(page.locator('.model-card')).toHaveCount(1)
  await page.getByRole('button',{name:'编辑规则'}).click();await page.getByLabel('规则名称').fill('入口安全帽告警')
  await page.getByLabel('阈值 JSON',{exact:true}).fill('{"minimumConfidence":0.6}')
  await page.getByRole('button',{name:'保存规则',exact:true}).click();await expect(page.getByRole('dialog')).toHaveCount(0)
  expect(writes.find(w=>w.method==='PUT')?.body.thresholds).toEqual({minimumConfidence:.6})
  await page.getByRole('button',{name:'校验与绑定'}).click();await selectElementOption(page, '实际来源', 'gate / helmet')
  await expect(page.getByRole('button',{name:'保存绑定'})).toBeDisabled()
  await page.getByRole('button',{name:'校验能力'}).click();await expect(page.getByRole('dialog')).toContainText('能力满足，可提交绑定')
  await page.getByRole('button',{name:'保存绑定'}).click();await expect(page.getByRole('dialog')).toContainText('gate · 已接受')
  expect(writes.find(w=>w.path.endsWith('/bindings'))?.body).toEqual({sourceId:'gate',modelId:'helmet',capabilities:['BOX','TRACK'],expectedRevision:3})
  await page.keyboard.press('Escape');await page.getByRole('button',{name:'删除规则',exact:true}).click();await page.getByRole('button',{name:'取消',exact:true}).click()
  expect(writes.filter(w=>w.method==='DELETE')).toHaveLength(0)
  await page.screenshot({path:'../evidence/M32/M32-T08-rules-desktop.png',fullPage:true})
})
test('rule version conflict and rejected capability retain truthful state',async({context,page})=>{
  const {writes}=await service(context,{conflict:true,reject:true});await page.goto(adminPath('/rules'))
  await page.getByRole('button',{name:'编辑规则'}).click();await page.getByLabel('规则名称').fill('未保存名称');await page.getByRole('button',{name:'保存规则',exact:true}).click()
  await expect(page.getByRole('dialog')).toContainText('规则版本已变化');await expect(page.getByLabel('规则名称')).toHaveValue('未保存名称');expect(writes.filter(w=>w.method==='PUT')).toHaveLength(1)
  await page.keyboard.press('Escape');await page.getByRole('button',{name:'刷新规则'}).click();await page.getByRole('button',{name:'校验与绑定'}).click();await selectElementOption(page, '实际来源', 'gate / helmet');await page.getByRole('button',{name:'校验能力'}).click()
  await expect(page.getByRole('dialog')).toContainText('算子尚未实现');await expect(page.getByRole('button',{name:'保存绑定'})).toBeDisabled()
})

test('binding refresh failure locks further mutations until reconciled',async({context,page})=>{
  await service(context)
  let reads=0
  const errors:string[]=[]
  page.on('pageerror',error=>errors.push(error.message))
  await context.route('**/rules/helmet-rule/bindings',async route=>{
    if(route.request().method()==='GET' && ++reads===2)return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'绑定读取失败'})})
    return route.fallback()
  })
  await page.goto(adminPath('/rules'));await page.getByRole('button',{name:'校验与绑定'}).click()
  await selectElementOption(page,'实际来源','gate / helmet');await page.getByRole('button',{name:'校验能力'}).click()
  await page.getByRole('button',{name:'保存绑定'}).click()
  await expect(page.getByRole('dialog')).toContainText('绑定读取失败')
  await expect(page.getByRole('button',{name:'保存绑定'})).toBeDisabled()
  await page.keyboard.press('Escape');await page.getByRole('button',{name:'刷新规则'}).click()
  await page.getByRole('button',{name:'校验与绑定'}).click()
  await expect(page.getByRole('button',{name:'解除绑定'})).toBeEnabled()
  expect(errors).toEqual([])
})
test('rule creation validates JSON and cancels without creating rules',async({context,page})=>{
  const {writes}=await service(context);await page.goto(adminPath('/rules'));await page.getByRole('button',{name:'新增规则'}).click()
  await page.getByLabel('规则 ID',{exact:true}).fill('new-rule');await page.getByLabel('规则名称').fill('新规则');await page.getByLabel('阈值 JSON',{exact:true}).fill('[]')
  await page.getByRole('button',{name:'保存规则',exact:true}).click();await expect(page.getByRole('dialog')).toContainText('JSON 类型不正确');expect(writes).toEqual([])
  await page.getByLabel('阈值 JSON',{exact:true}).fill('{"minimumConfidence":0.5}');await page.getByRole('button',{name:'保存规则',exact:true}).click()
  await expect(page.getByRole('dialog')).toHaveCount(0);expect(writes[0]?.body.ruleId).toBe('new-rule')
})
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
  await page.goto(adminPath('/rules'));await page.getByRole('button',{name:'编辑规则'}).click();await expect(page.getByLabel('规则名称')).toBeVisible();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
  await context.unroute('**/aiyoloapi/**');const {writes}=await service(context,{role:'operator'});await page.goto(adminPath('/push'));await expect(page).toHaveURL(/projects/);expect(writes).toEqual([])
})
