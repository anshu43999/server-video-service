<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ChevronDown, Layers3, Plus, RefreshCw } from '@lucide/vue'
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
import { memberPayload, planPayload as toPlanPayload, planParameter, planStatus, planCapability } from './presentation'
import { modelDisplayName } from '../models/presentation'
import '../models/models.css'
import './scenes.css'
import CameraPolicyFields from './CameraPolicyFields.vue'
import CreatePlanFields from './CreatePlanFields.vue'
import SceneExecutionHelp from './SceneExecutionHelp.vue'
import { defaultCameraPolicy, cameraPolicyError } from './cameraPolicy'
import { automaticScenePlans } from './automaticPlans'
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
  {key:'actions',label:'操作',minWidth:280,fixed:'right'},
]
const dialog=ref<'create'|'details'|'members'|null>(null),selected=ref<Scene|null>(null),localError=ref('')
const form=reactive({id:'',name:'',image:true,video:true,enabled:true})
const createAdvanced=ref(false),customPlans=ref(false)
const jointExecution=ref<'sync'|'async'>('sync')
const quickCreate=computed(()=>dialog.value==='create'&&!createAdvanced.value)
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
const parametersReady=(assignment:Assignment)=>assignment.parameterPublished===true
const availableChoices=computed(()=>inventoryChoices.value.filter(item=>item.assignment.enabled&&parametersReady(item.assignment)))
const unpublishedChoices=computed(()=>inventoryChoices.value.filter(item=>item.assignment.enabled&&item.assignment.parameterPublished===false))
const parameterStatus=(assignment:Assignment|undefined)=>!assignment?'参数状态待核实':assignment.parameterPublished===false?'平台参数尚未发布':parametersReady(assignment)?'平台参数 r'+assignment.parameterRevision:'参数状态待核实'
const inventoryLabel=(item:InventoryChoice)=>`${modelDisplayName(item.model)} / ${item.assignment.modelVersion} · ${item.assignment.target==='pc'?'PC 端':'移动端（Android）'}`
const chosen=computed(()=>inventoryChoices.value.find(item=>item.assignment.projectModelId===projectModelId.value))
const parameterSelection=ref<{scene:Scene;member:SceneMember;model:AssignedModel}|null>(null)
function viewParameters(scene:Scene,member:SceneMember){
  const model=memberModel(member)?.model
  if(!canManage.value||!model||!member.memberId||needsReload.value)return
  detailId.value=null;parameterSelection.value={scene,member,model}
}
const platformProfile=(member:SceneMember)=>member.parameterSnapshot
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
const invalidMembers=computed(()=>members.value.filter(member=>!memberInventory(member)?.enabled))
const unverifiedParameterMembers=computed(()=>members.value.filter(member=>{
  const assignment=memberInventory(member)
  return assignment?.enabled&&!parametersReady(assignment)
}))
const planMembers=computed(()=>members.value.filter(member=>planDraft.memberIds.includes(memberId(member))))
const planInputOptions=computed<SceneInputType[]>(()=>{
  return inputTypes().filter(kind=>planMembers.value.every(member=>editorMemberInputs(member).includes(kind)))
})
const suiteCapabilities=computed<SceneInputType[]>(()=>inputTypes().filter(kind=>members.value.some(member=>editorMemberInputs(member).includes(kind))))
// One creation plan covers every selected member; unsupported combinations never
// silently fall back to separate single-model runs. Existing plans stay untouched.
const automaticConfiguration=computed(()=>automaticScenePlans(members.value.map(member=>({
  ...member,memberId:memberId(member),inputTypes:memberInputs(member),
})),inputTypes(),jointExecution.value))
const automaticPlans=computed(()=>automaticConfiguration.value.plans)
const automaticPlanIssue=computed(()=>dialog.value==='create'&&!customPlans.value?automaticConfiguration.value.issue:'')
const effectivePlans=computed(()=>dialog.value==='create'&&!customPlans.value?automaticPlans.value:plans.value)
function customizePlans(){
  if(dialog.value!=='create'||customPlans.value)return
  plans.value=automaticPlans.value.map(plan=>toPlanPayload(plan))
  customPlans.value=true
}
const expandedPlan=ref<number|null>(null)
const inlinePlanMembers=computed(()=>members.value.map(member=>({id:memberId(member),label:`${memberName(member)} / ${member.version} · ${member.target==='pc'?'PC':'移动端'}`,inputs:editorMemberInputs(member)})))
function changeInlinePlan(index:number,patch:Partial<ScenePlan>){
  // Switching the automatic joint mode is the same action in either view.
  if(dialog.value==='create'&&!customPlans.value&&Object.keys(patch).length===1&&members.value.length>1&&(patch.execution==='sync'||patch.execution==='async')){
    jointExecution.value=patch.execution;return
  }
  customizePlans()
  Object.assign(plans.value[index]!,patch)
  localError.value=''
}
function addInlinePlan(){
  customizePlans()
  plans.value.push({planId:'plan-'+crypto.randomUUID(),name:'',inputTypes:inputTypes().slice(0,1),memberIds:[],execution:'single',enabled:true})
  expandedPlan.value=plans.value.length-1
  localError.value=''
}
function removeInlinePlan(index:number){
  customizePlans()
  plans.value.splice(index,1)
  if(plans.value.length===1)expandedPlan.value=0
  else if(expandedPlan.value===index)expandedPlan.value=null
  else if(expandedPlan.value!==null&&expandedPlan.value>index)expandedPlan.value--
  localError.value=''
}
function inlinePlanError(plan:ScenePlan,index:number){
  if(!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(plan.planId.trim()))return '方案 ID 使用字母、数字、点、下划线或连字符。'
  if(effectivePlans.value.slice(0,index).some(other=>other.planId.trim()===plan.planId.trim()))return '方案 ID 重复，请使用其他 ID。'
  if(!plan.name.trim())return '请填写方案名称。'
  if(!plan.memberIds.length)return '请至少选择一个方案成员。'
  if(!plan.inputTypes.length)return '请至少选择一种方案输入。'
  if(plan.execution==='single'&&plan.memberIds.length!==1)return '单模型方案只能选择一个成员，请调整成员或执行方式。'
  return plan.inputTypes.includes('video')?cameraPolicyError(plan.cameraPolicy??defaultCameraPolicy()):''
}
function selectModel(value:string|number){projectModelId.value=String(value);if(quickCreate.value&&value)add()}
const planExecutionLabel=(value:SceneExecution)=>value==='single'?'单模型':value==='sync'?'同步':'异步'
const draftPlanStatus=(plan:ScenePlan)=>{
  const capability=planCapability({inputTypes:inputTypes(),models:members.value.map(member=>({...member,memberId:memberId(member),inputTypes:editorMemberInputs(member)}))},plan)
  return capability==='single'?'单成员可预检':capability.startsWith('mobile-')?'新版 App · 双模型联合':'仅配置 · 当前端/输入未开放'
}
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
  Object.assign(form,{id:scene?.sceneId??'scene-'+crypto.randomUUID(),name:scene?.name??'',image:scene?.inputTypes.includes('image')??true,video:scene?.inputTypes.includes('video')??true,enabled:scene?.enabled??true})
  createAdvanced.value=false;customPlans.value=false;jointExecution.value='sync'
  members.value=(scene?.models??[]).map(member=>({...member,inputTypes:memberInputs(member)}))
  plans.value=(scene?.plans??[]).map(plan=>({...plan,inputTypes:[...plan.inputTypes],memberIds:[...plan.memberIds]}))
  expandedPlan.value=plans.value.length===1?0:null
  projectModelId.value='';execution.value='single'
  resetPlanDraft()
  if(alreadyVisible)void reloadInventory()
}
function add(){
  if(!canManage.value||busy.value||needsReload.value||inventoryLoading.value||inventoryError.value)return
  const choice=chosen.value;if(!choice||!choice.assignment.enabled)return
  if(!parametersReady(choice.assignment)){localError.value=`${inventoryLabel(choice)}：${parameterStatus(choice.assignment)}。请由平台管理员核对并发布该版本、该目标端参数，再刷新项目模型状态。`;return}
  if(members.value.some(member=>member.projectModelId===choice.assignment.projectModelId)){localError.value='该项目模型已在当前场景中。';return}
  if(members.value.length>=100){localError.value='场景最多保存 100 个模型成员。';return}
  const inputs=inputTypes().filter(kind=>modelInputs(choice.model).includes(kind))
  if(!inputs.length){localError.value='所选模型不支持当前场景的输入类型，请调整场景输入或选择其他项目模型。';return}
  members.value.push({memberId:'member-'+crypto.randomUUID(),projectModelId:choice.assignment.projectModelId,modelId:choice.assignment.modelId,version:choice.assignment.modelVersion,target:choice.assignment.target,position:members.value.length,inputTypes:inputs,execution:quickCreate.value?'single':execution.value,parameterRevision:choice.assignment.parameterRevision})
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
  if(planDraft.execution==='single'&&planDraft.memberIds.length!==1){localError.value='单模型方案只能选择一个成员；两个移动端视频模型可选择同步或异步，其他联合能力暂未开放。';return}
  if(planDraft.inputTypes.some(kind=>!planInputOptions.value.includes(kind))){localError.value='所选成员不支持方案声明的全部输入能力。';return}
  if(effectivePlans.value.some(plan=>plan.planId===id&&plan.planId!==planEditingId.value)){localError.value='方案 ID 已存在，请使用其他 ID。';return}
  const policyError=cameraPolicyError(planDraft.cameraPolicy)
  if(planDraft.inputTypes.includes('video')&&policyError){localError.value=policyError;return}
  const next:ScenePlan={planId:id,name,inputTypes:[...planDraft.inputTypes],memberIds:[...planDraft.memberIds],execution:planDraft.execution,enabled:planDraft.enabled,cameraPolicy:{...planDraft.cameraPolicy}}
  customizePlans()
  if(planEditingId.value){const index=plans.value.findIndex(plan=>plan.planId===planEditingId.value);if(index>=0)plans.value.splice(index,1,next)}else plans.value.push(next)
  resetPlanDraft();localError.value=''
}
function removePlan(plan:ScenePlan){
  customizePlans()
  plans.value=plans.value.filter(item=>item.planId!==plan.planId)
  if(planEditingId.value===plan.planId)resetPlanDraft()
}
async function save(){
  if(!canManage.value)return
  if(inventoryLoading.value||inventoryError.value){localError.value=inventoryError.value||'请等待项目模型核验完成';return}
  localError.value=''
  if(invalidMembers.value.length){localError.value='场景包含已停用或已移除的项目模型，请先移除这些成员。';return}
  if(unverifiedParameterMembers.value.length){localError.value='场景成员的平台参数尚未发布或状态待核实。请先由平台管理员核对并发布，再刷新项目模型状态；不能使用草稿或历史场景参数代替。';return}
  if(automaticPlanIssue.value){localError.value=automaticPlanIssue.value;return}
  const ordered=members.value.map((m,position)=>memberPayload(m,position,memberId(m),memberInputs(m)))
  // Read models may include server-derived fields (for example implicit and
  // executionSupported). The write contract is intentionally narrower, so
  // project each plan onto the accepted request fields instead of spreading it.
  const planPayload=effectivePlans.value.map(toPlanPayload)
  if(dialog.value!=='members'&&(!form.name.trim()||!inputTypes().length)){localError.value='请输入名称并选择至少一种输入类型。';return}
  if(dialog.value!=='details'&&!ordered.length){localError.value='场景至少包含一个模型。';return}
  if(dialog.value==='create'&&!planPayload.length){createAdvanced.value=true;localError.value='请至少保留一个运行方案，或添加自定义方案后再创建场景。';return}
  if(dialog.value==='create'&&!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(form.id)){createAdvanced.value=true;localError.value='场景 ID 使用字母、数字、点、下划线或连字符。';return}
  const invalidInput=members.value.find(member=>{
    const inputs=editorMemberInputs(member),allowed=memberInputOptions(member)
    return !inputs.length||inputs.some(kind=>!allowed.includes(kind))
  })
  if(invalidInput){localError.value=`模型「${invalidInput.modelId}」没有与当前场景兼容的输入类型，或包含未支持的输入。请调整场景输入或管理模型成员后保存。`;return}
  if(dialog.value==='create'||dialog.value==='details'){
    for(const [index,plan] of planPayload.entries()){
      const problem=inlinePlanError(plan,index)
      if(problem){expandedPlan.value=index;createAdvanced.value=true;localError.value=`方案 ${index+1}${plan.name.trim()?`「${plan.name.trim()}」`:''}：${problem}`;return}
      // Preserve read-back representation for unchanged plans (including legacy camera policies).
      if(dialog.value==='details'&&selected.value?.plans?.some(original=>original.planId===plan.planId&&JSON.stringify(toPlanPayload(original))===JSON.stringify(plan)))continue
      plan.planId=plan.planId.trim();plan.name=plan.name.trim()
      if(!plan.inputTypes.includes('video'))delete plan.cameraPolicy
    }
  }
  const invalidPlan=effectivePlans.value.find(plan=>!plan.memberIds.length||!plan.inputTypes.length||plan.inputTypes.some(kind=>!inputTypes().includes(kind)||plan.memberIds.some(id=>{
    const member=members.value.find(row=>memberId(row)===id);return !member||!editorMemberInputs(member).includes(kind)
  })))
  if(invalidPlan){expandedPlan.value=effectivePlans.value.indexOf(invalidPlan);createAdvanced.value=true;localError.value=`方案「${invalidPlan.name}」的输入能力与场景或成员不一致，请编辑或移除该方案后保存。`;return}
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
  const metadataChanged=mode==='details' && (current.name!==form.name.trim()||current.enabled!==form.enabled||current.inputTypes.length!==inputTypes().length||current.inputTypes.some(kind=>!inputTypes().includes(kind)))
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
          <UiButton v-if="canManage" type="button" class="secondary-button danger-text" :aria-label="`删除场景 ${scene.name}`" :disabled="busy||needsReload" @click="beginRemoval(scene as unknown as Scene)">删除场景</UiButton>
        </div></template>
      </UiDataTable>
    </div>
    <UiDialog :open="!!detailScene&&!error" title="场景详情" :busy="busy" @update:open="value=>{if(!value)detailId=null}"><article v-if="detailScene" class="model-detail scene-detail">
      <p v-if="inventoryLoading" role="status">正在读取项目模型…</p><p v-if="inventoryError" role="alert">{{inventoryError}} <UiButton @click="reloadInventory">重试模型候选</UiButton></p>
      <template v-for="scene in [detailScene]" :key="scene.sceneId">
      <header class="model-card-title"><Layers3 :size="22"/><div><h3>{{scene.name}}</h3><code>{{scene.sceneId}} · REV {{scene.revision}}</code></div><UiTag :tone="scene.approved&&scene.enabled?'success':'info'">{{!scene.enabled?'已停用':scene.approved?'已批准':'待批准'}}</UiTag></header>
      <p v-if="notice" class="operation-feedback is-success" role="status">{{notice}}</p><p v-if="mutationError" class="operation-feedback is-error" role="alert">{{mutationError}}</p>
      <div class="model-tags"><UiTag v-for="type in scene.inputTypes" :key="type">{{type==='image'?'图片识别':'视频识别'}}</UiTag><span>{{scene.models.length}} 个项目模型成员 · {{scene.plans?.length||0}} 个运行方案</span></div>
      <div class="model-actions scene-detail-actions"><UiButton v-if="canManage" class="secondary-button" :disabled="busy||needsReload" @click="begin('members',scene)">管理模型成员</UiButton></div>
      <section class="scene-surface"><header><div><span class="scene-section-kicker">成员清单</span><strong>项目模型成员</strong></div><small>同一项目模型可被多个场景复用</small></header><ol class="scene-members"><li v-for="member in scene.models" :key="memberId(member)"><span class="scene-index">{{member.position+1}}</span><div><strong>{{memberName(member)}}</strong><code>{{member.version}} · {{member.target==='pc'?'PC 端':'移动端'}} · 参数 r{{member.parameterRevision}}</code><small>{{(member.inputTypes||scene.inputTypes).map(type=>type==='image'?'图片':'本机相机连续帧').join(' / ')}}</small><small class="scene-inventory-id">项目模型 ID · {{member.projectModelId}}</small><small v-if="platformProfile(member)">平台发布修订 {{platformProfile(member)!.revision}}</small><UiButton v-if="canManage" class="secondary-button" :disabled="busy||needsReload||!memberModel(member)" :aria-label="`查看平台参数 ${memberId(member)}`" @click="viewParameters(scene,member)">查看平台参数</UiButton></div></li></ol></section>
      <section class="scene-plan-summary"><header><strong>运行方案（{{scene.plans?.length||0}}）</strong><small>方案只选择成员，不复制模型资产</small></header><p v-if="!scene.plans?.length" class="model-muted">尚未配置方案。</p><ul v-else><li v-for="plan in scene.plans" :key="plan.planId" class="scene-plan-status"><div><strong>{{plan.name}}</strong><code>{{plan.planId}} · {{plan.memberIds.length}} 个成员 · {{planExecutionLabel(plan.execution)}}</code><UiTag :tone="planStatus(scene,plan).startsWith('可使用')?'success':'info'">{{planStatus(scene,plan)}}</UiTag><details class="scene-approved-parameters"><summary>逐成员平台参数（{{plan.memberIds.length}}）</summary><div v-for="member in approvedPlanMembers(scene,plan)" :key="memberId(member)"><code>{{memberId(member)}} · {{memberName(member)}} / {{member.version}} · {{member.target}}</code><template v-if="scene.approved&&planParameter(plan,member)"><p>平台发布修订 {{planParameter(plan,member)!.revision}} · 置信度 {{planParameter(plan,member)!.detection.confidenceThreshold}} · IoU {{planParameter(plan,member)!.detection.iouThreshold}} · 最多 {{planParameter(plan,member)!.detection.maxDetections}} 项</p><pre>{{JSON.stringify(planParameter(plan,member),null,2)}}</pre></template><p v-else>平台参数尚未发布，暂不可运行。</p></div></details></div></li></ul><p class="model-muted">已配置不等于客户端可运行。联合方案要求 v3 及匹配模式能力；旧客户端继续拒绝。同步表示等待成员结果，不保证物理并行；后台不执行推理。</p></section>
      <SceneExecutionHelp/>
      <p class="model-muted">新版 App 支持两个移动端模型的图片与本机相机同步/异步方案，仍需升级 App 并通过在线授权和设备预算检查；PC及跨端联合尚未开放。后台不执行推理。</p>
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
    <UiDialog :open="dialog!==null" :title="dialog==='create'?'创建项目场景':dialog==='members'?'管理场景模型成员':'编辑项目场景'" :busy="busy" @update:open="value=>{if(!value)dialog=null}"><form class="model-form" :class="{'scene-create-form':dialog==='create'}" @submit.prevent="save">
      <fieldset v-if="dialog==='create'" class="scene-create-basics" :disabled="busy||needsReload||!canManage">
        <p class="scene-create-intro">给场景起个名字，选择用途和识别模型即可。编号与运行方案会自动准备。</p>
        <label for="scene-create-name">场景名称<UiInput id="scene-create-name" v-model="form.name" required maxlength="255" placeholder="例如：工地安全帽巡检"/></label>
        <div class="scene-inputs scene-create-usage" role="group" aria-label="场景用途">
          <label class="model-check"><UiInput :model-value="form.image" type="checkbox" @update:model-value="value=>setSceneInput('image',value)"/>拍照巡检 / 图片识别</label>
          <label class="model-check"><UiInput :model-value="form.video" type="checkbox" @update:model-value="value=>setSceneInput('video',value)"/>视频巡检 / 连续帧识别</label>
        </div>
      </fieldset>
      <p v-if="inventoryLoading" role="status">正在读取项目模型…</p><p v-if="inventoryError" role="alert">{{inventoryError}} <UiButton type="button" @click="reloadInventory">重试模型候选</UiButton></p>
      <section v-if="!inventoryLoading&&!inventoryError" class="scene-parameter-status" aria-label="项目模型参数状态">
        <div v-if="unpublishedChoices.length||unverifiedParameterMembers.length" class="scene-parameter-notice" role="status">
          <template v-if="unpublishedChoices.length">
            <h4>{{unpublishedChoices.length}} 项模型参数待发布</h4>
            <p>以下模型暂不可加入场景，其他已就绪模型仍可使用。</p>
            <ul class="scene-parameter-models" aria-label="参数未发布的项目模型">
              <li v-for="item in unpublishedChoices" :key="item.assignment.projectModelId">
                <strong>{{modelDisplayName(item.model)}}</strong>
                <span>{{item.assignment.modelVersion}} · {{item.assignment.target==='pc'?'PC 端（服务端）':'移动端（Android）'}}</span>
              </li>
            </ul>
            <p>请联系平台管理员在<strong>平台模型资产 → 模型参数档案</strong>中核对并发布对应版本、目标端的参数。</p>
            <p class="scene-parameter-note">模型文件发布或保存参数草稿，不等于参数已发布。</p>
          </template>
          <p v-if="unverifiedParameterMembers.length">当前成员含未发布或参数状态待核实的模型，暂不能保存；请发布后刷新，或移除对应成员。</p>
        </div>
        <div class="scene-parameter-actions" role="group" aria-label="刷新项目模型状态操作">
          <div class="scene-parameter-refresh-copy">
            <strong>{{unpublishedChoices.length||unverifiedParameterMembers.length?'发布完成后，刷新状态继续配置':'项目模型状态'}}</strong>
            <p id="scene-inventory-refresh-hint">只刷新状态，不清空当前场景草稿。</p>
          </div>
          <UiButton type="button" class="secondary-button" aria-describedby="scene-inventory-refresh-hint" :disabled="busy||needsReload||!canManage" @click="reloadInventory"><RefreshCw :size="14" aria-hidden="true"/>刷新项目模型状态</UiButton>
        </div>
      </section>
      <fieldset :disabled="busy||needsReload||!canManage||inventoryLoading||!!inventoryError">
        <template v-if="dialog==='details'">
          <label>场景名称<UiInput v-model="form.name" required maxlength="255"/></label>
          <div class="scene-inputs"><label class="model-check"><UiInput :model-value="form.image" type="checkbox" @update:model-value="value=>setSceneInput('image',value)"/>适用图片</label><label class="model-check"><UiInput :model-value="form.video" type="checkbox" @update:model-value="value=>setSceneInput('video',value)"/>适用视频</label><label class="model-check"><UiInput v-model="form.enabled" type="checkbox"/>启用场景</label></div>
          <p class="model-muted">成员输入取场景与模型支持能力的交集；调整场景输入后，请核对已有运行方案。</p>
        </template>
        <template v-if="dialog!=='details'">
          <section class="scene-inventory-picker">
            <header><h4>{{dialog==='create'?'选择识别模型':'从项目模型清单添加成员'}}</h4><UiTag tone="info">{{availableChoices.length}} 个可用</UiTag></header>
            <label>项目模型<UiSelect :model-value="projectModelId" popper-class="scene-model-options" :placeholder="quickCreate?'选择后自动加入，可继续选择':'选择已分配模型'" @update:model-value="selectModel"><UiOption value="">{{quickCreate?'选择后自动加入，可继续选择':'选择已分配模型'}}</UiOption><UiOption v-for="item in inventoryChoices" :key="item.assignment.projectModelId" :value="item.assignment.projectModelId" :disabled="!item.assignment.enabled||!parametersReady(item.assignment)||members.some(member=>member.projectModelId===item.assignment.projectModelId)">{{inventoryLabel(item)}} · {{item.assignment.enabled?parameterStatus(item.assignment):'已停用'}}</UiOption></UiSelect></label>
            <p v-if="!inventoryLoading&&!inventoryError&&!inventoryChoices.length" class="scene-picker-empty">项目模型清单为空。请先在“项目模型”分配并启用模型，再返回配置场景。</p>
            <p v-else class="model-muted">选择所需版本与目标端；不可用模型会标明原因，不能加入。</p>
            <template v-if="!quickCreate">
              <label>成员执行声明<UiSelect v-model="execution"><UiOption value="single">单模型</UiOption><UiOption value="sync">同步</UiOption><UiOption value="async">异步</UiOption></UiSelect></label>
              <UiButton type="button" class="secondary-button" :disabled="!chosen||!chosen.assignment.enabled||!parametersReady(chosen.assignment)||members.length>=100" @click="add">添加项目模型成员</UiButton>
            </template>
          </section>
          <section class="scene-surface scene-editor-members">
            <header><strong>{{dialog==='create'?'已选模型':'场景成员'}}（{{members.length}}）</strong><small>{{quickCreate?'可随时移除，不修改平台模型':'调整顺序与输入能力'}}</small></header>
            <p v-if="!members.length" class="scene-picker-empty">请在上方选择至少一个模型。</p>
            <ol v-else class="scene-members editable"><li v-for="(member,index) in members" :key="memberKey(member)">
              <span class="scene-index">{{index+1}}</span>
              <div><strong>{{memberName(member)}}</strong><code>{{member.version}} · {{member.target==='pc'?'PC 端':'移动端'}} · {{parameterStatus(memberInventory(member))}}</code>
                <small v-if="quickCreate">{{memberInputs(member).map(kind=>kind==='image'?'拍照 / 图片识别':'视频 / 连续帧识别').join(' · ')}}</small>
                <template v-else><small class="scene-inventory-id">{{member.projectModelId}}</small><div class="scene-member-inputs"><span>成员输入：</span><label v-for="kind in sceneInputOptions" :key="kind" class="model-check"><UiInput type="checkbox" :model-value="memberInputs(member).includes(kind)" :disabled="!memberInputOptions(member).includes(kind)" @update:model-value="value=>setMemberInput(member,kind,value)"/>{{kind==='image'?'图片':'本机相机连续帧'}}</label></div></template>
                <small v-if="!memberInputs(member).length" class="danger-text">没有与当前场景兼容的输入类型，请调整场景输入或移除此成员。</small>
              </div>
              <div class="model-actions"><template v-if="!quickCreate"><UiButton type="button" class="secondary-button" :disabled="index===0" :aria-label="`上移成员 ${index+1}`" @click="move(index,-1)">↑</UiButton><UiButton type="button" class="secondary-button" :disabled="index===members.length-1" :aria-label="`下移成员 ${index+1}`" @click="move(index,1)">↓</UiButton></template><UiButton type="button" class="secondary-button danger-text" :aria-label="`移除成员 ${index+1}`" @click="remove(index)">移除</UiButton></div>
            </li></ol>
          </section>
          <div v-if="!inventoryLoading&&!inventoryError&&invalidMembers.length" class="scene-member-warning" role="status"><p>存在已停用或已移除的项目模型成员，请移除这些成员后再保存。</p></div>
        </template>
        <section v-if="dialog==='create'" class="scene-create-summary" aria-label="创建配置摘要">
          <strong>{{customPlans?'保留自定义运行方案':members.length>1?`默认联合识别 · ${members.length} 个模型`:`自动准备 ${automaticPlans.length} 个单模型方案`}}</strong>
          <p v-if="customPlans">已自定义方案，收起高级设置不会清空配置；新增模型后请自行检查方案是否包含全部需要一起识别的成员。</p>
          <template v-else-if="members.length>1">
            <p>全部已选模型加入同一个方案，在同一次巡检中共同参与识别，不再拆成多个单模型方案。</p>
            <label class="scene-joint-execution">联合执行方式<UiSelect v-model="jointExecution"><UiOption value="sync">同步（默认）</UiOption><UiOption value="async">异步</UiOption></UiSelect></label>
            <SceneExecutionHelp/>
          </template>
          <p v-else>一个模型使用一个方案；添加多个模型后，自动合并为覆盖全部成员的联合方案。视频采用默认相机策略。</p>
          <div v-if="automaticPlanIssue" class="scene-joint-warning" role="alert">
            <p>{{automaticPlanIssue}}</p>
          </div>
          <p v-else-if="!customPlans&&members.length>1">需要支持联合识别的新版 App；使用前需通过在线预检、运行授权和设备性能检查。</p>
          <p v-if="!form.enabled">当前场景设为停用；创建后不能直接使用。</p>
        </section>
        <UiButton v-if="dialog==='create'" type="button" class="secondary-button scene-advanced-toggle" :aria-expanded="createAdvanced" aria-controls="scene-create-advanced" @click="createAdvanced=!createAdvanced">{{createAdvanced?'收起高级设置':'高级设置（可选）'}}</UiButton>
        <div id="scene-create-advanced" v-show="!quickCreate">
          <div v-if="dialog==='create'" class="scene-create-technical"><p class="model-muted">仅需要指定编号、成员能力或自定义运行方案时调整。收起后仍保留已做的修改。</p><label>场景 ID<UiInput v-model="form.id" maxlength="128"/></label><label class="model-check"><UiInput v-model="form.enabled" type="checkbox"/>启用场景</label></div>
          <section v-if="dialog!=='create'||members.length" class="scene-plan-editor">
            <header><div><h4>运行方案</h4><p class="model-muted">选择成员和输入能力形成可复用方案；方案复用成员引用，不复制模型资产。</p></div><UiTag v-if="effectivePlans.some(plan=>plan.execution!=='single')" tone="info">新版 App 支持双移动端图片 / 视频联合</UiTag></header>
            <p class="scene-capability-summary"><strong>当前套件能力</strong><span v-for="kind in suiteCapabilities" :key="kind">{{kind==='image'?'图片':'本机相机连续帧'}}</span><small>方案只能选择成员共同支持的输入能力。</small></p>
            <template v-if="dialog==='create'||dialog==='details'">
              <p class="model-muted">方案随场景一起保存。</p>
              <ol class="scene-plan-list scene-create-plans"><li v-for="(plan,index) in effectivePlans" :key="index">
                <header><button v-if="dialog==='details'" type="button" class="scene-plan-disclosure" :aria-expanded="expandedPlan===index" :aria-controls="`scene-plan-fields-${index}`" @click="expandedPlan=expandedPlan===index?null:index"><ChevronDown :size="16" aria-hidden="true"/>{{plan.name||'未命名方案'}}</button><strong v-else>方案 {{index+1}} · {{plan.name||'未命名'}}</strong><UiButton type="button" class="secondary-button danger-text" :aria-label="`移除方案 ${plan.name||index+1}`" @click="removeInlinePlan(index)">移除</UiButton></header>
                <small>{{plan.memberIds.length}} 个成员 · {{planExecutionLabel(plan.execution)}} · {{draftPlanStatus(plan)}}</small>
                <small v-if="dialog==='details'" class="scene-plan-member-names">{{plan.memberIds.map(id=>inlinePlanMembers.find(member=>member.id===id)?.label??id).join('、')}}</small>
                <div :id="`scene-plan-fields-${index}`"><CreatePlanFields v-if="dialog==='create'||expandedPlan===index" :plan="plan" :members="inlinePlanMembers" :inputs="inputTypes()" @change="patch=>changeInlinePlan(index,patch)"/></div>
              </li></ol>
              <UiButton type="button" class="secondary-button" @click="addInlinePlan"><Plus :size="14"/>新增方案</UiButton>
            </template>
            <template v-else>
            <ul class="scene-plan-list"><li v-for="plan in effectivePlans" :key="plan.planId"><div><strong>{{plan.name}}</strong><code>{{plan.planId}} · {{plan.memberIds.length}} 个成员 · {{planExecutionLabel(plan.execution)}}</code></div><div class="model-actions"><UiTag tone="info">{{draftPlanStatus(plan)}}</UiTag><UiButton type="button" class="secondary-button" :aria-label="`编辑方案 ${plan.name}`" @click="editPlan(plan)">编辑</UiButton><UiButton type="button" class="secondary-button danger-text" :aria-label="`移除方案 ${plan.name}`" @click="removePlan(plan)">移除</UiButton></div></li></ul>
            <div class="scene-plan-draft">
              <label>方案 ID<UiInput v-model="planDraft.planId" maxlength="128" placeholder="例如 image-safety"/></label><label>方案名称<UiInput v-model="planDraft.name" maxlength="255" placeholder="例如静态识别"/></label>
              <div class="scene-plan-options"><span>方案输入</span><label v-for="kind in sceneInputOptions" :key="kind" class="model-check"><UiInput type="checkbox" :model-value="planDraft.inputTypes.includes(kind)" :disabled="!planInputOptions.includes(kind)" @update:model-value="value=>togglePlanInput(kind,value)"/>{{kind==='image'?'图片':'本机相机连续帧'}}</label></div>
              <div class="scene-plan-options"><span>方案成员</span><label v-for="member in members" :key="memberId(member)" class="model-check"><UiInput type="checkbox" :model-value="planDraft.memberIds.includes(memberId(member))" @update:model-value="value=>togglePlanMember(memberId(member),value)"/>{{memberName(member)}} / {{member.version}} · {{member.target==='pc'?'PC':'移动端'}}</label></div>
              <CameraPolicyFields v-if="planDraft.inputTypes.includes('video')" v-model="planDraft.cameraPolicy"/>
              <label>执行方式<UiSelect v-model="planDraft.execution"><UiOption value="single">单模型</UiOption><UiOption value="sync">同步</UiOption><UiOption value="async">异步</UiOption></UiSelect></label><label class="model-check"><UiInput v-model="planDraft.enabled" type="checkbox"/>启用方案</label>
              <SceneExecutionHelp/>
              <div class="model-actions"><UiButton type="button" class="secondary-button" :disabled="!members.length" @click="savePlanDraft">{{planEditingId?'更新方案':'添加运行方案'}}</UiButton><UiButton v-if="planEditingId||planDraft.planId||planDraft.name||planDraft.memberIds.length" type="button" class="secondary-button" @click="resetPlanDraft">取消编辑方案</UiButton></div>
            </div>
            </template>
          </section>
        </div>
      </fieldset>
      <p class="model-muted">{{dialog==='create'?'创建后为待批准状态，需项目负责人批准后才能使用；不会自动开始巡检。':'保存后清除先前批准并生成新的修订快照。冲突时保留草稿，关闭并刷新核验后再操作；不会自动覆盖。'}}</p>
      <p v-if="localError||mutationError" class="operation-feedback is-error" role="alert">{{localError||mutationError}}</p>
      <footer><UiButton type="button" class="secondary-button" :disabled="busy" @click="dialog=null">取消</UiButton><UiButton class="primary-button" :disabled="busy||needsReload||!canManage||inventoryLoading||!!inventoryError||!!automaticPlanIssue">{{dialog==='create'?'保存新场景':'保存场景变更'}}</UiButton></footer>
    </form></UiDialog>
    <UiDialog :open="!!review" title="审核场景可用性" :busy="busy" @update:open="value=>{if(!value)review=null}"><form class="model-form" @submit.prevent="approve"><p>{{review?.name}} · 修订 {{review?.revision}} · {{review?.models.length}} 个模型</p><p class="model-muted">{{review?.approved&&!reapprove?'撤销后项目成员不能继续读取或下载该场景产物。':'批准当前模型版本、目标端、组合和运行策略；参数始终使用平台发布版。生成新场景修订并废止旧修订链接。服务器再次校验产物及当前权限，不启动推理。'}}</p><template v-if="review&&(!review.approved||reapprove)"><div v-for="member in review.models" :key="memberId(member)" class="scene-review-profile"><code>{{memberId(member)}} · {{memberName(member)}} / {{member.version}} · {{member.target}}</code><template v-if="platformProfile(member)"><p>平台发布修订 {{platformProfile(member)!.revision}} · 置信度 {{platformProfile(member)!.detection.confidenceThreshold}} · IoU {{platformProfile(member)!.detection.iouThreshold}}</p><details><summary>查看平台发布参数</summary><pre>{{JSON.stringify(platformProfile(member),null,2)}}</pre></details></template><p v-else>平台参数尚未发布，需由平台管理员发布后使用。</p></div></template><label>审核原因<UiInput v-model="reviewReason" required maxlength="512" :disabled="busy||needsReload"/></label><p v-if="mutationError" class="operation-feedback is-error" role="alert">{{mutationError}}</p><footer><UiButton type="button" class="secondary-button" :disabled="busy" @click="review=null">取消</UiButton><UiButton class="primary-button" :disabled="busy||needsReload||!canApprove||!reviewReason.trim()">{{review?.approved&&!reapprove?'确认撤销':reapprove?'确认重新批准':'确认批准'}}</UiButton></footer></form></UiDialog>
    <ParametersDialog v-if="parameterSelection" :model="parameterSelection.model" read-only project-mode :initial-platform="parameterSelection.member.target==='mobile'?'android':'server'" :scene-binding="{sceneId:parameterSelection.scene.sceneId,memberId:memberId(parameterSelection.member),revision:parameterSelection.scene.revision}" @close="parameterSelection=null;refresh()"/>
  </section>
</template>
