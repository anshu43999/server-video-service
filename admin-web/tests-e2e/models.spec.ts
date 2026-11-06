import { adminPath, openElementSelect, selectElementOption, toggleElementSwitch } from './helpers/navigation'
import { fixtureUser, fixtureProjects } from './helpers/project-fixture'
import { expect, test, type BrowserContext, type Page } from '@playwright/test'

function assets() { return [
  {modelId:'helmet',name:'安全帽巡检',version:'2',availableVersions:['2','1'],scenario:'工地安全',purpose:'business',status:'PUBLISHED',serverBindable:true,serverReady:true,androidConverted:true,androidReady:false,signatureStatus:'unsigned',active:false,inputSize:640,labels:['head','helmet','person'],artifacts:[{artifactId:'server',format:'pt',platform:'server',sizeBytes:1024,sha256:'abc123',exists:true,hashValid:true}],license:{release:'待业务验收'}},
  {modelId:'retired',name:'已撤回模型',version:'1',scenario:'通用检测',status:'REVOKED',serverBindable:false,serverReady:false,signatureStatus:'unsigned',labels:['person'],artifacts:[{artifactId:'server',format:'pt',platform:'server',exists:false,hashValid:false}]},
  {modelId:'helmet',name:'安全帽巡检旧版',version:'1',availableVersions:['2','1'],scenario:'工地安全',status:'DEPRECATED',serverBindable:false,labels:['head'],artifacts:[]},
] }
const config = {mode:'local',distribution:'Ubuntu',python_path:'python',input_size:640,calibration_data:'',default_calibration_dataset_id:'coco8-dev',timeout_seconds:1800,auto_convert:false,remote_endpoint:'',remote_token_env:'AIYOLO_REMOTE_CONVERSION_TOKEN',remote_allow_insecure_http:false,remote_poll_interval_seconds:2,remote_verifier_mode:'local'}
const dataset = {datasetId:'coco8-dev',name:'COCO8 功能测试',version:'1',scenario:'development-only',imageCount:8,sizeBytes:2048,contentSha256:'frozen-hash-001',yamlPath:'coco8.yaml',builtin:true,deletable:false,status:'ready'}
const custom = {...dataset,datasetId:'site-01',name:'现场校准集',builtin:false,deletable:true,scenario:'工地安全'}
function profile(platform: string) { return {schemaVersion:2,modelId:'helmet',modelVersion:'2',platform,revision:7,source:'custom',detection:{confidenceThreshold:.35,iouThreshold:.45,maxDetections:100},alertRules:[{rawLabel:'head',displayName:'未戴安全帽',eventCode:'PPE_NO_HELMET',operator:'PRESENCE',enabled:true,severity:'MAJOR',image:{minimumConfidence:.55,cooldownMs:60000},camera:{minimumConfidence:.55,minimumConsecutiveFrames:4,minimumDwellTimeMs:800,cooldownMs:60000}}],audit:[{action:'UPDATED',revision:7,actor:'admin',at:'2026-10-09T01:00:00Z'}]} }
function jobs() { return [
  {id:'inspected',action:'inspect',status:'succeeded',attempt:1,created_at:1700000000,started_at:1700000001,completed_at:1700000010,metadata:{name:'安全帽巡检',upload_id:'upload-01',model_id:'helmet'},result:{server_ready:true}},
  {id:'running',action:'mobile',status:'running',attempt:2,created_at:1700000020,started_at:1700000025,metadata:{name:'现场模型',upload_id:'upload-02',calibration_dataset:dataset},stage_label:'正在复验产物',progress:null,progress_message:'等待转换器输出'},
  {id:'failed',action:'mobile',status:'interrupted',attempt:1,created_at:1700000050,metadata:{upload_id:'upload-03'},error:'远程服务连接中断'},
] }
type Options = {uploadStatus?:number;deleteStatus?:number;parameterConflict?:boolean;role?:string;empty?:boolean;offline?:boolean;limit?:number;developmentModel?:boolean}
async function service(context: BrowserContext, options: Options = {}) {
  const writes: {method:string;path:string;query:URLSearchParams;body:any;bytes:Buffer | null}[]=[]
  const state={models:options.empty ? [] : [...assets(),...(options.developmentModel?[{modelId:'dev-helmet',name:'开发安全帽',version:'0.3.0',scenario:'工地安全',purpose:'development',status:'READY',serverReady:true,serverBindable:false,androidReady:false,labels:['helmet'],artifacts:[]}]:[])],datasets:[dataset,custom],jobs:options.empty ? [] : jobs(),jobReads:0}
  await context.route('**/aiyoloapi/**',async route => {
    const request=route.request(),url=new URL(request.url()),path=url.pathname,method=request.method()
    const respond=(value:unknown,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(value)})
    if(path.endsWith('/auth/status'))return respond({authenticated:true,setupRequired:false,user:{username:'test-admin',role:options.role || 'admin'}})
    if(path.endsWith('/auth/me'))return respond(fixtureUser(options.role))
    if(path.endsWith('/auth/projects'))return respond(fixtureProjects(options.role))
    if(path.endsWith('/alerts'))return respond({events:[]})
    if(path.endsWith('/streams') && method==='GET')return respond([{stream_id:'gate-01',display_name:'工地北门',model_id:'helmet'}])
    if(method!=='GET') {
      let body:any;try{body=request.postDataJSON()}catch{body=request.postData()}
      writes.push({method,path,query:url.searchParams,body,bytes:request.postDataBuffer()})
    }
    if(path.endsWith('/models') && method==='GET')return options.offline ? respond({detail:'仓储不可用'},503) : respond({models:state.models})
    if(path.endsWith('/models/register'))return respond({models:[]})
    if(path.endsWith('/streams/gate-01/model'))return respond({model:{modelId:'helmet'}})
    const parameter=path.match(/\/models\/([^/]+)\/parameters$/)
    if(parameter) {
      if(method==='PUT' && options.parameterConflict)return respond({detail:{code:'revision_conflict',message:'档案修订冲突，请重新读取'}},409)
      return respond({...profile(url.searchParams.get('platform') || 'android'),revision:method==='PUT' ? 8 : method==='DELETE' ? 9 : 7})
    }
    if(path.endsWith('/activate')) { state.models[0]!.active=true;return respond(state.models[0]) }
    if(path.endsWith('/publish'))return respond(state.models[0])
    const version=path.match(/\/models\/([^/]+)\/versions\/([^/]+)$/)
    if(version) {
      if(method==='DELETE') { if(options.deleteStatus)return respond({detail:'该模型被视频流引用'},options.deleteStatus);state.models=state.models.filter(m=>!(m.modelId===version[1] && m.version===version[2]));return respond({deleted:true}) }
      return respond(state.models.find(m=>m.modelId===version[1] && m.version===version[2]))
    }
    if(path.includes('/artifacts/'))return route.fulfill({contentType:'application/octet-stream',body:Buffer.from('artifact')})
    if(path.endsWith('/conversion/config'))return respond({config:method==='PUT' ? request.postDataJSON() : config,max_upload_bytes:options.limit ?? 1048576,max_calibration_upload_bytes:1048576,supported_modes:['local','wsl','remote']})
    if(path.endsWith('/conversion/calibration-datasets')) {
      if(method==='POST')return options.uploadStatus ? respond({detail:'校准ZIP校验失败'},options.uploadStatus) : respond(custom,201)
      return respond({datasets:state.datasets,max_upload_bytes:1048576})
    }
    if(path.includes('/calibration-datasets/')) {
      if(method==='DELETE') { if(options.deleteStatus)return respond({detail:'校准集已被转换任务引用'},options.deleteStatus);state.datasets=state.datasets.filter(d=>d.datasetId!==path.split('/').at(-1));return respond({deleted:true}) }
      return respond(custom)
    }
    if(path.endsWith('/conversion/jobs')) {state.jobReads++;return respond({jobs:state.jobs})}
    if(path.endsWith('/log'))return route.fulfill({contentType:'text/plain',body:'worker log\nBearer private-token\nremote_token=topsecret\n'+'x'.repeat(800)})
    if(path.endsWith('/retry') || path.endsWith('/mobile') || path.endsWith('/conversion/check'))return respond({id:'new-job',status:'queued'},202)
    if(path.endsWith('/conversion/uploads'))return options.uploadStatus ? respond({detail:'无效PT，上传失败'},options.uploadStatus) : respond({upload_id:'new-upload',model_id:'helmet',job:{id:'queued'}},202)
    return respond({detail:'not found'},404)
  })
  return {writes,state}
}
async function uploadFile(page:Page,name='inspection.pt') {
  await page.getByLabel('训练权重 .pt').setInputFiles({name,mimeType:'application/octet-stream',buffer:Buffer.from('trained-pt-bytes')})
}
async function noOverflow(page:Page) {expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)}

test('model directory uses backend readiness, version details, downloads and guarded uninstall',async({context,page})=>{
  const {writes}=await service(context,{deleteStatus:409});const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message))
  await page.goto(adminPath('/models'))
  await expect(page.locator('.model-card')).toHaveCount(3)
  await expect(page.getByText('此处维护全局模型资产，不读取任何项目的视频流。', { exact: false })).toBeVisible()
  await expect(page.getByRole('combobox', { name: 'gate-01 绑定模型' })).toHaveCount(0)
  const retired=page.locator('.model-card').filter({hasText:'已撤回模型'})
  await expect(retired.getByRole('button',{name:'设为新流默认'})).toBeDisabled()
  const current=page.locator('.model-card').filter({hasText:'helmet / 2'})
  await current.getByRole('button',{name:'设为新流默认'}).click()
  await expect(page.getByText('已设置新流默认模型，已有视频流绑定保持不变。')).toBeVisible()
  await current.getByRole('button',{name:'版本详情'}).click()
  await expect(page.getByRole('dialog')).toContainText('原始类别：head · helmet · person')
  const download=page.waitForEvent('download');await page.getByRole('button',{name:'下载产物'}).click();expect((await download).suggestedFilename()).toBe('helmet-2-server.pt')
  await selectElementOption(page, '查看版本', '1');await expect(page.getByRole('dialog')).toContainText('DEPRECATED')
  await page.keyboard.press('Escape');await expect(page.getByRole('dialog')).toHaveCount(0)
  await current.getByRole('button',{name:'卸载',exact:true}).click();await page.getByRole('button',{name:'取消',exact:true}).click();expect(writes.filter(w=>w.method==='DELETE')).toHaveLength(0)
  await current.getByRole('button',{name:'卸载',exact:true}).click();await page.getByRole('button',{name:'确认卸载'}).click()
  await expect(page.getByText('该模型被视频流引用')).toBeVisible();await expect(page.locator('.model-card')).toHaveCount(3)
  await noOverflow(page);await page.screenshot({path:'../evidence/M32/M32-T07-models-desktop.png',fullPage:true});expect(errors).toEqual([])
})
test('parameter revision conflicts retain edits and reset requires confirmation',async({context,page})=>{
  const {writes}=await service(context,{parameterConflict:true});await page.goto(adminPath('/models'))
  await page.locator('.model-card').first().getByRole('button',{name:'参数档案'}).click()
  await expect(page.getByRole('dialog')).toContainText('修订 7')
  await page.getByLabel('识别置信度', {exact:true}).fill('0.4')
  await page.getByRole('button',{name:'全部展开'}).click()
  await page.getByLabel('最少连续帧').fill('6')
  await page.getByRole('button',{name:'保存参数'}).click();await expect(page.getByRole('dialog')).toContainText('档案修订冲突')
  expect(writes.find(w=>w.method==='PUT')?.body.expectedRevision).toBe(7)
  await expect(page.getByLabel('最少连续帧')).toHaveValue('6')
  await page.getByRole('tab',{name:'服务端参数'}).click();await expect(page.getByRole('dialog')).toContainText('修订 7')
  await page.getByRole('button',{name:'恢复默认',exact:true}).click();await page.getByRole('button',{name:'取消恢复'}).click()
  expect(writes.filter(w=>w.method==='DELETE')).toHaveLength(0)
  await page.getByRole('button',{name:'恢复默认',exact:true}).click();await page.getByRole('button',{name:'确认恢复'}).click()
  await expect(page.getByRole('dialog')).toContainText('修订 9');expect(writes.find(w=>w.method==='DELETE')?.query.get('platform')).toBe('server')
})
test('successful raw PT upload clears file and name while keeping metadata',async({context,page})=>{
  const {writes}=await service(context);await page.goto(adminPath('/models?pane=upload'))
  await uploadFile(page);await expect(page.locator('.selected-file')).toContainText('inspection.pt')
  await page.getByLabel('模型版本', {exact:true}).fill('3.1')
  await page.getByLabel('新模型 ID（留空自动生成）').fill('new-family')
  await page.getByRole('button',{name:'上传并验证 PT'}).click()
  await expect(page.getByText('上传完成，PT 验证已排队。验证成功后才会登记模型。')).toBeVisible()
  await expect(page.getByLabel('模型名称',{exact:true})).toHaveValue('');await expect(page.getByLabel('模型版本',{exact:true})).toHaveValue('3.1')
  expect(await page.getByLabel('训练权重 .pt').evaluate((input:HTMLInputElement)=>input.files?.length)).toBe(0)
  const upload=writes.find(w=>w.path.endsWith('/conversion/uploads'))!
  expect(upload.query.get('modelId')).toBe('new-family');expect(upload.query.get('name')).toBe('inspection');expect(upload.bytes?.toString()).toBe('trained-pt-bytes')
})
test('target capabilities publish independently and dual upload preserves repeated targets',async({context,page})=>{
  const {writes}=await service(context);await page.goto(adminPath('/models'))
  const current=page.locator('.model-card').filter({hasText:'helmet / 2'})
  await expect(current.getByText('PC 端模型',{exact:true})).toBeVisible()
  await expect(current).toContainText('移动端不支持')
  await expect(current).toContainText('移动签名不适用')
  await current.getByRole('button',{name:'按端发布'}).click()
  await expect(page.getByRole('switch',{name:'发布 PC 端'})).toBeChecked()
  await expect(page.getByRole('switch',{name:'发布移动端'})).toBeDisabled()
  await page.getByLabel('发布原因').fill('PC 端产物已通过业务验收')
  await toggleElementSwitch(page,'确认来源及分发许可证已审核')
  await page.getByRole('button',{name:'确认发布'}).click()
  await expect(page.getByText('所选目标端已通过发布门禁。')).toBeVisible()
  expect(writes.find(w=>w.path.endsWith('/publish'))?.body).toEqual({targets:['pc'],licenseApproved:true,reason:'PC 端产物已通过业务验收'})

  await page.getByRole('tab',{name:'上传与处理'}).click()
  await selectElementOption(page,'支持目标端','PC / 移动双端')
  await uploadFile(page,'dual.pt');await page.getByRole('button',{name:'上传并验证 PT'}).click()
  await expect(page.getByText('上传完成，PT 验证已排队。验证成功后才会登记模型。')).toBeVisible()
  const upload=writes.filter(w=>w.path.endsWith('/conversion/uploads')).at(-1)!
  expect(upload.query.getAll('supportedTargets')).toEqual(['pc','mobile'])
})
test('development model action routes through project selection to project test authorization',async({context,page})=>{
  await service(context,{developmentModel:true});await page.goto(adminPath('/models'))
  const dev=page.locator('.model-card').filter({hasText:'dev-helmet / 0.3.0'})
  await expect(dev.getByRole('button',{name:'进入项目测试授权'})).toBeVisible()
  await dev.getByRole('button',{name:'进入项目测试授权'}).click()
  await expect(page).toHaveURL(/\/admin-next\/projects\?redirect=/)
  await expect(page.getByRole('heading',{name:'选择项目空间'})).toBeVisible()
})
test('failed upload retains selection and metadata; oversize stops before sending',async({context,page})=>{
  const {writes}=await service(context,{uploadStatus:422,limit:100});await page.goto(adminPath('/models?pane=upload'))
  await uploadFile(page);await page.getByRole('button',{name:'上传并验证 PT'}).click();await expect(page.getByText('无效PT，上传失败')).toBeVisible()
  await expect(page.getByLabel('模型名称',{exact:true})).toHaveValue('inspection');await expect(page.locator('.selected-file')).toContainText('inspection.pt')
  await page.getByLabel('训练权重 .pt').setInputFiles({name:'large.pt',mimeType:'application/octet-stream',buffer:Buffer.alloc(200)})
  await page.getByRole('button',{name:'上传并验证 PT'}).click();await expect(page.getByText('请选择有效 .pt 文件，大小必须在服务端上传限制内。')).toBeVisible()
  expect(writes.filter(w=>w.path.endsWith('/conversion/uploads'))).toHaveLength(1)
})
test('remote config, retry, frozen calibration, unknown progress and redacted logs',async({context,page})=>{
  const {writes}=await service(context);await page.goto(adminPath('/models?pane=upload'))
  await page.getByText('转换环境配置 · local', {exact:true}).click();await selectElementOption(page, '执行模式', '远程服务')
  await page.getByLabel('远程服务地址').fill('https://converter.example/v1');await page.getByRole('button',{name:'保存转换配置'}).click()
  await expect(page.getByText('配置已保存。新任务使用此配置，执行中的任务保持原配置。')).toBeVisible()
  expect(writes.find(w=>w.path.endsWith('/conversion/config'))?.body.remote_token_env).toBe('AIYOLO_REMOTE_CONVERSION_TOKEN')
  const running=page.locator('.conversion-job').filter({hasText:'running'})
  await expect(running.getByRole('progressbar')).not.toHaveAttribute('aria-valuenow');await expect(running).toContainText('处理中')
  await selectElementOption(page, '本次移动端转换校准集', '现场校准集 / 1')
  await page.getByRole('button',{name:'生成移动端模型'}).click();await expect(page.getByText('移动端转换已排队，校准集版本与哈希已冻结。')).toBeVisible()
  expect(writes.find(w=>w.path.endsWith('/upload-01/mobile'))?.query.get('calibrationDatasetId')).toBe('site-01')
  await page.getByRole('button',{name:'按当前配置重试'}).click();await expect(page.getByText('任务已按当前配置重新排队。')).toBeVisible()
  await page.locator('.conversion-job').first().getByRole('button',{name:'查看日志'}).click()
  await expect(page.getByRole('dialog')).toContainText('[REDACTED]');await expect(page.getByRole('dialog')).not.toContainText('private-token');await expect(page.getByRole('dialog')).not.toContainText('topsecret')
  const download=page.waitForEvent('download');await page.getByRole('button',{name:'下载日志'}).click();expect((await download).suggestedFilename()).toBe('conversion-inspected.txt')
})
test('calibration workflow protects builtin and referenced versions, keeps failed ZIP',async({context,page})=>{
  const {writes}=await service(context,{deleteStatus:409,uploadStatus:422});await page.goto(adminPath('/models?pane=calibration'))
  await expect(page.locator('.dataset-row')).toHaveCount(2)
  await expect(page.locator('.dataset-row').first().getByRole('button',{name:'删除校准集'})).toBeDisabled()
  await page.locator('.dataset-row').last().getByRole('button',{name:'详情',exact:true}).click();await expect(page.getByRole('dialog')).toContainText('frozen-hash-001');await page.keyboard.press('Escape')
  await page.locator('.dataset-row').last().getByRole('button',{name:'删除校准集'}).click();await page.getByRole('button',{name:'确认删除'}).click();await expect(page.getByText('校准集已被转换任务引用')).toBeVisible()
  await expect(page.locator('.dataset-row')).toHaveCount(2)
  await page.getByLabel('校准集名称').fill('新现场');await page.getByLabel('校准图片 ZIP').setInputFiles({name:'site.zip',mimeType:'application/zip',buffer:Buffer.from('invalid-zip')})
  await page.getByRole('button',{name:'上传并校验校准集'}).click();await expect(page.getByText('校准ZIP校验失败')).toBeVisible();await expect(page.locator('.selected-file')).toContainText('site.zip')
  expect(writes.find(w=>w.path.endsWith('/calibration-datasets'))?.bytes?.toString()).toBe('invalid-zip')
})
test('narrow layout supports direct tabs and stops job polling after navigation',async({context,page})=>{
  const {state}=await service(context);await page.setViewportSize({width:390,height:844});await page.goto(adminPath('/models?pane=upload'))
  await expect(page.locator('.conversion-job')).toHaveCount(3);await noOverflow(page)
  await page.screenshot({path:'../evidence/M32/M32-T07-upload-mobile.png',fullPage:true})
  await page.getByRole('tab',{name:'校准集',exact:true}).click();await expect(page).toHaveURL(/pane=calibration/)
  await expect(page.locator('.dataset-row')).toHaveCount(2);const reads=state.jobReads
  await page.waitForTimeout(3400);expect(state.jobReads).toBe(reads);await noOverflow(page)
  await page.screenshot({path:'../evidence/M32/M32-T07-calibration-mobile.png',fullPage:true})
  await page.reload();await expect(page.locator('.dataset-row')).toHaveCount(2)
})
test('empty and unavailable directories never invent model assets; operator is restricted',async({context,page})=>{
  await service(context,{empty:true});await page.goto(adminPath('/models'));await expect(page.getByText('暂无匹配的模型')).toBeVisible()
  await context.unroute('**/aiyoloapi/**');await service(context,{offline:true});await page.reload();await expect(page.getByText('仓储不可用')).toBeVisible();await expect(page.locator('.model-card')).toHaveCount(0)
  await context.unroute('**/aiyoloapi/**');const {writes}=await service(context,{role:'operator'});await page.reload();await expect(page).toHaveURL(/projects/);expect(writes).toEqual([])
})
test('manifest registration validates a controlled path; successful ZIP clears its selection',async({context,page})=>{
  const {writes}=await service(context);await page.goto(adminPath('/models'))
  await page.getByRole('button',{name:'登记 Manifest',exact:true}).click()
  await page.getByLabel('Manifest 路径').fill('models/imported/manifest.json')
  await page.getByRole('button',{name:'校验并登记'}).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect(writes.find(w=>w.path.endsWith('/models/register'))?.body).toEqual({manifest_path:'models/imported/manifest.json'})
  await page.getByRole('tab',{name:'校准集',exact:true}).click()
  await page.getByLabel('校准集名称').fill('现场图片')
  await page.getByLabel('校准图片 ZIP').setInputFiles({name:'site.zip',mimeType:'application/zip',buffer:Buffer.from('zip-content')})
  await page.getByRole('button',{name:'上传并校验校准集'}).click()
  await expect(page.getByText('校准集已上传并校验。')).toBeVisible();await expect(page.getByLabel('校准集名称')).toHaveValue('')
  expect(await page.getByLabel('校准图片 ZIP').evaluate((input:HTMLInputElement)=>input.files?.length)).toBe(0)
  await page.locator('.dataset-row').last().getByRole('button',{name:'删除校准集'}).click();await page.getByRole('button',{name:'取消',exact:true}).click()
  expect(writes.filter(w=>w.method==='DELETE')).toHaveLength(0)
})
test('navigation aborts active uploads and discards stale parameter responses',async({context,page})=>{
  await service(context);await page.goto(adminPath('/models?pane=upload'))
  await page.evaluate(()=>{
    const NativeXhr=window.XMLHttpRequest
    const state={aborted:0};(window as any).__upload=state
    ;(window as any).XMLHttpRequest=class extends NativeXhr {
      override send(_body?: Document | XMLHttpRequestBodyInit | null) { /* Keep transfer pending to observe page lifecycle. */ }
      override abort() {state.aborted++;this.dispatchEvent(new ProgressEvent('abort'))}
    }
  })
  await uploadFile(page);await page.getByRole('button',{name:'上传并验证 PT'}).click()
  await expect(page.getByRole('button',{name:'中止上传'})).toBeVisible()
  await page.getByRole('tab',{name:'模型目录',exact:true}).click()
  expect(await page.evaluate(()=>(window as any).__upload.aborted)).toBe(1)
  let release: ()=>void=()=>{}
  const wait=new Promise<void>(resolve=>{release=resolve})
  await context.route('**/models/helmet/parameters?platform=android',async route=>{await wait;try{await route.fulfill({contentType:'application/json',body:JSON.stringify({...profile('android'),revision:100})})}catch{/* Component cancellation has already closed the route. */}})
  await page.locator('.model-card').first().getByRole('button',{name:'参数档案'}).click()
  await page.getByRole('tab',{name:'服务端参数'}).click();await expect(page.getByRole('dialog')).toContainText('修订 7')
  release();await page.waitForTimeout(200);await expect(page.getByRole('dialog')).not.toContainText('修订 100')
})
