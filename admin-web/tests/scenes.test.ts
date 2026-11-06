// @vitest-environment happy-dom
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { projectScope } from '../src/api/projectScope'
import { scenesApi } from '../src/features/scenes/api'
import { modelsApi } from '../src/features/models/api'
import { targetLabel, targetStatus } from '../src/features/models/capabilities'
import { useProjectsStore } from '../src/stores/projects'
import { projectModelsApi } from '../src/features/models/projectApi'
import ScenesView from '../src/features/scenes/ScenesView.vue'
import UiDialog from '../src/components/ui/UiDialog.vue'
import { installUiComponents } from '../src/components/ui/plugin'
import { memberPayload, planPayload, planStatus } from '../src/features/scenes/presentation'
import type { Scene, ScenePlan } from '../src/features/scenes/api'

beforeEach(()=>setActivePinia(createPinia()))
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals();projectScope.clear();projectScope.enabled=false;document.body.innerHTML=''})
const assignment=(id:string,target:'pc'|'mobile',enabled=true,parameterRevision=2)=>({projectModelId:id,modelId:'helmet',modelVersion:'1.0',target,parameterPlatform:target==='pc'?'server':'android',parameterRevision,enabled,revision:1}) as any
const inventory=(...assignments:any[])=>[{modelId:'helmet',version:'1.0',name:'安全帽检测',inputTypes:['image','video'],assignment:assignments[0],assignments,effectiveParametersByTarget:{}}] as any
const dialogStub={props:['open','title'],template:'<section v-if="open" :aria-label="title"><slot/></section>'}
it('roundtrips camera policy through plan editing and resets it for the next plan',async()=>{
  const {wrapper,create}=await newSceneEditor(['video']);await sceneInput(wrapper,'适用图片',false);await addInventoryMember(wrapper)
  const draft=wrapper.find('.scene-plan-draft')
  await draft.findAll('input')[0]!.setValue('camera');await draft.findAll('input')[1]!.setValue('相机方案')
  draft.findAll('.scene-plan-options')[1]!.findComponent({name:'UiInput'}).vm.$emit('update:modelValue',true);await flushPromises()
  wrapper.find('.scene-camera-policy').findAllComponents({name:'UiInput'})[0]!.vm.$emit('update:modelValue',12);await flushPromises()
  await wrapper.findAll('button').find(button=>button.text()==='添加运行方案')!.trigger('click')
  expect(wrapper.find('.scene-camera-policy').findAllComponents({name:'UiInput'})[0]!.props('modelValue')).toBe(5)
  await wrapper.findAll('button').find(button=>button.attributes('aria-label')==='编辑方案 相机方案')!.trigger('click')
  expect(wrapper.find('.scene-camera-policy').findAllComponents({name:'UiInput'})[0]!.props('modelValue')).toBe(12)
  await wrapper.findAll('button').find(button=>button.text()==='更新方案')!.trigger('click')
  await wrapper.find('form').trigger('submit');await flushPromises()
  expect(create).toHaveBeenCalledWith(expect.objectContaining({plans:[expect.objectContaining({cameraPolicy:expect.objectContaining({frameInterval:12})})]}),expect.any(AbortSignal))
  wrapper.unmount()
})
async function openDetails(wrapper:VueWrapper) {
  await wrapper.findAll('button').find(button=>button.attributes('aria-label')?.startsWith('查看详情 '))!.trigger('click');await flushPromises()
}
async function sceneAction(wrapper:VueWrapper,label:string) {
  const rowAction=wrapper.findAllComponents({name:'UiButton'}).find(button=>button.attributes('aria-label')?.startsWith(label+' '))
  if(rowAction){await rowAction.trigger('click');await flushPromises();return}
  await openDetails(wrapper)
  await wrapper.findAllComponents({name:'UiButton'}).find(button=>button.text()===label)!.trigger('click');await flushPromises()
}
async function newSceneEditor(inputs:string[]=['image','video']) {
  const projects=useProjectsStore();projects.phase='ready';projects.current={projectId:'p1',lifecycleState:'ACTIVE',capabilities:['project.read','project.scenes.manage']} as any
  vi.spyOn(scenesApi,'list').mockResolvedValue([])
  vi.spyOn(projectModelsApi,'models').mockResolvedValue(inventory(assignment('pm-pc','pc')).map((model:any)=>({...model,inputTypes:inputs})))
  const create=vi.spyOn(scenesApi,'create').mockResolvedValue({} as any)
  const wrapper=mount(ScenesView,{global:{plugins:[installUiComponents],stubs:{UiDialog:{props:['open'],template:'<section v-if="open"><slot/></section>'}}}})
  await flushPromises()
  await wrapper.findAll('button').find(button=>button.text()==='创建场景')!.trigger('click')
  const fields=wrapper.findAll('input');await fields[0]!.setValue('input-safety');await fields[1]!.setValue('输入能力场景')
  return {wrapper,create}
}
async function sceneInput(wrapper:VueWrapper,label:string,checked:boolean) {
  wrapper.find('.scene-inputs').findAll('label').find(row=>row.text()===label)!.findComponent({name:'UiInput'}).vm.$emit('update:modelValue',checked)
  await flushPromises()
}
async function addInventoryMember(wrapper:VueWrapper,id='pm-pc') {
  wrapper.findAllComponents({name:'UiSelect'})[0]!.vm.$emit('update:modelValue',id);await flushPromises()
  await wrapper.findAll('button').find(button=>button.text()==='添加项目模型成员')!.trigger('click')
}
for(const kind of ['image','video'] as const)for(const order of ['before','after'] as const) {
  it(`submits only ${kind} member inputs when the scene is narrowed ${order} adding a dual-input model`,async()=>{
    const {wrapper,create}=await newSceneEditor()
    if(order==='after')await addInventoryMember(wrapper)
    await sceneInput(wrapper,kind==='image'?'适用视频':'适用图片',false)
    if(order==='before')await addInventoryMember(wrapper)
    const memberSwitches=wrapper.find('.scene-member-inputs').findAllComponents({name:'UiInput'})
    expect(memberSwitches[kind==='image'?1:0]!.props('disabled')).toBe(true)
    await wrapper.find('form').trigger('submit');await flushPromises()
    expect(create).toHaveBeenCalledWith(expect.objectContaining({inputTypes:[kind],models:[expect.objectContaining({inputTypes:[kind]})]}),expect.any(AbortSignal))
    wrapper.unmount()
  })
}
it('keeps an incompatible model out of an image-only scene with a recoverable Chinese explanation',async()=>{
  const {wrapper,create}=await newSceneEditor(['video'])
  await sceneInput(wrapper,'适用视频',false);await addInventoryMember(wrapper)
  expect(wrapper.findAll('.scene-members.editable > li')).toHaveLength(0)
  expect(wrapper.text()).toContain('所选模型不支持当前场景的输入类型')
  expect(create).not.toHaveBeenCalled()
  await sceneInput(wrapper,'适用视频',true);await addInventoryMember(wrapper)
  await wrapper.find('form').trigger('submit');await flushPromises()
  expect(create).toHaveBeenCalledWith(expect.objectContaining({models:[expect.objectContaining({inputTypes:['video']})]}),expect.any(AbortSignal))
  wrapper.unmount()
})
it('does not turn an empty member input intersection back into all scene inputs',async()=>{
  const {wrapper,create}=await newSceneEditor(['video']);await addInventoryMember(wrapper)
  await sceneInput(wrapper,'适用视频',false)
  await wrapper.find('form').trigger('submit');await flushPromises()
  expect(create).not.toHaveBeenCalled()
  expect(wrapper.text()).toContain('没有与当前场景兼容的输入类型')
  expect(wrapper.find('input').element.value).toBe('input-safety')
  await sceneInput(wrapper,'适用视频',true)
  await wrapper.find('form').trigger('submit');await flushPromises()
  expect(create).toHaveBeenCalledWith(expect.objectContaining({models:[expect.objectContaining({inputTypes:['video']})]}),expect.any(AbortSignal))
  wrapper.unmount()
})
it('constrains plan choices to the scene and asks to edit saved plans invalidated by narrowing',async()=>{
  const {wrapper,create}=await newSceneEditor();await addInventoryMember(wrapper)
  const draft=wrapper.find('.scene-plan-draft')
  await draft.findAll('input')[0]!.setValue('photo');await draft.findAll('input')[1]!.setValue('图片方案')
  draft.findAll('.scene-plan-options')[1]!.findComponent({name:'UiInput'}).vm.$emit('update:modelValue',true)
  await flushPromises();await wrapper.findAll('button').find(button=>button.text()==='添加运行方案')!.trigger('click')
  await sceneInput(wrapper,'适用图片',false)
  expect(draft.findAll('.scene-plan-options')[0]!.findAllComponents({name:'UiInput'})[0]!.props('disabled')).toBe(true)
  await wrapper.find('form').trigger('submit');await flushPromises()
  expect(create).not.toHaveBeenCalled();expect(wrapper.text()).toContain('请编辑或移除该方案后保存')
  await wrapper.findAll('button').find(button=>button.text()==='编辑')!.trigger('click')
  await wrapper.findAll('button').find(button=>button.text()==='更新方案')!.trigger('click')
  await wrapper.find('form').trigger('submit');await flushPromises()
  expect(create).toHaveBeenCalledWith(expect.objectContaining({inputTypes:['video'],models:[expect.objectContaining({inputTypes:['video']})],plans:[expect.objectContaining({inputTypes:['video']})]}),expect.any(AbortSignal))
  wrapper.unmount()
})
it('narrows inherited inputs through one metadata patch without writing members separately',async()=>{
  const projects=useProjectsStore();projects.phase='ready';projects.current={projectId:'p1',lifecycleState:'ACTIVE',capabilities:['project.read','project.scenes.manage']} as any
  const scene={projectId:'p1',sceneId:'safety',name:'安全检查',inputTypes:['image','video'],revision:3,enabled:true,approved:true,plans:[],models:[{memberId:'pc',projectModelId:'pm-pc',modelId:'helmet',version:'1.0',target:'pc',parameterRevision:2,position:0,inputTypes:['image','video'],execution:'single'}]} as any
  vi.spyOn(scenesApi,'list').mockResolvedValue([scene]);vi.spyOn(projectModelsApi,'models').mockResolvedValue(inventory(assignment('pm-pc','pc')))
  const patch=vi.spyOn(scenesApi,'patch').mockResolvedValue({...scene,revision:4}),members=vi.spyOn(scenesApi,'members')
  const wrapper=mount(ScenesView,{global:{plugins:[installUiComponents],stubs:{UiDialog:{props:['open'],template:'<section v-if="open"><slot/></section>'}}}});await flushPromises()
  await sceneAction(wrapper,'编辑场景')
  await sceneInput(wrapper,'适用视频',false);await wrapper.find('form').trigger('submit');await flushPromises()
  expect(members).not.toHaveBeenCalled();expect(patch).toHaveBeenCalledExactlyOnceWith('safety',expect.objectContaining({inputTypes:['image'],expectedRevision:3}),expect.any(AbortSignal))
  expect(scene.models[0].inputTypes).toEqual(['image','video']);wrapper.unmount()
})
it('rejects metadata expansion beyond an inherited member model capability before any write',async()=>{
  const projects=useProjectsStore();projects.phase='ready';projects.current={projectId:'p1',lifecycleState:'ACTIVE',capabilities:['project.read','project.scenes.manage']} as any
  const scene={projectId:'p1',sceneId:'safety',name:'安全检查',inputTypes:['image'],revision:3,enabled:true,approved:true,plans:[],models:[{memberId:'pc',projectModelId:'pm-pc',modelId:'helmet',version:'1.0',target:'pc',parameterRevision:2,position:0,inputTypes:['image'],execution:'single'}]} as any
  vi.spyOn(scenesApi,'list').mockResolvedValue([scene]);vi.spyOn(projectModelsApi,'models').mockResolvedValue(inventory(assignment('pm-pc','pc')).map((model:any)=>({...model,inputTypes:['image']})))
  const patch=vi.spyOn(scenesApi,'patch'),members=vi.spyOn(scenesApi,'members')
  const wrapper=mount(ScenesView,{global:{plugins:[installUiComponents],stubs:{UiDialog:{props:['open'],template:'<section v-if="open"><slot/></section>'}}}});await flushPromises()
  await sceneAction(wrapper,'编辑场景')
  await sceneInput(wrapper,'适用视频',true);await wrapper.find('form').trigger('submit');await flushPromises()
  expect(members).not.toHaveBeenCalled();expect(patch).not.toHaveBeenCalled();expect(wrapper.text()).toContain('包含未支持的输入')
  wrapper.unmount()
})
it('adds a dual-input model to image-only member management without expanding the scene',async()=>{
  const projects=useProjectsStore();projects.phase='ready';projects.current={projectId:'p1',lifecycleState:'ACTIVE',capabilities:['project.read','project.scenes.manage']} as any
  const scene={projectId:'p1',sceneId:'safety',name:'安全检查',inputTypes:['image'],revision:3,enabled:true,approved:true,plans:[],models:[{memberId:'pc',projectModelId:'pm-pc',modelId:'helmet',version:'1.0',target:'pc',parameterRevision:2,position:0,inputTypes:['image'],execution:'single'}]} as any
  vi.spyOn(scenesApi,'list').mockResolvedValue([scene]);vi.spyOn(projectModelsApi,'models').mockResolvedValue(inventory(assignment('pm-pc','pc'),assignment('pm-mobile','mobile')))
  const write=vi.spyOn(scenesApi,'members').mockResolvedValue({...scene,revision:4}),patch=vi.spyOn(scenesApi,'patch')
  const wrapper=mount(ScenesView,{global:{plugins:[installUiComponents],stubs:{UiDialog:{props:['open'],template:'<section v-if="open"><slot/></section>'}}}});await flushPromises()
  await sceneAction(wrapper,'管理模型成员');await addInventoryMember(wrapper,'pm-mobile')
  await wrapper.find('form').trigger('submit');await flushPromises()
  expect(write).toHaveBeenCalledWith('safety',[expect.objectContaining({projectModelId:'pm-pc',inputTypes:['image']}),expect.objectContaining({projectModelId:'pm-mobile',inputTypes:['image']})],3,expect.any(AbortSignal))
  expect(patch).not.toHaveBeenCalled();wrapper.unmount()
})
it('keeps scene mutations scoped to the current project and forwards exact revisions',async()=>{
  projectScope.enable();projectScope.enter('alpha')
  const fetcher=vi.fn(async(_path:unknown,_init?:RequestInit)=>new Response('{}'));vi.stubGlobal('fetch',fetcher)
  await scenesApi.members('site/01',[{projectModelId:'pm-helmet-pc',parameterRevision:4,position:0,execution:'single'}],7)
  await scenesApi.approve('site/01',true,8,'reviewed')
  expect(fetcher.mock.calls[0]?.[0]).toBe('/aiyoloapi/projects/alpha/scenes/site%2F01/models')
  expect(JSON.parse(String(fetcher.mock.calls[0]?.[1]?.body))).toEqual({expectedRevision:7,models:[{projectModelId:'pm-helmet-pc',parameterRevision:4,position:0,execution:'single'}]})
  expect(JSON.parse(String(fetcher.mock.calls[1]?.[1]?.body))).toEqual({expectedRevision:8,approved:true,reason:'reviewed'})
  projectScope.clear();await expect(scenesApi.list()).rejects.toMatchObject({code:'project_context_required'})
})
it('forwards explicit suite plans without copying model assets',async()=>{
  projectScope.enable();projectScope.enter('alpha')
  const fetcher=vi.fn(async(_path:unknown,_init?:RequestInit)=>new Response('{}'));vi.stubGlobal('fetch',fetcher)
  await scenesApi.plans('site/01',[{planId:'image-safety',name:'静态识别',inputTypes:['image'],memberIds:['member-helmet'],execution:'single',enabled:true}],9)
  expect(fetcher.mock.calls[0]?.[0]).toBe('/aiyoloapi/projects/alpha/scenes/site%2F01/plans')
  expect(JSON.parse(String(fetcher.mock.calls[0]?.[1]?.body))).toEqual({expectedRevision:9,plans:[{planId:'image-safety',name:'静态识别',inputTypes:['image'],memberIds:['member-helmet'],execution:'single',enabled:true}]})
})
it('previews then deletes the exact scene revision without cascade options',async()=>{
  projectScope.enable();projectScope.enter('alpha')
  const fetcher=vi.fn(async(_path:unknown,_init?:RequestInit)=>new Response('{}'));vi.stubGlobal('fetch',fetcher)
  await scenesApi.impact('site/01');await scenesApi.remove('site/01',7,'scene-remove-1')
  expect(fetcher.mock.calls[0]?.[0]).toBe('/aiyoloapi/projects/alpha/scenes/site%2F01/removal-impact')
  expect(fetcher.mock.calls[1]?.[1]).toMatchObject({method:'DELETE'})
  const headers=new Headers(fetcher.mock.calls[1]?.[1]?.headers)
  expect(headers.get('If-Match')).toBe('"7"');expect(headers.get('Idempotency-Key')).toBe('scene-remove-1')
  expect(fetcher.mock.calls[1]?.[1]?.body).toBeUndefined()
})
it('distinguishes supported, ready and published targets without forcing Android on PC',()=>{
  const pc={supportedTargets:['pc'],targetReadiness:{pc:{ready:true}},targetReleaseEligible:{pc:true}} as any
  expect(targetLabel(pc)).toBe('PC 端模型');expect(targetStatus(pc,'mobile')).toBe('不支持');expect(targetStatus(pc,'pc')).toBe('已发布')
  const dual={...pc,supportedTargets:['pc','mobile']}
  expect(targetLabel(dual)).toBe('PC / 移动双端');expect(targetStatus(dual,'mobile')).toBe('产物待就绪')
  expect(targetStatus({...pc,targetReleaseEligible:{pc:false}},'pc')).toBe('已就绪 / 待发布')
  expect(targetLabel({androidReady:true} as any)).toBe('移动端模型')
})
it('publishes the selected version and target with explicit license review',async()=>{
  vi.stubGlobal('fetch',vi.fn(async()=>new Response('{}')))
  await modelsApi.publish({modelId:'helmet',version:'1.0.0'} as any,['pc'],'reviewed')
  const fetcher=vi.mocked(fetch);const call=fetcher.mock.calls[0]!
  expect(call[0]).toBe('/aiyoloapi/models/helmet/versions/1.0.0/publish')
  expect(JSON.parse(String(call[1]?.body))).toEqual({targets:['pc'],licenseApproved:true,reason:'reviewed'})
})
it('does not request project model inventory or render write actions for project users',async()=>{
  const projects=useProjectsStore();projects.phase='ready';projects.current={projectId:'p1',lifecycleState:'ACTIVE',capabilities:['project.read']} as any
  vi.spyOn(scenesApi,'list').mockResolvedValue([]);const inventory=vi.spyOn(projectModelsApi,'models')
  const wrapper=mount(ScenesView,{global:{plugins:[installUiComponents]}});await flushPromises()
  expect(inventory).not.toHaveBeenCalled();expect(wrapper.text()).toContain('暂无可见场景');expect(wrapper.text()).not.toContain('创建场景')
  wrapper.unmount()
})
it('loads owner controls and keeps execution limitations visible',async()=>{
  const projects=useProjectsStore();projects.phase='ready';projects.current={projectId:'p1',lifecycleState:'ACTIVE',capabilities:['project.read','project.scenes.manage','project.scenes.approve']} as any
  vi.spyOn(scenesApi,'list').mockResolvedValue([{sceneId:'safety',projectId:'p1',name:'现场安全',models:[{projectModelId:'pm-helmet-pc',parameterRevision:0,modelId:'helmet',version:'1.0',target:'pc',position:0,execution:'async'}],enabled:true,approved:false,revision:1,inputTypes:['image'] }]);vi.spyOn(projectModelsApi,'models').mockResolvedValue([])
  const wrapper=mount(ScenesView,{global:{plugins:[installUiComponents],stubs:{UiDialog:dialogStub}}});await flushPromises()
  expect(wrapper.text()).toContain('创建场景');expect(wrapper.text()).toContain('图片识别')
  expect(wrapper.find('.scene-members').exists()).toBe(false)
  await openDetails(wrapper)
  const detail=wrapper.find('.scene-detail').text()
  expect(detail).toContain('尚未支持')
  expect(wrapper.findAllComponents({name:'UiButton'}).some(button=>button.attributes('aria-label')==='批准场景 现场安全')).toBe(true)
  wrapper.unmount()
})
it('adds exact project model inventory items and writes only stable inventory identities',async()=>{
  const projects=useProjectsStore();projects.phase='ready';projects.current={projectId:'p1',lifecycleState:'ACTIVE',capabilities:['project.read','project.scenes.manage']} as any
  vi.spyOn(scenesApi,'list').mockResolvedValue([])
  vi.spyOn(projectModelsApi,'models').mockResolvedValue(inventory(assignment('pm-pc','pc',true,4),assignment('pm-mobile','mobile',true,7)))
  const create=vi.spyOn(scenesApi,'create').mockResolvedValue({} as any)
  const wrapper=mount(ScenesView,{global:{plugins:[installUiComponents],stubs:{UiDialog:{props:['open'],template:'<section v-if="open"><slot/></section>'}}}});await flushPromises()
  await wrapper.findAll('button').find(button=>button.text()==='创建场景')!.trigger('click');await flushPromises()
  const selects=wrapper.findAllComponents({name:'UiSelect'})
  selects[0]!.vm.$emit('update:modelValue','pm-pc');await flushPromises()
  await wrapper.findAll('button').find(button=>button.text()==='添加项目模型成员')!.trigger('click')
  const inputs=wrapper.findAll('input');await inputs[0]!.setValue('site-safety');await inputs[1]!.setValue('现场安全')
  await wrapper.find('form').trigger('submit');await flushPromises()
  expect(create).toHaveBeenCalledWith(expect.objectContaining({models:[{memberId:expect.any(String),projectModelId:'pm-pc',position:0,inputTypes:['image','video'],execution:'single',parameterRevision:4}]}),expect.any(AbortSignal))
  expect(JSON.stringify(create.mock.calls[0]?.[0].models)).not.toContain('modelId')
  expect(JSON.stringify(create.mock.calls[0]?.[0].models)).not.toContain('target')
  wrapper.unmount()
})
it('keeps disabled inventory visible but prevents adding it as a scene member',async()=>{
  const projects=useProjectsStore();projects.phase='ready';projects.current={projectId:'p1',lifecycleState:'ACTIVE',capabilities:['project.read','project.scenes.manage']} as any
  vi.spyOn(scenesApi,'list').mockResolvedValue([]);vi.spyOn(projectModelsApi,'models').mockResolvedValue(inventory(assignment('pm-disabled','pc',false)))
  const wrapper=mount(ScenesView,{global:{plugins:[installUiComponents],stubs:{UiDialog:{props:['open'],template:'<section v-if="open"><slot/></section>'}}}});await flushPromises()
  await wrapper.findAll('button').find(button=>button.text()==='创建场景')!.trigger('click');await flushPromises()
  expect(wrapper.text()).toContain('0 个可用')
  const add=wrapper.findAll('button').find(button=>button.text()==='添加项目模型成员')!
  expect(add.attributes('disabled')).toBeDefined()
  wrapper.unmount()
})
it('shows suite capability summary and configuration-only multi-member plans',async()=>{
  const projects=useProjectsStore();projects.phase='ready';projects.current={projectId:'p1',lifecycleState:'ACTIVE',capabilities:['project.read','project.scenes.manage']} as any
  vi.spyOn(scenesApi,'list').mockResolvedValue([{sceneId:'safety',projectId:'p1',name:'工地安全套件',models:[
    {memberId:'helmet-image',projectModelId:'pm-helmet-mobile',parameterRevision:0,modelId:'helmet',version:'1.0',target:'mobile',position:0,inputTypes:['image'],execution:'single'},
    {memberId:'ppe-video',projectModelId:'pm-ppe-mobile',parameterRevision:0,modelId:'ppe',version:'1.0',target:'mobile',position:1,inputTypes:['video'],execution:'single'},
  ],plans:[{planId:'combined',name:'联合识别',inputTypes:['image'],memberIds:['helmet-image','ppe-video'],execution:'sync',enabled:true}],enabled:true,approved:false,revision:1,inputTypes:['image','video']}])
  vi.spyOn(projectModelsApi,'models').mockResolvedValue([])
  const wrapper=mount(ScenesView,{global:{plugins:[installUiComponents],stubs:{UiDialog:dialogStub}}});await flushPromises()
  expect(wrapper.find('.scene-plan-summary').exists()).toBe(false)
  await openDetails(wrapper)
  const detail=wrapper.find('.scene-detail').text()
  expect(detail).toContain('项目模型成员');expect(detail).toContain('同一项目模型可被多个场景复用');expect(detail).toContain('已配置 · 待批准')
  wrapper.unmount()
})
it('renders server model names for read-only users without inventory permissions and escapes markup',async()=>{
  const projects=useProjectsStore();projects.phase='ready';projects.current={projectId:'p1',lifecycleState:'ACTIVE',capabilities:['project.read']} as any
  vi.spyOn(scenesApi,'list').mockResolvedValue([{projectId:'p1',sceneId:'names',name:'名称场景',inputTypes:['image'],revision:1,enabled:true,approved:true,models:[{memberId:'m',projectModelId:'pm',modelId:'uploaded-06abcd',modelName:'安全帽 <script>not code</script>',version:'2.0.0',target:'mobile',parameterRevision:0,position:0,execution:'single'}],plans:[]}] as any)
  const inventory=vi.spyOn(projectModelsApi,'models')
  const wrapper=mount(ScenesView,{global:{plugins:[installUiComponents],stubs:{UiDialog:dialogStub}}});await flushPromises()
  await openDetails(wrapper)
  const detail=wrapper.find('.scene-detail')
  expect(detail.find('.scene-members strong').text()).toBe('安全帽 <script>not code</script>')
  expect(detail.find('.scene-members strong').find('script').exists()).toBe(false)
  expect(detail.text()).not.toContain('编辑场景');expect(detail.text()).not.toContain('批准场景')
  expect(inventory).not.toHaveBeenCalled()
  wrapper.unmount()
})
it('does not confuse approval, availability and device runtime capability',()=>{
  const member={memberId:'m',projectModelId:'pm-mobile',parameterRevision:0,modelId:'helmet',version:'1',target:'mobile',position:0,execution:'single',available:true,executionReady:true} as const
  const plan:ScenePlan={planId:'p',name:'Photo',memberIds:['m'],inputTypes:['image'],execution:'single',enabled:true}
  const scene:Scene={projectId:'p1',sceneId:'s',name:'Safety',revision:1,inputTypes:['image'],models:[member],plans:[plan],approved:true,enabled:true,available:true}
  expect(planStatus({...scene,approved:false},plan)).toBe('已配置 · 待批准')
  expect(planStatus({...scene,available:false},plan)).toBe('已配置 · 待核验')
  expect(planStatus(scene,{...plan,enabled:false})).toBe('已配置 · 已停用')
  expect(planStatus(scene,{...plan,execution:'async'})).toBe('已配置 · 客户端未支持')
  expect(planStatus(scene,plan)).toBe('可使用 · 需在线预检')
})
it('resolves details from the refreshed list and resets the selected scene on reopen',async()=>{
  const projects=useProjectsStore();projects.phase='ready';projects.current={projectId:'p1',lifecycleState:'ACTIVE',capabilities:['project.read']} as any
  const scene={projectId:'p1',sceneId:'a',name:'场景甲',models:[],plans:[],inputTypes:['image'],enabled:true,approved:true,revision:1} as Scene
  const list=vi.spyOn(scenesApi,'list').mockResolvedValue([scene,{...scene,sceneId:'b',name:'场景乙'}])
  const wrapper=mount(ScenesView,{global:{plugins:[installUiComponents],stubs:{UiDialog:{props:['open'],template:'<section v-if="open"><slot/></section>'}}}});await flushPromises()
  await openDetails(wrapper)
  expect(wrapper.find('.scene-detail').text()).toContain('场景甲')
  list.mockResolvedValue([{...scene,name:'场景甲已更新',revision:2}])
  await wrapper.findAll('button').find(button=>button.text()==='刷新场景')!.trigger('click');await flushPromises()
  expect(wrapper.find('.scene-detail').text()).toContain('场景甲已更新')
  wrapper.findComponent(UiDialog).vm.$emit('update:open',false);await flushPromises()
  expect(wrapper.find('.scene-detail').exists()).toBe(false)
  await openDetails(wrapper);expect(wrapper.find('.scene-detail').text()).toContain('REV 2')
  list.mockResolvedValue([])
  await wrapper.findAll('button').find(button=>button.text()==='刷新场景')!.trigger('click');await flushPromises()
  expect(wrapper.find('.scene-detail').exists()).toBe(false);expect(wrapper.text()).toContain('暂无可见场景')
  wrapper.unmount()
})
it('keeps loading, empty and failed reads out of the scene table',async()=>{
  const projects=useProjectsStore();projects.phase='ready';projects.current={projectId:'p1',lifecycleState:'ACTIVE',capabilities:['project.read']} as any
  let resolve!:(scenes:Scene[])=>void
  const list=vi.spyOn(scenesApi,'list').mockImplementation(()=>new Promise(r=>{resolve=r}))
  const wrapper=mount(ScenesView,{global:{plugins:[installUiComponents]}});await flushPromises()
  expect(wrapper.text()).toContain('正在加载');expect(wrapper.find('.scene-list').exists()).toBe(false)
  resolve([]);await flushPromises();expect(wrapper.text()).toContain('暂无可见场景')
  list.mockRejectedValue(new Error('测试读取失败'))
  await wrapper.findAll('button').find(button=>button.text()==='刷新场景')!.trigger('click');await flushPromises()
  expect(wrapper.find('.scene-list').exists()).toBe(false);expect(wrapper.findComponent({name:'UiStatePanel'}).props('state')).toBe('error')
  wrapper.unmount()
})
it('toggles the exact scene revision from details and displays the refreshed state',async()=>{
  const projects=useProjectsStore();projects.phase='ready';projects.current={projectId:'p1',lifecycleState:'ACTIVE',capabilities:['project.read','project.scenes.manage']} as any
  const scene={projectId:'p1',sceneId:'a',name:'场景甲',models:[],plans:[],inputTypes:['image'],enabled:true,approved:true,revision:7} as Scene
  const list=vi.spyOn(scenesApi,'list').mockResolvedValue([scene]);vi.spyOn(projectModelsApi,'models').mockResolvedValue([])
  const patch=vi.spyOn(scenesApi,'patch').mockImplementation(async()=>{list.mockResolvedValue([{...scene,enabled:false,revision:8}]);return {...scene,enabled:false,revision:8}})
  const wrapper=mount(ScenesView,{global:{plugins:[installUiComponents],stubs:{UiDialog:dialogStub}}});await flushPromises()
  await sceneAction(wrapper,'停用场景')
  expect(patch).toHaveBeenCalledExactlyOnceWith('a',{enabled:false,expectedRevision:7},expect.any(AbortSignal))
  expect(wrapper.find('.scene-list').text()).toContain('REV 8');expect(wrapper.find('.scene-list').text()).toContain('已停用')
  expect(wrapper.findAllComponents({name:'UiButton'}).some(button=>button.attributes('aria-label')==='启用场景 场景甲')).toBe(true);wrapper.unmount()
})
it('requires removal impact and explicit confirmation after leaving details',async()=>{
  const projects=useProjectsStore();projects.phase='ready';projects.current={projectId:'p1',lifecycleState:'ACTIVE',capabilities:['project.read','project.scenes.manage']} as any
  const scene={projectId:'p1',sceneId:'a',name:'场景甲',models:[],plans:[],inputTypes:['image'],enabled:true,approved:true,revision:7} as Scene
  const list=vi.spyOn(scenesApi,'list').mockResolvedValue([scene]);vi.spyOn(projectModelsApi,'models').mockResolvedValue([])
  const impact=vi.spyOn(scenesApi,'impact').mockResolvedValue({expectedRevision:7,safeToRemove:true,knownDevices:0,unknownDeviceCount:0,dependentCounts:{assignments:0,scenes:0,plans:0,streams:0,activeSlots:0}})
  const remove=vi.spyOn(scenesApi,'remove').mockImplementation(async()=>{list.mockResolvedValue([]);return {}})
  const wrapper=mount(ScenesView,{global:{plugins:[installUiComponents],stubs:{UiDialog:dialogStub}}});await flushPromises()
  await sceneAction(wrapper,'删除场景');expect(impact).toHaveBeenCalledExactlyOnceWith('a',expect.any(AbortSignal))
  expect(wrapper.find('.scene-detail').exists()).toBe(false)
  const confirm=wrapper.findAll('button').find(button=>button.text()==='确认删除场景')!
  expect(confirm.attributes('disabled')).toBeDefined();expect(remove).not.toHaveBeenCalled()
  wrapper.findComponent({name:'UiInput'}).vm.$emit('update:modelValue',true);await flushPromises()
  await wrapper.find('form').trigger('submit');await flushPromises()
  expect(remove).toHaveBeenCalledExactlyOnceWith('a',7,expect.any(String),expect.any(AbortSignal))
  expect(wrapper.text()).toContain('暂无可见场景');wrapper.unmount()
})
it('projects writable identities without approval snapshots or server-derived fields',()=>{
  const member={memberId:'m',projectModelId:'pm-pc',parameterRevision:4,modelId:'helmet',version:'1',target:'pc',position:0,inputTypes:['image'],execution:'single',executionReady:true,parameterSnapshot:{revision:4},artifacts:[{url:'/secret'}]} as any
  const plan={planId:'p',name:'Photo',inputTypes:['image'],memberIds:['m'],execution:'single',enabled:true,implicit:true,parameterSources:[{memberId:'m'}]} as any
  expect(memberPayload(member,0,'m',['image'])).toEqual({memberId:'m',projectModelId:'pm-pc',parameterRevision:4,position:0,inputTypes:['image'],execution:'single'})
  expect(Object.keys(planPayload(plan)).sort()).toEqual(['enabled','execution','inputTypes','memberIds','name','planId'])
})
it('does not mutate an approved catalog when an unchanged editor is saved',async()=>{
  const projects=useProjectsStore();projects.phase='ready';projects.current={projectId:'p1',lifecycleState:'ACTIVE',capabilities:['project.read','project.scenes.manage']} as any
  const scene={sceneId:'s',projectId:'p1',name:'Safety',revision:2,inputTypes:['image'],approved:true,enabled:true,models:[{memberId:'m',projectModelId:'pm-pc',parameterRevision:0,modelId:'helmet',version:'1',target:'pc',position:0,inputTypes:['image'],execution:'single',executionReady:true,parameterSnapshot:{revision:0}}],plans:[{planId:'photo',name:'Photo',memberIds:['m'],inputTypes:['image'],execution:'single',enabled:true,parameterSources:[{memberId:'m',parameterSnapshot:{revision:0}}]}]} as any
  const snapshot={revision:0,detection:{confidenceThreshold:0.3,iouThreshold:0.5,maxDetections:100},alertRules:[]}
  scene.models[0].parameterSnapshot=snapshot;scene.plans[0].parameterSources[0].parameterSnapshot=snapshot
  vi.spyOn(scenesApi,'list').mockResolvedValue([scene]);vi.spyOn(projectModelsApi,'models').mockResolvedValue([])
  const patch=vi.spyOn(scenesApi,'patch'),members=vi.spyOn(scenesApi,'members'),plans=vi.spyOn(scenesApi,'plans')
  const wrapper=mount(ScenesView,{global:{plugins:[installUiComponents]},attachTo:document.body});await flushPromises()
  await sceneAction(wrapper,'编辑场景')
  const editor=document.querySelector('form')!;expect(editor).not.toBeNull();editor.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));await flushPromises()
  expect(patch).not.toHaveBeenCalled();expect(members).not.toHaveBeenCalled();expect(plans).not.toHaveBeenCalled()
  wrapper.unmount()
})
