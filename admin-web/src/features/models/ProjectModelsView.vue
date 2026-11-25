<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import UiDialog from '../../components/ui/UiDialog.vue'
import UiConfirmDialog from '../../components/ui/UiConfirmDialog.vue'
import UiStatePanel from '../../components/ui/UiStatePanel.vue'
import { useManagement } from '../management/useManagement'
import { useCandidates } from '../management/useCandidates'
import { useProjectCapabilities } from '../projects/capabilities'
import { modelsApi, formatBytes } from './api'
import { targetStatus } from './capabilities'
import ParametersDialog from './ParametersDialog.vue'
import { modelDisplayName, modelStatusLabel } from './presentation'
import { projectModelsApi, type AssignedModel, type Assignment, type AvailableModel } from './projectApi'
import type { ModelAsset, ModelTarget, Platform } from './types'
import './models.css'

const { models: canAssign, active } = useProjectCapabilities()
const route = useRoute()
const state = useManagement<{models:AssignedModel[];assignments:Assignment[];available:AvailableModel[]}>(
  {models:[],assignments:[],available:[]},
  async signal => {
    const [models, assignments] = await Promise.all([
      projectModelsApi.models(signal),
      projectModelsApi.assignments(signal),
    ])
    // Disabled assignments may be absent from /models. Preserve their status,
    // name and integrity metadata instead of dropping the available fallback.
    const needsMetadata = assignments.some(a => !models.some(m => m.modelId === a.modelId && m.version === a.modelVersion))
    const available = canAssign.value && needsMetadata ? await projectModelsApi.available(signal) : []
    return {models, assignments, available}
  },
)
const {data,loading,error,notice,busy,mutationError,needsReload,refresh,run,resetMutation} = state

const selectedKey = ref('')
const selectedTarget = ref<ModelTarget>('pc')
const activeTarget = ref<ModelTarget>('pc')
const open = ref(false)
const {data:candidates,loading:candidatesLoading,error:candidatesError,refresh:reloadCandidates}=useCandidates(computed(()=>open.value&&canAssign.value),projectModelsApi.available)
const confirm = ref(false)
const editing = ref<Assignment|null>(null)
const parameters = ref<AssignedModel|null>(null)
const disabling = ref<Assignment|null>(null)
const removing = ref<Assignment|null>(null)

const key = (model:Pick<ModelAsset,'modelId'|'version'>) => JSON.stringify([model.modelId, model.version])
const selected = computed(() => candidates.value.find(model => key(model) === selectedKey.value))
const platformFor = (target:ModelTarget):Platform => target === 'pc' ? 'server' : 'android'
const targetLabel = (target:ModelTarget) => target === 'pc' ? 'PC 端' : '移动端'
const targetDetail = (target:ModelTarget) => target === 'pc'
  ? '服务端分析、视频流绑定与桌面运行使用的模型清单'
  : 'Android 下载、安装与本地巡检使用的模型清单'
const targetAssignments = (target:ModelTarget) => data.value.assignments
  .filter(assignment => assignment.target === target)
  .sort((left,right) => Number(right.enabled)-Number(left.enabled) || left.modelId.localeCompare(right.modelId) || left.modelVersion.localeCompare(right.modelVersion))
const pcAssignments = computed(() => targetAssignments('pc'))
const mobileAssignments = computed(() => targetAssignments('mobile'))
const availableTargets = computed<ModelTarget[]>(() => {
  const profiles = selected.value?.parameterProfiles
  return ([profiles?.server ? 'pc' : null, profiles?.android ? 'mobile' : null].filter(Boolean) as ModelTarget[])
})
function assignmentFor(model:Pick<ModelAsset,'modelId'|'version'>|undefined, target:ModelTarget) {
  return data.value.assignments.find(assignment => assignment.modelId === model?.modelId
    && assignment.modelVersion === model?.version && assignment.target === target)
}
function assignmentLabel(model:Pick<ModelAsset,'modelId'|'version'>|undefined, target:ModelTarget, includeTarget=true) {
  const existing = assignmentFor(model, target)
  return existing ? `（${includeTarget ? targetLabel(target) : ''}${existing.enabled ? '已添加' : '已停用，可重新启用'}）` : ''
}
const current = computed(() => assignmentFor(selected.value, selectedTarget.value))
const alreadyAssigned = computed(() => current.value?.enabled === true)
const reactivating = computed(() => current.value?.enabled === false)
const assignmentAction = computed(() => alreadyAssigned.value ? '已添加' : reactivating.value ? '重新启用' : '确认分配')
const assignmentDescription = computed(() => `${modelDisplayName(selected.value)} / ${selected.value?.version} ${
  reactivating.value ? `将在${targetLabel(selectedTarget.value)}模型池中重新启用，保留原项目模型条目，不新增重复条目。`
    : `将作为独立条目加入${targetLabel(selectedTarget.value)}模型池。`
}此操作不会创建场景，也不会启动运行任务。`)
const selectedProfile = computed(() => selected.value?.parameterProfiles[platformFor(selectedTarget.value)])
const canSave = computed(() => !!selected.value && availableTargets.value.includes(selectedTarget.value)
  && !!selectedProfile.value && !alreadyAssigned.value && (!current.value || !unavailableReason(current.value))
  && !loading.value && !error.value && !needsReload.value && !candidatesLoading.value && !candidatesError.value)

function assetFor(assignment:Assignment):ModelAsset|undefined {
  return data.value.models.find(model => model.modelId === assignment.modelId && model.version === assignment.modelVersion)
    ?? data.value.available.find(model => model.modelId === assignment.modelId && model.version === assignment.modelVersion)
}
const assignmentStatus=(assignment:Assignment)=>assignment.modelStatus??assetFor(assignment)?.status
const assignmentName=(assignment?:Assignment|null)=>{
  const name=modelDisplayName(assignment?.modelName?.trim()?assignment:assignment?assetFor(assignment):null)
  if(name!=='未命名模型'||!assignment)return name
  return assignmentStatus(assignment)==='UNINSTALLED'?'已卸载模型（历史名称未留存）'
    :assignmentStatus(assignment)==='MISSING'?'模型版本已不可用':name
}
function unavailableReason(assignment:Assignment) {
  const status=assignmentStatus(assignment)
  if(status==='UNINSTALLED')return '平台已卸载此模型版本，不能重新启用。可移除项目中的旧条目，再添加平台已发布的可用版本；重新上传不会自动恢复旧引用。'
  if(status==='MISSING')return '平台中已找不到此精确模型版本，不能重新启用。请联系平台管理员核查，或移除旧条目后重新分配可用版本。'
  if(status==='UNKNOWN')return '暂时无法核实平台模型状态，请刷新清单或联系平台管理员；核实前不能重新启用。'
  if(status&&status!=='PUBLISHED')return `平台模型${modelStatusLabel(status)}，当前不能重新启用。请联系平台管理员核查发布状态。`
  return ''
}
function artifactsFor(assignment:Assignment) {
  return (assetFor(assignment)?.artifacts ?? []).filter(artifact => artifact.platform === assignment.parameterPlatform)
}
function assignmentTargetStatus(assignment:Assignment) {
  if(assignmentStatus(assignment)==='UNINSTALLED')return '产物已卸载'
  if(assignmentStatus(assignment)==='MISSING')return '版本不可用'
  const asset = assetFor(assignment)
  return asset ? targetStatus(asset, assignment.target) : '状态未知'
}
function selectRelease(value:string|number) {
  selectedKey.value = String(value)
  if (!availableTargets.value.includes(selectedTarget.value)) selectedTarget.value = availableTargets.value[0] ?? 'pc'
}
watch(candidates,()=>{if(selectedKey.value)selectRelease(selectedKey.value)})
function begin(assignment?:Assignment, preferredTarget?:ModelTarget, initialModelKey?:string) {
  if (!canAssign.value || needsReload.value || assignment&&unavailableReason(assignment)) return
  resetMutation()
  confirm.value = false
  editing.value = assignment ?? null
  activeTarget.value = assignment?.target ?? preferredTarget ?? activeTarget.value
  selectedTarget.value = assignment?.target ?? preferredTarget ?? 'pc'
  selectedKey.value = assignment ? key({modelId:assignment.modelId,version:assignment.modelVersion}) : initialModelKey ?? ''
  open.value = true
}
function changeTarget(target:ModelTarget) { activeTarget.value = target }
function onTargetKeydown(event:KeyboardEvent) {
  if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return
  event.preventDefault()
  const next = event.key === 'Home' ? 'pc' : event.key === 'End' ? 'mobile'
    : activeTarget.value === 'pc' ? 'mobile' : 'pc'
  activeTarget.value = next
  document.getElementById(`project-model-tab-${next}`)?.focus()
}
function requestAssignment() {
  if (canAssign.value && canSave.value && !busy.value) confirm.value = true
}
async function save() {
  const model = selected.value
  const profile = selectedProfile.value
  if (!canAssign.value || candidatesLoading.value || candidatesError.value || !model || !profile || !canSave.value) return
  await run(signal => projectModelsApi.save({
    modelId:model.modelId, modelVersion:model.version, target:selectedTarget.value,
    enabled:true, expectedRevision:current.value?.revision ?? 0,
  }, signal), () => { confirm.value=false; open.value=false; editing.value=null })
  if (mutationError.value) confirm.value = false
}
async function disable(assignment:Assignment) {
  if (!canAssign.value || needsReload.value) return
  await run(signal => projectModelsApi.save({
    modelId:assignment.modelId, modelVersion:assignment.modelVersion, target:assignment.target,
    enabled:false, expectedRevision:assignment.revision,
  }, signal), () => { disabling.value=null })
}
async function remove(assignment:Assignment) {
  if (!canAssign.value || assignment.enabled || needsReload.value) return
  await run(signal => projectModelsApi.remove(assignment.projectModelId, assignment.revision, signal), () => { removing.value=null })
}
function assignedModel(assignment:Assignment):AssignedModel|null {
  const asset = assetFor(assignment)
  return asset ? {...asset, assignment} as AssignedModel : null
}
function showParameters(assignment:Assignment) { parameters.value = assignedModel(assignment) }
async function download(assignment:Assignment, artifactId:string) {
  const model = assignedModel(assignment)
  if (!active.value || !assignment.enabled || !model) return
  await run(() => modelsApi.download(model, artifactId), () => {})
}

onMounted(async () => {
  await refresh()
  const modelId = typeof route.query.modelId === 'string' ? route.query.modelId : ''
  const version = typeof route.query.version === 'string' ? route.query.version : ''
  if (modelId && version && canAssign.value) begin(undefined, undefined, key({modelId,version}))
})
</script>

<template>
  <section class="model-workspace project-model-workspace">
    <div class="model-actions project-model-actions">
      <UiButton class="secondary-button" :disabled="busy||loading" @click="refresh">刷新清单</UiButton>
      <UiButton v-if="canAssign" class="primary-button" :disabled="busy||loading||needsReload||!!error" @click="begin(undefined,activeTarget)">{{activeTarget==='pc'?'添加 PC 模型':'添加移动端模型'}}</UiButton>
    </div>

    <aside class="inventory-guide">
      <strong>这是项目级可用模型池。</strong>
      <span>场景会从这里选择成员；视频流和运行任务会再显式选择场景与方案。分配模型不会创建场景，也不会启动运行任务。</span>
    </aside>
    <p v-if="notice" class="operation-feedback" role="status">{{notice}}</p>
    <p v-if="mutationError" class="operation-feedback is-error" role="alert">{{mutationError}}</p>
    <UiStatePanel v-if="loading" state="loading"/>
    <UiStatePanel v-else-if="error" state="error" :message="error" @retry="refresh"/>

    <div v-else class="target-pools">
      <div class="target-switch" role="tablist" aria-label="模型目标端" @keydown="onTargetKeydown">
        <button id="project-model-tab-pc" type="button" role="tab" aria-controls="project-model-panel-pc" :aria-selected="activeTarget==='pc'" :tabindex="activeTarget==='pc'?0:-1" @click="changeTarget('pc')">
          <span class="target-switch-mark">PC</span><span>PC 端</span><strong>{{pcAssignments.length}}</strong>
        </button>
        <button id="project-model-tab-mobile" type="button" role="tab" aria-controls="project-model-panel-mobile" :aria-selected="activeTarget==='mobile'" :tabindex="activeTarget==='mobile'?0:-1" @click="changeTarget('mobile')">
          <span class="target-switch-mark">APP</span><span>移动端</span><strong>{{mobileAssignments.length}}</strong>
        </button>
      </div>

      <article v-if="activeTarget==='pc'" id="project-model-panel-pc" class="target-pool" role="tabpanel" aria-labelledby="project-model-tab-pc">
        <header class="target-pool-heading">
          <div><h3>PC 端模型</h3><span>{{targetDetail('pc')}}</span></div>
        </header>
        <UiStatePanel v-if="!pcAssignments.length" state="empty" title="PC 端尚未分配模型" message="可从已发布且 PC 端就绪的模型版本中添加。"/>
        <div v-else class="inventory-list">
          <section v-for="assignment in pcAssignments" :key="assignment.projectModelId" class="inventory-row" :class="{'is-disabled':!assignment.enabled}">
            <div class="inventory-main"><span class="inventory-state" :class="assignment.enabled?'is-enabled':'is-stopped'">{{assignment.enabled?'已启用':'已停用'}}</span><div><h4>{{assignmentName(assignment)}}</h4><code>模型 ID：{{assignment.modelId}} · 版本 {{assignment.modelVersion}}</code></div></div>
            <div class="inventory-meta"><span><small>平台模型</small>{{modelStatusLabel(assignmentStatus(assignment))}}</span><span><small>PC 端</small>{{assignmentTargetStatus(assignment)}}</span><span><small>参数修订</small>{{unavailableReason(assignment)?'不可用':assignment.parameterPublished === false ? '尚未发布' : 'r' + assignment.parameterRevision}}</span></div>
            <div class="inventory-actions">
              <UiButton v-if="assignment.enabled" class="secondary-button" @click="showParameters(assignment)">查看平台参数</UiButton>
              <UiButton v-if="canAssign&&!assignment.enabled" class="secondary-button" :disabled="busy||needsReload||!!unavailableReason(assignment)" :aria-describedby="unavailableReason(assignment)?'inventory-unavailable-'+assignment.projectModelId:undefined" @click="begin(assignment)">重新启用</UiButton>
              <UiButton v-if="canAssign&&assignment.enabled" class="secondary-button danger-text" :disabled="busy||needsReload" @click="disabling=assignment">停用</UiButton>
              <UiButton v-if="canAssign&&!assignment.enabled" class="secondary-button danger-text" :disabled="busy||needsReload" @click="removing=assignment">移除</UiButton>
            </div>
            <p v-if="unavailableReason(assignment)" :id="'inventory-unavailable-'+assignment.projectModelId" class="inventory-unavailable" role="status">{{unavailableReason(assignment)}}</p>
            <details class="inventory-more"><summary>详情与产物 <span>清单 r{{assignment.revision}}</span></summary><div class="inventory-detail"><p>项目模型 ID <code>{{assignment.projectModelId}}</code></p><div v-if="artifactsFor(assignment).length" class="inventory-artifacts"><div v-for="artifact in artifactsFor(assignment)" :key="artifact.artifactId"><span>{{artifact.format.toUpperCase()}} · {{formatBytes(artifact.sizeBytes)}}</span><UiButton class="secondary-button" :disabled="busy||!active||!assignment.enabled||!artifact.exists||!artifact.hashValid" @click="download(assignment,artifact.artifactId)">下载产物</UiButton></div></div><span v-else class="model-muted">暂无可下载产物</span></div></details>
          </section>
        </div>
      </article>
      <article v-else id="project-model-panel-mobile" class="target-pool is-mobile" role="tabpanel" aria-labelledby="project-model-tab-mobile">
        <header class="target-pool-heading">
          <div><h3>移动端模型</h3><span>{{targetDetail('mobile')}}</span></div>
        </header>
        <UiStatePanel v-if="!mobileAssignments.length" state="empty" title="移动端尚未分配模型" message="可从已发布且移动端就绪的模型版本中添加。"/>
        <div v-else class="inventory-list">
          <section v-for="assignment in mobileAssignments" :key="assignment.projectModelId" class="inventory-row" :class="{'is-disabled':!assignment.enabled}">
            <div class="inventory-main"><span class="inventory-state" :class="assignment.enabled?'is-enabled':'is-stopped'">{{assignment.enabled?'已启用':'已停用'}}</span><div><h4>{{assignmentName(assignment)}}</h4><code>模型 ID：{{assignment.modelId}} · 版本 {{assignment.modelVersion}}</code></div></div>
            <div class="inventory-meta"><span><small>平台模型</small>{{modelStatusLabel(assignmentStatus(assignment))}}</span><span><small>移动端</small>{{assignmentTargetStatus(assignment)}}</span><span><small>参数修订</small>{{unavailableReason(assignment)?'不可用':assignment.parameterPublished === false ? '尚未发布' : 'r' + assignment.parameterRevision}}</span></div>
            <div class="inventory-actions">
              <UiButton v-if="assignment.enabled" class="secondary-button" @click="showParameters(assignment)">查看平台参数</UiButton>
              <UiButton v-if="canAssign&&!assignment.enabled" class="secondary-button" :disabled="busy||needsReload||!!unavailableReason(assignment)" :aria-describedby="unavailableReason(assignment)?'inventory-unavailable-'+assignment.projectModelId:undefined" @click="begin(assignment)">重新启用</UiButton>
              <UiButton v-if="canAssign&&assignment.enabled" class="secondary-button danger-text" :disabled="busy||needsReload" @click="disabling=assignment">停用</UiButton>
              <UiButton v-if="canAssign&&!assignment.enabled" class="secondary-button danger-text" :disabled="busy||needsReload" @click="removing=assignment">移除</UiButton>
            </div>
            <p v-if="unavailableReason(assignment)" :id="'inventory-unavailable-'+assignment.projectModelId" class="inventory-unavailable" role="status">{{unavailableReason(assignment)}}</p>
            <details class="inventory-more"><summary>详情与产物 <span>清单 r{{assignment.revision}}</span></summary><div class="inventory-detail"><p>项目模型 ID <code>{{assignment.projectModelId}}</code></p><div v-if="artifactsFor(assignment).length" class="inventory-artifacts"><div v-for="artifact in artifactsFor(assignment)" :key="artifact.artifactId"><span>{{artifact.format.toUpperCase()}} · {{formatBytes(artifact.sizeBytes)}}</span><UiButton class="secondary-button" :disabled="busy||!active||!assignment.enabled||!artifact.exists||!artifact.hashValid" @click="download(assignment,artifact.artifactId)">下载产物</UiButton></div></div><span v-else class="model-muted">暂无可下载产物</span></div></details>
          </section>
        </div>
      </article>
    </div>

    <UiDialog v-model:open="open" :title="reactivating ? '重新启用项目模型' : '分配项目模型'" :busy="busy">
      <p v-if="candidatesLoading" role="status">正在读取可分配模型…</p><p v-if="candidatesError" role="alert">{{candidatesError}} <UiButton @click="reloadCandidates">重试模型候选</UiButton></p>
      <form class="model-form assignment-form" @submit.prevent="requestAssignment">
        <label>模型版本
          <UiSelect :model-value="selectedKey" :disabled="busy||needsReload" @update:model-value="selectRelease">
            <UiOption value="">请选择模型版本</UiOption>
            <UiOption v-for="model in candidates" :key="key(model)" :value="key(model)">{{modelDisplayName(model)}} / {{model.version}}{{assignmentLabel(model,selectedTarget)}}</UiOption>
          </UiSelect>
        </label>
        <label>启用目标端
          <UiSelect v-model="selectedTarget" :disabled="busy||needsReload||!!editing">
            <UiOption value="pc" :disabled="!availableTargets.includes('pc')">PC 端{{availableTargets.includes('pc')?assignmentLabel(selected,'pc',false):'（不可用）'}}</UiOption>
            <UiOption value="mobile" :disabled="!availableTargets.includes('mobile')">移动端{{availableTargets.includes('mobile')?assignmentLabel(selected,'mobile',false):'（不可用）'}}</UiOption>
          </UiSelect>
        </label>
        <section v-if="selected&&selectedProfile" class="assignment-preview">
          <div><span>目标模型池</span><strong>{{targetLabel(selectedTarget)}}模型池</strong></div>
          <div><span>参数修订</span><strong>r{{selectedProfile.revision}}</strong></div>
          <div><span>当前条目</span><strong>{{current?`${current.enabled?'已添加':'已停用'} · r${current.revision}`:'尚未添加'}}</strong></div>
          <p role="status">{{alreadyAssigned?'该模型版本已在当前项目的此目标端启用，无需重复添加；可选择其他版本或目标端。':reactivating?'重新启用将保留原项目模型条目，不新增重复条目；不会创建场景，也不会启动运行任务。':'作为独立条目加入模型池；不会创建场景，也不会启动运行任务。'}}</p>
        </section>
        <p v-if="selected&&!selectedProfile" class="operation-feedback is-warning">该模型版本的{{targetLabel(selectedTarget)}}产物或参数尚未就绪，请选择其他目标端。</p>
        <p v-if="!candidatesLoading&&!candidatesError&&!candidates.length" class="model-muted">当前没有满足项目授权条件的可分配版本，请联系平台管理员检查模型发布与目标端就绪状态。</p>
        <p v-if="mutationError" class="operation-feedback is-error" role="alert">{{mutationError}}</p>
        <footer><UiButton type="button" class="secondary-button" :disabled="busy" @click="open=false">取消</UiButton><UiButton class="primary-button" :disabled="busy||!canSave||!canAssign">{{assignmentAction}}</UiButton></footer>
      </form>
    </UiDialog>
    <UiConfirmDialog v-model:open="confirm" :title="reactivating ? '确认重新启用项目模型' : '确认加入项目模型池'" :description="assignmentDescription" :confirm-label="reactivating ? '确认重新启用' : '确认分配'" :busy="busy" @confirm="save"/>
    <ParametersDialog v-if="parameters" :model="parameters" read-only project-mode :initial-platform="parameters.assignment.parameterPlatform" @close="parameters=null;refresh()"/>
    <UiConfirmDialog :open="!!disabling" title="停用项目模型" :description="`停用 ${assignmentName(disabling)} / ${disabling?.modelVersion} 的${targetLabel(disabling?.target ?? 'pc')}条目。场景中已有的引用需要在场景配置中另行处理；在用 PC 流须先停止。`" confirm-label="确认停用" tone="danger" :busy="busy" @update:open="value=>{if(!value)disabling=null}" @confirm="disabling&&disable(disabling)"/>
    <UiConfirmDialog :open="!!removing" title="移除项目模型" :description="`永久移除已停用的 ${assignmentName(removing)} / ${removing?.modelVersion} ${targetLabel(removing?.target ?? 'pc')}条目。`" confirm-label="确认移除" tone="danger" :busy="busy" @update:open="value=>{if(!value)removing=null}" @confirm="removing&&remove(removing)"/>
  </section>
</template>

<style scoped>
.inventory-unavailable{grid-column:1/-1;margin:0;padding:10px 12px;border:1px solid #ead8b6;border-radius:8px;background:var(--color-warning-soft);color:#795016;font-size:12px;line-height:1.7;overflow-wrap:anywhere}
.inventory-guide{display:flex;align-items:center;gap:10px;margin:18px 0 16px;padding:12px 16px;border-radius:8px;background:var(--color-primary-soft);color:var(--color-primary)}.inventory-guide span{color:var(--color-ink-muted);line-height:1.55}
.target-pools{display:grid;gap:10px}.target-switch{display:flex;width:max-content;max-width:100%;gap:4px;padding:4px;border-radius:8px;background:var(--color-border)}.target-switch button{display:flex;align-items:center;gap:9px;min-height:40px;padding:0 12px;border:0;border-radius:6px;background:transparent;color:var(--color-ink-muted);font:inherit;font-size:12px;font-weight:600;cursor:pointer}.target-switch button[aria-selected="true"]{background:var(--color-surface);color:var(--color-ink);box-shadow:0 1px 4px rgb(17 38 68 / 12%)}.target-switch button:focus-visible{outline:2px solid var(--color-primary);outline-offset:2px}.target-switch-mark{display:grid;place-items:center;min-width:28px;height:24px;padding:0 5px;border-radius:5px;background:var(--color-primary);color:#fff;font-size:9px;font-weight:800}.target-switch button:nth-child(2) .target-switch-mark{background:#365f7d}.target-switch strong{display:grid;place-items:center;min-width:22px;height:22px;padding:0 5px;border-radius:11px;background:var(--color-border);color:var(--color-ink-muted);font-size:10px}
.target-pool{overflow:hidden;border:1px solid var(--color-border);border-radius:8px;background:var(--color-surface)}.target-pool-heading{display:flex;align-items:center;justify-content:space-between;gap:14px;padding:12px 16px;background:var(--color-info-soft);border-bottom:1px solid var(--color-border)}.target-pool.is-mobile .target-pool-heading{background:#f1f5f8}.target-pool-heading h3{font-size:15px}.target-pool-heading span{display:block;margin-top:3px;color:var(--color-ink-muted);font-size:10px;line-height:1.45}.pool-add{margin:0;flex:none}
.inventory-list{padding:0 14px}.inventory-row{display:grid;grid-template-columns:minmax(210px,1.25fr) minmax(230px,1fr) auto;align-items:center;gap:12px;padding:11px 2px;border-bottom:1px solid var(--color-border)}.inventory-row:last-child{border-bottom:0}.inventory-row.is-disabled{background:linear-gradient(90deg,#f8f7f5,transparent);opacity:.82}.inventory-main{display:flex;align-items:center;gap:10px;min-width:0}.inventory-main>div{min-width:0}.inventory-main h4{font-size:13px;overflow-wrap:anywhere}.inventory-main code{font-size:10px;line-height:1.5}.inventory-state{flex:none;padding:4px 7px;border-radius:5px;font-size:10px;font-weight:700}.inventory-state.is-enabled{color:var(--color-primary);background:var(--color-primary-soft)}.inventory-state.is-stopped{color:#7c4b42;background:#f5e5e1}
.inventory-meta{display:flex;flex-wrap:wrap;gap:6px 14px;color:var(--color-ink);font-size:10px}.inventory-meta span{display:grid;gap:2px}.inventory-meta small{color:var(--color-ink-muted);font-size:9px}.inventory-actions{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:5px}.inventory-actions button{min-height:29px;padding:0 8px;font-size:10px}.inventory-more{grid-column:1/-1;padding:0 0 0 40px;color:var(--color-ink-muted);font-size:10px}.inventory-more summary{width:max-content;max-width:100%;cursor:pointer;list-style-position:inside}.inventory-more summary span{margin-left:7px;color:var(--color-ink-muted)}.inventory-detail{display:flex;align-items:center;flex-wrap:wrap;gap:8px 18px;padding:7px 0 2px}.inventory-detail p{margin:0}.inventory-detail code{display:inline;overflow-wrap:anywhere}.inventory-artifacts{display:flex;flex-wrap:wrap;gap:6px}.inventory-artifacts>div{display:flex;align-items:center;gap:7px;padding:3px 6px;border-radius:5px;background:var(--color-border);color:var(--color-ink-muted);font-size:10px}
.assignment-form>label{margin:16px 0}.assignment-preview{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:18px;padding:16px;border-radius:14px;background:var(--color-info-soft)}.assignment-preview div{display:grid;gap:4px}.assignment-preview span{color:var(--color-ink-muted);font-size:10px}.assignment-preview p{grid-column:1/-1;margin:4px 0 0;color:var(--color-ink-muted);font-size:11px;line-height:1.7}
@media(max-width:980px){.inventory-row{grid-template-columns:minmax(190px,1fr) minmax(190px,1fr);gap:8px 12px}.inventory-actions{grid-column:1/-1;justify-content:flex-start}.inventory-more{grid-column:1/-1}}
@media(max-width:620px){.inventory-guide{align-items:flex-start;flex-direction:column}.target-switch{width:100%}.target-switch button{flex:1;justify-content:center;padding:0 7px}.target-pool-heading{align-items:flex-start;padding:12px;flex-direction:column}.inventory-list{padding:0 10px}.inventory-row{grid-template-columns:1fr;gap:8px;padding:12px 0}.inventory-meta{gap:7px 14px}.inventory-actions{grid-column:auto;justify-content:flex-start}.inventory-more{grid-column:auto;padding-left:0}.inventory-detail{align-items:flex-start;flex-direction:column}.assignment-preview{grid-template-columns:1fr}.assignment-preview p{grid-column:auto}}
</style>
