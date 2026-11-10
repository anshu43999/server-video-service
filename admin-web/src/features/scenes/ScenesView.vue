<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { Layers3, Plus, RefreshCw } from '@lucide/vue'
import UiDialog from '../../components/ui/UiDialog.vue'
import UiDataTable, { type TableColumn } from '../../components/ui/UiDataTable.vue'
import { removalSummary, type RemovalImpact } from '../models/lifecycle'
import UiStatePanel from '../../components/ui/UiStatePanel.vue'
import { useManagement } from '../management/useManagement'
import { useCandidates } from '../management/useCandidates'
import { useProjectCapabilities } from '../projects/capabilities'
import { projectModelsApi, type AssignedModel, type Assignment } from '../models/projectApi'
import ParametersDialog from '../models/ParametersDialog.vue'
import { scenesApi, type Scene, type SceneExecution, type SceneInputType, type SceneMember, type ScenePlan } from './api'
import { memberPayload, planPayload as toPlanPayload, planParameter, planStatus } from './presentation'
import { modelDisplayName } from '../models/presentation'
import '../models/models.css'
import './scenes.css'
import CameraPolicyFields from './CameraPolicyFields.vue'
import { defaultCameraPolicy, cameraPolicyError } from './cameraPolicy'
const caps=useProjectCapabilities()
const canManage=computed(()=>caps.can('project.scenes.manage')),canApprove=computed(()=>caps.can('project.scenes.approve'))
const state=useManagement<{scenes:Scene[]}>({scenes:[]},async signal=>({scenes:await scenesApi.list(signal)}))
const {data,loading,error,notice,busy,mutationError,needsReload,refresh,run,resetMutation}=state
const detailId=ref<string|null>(null)
const detailScene=computed(()=>data.value.scenes.find(scene=>scene.sceneId===detailId.value))
watch(detailScene,scene=>{if(!scene)detailId.value=null})
const sceneRows=computed(()=>data.value.scenes.map(scene=>({...scene})))
const sceneColumns:TableColumn[]=[
  {key:'name',label:'场景名称',align:'start',minWidth:180},
  {key:'status',label:'状态',width:100},
  {key:'inputs',label:'输入能力',width:150},
  {key:'models',label:'模型数',width:80},
  {key:'plans',label:'方案数',width:80},
  {key:'actions',label:'操作',minWidth:204,fixed:'right'},
]
const dialog=ref<'create'|'details'|'members'|null>(null),selected=ref<Scene|null>(null),localError=ref('')
const form=reactive({id:'',name:'',image:true,video:true,enabled:true})
const members=ref<SceneMember[]>([]),plans=ref<ScenePlan[]>([]),projectModelId=ref(''),execution=ref<SceneExecution>('single')
const planEditingId=ref<string|null>(null)
const planDraft=reactive<ScenePlan & {cameraPolicy:ReturnType<typeof defaultCameraPolicy>}>({planId:'',name:'',inputTypes:['image'],memberIds:[],execution:'single',enabled:true,cameraPolicy:defaultCameraPolicy()})
const review=ref<Scene|null>(null),reviewReason=ref('')
const {data:inventory,loading:inventoryLoading,error:inventoryError,refresh:reloadInventory}=useCandidates<AssignedModel>(computed(()=>canManage.value&&(dialog.value!==null||detailId.value!==null||review.value!==null)),projectModelsApi.models)
const reapprove=ref(false)
const removal=ref<{scene:Scene;impact:RemovalImpact;key:string}|null>(null),removalChecked=ref(false)
async function beginRemoval(scene:Scene){
  if(!canManage.value||needsReload.value||busy.value)return
  removalChecked.value=false
  await run(async signal=>{
    const impact=await scenesApi.impact(scene.sceneId,signal)
    if(impact.expectedRevision!==scene.revision)throw new Error('场景已变更，请刷新后重新预览')
    detailId.value=null;removal.value={scene,impact,key:crypto.randomUUID()}
  },()=>{})
}
async function removeScene(){
  const current=removal.value
  if(!current||!removalChecked.value||!current.impact.safeToRemove||!canManage.value)return
  await run(signal=>scenesApi.remove(current.scene.sceneId,current.impact.expectedRevision,current.key,signal),()=>{removal.value=null})
}
interface InventoryChoice {assignment:Assignment;model:AssignedModel}
const inventoryChoices=computed<InventoryChoice[]>(()=>inventory.value.flatMap(model=>
  (model.assignments?.length?model.assignments:[model.assignment]).map(assignment=>({assignment,model})),
))
const chosen=computed(()=>inventoryChoices.value.find(item=>item.assignment.projectModelId===projectModelId.value))
const parameterSelection=ref<{scene:Scene;member:SceneMember;model:AssignedModel}|null>(null)
function editParameters(scene:Scene,member:SceneMember){
  const model=memberModel(member)?.model
  if(!canManage.value||!caps.models.value||!model||!member.memberId||needsReload.value)return
  detailId.value=null;parameterSelection.value={scene,member,model}
}
const pendingProfile=(member:SceneMember)=>member.parameterSnapshot ?? member.pendingParameterSnapshot
const approvedPlanMembers=(scene:Scene,plan:ScenePlan)=>scene.models.filter(member=>plan.memberIds.includes(memberId(member)))
const inputTypes=()=>[...(form.image?['image' as const]:[]),...(form.video?['video' as const]:[])]
const modelInputs=(model:AssignedModel|undefined):SceneInputType[]=>model?.inputTypes?.length?[...model.inputTypes]:['image','video']
const memberKey=(member:Pick<SceneMember,'projectModelId'>)=>member.projectModelId
const memberId=(member:SceneMember)=>member.memberId||('member-'+encodeURIComponent(member.projectModelId).replaceAll('%','_'))
const memberModel=(member:SceneMember)=>inventoryChoices.value.find(item=>item.assignment.projectModelId===member.projectModelId)
const memberName=(member:SceneMember)=>modelDisplayName(member.modelName?.trim()?member:memberModel(member)?.model)
const memberInputs=(member:SceneMember):SceneInputType[]=>[...(member.inputTypes??inputTypes())]
const memberInputOptions=(member:SceneMember)=>inputTypes().filter(kind=>modelInputs(memberModel(member)?.model).includes(kind))
// Metadata edits inherit the scene declaration only when the server does too.
// Do not rewrite those members through a separate, non-atomic members request.
const editorMemberInputs=(member:SceneMember):SceneInputType[]=>{
  const current=memberInputs(member),previous=selected.value?.inputTypes
  return dialog.value==='details'&&previous&&current.length===previous.length&&previous.every(kind=>current.includes(kind))?inputTypes():current
}
const memberInventory=(member:SceneMember)=>memberModel(member)?.assignment
const memberNeedsRefresh=(member:SceneMember)=>memberInventory(member)?.parameterRevision!==(member.parameterSnapshot?.inventoryRevision??member.parameterRevision)
const invalidMembers=computed(()=>members.value.filter(member=>!memberInventory(member)?.enabled))
const planMembers=computed(()=>members.value.filter(member=>planDraft.memberIds.includes(memberId(member))))
const planInputOptions=computed<SceneInputType[]>(()=>{
  return inputTypes().filter(kind=>planMembers.value.every(member=>editorMemberInputs(member).includes(kind)))
})
const suiteCapabilities=computed<SceneInputType[]>(()=>inputTypes().filter(kind=>members.value.some(member=>editorMemberInputs(member).includes(kind))))
const planExecutionLabel=(value:SceneExecution)=>value==='single'?'单模型':value==='sync'?'同步（仅配置）':'异步（仅配置）'
const sceneInputOptions:SceneInputType[]=['image','video']
function setSceneInput(kind:SceneInputType,checked:unknown){
  if(kind==='image')form.image=checked===true;else form.video=checked===true
  if(dialog.value==='create'){
    for(const member of members.value){
      const allowed=memberInputOptions(member),retained=memberInputs(member).filter(input=>allowed.includes(input))
      member.inputTypes=retained.length?retained:allowed
    }
  }
  planDraft.inputTypes=planDraft.inputTypes.filter(input=>planInputOptions.value.includes(input))
  if(!planDraft.inputTypes.length)planDraft.inputTypes=planInputOptions.value.slice(0,1)
  localError.value=''
}
function begin(mode:'create'|'details'|'members',scene?:Scene){
  if(!canManage.value||needsReload.value)return
  const alreadyVisible=dialog.value!==null||detailId.value!==null||review.value!==null
  detailId.value=null
  resetMutation();localError.value='';selected.value=scene??null;dialog.value=mode
  Object.assign(form,{id:scene?.sceneId??'',name:scene?.name??'',image:scene?.inputTypes.includes('image')??true,video:scene?.inputTypes.includes('video')??true,enabled:scene?.enabled??true})
  members.value=(scene?.models??[]).map(member=>({...member,inputTypes:memberInputs(member)}))
  plans.value=(scene?.plans??[]).map(plan=>({...plan,inputTypes:[...plan.inputTypes],memberIds:[...plan.memberIds]}))
  projectModelId.value='';execution.value='single'
  resetPlanDraft()
  if(alreadyVisible)void reloadInventory()
}
function add(){
  const choice=chosen.value;if(!choice||!choice.assignment.enabled)return
  if(members.value.some(member=>member.projectModelId===choice.assignment.projectModelId)){localError.value='该项目模型已在当前场景中。';return}
  if(members.value.length>=100){localError.value='场景最多保存 100 个模型成员。';return}
  const inputs=inputTypes().filter(kind=>modelInputs(choice.model).includes(kind))
  if(!inputs.length){localError.value='所选模型不支持当前场景的输入类型，请调整场景输入或选择其他项目模型。';return}
  members.value.push({memberId:'member-'+crypto.randomUUID(),projectModelId:choice.assignment.projectModelId,modelId:choice.assignment.modelId,version:choice.assignment.modelVersion,target:choice.assignment.target,position:members.value.length,inputTypes:inputs,execution:execution.value,parameterRevision:choice.assignment.parameterRevision})
  projectModelId.value='';localError.value=''
}
function move(index:number,offset:number){const next=index+offset;if(next<0||next>=members.value.length)return;const row=members.value.splice(index,1)[0]!;members.value.splice(next,0,row)}
function remove(index:number){
  const removed=members.value[index];if(!removed)return
  const removedId=memberId(removed)
  members.value.splice(index,1)
  plans.value=plans.value.map(plan=>({...plan,memberIds:plan.memberIds.filter(id=>id!==removedId)}))
  if(planDraft.memberIds.includes(removedId))planDraft.memberIds=planDraft.memberIds.filter(id=>id!==removedId)
}
function refreshMember(index:number){
  const member=members.value[index],choice=member&&memberModel(member)
  if(!member||!choice?.assignment.enabled){localError.value='该项目模型已停用或移除，请移除成员后重新选择。';return}
  const allowed=memberInputOptions(member),retained=memberInputs(member).filter(kind=>allowed.includes(kind))
  members.value[index]={...member,parameterSnapshot:undefined,modelId:choice.assignment.modelId,version:choice.assignment.modelVersion,target:choice.assignment.target,parameterRevision:choice.assignment.parameterRevision,inputTypes:retained.length?retained:allowed}
  localError.value=''
}
function setMemberInput(member:SceneMember,kind:SceneInputType,checked:unknown){
  const supported=memberInputOptions(member);const current=memberInputs(member)
  if(!supported.includes(kind))return
  const next=checked?[...new Set([...current,kind])]:current.filter(value=>value!==kind)
  if(!next.length){localError.value='每个模型成员至少保留一种输入能力。';return}
  member.inputTypes=next
  if(plans.value.some(plan=>plan.inputTypes.some(input=>plan.memberIds.some(id=>{
    const selected=members.value.find(row=>memberId(row)===id);return !selected||!memberInputs(selected).includes(input)
  })))
  )localError.value='成员输入能力变更使现有方案失效，请先编辑方案输入或恢复成员能力。'
}
function resetPlanDraft(){
  planEditingId.value=null
  Object.assign(planDraft,{planId:'',name:'',inputTypes:inputTypes().slice(0,1),memberIds:[],execution:'single',enabled:true,cameraPolicy:defaultCameraPolicy()})
}
function editPlan(plan:ScenePlan){
  planEditingId.value=plan.planId
  Object.assign(planDraft,{planId:plan.planId,name:plan.name,inputTypes:[...plan.inputTypes],memberIds:[...plan.memberIds],execution:plan.execution,enabled:plan.enabled,cameraPolicy:{...(plan.cameraPolicy??defaultCameraPolicy())}})
  planDraft.inputTypes=planDraft.inputTypes.filter(kind=>planInputOptions.value.includes(kind))
  if(!planDraft.inputTypes.length&&planInputOptions.value.length)planDraft.inputTypes=[planInputOptions.value[0]]
}
function togglePlanMember(id:string,checked:unknown){
  planDraft.memberIds=checked?[...new Set([...planDraft.memberIds,id])]:planDraft.memberIds.filter(value=>value!==id)
  planDraft.inputTypes=planDraft.inputTypes.filter(kind=>planInputOptions.value.includes(kind))
  if(!planDraft.inputTypes.length&&planInputOptions.value.length)planDraft.inputTypes=[planInputOptions.value[0]]
}
function togglePlanInput(kind:SceneInputType,checked:unknown){
  if(!planInputOptions.value.includes(kind))return
  planDraft.inputTypes=checked?[...new Set([...planDraft.inputTypes,kind])]:planDraft.inputTypes.filter(value=>value!==kind)
}
function savePlanDraft(){
  const id=planDraft.planId.trim(),name=planDraft.name.trim()
  if(!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(id)){localError.value='方案 ID 使用字母、数字、点、下划线或连字符。';return}
  if(!name||!planDraft.memberIds.length||!planDraft.inputTypes.length){localError.value='方案需要名称、至少一个成员和一种输入能力。';return}
  if(planDraft.execution==='single'&&planDraft.memberIds.length!==1){localError.value='单模型方案只能选择一个成员；多成员请使用同步或异步（仅配置）。';return}
  if(planDraft.inputTypes.some(kind=>!planInputOptions.value.includes(kind))){localError.value='所选成员不支持方案声明的全部输入能力。';return}
  if(plans.value.some(plan=>plan.planId===id&&plan.planId!==planEditingId.value)){localError.value='方案 ID 已存在，请使用其他 ID。';return}
  const policyError=cameraPolicyError(planDraft.cameraPolicy)
  if(planDraft.inputTypes.includes('video')&&policyError){localError.value=policyError;return}
  const next:ScenePlan={planId:id,name,inputTypes:[...planDraft.inputTypes],memberIds:[...planDraft.memberIds],execution:planDraft.execution,enabled:planDraft.enabled,cameraPolicy:{...planDraft.cameraPolicy}}
  if(planEditingId.value){const index=plans.value.findIndex(plan=>plan.planId===planEditingId.value);if(index>=0)plans.value.splice(index,1,next)}else plans.value.push(next)
  resetPlanDraft();localError.value=''
}
function removePlan(plan:ScenePlan){
  plans.value=plans.value.filter(item=>item.planId!==plan.planId)
  if(planEditingId.value===plan.planId)resetPlanDraft()
}
async function save(){
  if(!canManage.value)return
  if(inventoryLoading.value||inventoryError.value){localError.value=inventoryError.value||'请等待项目模型核验完成';return}
  localError.value=''
  if(invalidMembers.value.length){localError.value='场景包含已停用或已移除的项目模型，请先移除这些成员。';return}
  if(members.value.some(memberNeedsRefresh)){localError.value='项目模型参数已更新，请先同步最新修订，再保存场景。';return}
  const ordered=members.value.map((m,position)=>memberPayload(m,position,memberId(m),memberInputs(m)))
  // Read models may include server-derived fields (for example implicit and
  // executionSupported). The write contract is intentionally narrower, so
  // project each plan onto the accepted request fields instead of spreading it.
  const planPayload=plans.value.map(toPlanPayload)
  if(dialog.value!=='members'&&(!form.name.trim()||!inputTypes().length)){localError.value='请输入名称并选择至少一种输入类型。';return}
  if(dialog.value!=='details'&&!ordered.length){localError.value='场景至少包含一个模型。';return}
  if(dialog.value==='create'&&!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(form.id)){localError.value='场景 ID 使用字母、数字、点、下划线或连字符。';return}
  const invalidInput=members.value.find(member=>{
    const inputs=editorMemberInputs(member),allowed=memberInputOptions(member)
    return !inputs.length||inputs.some(kind=>!allowed.includes(kind))
  })
  if(invalidInput){localError.value=`模型「${invalidInput.modelId}」没有与当前场景兼容的输入类型，或包含未支持的输入。请调整场景输入或管理模型成员后保存。`;return}
  const invalidPlan=plans.value.find(plan=>!plan.inputTypes.length||plan.inputTypes.some(kind=>!inputTypes().includes(kind)||plan.memberIds.some(id=>{
    const member=members.value.find(row=>memberId(row)===id);return !member||!editorMemberInputs(member).includes(kind)
  })))
  if(invalidPlan){localError.value=`方案「${invalidPlan.name}」的输入能力与场景或成员不一致，请编辑或移除该方案后保存。`;return}
  const current=selected.value,mode=dialog.value
  if(mode==='create'){
    await run(signal=>scenesApi.create({sceneId:form.id,name:form.name.trim(),inputTypes:inputTypes(),models:ordered,plans:planPayload,enabled:form.enabled,expectedRevision:0},signal),()=>{dialog.value=null})
    return
  }
  if(!current)return
  const originalMembers=current.models.map(member=>memberPayload(member,member.position,memberId(member),memberInputs(member)))
  const originalPlans=(current.plans??[]).map(toPlanPayload)
  const membersChanged=JSON.stringify(originalMembers)!==JSON.stringify(ordered)
  const plansChanged=JSON.stringify(originalPlans)!==JSON.stringify(planPayload)
  const metadataChanged=mode==='details' && (current.name!==form.name.trim()||current.enabled!==form.enabled||JSON.stringify(current.inputTypes)!==JSON.stringify(inputTypes()))
  if(!membersChanged&&!plansChanged&&!metadataChanged){dialog.value=null;return}
  await run(async signal=>{
    let revision=current.revision
    const saveMembers=async()=>{if(membersChanged){const result=await scenesApi.members(current.sceneId,ordered,revision,signal);revision=result.revision}}
    const savePlans=async()=>{if(plansChanged){const result=await scenesApi.plans(current.sceneId,planPayload,revision,signal);revision=result.revision}}
    if(mode==='members'){
      const removedIds=new Set(originalMembers.map(member=>member.memberId).filter(id=>!ordered.some(member=>member.memberId===id)))
      const plansNeedCleanup=removedIds.size>0&&originalPlans.some(plan=>plan.memberIds.some(id=>removedIds.has(id)))
      if(plansNeedCleanup){await savePlans();await saveMembers()}else{await saveMembers();await savePlans()}
    }else{
      await saveMembers()
      if(metadataChanged||plansChanged){const result=await scenesApi.patch(current.sceneId,{name:form.name.trim(),inputTypes:inputTypes(),enabled:form.enabled,plans:plansChanged?planPayload:undefined,expectedRevision:revision},signal);revision=result.revision}
    }
  },()=>{dialog.value=null})
}
async function toggle(scene:Scene){if(canManage.value)await run(signal=>scenesApi.patch(scene.sceneId,{enabled:!scene.enabled,expectedRevision:scene.revision},signal),()=>{})}
function beginReview(scene:Scene,again=false){if(!canApprove.value||needsReload.value)return;detailId.value=null;resetMutation();review.value=scene;reapprove.value=again;reviewReason.value=''}
async function approve(){const scene=review.value;if(!scene||!canApprove.value||!reviewReason.value.trim())return;await run(signal=>scenesApi.approve(scene.sceneId,reapprove.value||!scene.approved,scene.revision,reviewReason.value.trim(),signal),()=>{review.value=null})}
onMounted(refresh)
</script>
<template>
  <section class="model-workspace scene-workspace">
    <div class="model-actions page-actions"><UiButton class="secondary-button" :disabled="busy" @click="refresh"><RefreshCw :size="16"/>刷新场景</UiButton><UiButton v-if="canManage" class="primary-button" :disabled="busy||needsReload" @click="begin('create')"><Plus :size="16"/>创建场景</UiButton></div>
    <aside class="scene-boundary"><Layers3 :size="18"/><p>从项目模型选择成员，配置场景专属方案；保存场景不会自动启动运行。</p></aside>
    <p v-if="notice" class="operation-feedback is-success" role="status">{{notice}}</p><p v-if="mutationError" class="operation-feedback is-error" role="alert">{{mutationError}}</p>
    <UiStatePanel v-if="loading" state="loading"/><UiStatePanel v-else-if="error" state="error" :message="error" @retry="refresh"/>
    <UiStatePanel v-else-if="!data.scenes.length" state="empty" title="暂无可见场景" :message="canManage?'创建场景并添加已发布模型，再明确批准供项目成员使用。':'项目负责人批准场景后，将在此处显示。'"/>
    <div v-else class="scene-list">
      <p class="scene-list-caption">共 {{data.scenes.length}} 个场景<span>{{canManage||canApprove?'查看详情可管理成员、运行方案和审批':'查看详情了解模型成员和运行方案'}}</span></p>
      <UiDataTable :columns="sceneColumns" :rows="sceneRows" row-key="sceneId" caption="项目识别场景列表">
        <template #cell-name="{row:scene}"><div class="scene-list-name"><strong :title="scene.name">{{scene.name}}</strong><code :title="scene.sceneId">{{scene.sceneId}} · REV {{scene.revision}}</code></div></template>
        <template #cell-status="{row:scene}"><UiTag :tone="scene.approved&&scene.enabled?'success':'info'">{{!scene.enabled?'已停用':scene.approved?'已批准':'待批准'}}</UiTag></template>
        <template #cell-inputs="{row:scene}"><span class="scene-list-inputs">{{scene.inputTypes.map((type:SceneInputType)=>type==='image'?'图片识别':'视频识别').join(' / ')}}</span></template>
        <template #cell-models="{row:scene}">{{scene.models.length}}</template>
        <template #cell-plans="{row:scene}">{{scene.plans?.length||0}}</template>
        <template #cell-actions="{row:scene}"><div v-if="scene.sceneId" class="scene-row-actions">
          <UiButton v-if="canManage" type="button" class="secondary-button" :aria-label="`编辑场景 ${scene.name}`" :disabled="busy||needsReload" @click="begin('details',scene as unknown as Scene)">编辑</UiButton>
          <UiButton v-if="canManage" type="button" class="secondary-button" :aria-label="`${scene.enabled?'停用':'启用'}场景 ${scene.name}`" :disabled="busy||needsReload" @click="toggle(scene as unknown as Scene)">{{scene.enabled?'停用':'启用'}}</UiButton>
          <UiButton v-if="canApprove&&(scene.enabled||scene.approved)" type="button" class="secondary-button" :aria-label="`${scene.approved?'撤销批准':'批准场景'} ${scene.name}`" :disabled="busy||needsReload" @click="beginReview(scene as unknown as Scene)">{{scene.approved?'撤销':'批准'}}</UiButton>
          <UiButton type="button" class="secondary-button" :aria-label="`查看详情 ${scene.name}`" @click="detailId=scene.sceneId">详情</UiButton>
        </div></template>
      </UiDataTable>
    </div>
    <UiDialog :open="!!detailScene&&!error" title="场景详情" :busy="busy" @update:open="value=>{if(!value)detailId=null}"><article v-if="detailScene" class="model-detail scene-detail">
      <p v-if="inventoryLoading" role="status">正在读取项目模型…</p><p v-if="inventoryError" role="alert">{{inventoryError}} <UiButton @click="reloadInventory">重试模型候选</UiButton></p>
      <template v-for="scene in [detailScene]" :key="scene.sceneId">
      <header class="model-card-title"><Layers3 :size="22"/><div><h3>{{scene.name}}</h3><code>{{scene.sceneId}} · REV {{scene.revision}}</code></div><UiTag :tone="scene.approved&&scene.enabled?'success':'info'">{{!scene.enabled?'已停用':scene.approved?'已批准':'待批准'}}</UiTag></header>
      <p v-if="notice" class="operation-feedback is-success" role="status">{{notice}}</p><p v-if="mutationError" class="operation-feedback is-error" role="alert">{{mutationError}}</p>
      <div class="model-tags"><UiTag v-for="type in scene.inputTypes" :key="type">{{type==='image'?'图片识别':'视频识别'}}</UiTag><span>{{scene.models.length}} 个项目模型成员 · {{scene.plans?.length||0}} 个运行方案</span></div>
      <div class="model-actions scene-detail-actions"><UiButton v-if="canManage" class="secondary-button" :disabled="busy||needsReload" @click="begin('members',scene)">管理模型成员</UiButton><UiButton v-if="canApprove&&scene.approved&&scene.enabled" class="secondary-button" :disabled="busy||needsReload" @click="beginReview(scene,true)">重新批准参数</UiButton></div>
      <section class="scene-surface"><header><div><span class="scene-section-kicker">成员清单</span><strong>项目模型成员</strong></div><small>同一项目模型可被多个场景复用</small></header><ol class="scene-members"><li v-for="member in scene.models" :key="memberId(member)"><span class="scene-index">{{member.position+1}}</span><div><strong>{{memberName(member)}}</strong><code>{{member.version}} · {{member.target==='pc'?'PC 端':'移动端'}} · 参数 r{{member.parameterRevision}}</code><small>{{(member.inputTypes||scene.inputTypes).map(type=>type==='image'?'图片':'本机相机连续帧').join(' / ')}}</small><small class="scene-inventory-id">项目模型 ID · {{member.projectModelId}}</small><small v-if="pendingProfile(member)">待审档案修订 {{pendingProfile(member)!.revision}} · 已批准 {{member.parameterSnapshot?.revision??'无'}}</small><UiButton v-if="canManage&&caps.models.value" class="secondary-button" :disabled="busy||needsReload||!memberModel(member)" :aria-label="`配置待审参数 ${memberId(member)}`" @click="editParameters(scene,member)">配置待审参数</UiButton></div></li></ol></section>
      <section class="scene-plan-summary"><header><strong>运行方案（{{scene.plans?.length||0}}）</strong><small>方案只选择成员，不复制模型资产</small></header><p v-if="!scene.plans?.length" class="model-muted">尚未配置方案。</p><ul v-else><li v-for="plan in scene.plans" :key="plan.planId" class="scene-plan-status"><div><strong>{{plan.name}}</strong><code>{{plan.planId}} · {{plan.memberIds.length}} 个成员 · {{planExecutionLabel(plan.execution)}}</code><UiTag :tone="planStatus(scene,plan).startsWith('可使用')?'success':'info'">{{planStatus(scene,plan)}}</UiTag><details class="scene-approved-parameters"><summary>逐成员获准参数（{{plan.memberIds.length}}）</summary><div v-for="member in approvedPlanMembers(scene,plan)" :key="memberId(member)"><code>{{memberId(member)}} · {{memberName(member)}} / {{member.version}} · {{member.target}}</code><template v-if="scene.approved&&planParameter(plan,member)"><p>获准修订 {{planParameter(plan,member)!.revision}} · 置信度 {{planParameter(plan,member)!.detection.confidenceThreshold}} · IoU {{planParameter(plan,member)!.detection.iouThreshold}} · 最多 {{planParameter(plan,member)!.detection.maxDetections}} 项</p><pre>{{JSON.stringify(planParameter(plan,member),null,2)}}</pre></template><p v-else>尚无获准快照，批准后按成员冻结。</p></div></details></div></li></ul><p class="model-muted">已配置不等于客户端可运行。联合方案要求 v3 及匹配模式能力；旧客户端继续拒绝。同步表示等待成员结果，不保证物理并行；后台不执行推理。</p></section>
      <p class="model-muted">{{scene.executionSupported?'各端单模型配置可预检；双端部署不等于多模型识别。运行仍沿用原有链路。':'按运行端判断可预检能力；同端多模型或同步/异步执行尚未支持。'}}</p>
      <div v-if="canManage" class="model-actions"><UiButton class="secondary-button danger-text" :disabled="busy||needsReload" @click="beginRemoval(scene)">删除场景</UiButton></div>
      </template>
    </article></UiDialog>
    <UiDialog :open="!!removal" title="云端软删除场景" :busy="busy" @update:open="value=>{if(!value)removal=null}"><form class="model-form" @submit.prevent="removeScene">
      <p>{{removal?.scene.name}} · 修订 {{removal?.impact.expectedRevision}}</p>
      <p v-if="removal">{{removalSummary(removal.impact)}}</p>
      <p>停用可以在重新审核后启用；删除会永久退役这个场景 ID，不能编辑或恢复。成员与方案保留审计，不级联删除模型资产。</p>
      <p>已下载文件不会被远程擦除。App 在后续在线核验后拒绝受影响授权，用户可另行清理；离线设备无法即时收到变化。</p>
      <label class="model-check"><UiInput v-model="removalChecked" type="checkbox" :disabled="busy||needsReload"/>我已确认影响，执行云端软删除</label>
      <p v-if="mutationError" role="alert">{{mutationError}}</p><footer><UiButton type="button" class="secondary-button" :disabled="busy" @click="removal=null">取消</UiButton><UiButton class="primary-button" :disabled="busy||needsReload||!removalChecked||!removal?.impact.safeToRemove">确认删除场景</UiButton></footer>
    </form></UiDialog>
    <UiDialog :open="dialog!==null" :title="dialog==='create'?'创建项目场景':dialog==='members'?'管理场景模型成员':'编辑项目场景'" :busy="busy" @update:open="value=>{if(!value)dialog=null}"><form class="model-form" @submit.prevent="save">
      <p v-if="inventoryLoading" role="status">正在读取项目模型…</p><p v-if="inventoryError" role="alert">{{inventoryError}} <UiButton type="button" @click="reloadInventory">重试模型候选</UiButton></p>
      <fieldset :disabled="busy||needsReload||!canManage||inventoryLoading||!!inventoryError"><template v-if="dialog!=='members'"><label v-if="dialog==='create'">场景 ID<UiInput v-model="form.id" required maxlength="128"/></label><label>场景名称<UiInput v-model="form.name" required maxlength="255"/></label><div class="scene-inputs"><label class="model-check"><UiInput :model-value="form.image" type="checkbox" @update:model-value="value=>setSceneInput('image',value)"/>适用图片</label><label class="model-check"><UiInput :model-value="form.video" type="checkbox" @update:model-value="value=>setSceneInput('video',value)"/>适用视频</label><label class="model-check"><UiInput v-model="form.enabled" type="checkbox"/>启用场景</label></div><p class="model-muted">成员输入取场景与模型支持能力的交集；调整场景输入后，请核对已有运行方案。</p></template>
      <template v-if="dialog!=='details'"><section class="scene-inventory-picker"><header><div><span class="scene-section-kicker">第一步</span><h4>从项目模型清单添加成员</h4></div><UiTag tone="info">{{inventoryChoices.filter(item=>item.assignment.enabled).length}} 个可用</UiTag></header><label>项目模型<UiSelect v-model="projectModelId"><UiOption value="">选择已分配模型</UiOption><UiOption v-for="item in inventoryChoices" :key="item.assignment.projectModelId" :value="item.assignment.projectModelId" :disabled="!item.assignment.enabled||members.some(member=>member.projectModelId===item.assignment.projectModelId)">{{modelDisplayName(item.model)}} / {{item.assignment.modelVersion}} · {{item.assignment.target==='pc'?'PC 端':'移动端'}} · {{item.assignment.enabled?'参数 r'+item.assignment.parameterRevision:'已停用'}}</UiOption></UiSelect></label>
        <p v-if="!inventoryLoading&&!inventoryError&&!inventoryChoices.length" class="scene-picker-empty">项目模型清单为空。请先在“项目模型”分配并启用模型，再返回配置场景。</p><p v-else class="model-muted">每个选项就是一个精确的项目模型清单项，目标端已经确定；停用项或已加入成员不可重复选择。</p>
        <label>成员执行声明<UiSelect v-model="execution"><UiOption value="single">单模型</UiOption><UiOption value="sync">同步（仅配置）</UiOption><UiOption value="async">异步（仅配置）</UiOption></UiSelect></label><UiButton type="button" class="secondary-button" :disabled="!chosen||!chosen.assignment.enabled||members.length>=100" @click="add">添加项目模型成员</UiButton></section>
        <section class="scene-surface scene-editor-members"><header><div><span class="scene-section-kicker">第二步</span><strong>场景成员（{{members.length}}）</strong></div><small>调整顺序与输入能力</small></header><p v-if="!members.length" class="scene-picker-empty">尚未添加成员。场景不会自动继承全部项目模型。</p><ol v-else class="scene-members editable"><li v-for="(member,index) in members" :key="memberKey(member)"><span class="scene-index">{{index+1}}</span><div><strong>{{memberName(member)}}</strong><code>{{member.version}} · {{member.target==='pc'?'PC 端':'移动端'}} · 参数 r{{member.parameterRevision}}</code><small class="scene-inventory-id">{{member.projectModelId}}</small><div class="scene-member-inputs"><span>成员输入：</span><label v-for="kind in sceneInputOptions" :key="kind" class="model-check"><UiInput type="checkbox" :model-value="memberInputs(member).includes(kind)" :disabled="!memberInputOptions(member).includes(kind)" @update:model-value="value=>setMemberInput(member,kind,value)"/>{{kind==='image'?'图片':'本机相机连续帧'}}</label></div><small v-if="!memberInputs(member).length" class="danger-text">没有与当前场景兼容的输入类型，请调整场景输入或移除此成员。</small></div><div class="model-actions"><UiButton type="button" class="secondary-button" :disabled="index===0" :aria-label="`上移成员 ${index+1}`" @click="move(index,-1)">↑</UiButton><UiButton type="button" class="secondary-button" :disabled="index===members.length-1" :aria-label="`下移成员 ${index+1}`" @click="move(index,1)">↓</UiButton><UiButton type="button" class="secondary-button danger-text" :aria-label="`移除成员 ${index+1}`" @click="remove(index)">移除</UiButton></div></li></ol></section>
        <div v-if="!inventoryLoading&&!inventoryError&&(invalidMembers.length||members.some(memberNeedsRefresh))" class="scene-member-warning" role="status"><p v-if="invalidMembers.length">存在已停用或已移除的项目模型成员，请移除这些成员后再保存。</p><template v-for="(member,index) in members" :key="memberKey(member)"><p v-if="memberNeedsRefresh(member)&&memberInventory(member)?.enabled">{{memberName(member)}} / {{member.version}} 参数已更新为 r{{memberInventory(member)?.parameterRevision}}，当前场景成员仍是 r{{member.parameterRevision}}。<UiButton type="button" class="secondary-button" :aria-label="`同步最新修订 ${index+1}`" @click="refreshMember(index)">同步最新修订</UiButton></p></template></div>
      </template>
      <section v-if="dialog!=='create'||members.length" class="scene-plan-editor"><header><div><h4>运行方案</h4><p class="model-muted">选择成员和输入能力形成可复用方案；方案复用成员引用，不复制模型资产。</p></div><UiTag v-if="plans.some(plan=>plan.execution!=='single')" tone="info">多模型方案当前仅配置，不可运行</UiTag></header><p class="scene-capability-summary"><strong>当前套件能力</strong><span v-for="kind in suiteCapabilities" :key="kind">{{kind==='image'?'图片':'本机相机连续帧'}}</span><small>方案只能选择成员共同支持的输入能力。</small></p><ul class="scene-plan-list"><li v-for="plan in plans" :key="plan.planId"><div><strong>{{plan.name}}</strong><code>{{plan.planId}} · {{plan.memberIds.length}} 个成员 · {{planExecutionLabel(plan.execution)}}</code></div><div class="model-actions"><UiTag :tone="plan.execution==='single'?'success':'info'">{{plan.execution==='single'?'单成员可预检':'仅配置'}}</UiTag><UiButton type="button" class="secondary-button" :aria-label="`编辑方案 ${plan.name}`" @click="editPlan(plan)">编辑</UiButton><UiButton type="button" class="secondary-button danger-text" :aria-label="`移除方案 ${plan.name}`" @click="removePlan(plan)">移除</UiButton></div></li></ul><div class="scene-plan-draft"><label>方案 ID<UiInput v-model="planDraft.planId" maxlength="128" placeholder="例如 image-safety"/></label><label>方案名称<UiInput v-model="planDraft.name" maxlength="255" placeholder="例如静态识别"/></label><div class="scene-plan-options"><span>方案输入</span><label v-for="kind in sceneInputOptions" :key="kind" class="model-check"><UiInput type="checkbox" :model-value="planDraft.inputTypes.includes(kind)" :disabled="!planInputOptions.includes(kind)" @update:model-value="value=>togglePlanInput(kind,value)"/>{{kind==='image'?'图片':'本机相机连续帧'}}</label></div><div class="scene-plan-options"><span>方案成员</span><label v-for="member in members" :key="memberId(member)" class="model-check"><UiInput type="checkbox" :model-value="planDraft.memberIds.includes(memberId(member))" @update:model-value="value=>togglePlanMember(memberId(member),value)"/>{{memberName(member)}} / {{member.version}} · {{member.target==='pc'?'PC':'移动端'}}</label></div><CameraPolicyFields v-if="planDraft.inputTypes.includes('video')" v-model="planDraft.cameraPolicy"/><label>执行方式<UiSelect v-model="planDraft.execution"><UiOption value="single">单模型</UiOption><UiOption value="sync">同步（仅配置）</UiOption><UiOption value="async">异步（仅配置）</UiOption></UiSelect></label><label class="model-check"><UiInput v-model="planDraft.enabled" type="checkbox"/>启用方案</label><div class="model-actions"><UiButton type="button" class="secondary-button" :disabled="!members.length" @click="savePlanDraft">{{planEditingId?'更新方案':'添加运行方案'}}</UiButton><UiButton v-if="planEditingId" type="button" class="secondary-button" @click="resetPlanDraft">取消编辑方案</UiButton></div></div></section></fieldset><p class="model-muted">保存后清除先前批准并生成新的修订快照。冲突时保留草稿，关闭并刷新核验后再操作；不会自动覆盖。</p><p v-if="localError||mutationError" class="operation-feedback is-error" role="alert">{{localError||mutationError}}</p><footer><UiButton type="button" class="secondary-button" :disabled="busy" @click="dialog=null">取消</UiButton><UiButton class="primary-button" :disabled="busy||needsReload||!canManage||inventoryLoading||!!inventoryError">{{dialog==='create'?'保存新场景':'保存场景变更'}}</UiButton></footer>
    </form></UiDialog>
    <UiDialog :open="!!review" title="审核场景可用性" :busy="busy" @update:open="value=>{if(!value)review=null}"><form class="model-form" @submit.prevent="approve"><p>{{review?.name}} · 修订 {{review?.revision}} · {{review?.models.length}} 个模型</p><p class="model-muted">{{review?.approved&&!reapprove?'撤销后项目成员不能继续读取或下载该场景产物。':'批准当前精确版本、目标端和待审项目参数；生成新场景修订并废止旧修订链接。服务器再次校验产物及当前权限，不启动推理。'}}</p><template v-if="review&&(!review.approved||reapprove)"><div v-for="member in review.models" :key="memberId(member)" class="scene-review-profile"><code>{{memberId(member)}} · {{memberName(member)}} / {{member.version}} · {{member.target}}</code><template v-if="pendingProfile(member)"><p>待审修订 {{pendingProfile(member)!.revision}} · 置信度 {{pendingProfile(member)!.detection.confidenceThreshold}} · IoU {{pendingProfile(member)!.detection.iouThreshold}}</p><details><summary>核对完整待审参数</summary><pre>{{JSON.stringify(pendingProfile(member),null,2)}}</pre></details></template><p v-else>未取得待审参数，服务器在批准时重新核验；如有疑问请取消并刷新。</p></div></template><label>审核原因<UiInput v-model="reviewReason" required maxlength="512" :disabled="busy||needsReload"/></label><p v-if="mutationError" class="operation-feedback is-error" role="alert">{{mutationError}}</p><footer><UiButton type="button" class="secondary-button" :disabled="busy" @click="review=null">取消</UiButton><UiButton class="primary-button" :disabled="busy||needsReload||!canApprove||!reviewReason.trim()">{{review?.approved&&!reapprove?'确认撤销':reapprove?'确认重新批准':'确认批准'}}</UiButton></footer></form></UiDialog>
    <ParametersDialog v-if="parameterSelection" :model="parameterSelection.model" project-mode :initial-platform="parameterSelection.member.target==='mobile'?'android':'server'" :scene-binding="{sceneId:parameterSelection.scene.sceneId,memberId:memberId(parameterSelection.member),revision:parameterSelection.scene.revision}" @close="parameterSelection=null;refresh()"/>
  </section>
</template>
