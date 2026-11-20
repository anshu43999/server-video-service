// @vitest-environment happy-dom
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { installUiComponents } from '../src/components/ui/plugin'
import { ApiError } from '../src/api/errors'
import { projectScope } from '../src/api/projectScope'
import ProjectModelsView from '../src/features/models/ProjectModelsView.vue'
import { projectModelsApi, type Assignment, type AssignmentWrite } from '../src/features/models/projectApi'
import { useProjectsStore } from '../src/stores/projects'

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); projectScope.clear(); projectScope.enabled=false; document.body.innerHTML='' })

const profile=(revision:number,confidence:number)=>({schemaVersion:1,modelId:'helmet',modelVersion:'1.0',platform:'server',source:'project',revision,detection:{confidenceThreshold:confidence,iouThreshold:.45,maxDetections:100},alertRules:[]})
const assignment=(target:'pc'|'mobile',modelId:string,version:string,revision:number,enabled=true):Assignment=>({
  projectModelId:`pm-${target}-${modelId}-${version}`,assignmentId:`pm-${target}-${modelId}-${version}`,projectId:'p1',
  modelId,modelVersion:version,target,parameterPlatform:target==='pc'?'server':'android',parameterRevision:target==='pc'?2:5,revision,enabled,
})
const available=[
  {modelId:'helmet',version:'1.0',name:'Helmet',status:'PUBLISHED',releaseEligible:true,supportedTargets:['pc','mobile'],serverReady:true,androidReady:true,targetReleaseEligible:{pc:true,mobile:true},parameterProfiles:{server:profile(2,.3),android:{...profile(5,.4),platform:'android'}}},
  {modelId:'vehicle',version:'2.0',name:'车辆检测',status:'PUBLISHED',releaseEligible:true,supportedTargets:['pc'],serverReady:true,targetReleaseEligible:{pc:true},parameterProfiles:{server:{...profile(3,.35),modelId:'vehicle',modelVersion:'2.0'}}},
] as any

async function setup(owner=true, initial:Assignment[]=[assignment('pc','helmet','1.0',3),assignment('pc','vehicle','2.0',1),assignment('mobile','helmet','1.0',7)]) {
  const projects=useProjectsStore(); projects.phase='ready'
  projects.current={projectId:'p1',lifecycleState:'ACTIVE',capabilities:owner?['project.read','project.models.assign']:['project.read']} as any
  let assignments=[...initial]
  vi.spyOn(projectModelsApi,'models').mockImplementation(async()=>assignments.map(a=>({
    modelId:a.modelId,version:a.modelVersion,name:a.modelId==='vehicle'?'车辆检测':'Helmet',status:'PUBLISHED',releaseEligible:true,
    supportedTargets:[a.target],serverReady:a.target==='pc',androidReady:a.target==='mobile',targetReleaseEligible:{[a.target]:true},assignment:a,artifacts:[],
  })) as any)
  vi.spyOn(projectModelsApi,'assignments').mockImplementation(async()=>assignments)
  const availableSpy=vi.spyOn(projectModelsApi,'available').mockResolvedValue(available)
  const save=vi.spyOn(projectModelsApi,'save').mockImplementation(async(value:AssignmentWrite)=>{
    const previous=assignments.find(a=>a.modelId===value.modelId&&a.modelVersion===value.modelVersion&&a.target===value.target)
    const next=assignment(value.target,value.modelId,value.modelVersion,(previous?.revision??0)+1,value.enabled)
    assignments=previous?assignments.map(a=>a.projectModelId===previous.projectModelId?next:a):[...assignments,next]
    return next
  })
  const remove=vi.spyOn(projectModelsApi,'remove').mockImplementation(async(projectModelId:string)=>{assignments=assignments.filter(a=>a.projectModelId!==projectModelId);return {removed:true,projectModelId}})
  const router=createRouter({history:createMemoryHistory(),routes:[{path:'/',component:ProjectModelsView}]}); await router.push('/')
  const wrapper=mount(ProjectModelsView,{global:{plugins:[installUiComponents,router],stubs:{UiDialog:{name:'UiDialog',props:['open','title'],template:'<section v-if="open"><slot/></section>'}}}}); await flushPromises()
  return {wrapper,availableSpy,save,remove}
}

it('shows independent PC and mobile pools with multiple exact releases and Chinese states',async()=>{
  const {wrapper}=await setup()
  expect(wrapper.findAll('.target-pool')).toHaveLength(1)
  expect(wrapper.findAll('.target-pool .inventory-row')).toHaveLength(2)
  expect(wrapper.find('.target-switch').text()).toContain('PC 端2')
  expect(wrapper.find('.target-switch').text()).toContain('移动端1')
  expect(wrapper.text()).toContain('已发布'); expect(wrapper.text()).not.toContain('PUBLISHED')
  expect(wrapper.text()).toContain('不会创建场景，也不会启动运行任务')
  expect(wrapper.text()).not.toContain('场景 ID')
  await wrapper.get('#project-model-tab-mobile').trigger('click')
  expect(wrapper.findAll('.target-pool .inventory-row')).toHaveLength(1)
  expect(wrapper.find('.target-pool').text()).toContain('移动端模型')
  expect(wrapper.find('.target-pool').text()).not.toContain('车辆检测')
  wrapper.unmount()
})

it.each(['pc','mobile'] as const)('distinguishes unpublished parameters from a valid published revision zero for %s',async target=>{
  const {wrapper}=await setup(true,[
    {...assignment(target,'helmet','1.0',3),parameterPublished:false,parameterRevision:0},
    {...assignment(target,'vehicle','2.0',1),parameterPublished:true,parameterRevision:0},
  ])
  if(target==='mobile') await wrapper.get('#project-model-tab-mobile').trigger('click')
  const rows=wrapper.findAll('.inventory-row')
  expect(rows.find(row=>row.text().includes('Helmet'))!.find('.inventory-meta').text()).toContain('参数修订尚未发布')
  expect(rows.find(row=>row.text().includes('车辆检测'))!.find('.inventory-meta').text()).toContain('参数修订r0')
  wrapper.unmount()
})

it('creates one target-specific inventory item and refreshes the correct pool',async()=>{
  const {wrapper,save}=await setup(true,[])
  await wrapper.get('#project-model-tab-mobile').trigger('click')
  await wrapper.findAll('button').find(button=>button.text()==='添加移动端模型')!.trigger('click'); await flushPromises()
  wrapper.findComponent({name:'UiSelect'}).vm.$emit('update:modelValue',JSON.stringify(['helmet','1.0'])); await flushPromises()
  const selects=wrapper.findAllComponents({name:'UiSelect'}); selects[1]!.vm.$emit('update:modelValue','mobile'); await flushPromises()
  await wrapper.find('form').trigger('submit'); wrapper.findComponent({name:'UiConfirmDialog'}).vm.$emit('confirm'); await flushPromises()
  expect(save).toHaveBeenCalledWith({modelId:'helmet',modelVersion:'1.0',target:'mobile',enabled:true,expectedRevision:0},expect.any(AbortSignal))
  expect(wrapper.findAll('.target-pool .inventory-row')).toHaveLength(1)
  expect(wrapper.find('.target-pool').text()).toContain('Helmet')
  wrapper.unmount()
})

it.each(['pc','mobile'] as const)('blocks an enabled exact release on %s even through programmatic submission',async target=>{
  const {wrapper,save}=await setup(true,[assignment(target,'helmet','1.0',3)])
  if(target==='mobile') await wrapper.get('#project-model-tab-mobile').trigger('click')
  await wrapper.findAll('button').find(button=>button.text()===(target==='pc'?'添加 PC 模型':'添加移动端模型'))!.trigger('click')
  await flushPromises()
  const modelSelect=wrapper.findComponent({name:'UiSelect'})
  expect(modelSelect.findAllComponents({name:'ElOption'}).map(option=>option.props('label')).join(' ')).toContain(`${target==='pc'?'PC 端':'移动端'}已添加`)
  modelSelect.vm.$emit('update:modelValue',JSON.stringify(['helmet','1.0']));await flushPromises()
  expect(wrapper.find('.assignment-preview').text()).toContain('已添加 · r3')
  expect(wrapper.find('.assignment-preview [role="status"]').text()).toContain('无需重复添加')
  expect(wrapper.find('form button.primary-button').text()).toBe('已添加')
  expect(wrapper.find('form button.primary-button').attributes('disabled')).toBeDefined()
  await wrapper.find('form').trigger('submit')
  const confirmation=wrapper.findComponent({name:'UiConfirmDialog'})
  expect(confirmation.props('open')).toBe(false)
  confirmation.vm.$emit('confirm');await flushPromises()
  expect(save).not.toHaveBeenCalled()
  expect(wrapper.findAll('.inventory-row')).toHaveLength(1)
  wrapper.unmount()
})

it('allows the same release on another target without changing the enabled entry',async()=>{
  const {wrapper,save}=await setup(true,[assignment('pc','helmet','1.0',3)])
  await wrapper.findAll('button').find(button=>button.text()==='添加 PC 模型')!.trigger('click');await flushPromises()
  wrapper.findComponent({name:'UiSelect'}).vm.$emit('update:modelValue',JSON.stringify(['helmet','1.0']));await flushPromises()
  expect(wrapper.find('form button.primary-button').attributes('disabled')).toBeDefined()
  wrapper.findAllComponents({name:'UiSelect'})[1]!.vm.$emit('update:modelValue','mobile');await flushPromises()
  expect(wrapper.find('.assignment-preview').text()).toContain('尚未添加')
  expect(wrapper.find('form button.primary-button').attributes('disabled')).toBeUndefined()
  await wrapper.find('form').trigger('submit');await flushPromises()
  wrapper.findComponent({name:'UiConfirmDialog'}).vm.$emit('confirm');await flushPromises()
  expect(save).toHaveBeenCalledExactlyOnceWith({modelId:'helmet',modelVersion:'1.0',target:'mobile',enabled:true,expectedRevision:0},expect.any(AbortSignal))
  expect(wrapper.find('.target-switch').text()).toContain('PC 端1')
  expect(wrapper.find('.target-switch').text()).toContain('移动端1')
  await wrapper.get('#project-model-tab-pc').trigger('click')
  expect(wrapper.find('.inventory-more').text()).toContain('清单 r3')
  wrapper.unmount()
})

it('explicitly reenables a disabled release from the add dialog and keeps the same row',async()=>{
  const existing=assignment('pc','helmet','1.0',8,false)
  const {wrapper,save}=await setup(true,[existing,assignment('pc','vehicle','2.0',1)])
  await wrapper.findAll('button').find(button=>button.text()==='添加 PC 模型')!.trigger('click');await flushPromises()
  const modelSelect=wrapper.findComponent({name:'UiSelect'})
  expect(modelSelect.findAllComponents({name:'ElOption'}).map(option=>option.props('label')).join(' ')).toContain('PC 端已停用，可重新启用')
  modelSelect.vm.$emit('update:modelValue',JSON.stringify(['helmet','1.0']));await flushPromises()
  expect(wrapper.findComponent({name:'UiDialog'}).props('title')).toBe('重新启用项目模型')
  expect(wrapper.find('form button.primary-button').text()).toBe('重新启用')
  expect(wrapper.find('.assignment-preview').text()).toContain('已停用 · r8')
  expect(wrapper.find('.assignment-preview').text()).toContain('不新增重复条目')
  await wrapper.find('form').trigger('submit');await flushPromises()
  const confirmation=wrapper.findComponent({name:'UiConfirmDialog'})
  expect(confirmation.props('title')).toBe('确认重新启用项目模型')
  expect(confirmation.props('confirmLabel')).toBe('确认重新启用')
  expect(confirmation.props('description')).toContain('保留原项目模型条目')
  confirmation.vm.$emit('update:open',false);await flushPromises()
  expect(save).not.toHaveBeenCalled()
  await wrapper.find('form').trigger('submit');confirmation.vm.$emit('confirm');await flushPromises()
  expect(save).toHaveBeenCalledExactlyOnceWith({modelId:'helmet',modelVersion:'1.0',target:'pc',enabled:true,expectedRevision:8},expect.any(AbortSignal))
  expect(wrapper.findAll('.inventory-row')).toHaveLength(2)
  const row=wrapper.findAll('.inventory-row').find(item=>item.text().includes('Helmet'))!
  expect(row.text()).toContain(existing.projectModelId)
  expect(row.text()).toContain('清单 r9')
  expect(row.text()).toContain('已启用')
  wrapper.unmount()
})

it.each([
  {modelId:'helmet',version:'2.0'},
  {modelId:'another-helmet',version:'1.0'},
])('allows a distinct exact release with the same display name: $modelId/$version',async release=>{
  const {wrapper,save,availableSpy}=await setup(true,[assignment('pc','helmet','1.0',3)])
  availableSpy.mockResolvedValue([...available,{...available[0],...release,parameterProfiles:{server:{...profile(4,.3),modelId:release.modelId,modelVersion:release.version}}}])
  await wrapper.findAll('button').find(button=>button.text()==='添加 PC 模型')!.trigger('click');await flushPromises()
  wrapper.findComponent({name:'UiSelect'}).vm.$emit('update:modelValue',JSON.stringify([release.modelId,release.version]));await flushPromises()
  expect(wrapper.find('.assignment-preview').text()).toContain('尚未添加')
  await wrapper.find('form').trigger('submit');wrapper.findComponent({name:'UiConfirmDialog'}).vm.$emit('confirm');await flushPromises()
  expect(save).toHaveBeenCalledExactlyOnceWith({modelId:release.modelId,modelVersion:release.version,target:'pc',enabled:true,expectedRevision:0},expect.any(AbortSignal))
  expect(wrapper.findAll('.inventory-row')).toHaveLength(2)
  wrapper.unmount()
})

it('blocks submission while candidates are loading or failed and allows an explicit reload',async()=>{
  const {wrapper,save,availableSpy}=await setup(true,[])
  let reject!:(reason:unknown)=>void
  availableSpy.mockImplementationOnce(()=>new Promise((_,fail)=>{reject=fail}))
  await wrapper.findAll('button').find(button=>button.text()==='添加 PC 模型')!.trigger('click');await flushPromises()
  wrapper.findComponent({name:'UiSelect'}).vm.$emit('update:modelValue',JSON.stringify(['helmet','1.0']));await flushPromises()
  expect(wrapper.text()).toContain('正在读取可分配模型')
  expect(wrapper.find('form button.primary-button').attributes('disabled')).toBeDefined()
  await wrapper.find('form').trigger('submit')
  expect(wrapper.findComponent({name:'UiConfirmDialog'}).props('open')).toBe(false)
  wrapper.findComponent({name:'UiConfirmDialog'}).vm.$emit('confirm');await flushPromises()
  expect(save).not.toHaveBeenCalled()
  reject(new Error('candidates unavailable'));await flushPromises()
  expect(wrapper.find('form button.primary-button').attributes('disabled')).toBeDefined()
  await wrapper.find('form').trigger('submit')
  wrapper.findComponent({name:'UiConfirmDialog'}).vm.$emit('confirm');await flushPromises()
  expect(save).not.toHaveBeenCalled()
  await wrapper.findAll('button').find(button=>button.text()==='重试模型候选')!.trigger('click');await flushPromises()
  expect(wrapper.find('form button.primary-button').attributes('disabled')).toBeUndefined()
  expect(save).not.toHaveBeenCalled()
  wrapper.unmount()
})

it('clears a new assignment draft on reopen while preserving the requested target',async()=>{
  const {wrapper}=await setup(true,[])
  await wrapper.get('#project-model-tab-mobile').trigger('click')
  await wrapper.findAll('button').find(button=>button.text()==='添加移动端模型')!.trigger('click')
  let selects=wrapper.findAllComponents({name:'UiSelect'})
  expect(selects[0]!.props('modelValue')).toBe('')
  expect(selects[1]!.props('modelValue')).toBe('mobile')
  selects[0]!.vm.$emit('update:modelValue',JSON.stringify(['helmet','1.0']))
  await flushPromises()
  await wrapper.findAll('button').find(button=>button.text()==='取消')!.trigger('click')
  await wrapper.findAll('button').find(button=>button.text()==='添加移动端模型')!.trigger('click')
  selects=wrapper.findAllComponents({name:'UiSelect'})
  expect(selects[0]!.props('modelValue')).toBe('')
  expect(selects[1]!.props('modelValue')).toBe('mobile')
  await wrapper.findAll('button').find(button=>button.text()==='取消')!.trigger('click')
  await wrapper.findAll('button').find(button=>button.text()==='添加移动端模型')!.trigger('click')
  selects=wrapper.findAllComponents({name:'UiSelect'})
  expect(selects[0]!.props('modelValue')).toBe('')
  expect(selects[1]!.props('modelValue')).toBe('mobile')
  wrapper.unmount()
})

it('reenables only the chosen target and preserves multiple models in the same pool',async()=>{
  const existing=assignment('pc','helmet','1.0',3,false)
  const {wrapper,save}=await setup(true,[existing,assignment('pc','vehicle','2.0',1)])
  const helmet=wrapper.findAll('.inventory-row').find(card=>card.text().includes('Helmet'))!
  await helmet.findAll('button').find(button=>button.text()==='重新启用')!.trigger('click'); await flushPromises()
  const selects=wrapper.findAllComponents({name:'UiSelect'})
  expect(selects[0]!.props('modelValue')).toBe(JSON.stringify(['helmet','1.0']))
  expect(selects[1]!.props('modelValue')).toBe('pc')
  await wrapper.find('form').trigger('submit'); wrapper.findComponent({name:'UiConfirmDialog'}).vm.$emit('confirm'); await flushPromises()
  expect(save).toHaveBeenCalledWith(expect.objectContaining({modelId:'helmet',target:'pc',expectedRevision:3}),expect.any(AbortSignal))
  expect(wrapper.findAll('.target-pool .inventory-row')).toHaveLength(2)
  wrapper.unmount()
})

it('stops and then removes an inventory item with revision checks',async()=>{
  const existing=assignment('pc','helmet','1.0',3)
  const {wrapper,save,remove}=await setup(true,[existing])
  await wrapper.get('button.danger-text').trigger('click'); wrapper.findAllComponents({name:'UiConfirmDialog'})[1]!.vm.$emit('confirm'); await flushPromises()
  expect(save).toHaveBeenCalledWith(expect.objectContaining({enabled:false,expectedRevision:3,target:'pc'}),expect.any(AbortSignal))
  expect(wrapper.text()).toContain('已停用')
  await wrapper.get('button.danger-text').trigger('click'); wrapper.findAllComponents({name:'UiConfirmDialog'})[2]!.vm.$emit('confirm'); await flushPromises()
  expect(remove).toHaveBeenCalledWith(existing.projectModelId,4,expect.any(AbortSignal))
  expect(wrapper.findAll('.inventory-row')).toHaveLength(0)
  wrapper.unmount()
})

it('preserves the draft and does not retry a conflicting save',async()=>{
  const {wrapper,save}=await setup(true,[])
  save.mockRejectedValueOnce(new ApiError({kind:'http',message:'conflict',status:409}))
  await wrapper.findAll('button').find(button=>button.text()==='添加 PC 模型')!.trigger('click'); await flushPromises()
  wrapper.findComponent({name:'UiSelect'}).vm.$emit('update:modelValue',JSON.stringify(['helmet','1.0'])); await flushPromises()
  await wrapper.find('form').trigger('submit'); wrapper.findComponent({name:'UiConfirmDialog'}).vm.$emit('confirm'); await flushPromises()
  expect(save).toHaveBeenCalledTimes(1); expect(wrapper.text()).toContain('不会自动重试')
  expect(wrapper.find('form').exists()).toBe(true)
  await wrapper.find('form').trigger('submit')
  expect(wrapper.findComponent({name:'UiConfirmDialog'}).props('open')).toBe(false)
  wrapper.findComponent({name:'UiConfirmDialog'}).vm.$emit('confirm');await flushPromises()
  expect(save).toHaveBeenCalledTimes(1)
  wrapper.unmount()
})

it('shows one add entry whose label and target follow the selected tab',async()=>{
  const {wrapper}=await setup()
  expect(wrapper.findAll('button').filter(button=>['分配模型','添加 PC 模型','添加移动端模型'].includes(button.text()))).toHaveLength(1)
  expect(wrapper.findAll('button').find(button=>button.text()==='添加 PC 模型')).toBeTruthy()
  await wrapper.get('#project-model-tab-mobile').trigger('click')
  expect(wrapper.findAll('button').filter(button=>['分配模型','添加 PC 模型','添加移动端模型'].includes(button.text()))).toHaveLength(1)
  await wrapper.findAll('button').find(button=>button.text()==='添加移动端模型')!.trigger('click')
  expect(wrapper.findAllComponents({name:'UiSelect'})[1]!.props('modelValue')).toBe('mobile')
  wrapper.unmount()
})

for(const target of ['pc','mobile'] as const)it(`explains platform uninstall without reopening a dead assignment (${target})`,async()=>{
  const old={...assignment(target,'helmet','1.0',4,false),modelName:'安全帽历史版',modelStatus:'UNINSTALLED',parameterPublished:false}
  const {wrapper,save,remove,availableSpy}=await setup(true,[old])
  vi.mocked(projectModelsApi.models).mockResolvedValue([])
  availableSpy.mockResolvedValue([])
  await wrapper.findAll('button').find(button=>button.text()==='刷新清单')!.trigger('click');await flushPromises()
  if(target==='mobile')await wrapper.get('#project-model-tab-mobile').trigger('click')
  const row=wrapper.find('.inventory-row')
  expect(row.find('h4').text()).toBe('安全帽历史版')
  expect(row.text()).toContain('已卸载')
  expect(row.text()).toContain('不能重新启用')
  expect(row.text()).toContain('重新上传不会自动恢复旧引用')
  const enable=row.findAll('button').find(button=>button.text()==='重新启用')!
  expect(enable.attributes('disabled')).toBeDefined()
  expect(enable.attributes('aria-describedby')).toBe(row.find('.inventory-unavailable').attributes('id'))
  await enable.trigger('click');await flushPromises()
  expect(wrapper.find('form').exists()).toBe(false)
  expect(save).not.toHaveBeenCalled()
  await row.findAll('button').find(button=>button.text()==='移除')!.trigger('click')
  wrapper.findAllComponents({name:'UiConfirmDialog'})[2]!.vm.$emit('confirm');await flushPromises()
  expect(remove).toHaveBeenCalledWith(old.projectModelId,4,expect.any(AbortSignal))
  wrapper.unmount()
})
for(const [status,label] of [['UNINSTALLED','已卸载模型（历史名称未留存）'],['MISSING','模型版本已不可用'],['UNKNOWN','未命名模型']])it(`does not guess a name or enable an unavailable assignment (${status})`,async()=>{
  const old={...assignment('pc','helmet','1.0',4,false),modelName:'未命名模型',modelStatus:status}
  const {wrapper,availableSpy}=await setup(true,[old])
  vi.mocked(projectModelsApi.models).mockResolvedValue([]);availableSpy.mockResolvedValue([])
  await wrapper.findAll('button').find(button=>button.text()==='刷新清单')!.trigger('click');await flushPromises()
  expect(wrapper.find('.inventory-row h4').text()).toBe(label)
  expect(wrapper.find('.inventory-unavailable').exists()).toBe(true)
  expect(wrapper.findAll('button').find(button=>button.text()==='重新启用')!.attributes('disabled')).toBeDefined()
  wrapper.unmount()
})
it('does not load selection data or expose writes to ordinary project users',async()=>{
  const {wrapper,availableSpy}=await setup(false,[assignment('pc','helmet','1.0',3)])
  expect(availableSpy).not.toHaveBeenCalled()
  expect(wrapper.findAll('button').some(button=>button.text()==='添加 PC 模型')).toBe(false)
  expect(wrapper.findAll('button').some(button=>button.text()==='停用')).toBe(false)
  expect(wrapper.findAll('button').some(button=>button.text()==='移除')).toBe(false)
  expect(wrapper.text()).toContain('查看平台参数')
  wrapper.unmount()
})
