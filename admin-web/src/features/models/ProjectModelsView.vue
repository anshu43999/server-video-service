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
const current = computed(() => data.value.assignments.find(assignment =>
  assignment.modelId === selected.value?.modelId
  && assignment.modelVersion === selected.value?.version
  && assignment.target === selectedTarget.value,
))
const selectedProfile = computed(() => selected.value?.parameterProfiles[platformFor(selectedTarget.value)])
const canSave = computed(() => !!selected.value && availableTargets.value.includes(selectedTarget.value) && !!selectedProfile.value)

function assetFor(assignment:Assignment):ModelAsset|undefined {
  return data.value.models.find(model => model.modelId === assignment.modelId && model.version === assignment.modelVersion)
    ?? data.value.available.find(model => model.modelId === assignment.modelId && model.version === assignment.modelVersion)
}
const assignmentName=(assignment?:Assignment|null)=>modelDisplayName(assignment?.modelName?.trim()?assignment:assignment?assetFor(assignment):null)
function artifactsFor(assignment:Assignment) {
  return (assetFor(assignment)?.artifacts ?? []).filter(artifact => artifact.platform === assignment.parameterPlatform)
}
function assignmentTargetStatus(assignment:Assignment) {
  const asset = assetFor(assignment)
  return asset ? targetStatus(asset, assignment.target) : '状态未知'
}
function selectRelease(value:string|number) {
  selectedKey.value = String(value)
  if (!availableTargets.value.includes(selectedTarget.value)) selectedTarget.value = availableTargets.value[0] ?? 'pc'
}
watch(candidates,()=>{if(selectedKey.value)selectRelease(selectedKey.value)})
function begin(assignment?:Assignment, preferredTarget?:ModelTarget, initialModelKey?:string) {
  if (!canAssign.value || needsReload.value) return
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
async function save() {
  const model = selected.value
  const profile = selectedProfile.value
  if (!canAssign.value || candidatesLoading.value || candidatesError.value || !model || !profile || !canSave.value) return
  await run(signal => projectModelsApi.save({
    modelId:model.modelId, modelVersion:model.version, target:selectedTarget.value,
    parameterRevision:profile.revision, enabled:true, expectedRevision:current.value?.revision ?? 0,
  }, signal), () => { confirm.value=false; open.value=false; editing.value=null })
  if (mutationError.value) confirm.value = false
}
async function disable(assignment:Assignment) {
  if (!canAssign.value || needsReload.value) return
  await run(signal => projectModelsApi.save({
    modelId:assignment.modelId, modelVersion:assignment.modelVersion, target:assignment.target,
    parameterRevision:assignment.parameterRevision, enabled:false, expectedRevision:assignment.revision,
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
            <div class="inventory-meta"><span><small>发布</small>{{modelStatusLabel(assetFor(assignment)?.status)}}</span><span><small>PC 端</small>{{assignmentTargetStatus(assignment)}}</span><span><small>参数修订</small>r{{assignment.parameterRevision}}</span></div>
            <div class="inventory-actions">
              <UiButton v-if="assignment.enabled" class="secondary-button" @click="showParameters(assignment)">{{canAssign?'参数':'查看参数'}}</UiButton>
              <UiButton v-if="canAssign" class="secondary-button" :disabled="busy||needsReload" @click="begin(assignment)">{{assignment.enabled?'重新批准':'重新启用'}}</UiButton>
              <UiButton v-if="canAssign&&assignment.enabled" class="secondary-button danger-text" :disabled="busy||needsReload" @click="disabling=assignment">停用</UiButton>
              <UiButton v-if="canAssign&&!assignment.enabled" class="secondary-button danger-text" :disabled="busy||needsReload" @click="removing=assignment">移除</UiButton>
            </div>
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
            <div class="inventory-meta"><span><small>发布</small>{{modelStatusLabel(assetFor(assignment)?.status)}}</span><span><small>移动端</small>{{assignmentTargetStatus(assignment)}}</span><span><small>参数修订</small>r{{assignment.parameterRevision}}</span></div>
            <div class="inventory-actions">
              <UiButton v-if="assignment.enabled" class="secondary-button" @click="showParameters(assignment)">{{canAssign?'参数':'查看参数'}}</UiButton>
              <UiButton v-if="canAssign" class="secondary-button" :disabled="busy||needsReload" @click="begin(assignment)">{{assignment.enabled?'重新批准':'重新启用'}}</UiButton>
              <UiButton v-if="canAssign&&assignment.enabled" class="secondary-button danger-text" :disabled="busy||needsReload" @click="disabling=assignment">停用</UiButton>
              <UiButton v-if="canAssign&&!assignment.enabled" class="secondary-button danger-text" :disabled="busy||needsReload" @click="removing=assignment">移除</UiButton>
            </div>
            <details class="inventory-more"><summary>详情与产物 <span>清单 r{{assignment.revision}}</span></summary><div class="inventory-detail"><p>项目模型 ID <code>{{assignment.projectModelId}}</code></p><div v-if="artifactsFor(assignment).length" class="inventory-artifacts"><div v-for="artifact in artifactsFor(assignment)" :key="artifact.artifactId"><span>{{artifact.format.toUpperCase()}} · {{formatBytes(artifact.sizeBytes)}}</span><UiButton class="secondary-button" :disabled="busy||!active||!assignment.enabled||!artifact.exists||!artifact.hashValid" @click="download(assignment,artifact.artifactId)">下载产物</UiButton></div></div><span v-else class="model-muted">暂无可下载产物</span></div></details>
          </section>
        </div>
      </article>
    </div>

    <UiDialog v-model:open="open" title="分配项目模型" :busy="busy">
      <p v-if="candidatesLoading" role="status">正在读取可分配模型…</p><p v-if="candidatesError" role="alert">{{candidatesError}} <UiButton @click="reloadCandidates">重试模型候选</UiButton></p>
      <form class="model-form assignment-form" @submit.prevent="confirm=true">
        <label>模型版本
          <UiSelect :model-value="selectedKey" :disabled="busy||needsReload" @update:model-value="selectRelease">
            <UiOption value="">请选择模型版本</UiOption>
            <UiOption v-for="model in candidates" :key="key(model)" :value="key(model)">{{modelDisplayName(model)}} / {{model.version}}</UiOption>
          </UiSelect>
        </label>
        <label>启用目标端
          <UiSelect v-model="selectedTarget" :disabled="busy||needsReload||!!editing">
            <UiOption value="pc" :disabled="!availableTargets.includes('pc')">PC 端{{availableTargets.includes('pc')?'':'（不可用）'}}</UiOption>
            <UiOption value="mobile" :disabled="!availableTargets.includes('mobile')">移动端{{availableTargets.includes('mobile')?'':'（不可用）'}}</UiOption>
          </UiSelect>
        </label>
        <section v-if="selected&&selectedProfile" class="assignment-preview">
          <div><span>将加入</span><strong>{{targetLabel(selectedTarget)}}模型池</strong></div>
          <div><span>参数修订</span><strong>r{{selectedProfile.revision}}</strong></div>
          <div><span>当前条目</span><strong>{{current?`更新 r${current.revision}`:'新建'}}</strong></div>
          <p>作为独立条目加入模型池；不会创建场景，也不会启动运行任务。</p>
        </section>
        <p v-if="selected&&!selectedProfile" class="operation-feedback is-warning">该模型版本的{{targetLabel(selectedTarget)}}产物或参数尚未就绪，请选择其他目标端。</p>
        <p v-if="!candidatesLoading&&!candidatesError&&!candidates.length" class="model-muted">当前没有满足项目授权条件的可分配版本，请联系平台管理员检查模型发布与目标端就绪状态。</p>
        <p v-if="mutationError" class="operation-feedback is-error" role="alert">{{mutationError}}</p>
        <footer><UiButton type="button" class="secondary-button" :disabled="busy" @click="open=false">取消</UiButton><UiButton class="primary-button" :disabled="busy||needsReload||!canSave||!canAssign">确认分配</UiButton></footer>
      </form>
    </UiDialog>
    <UiConfirmDialog v-model:open="confirm" title="确认加入项目模型池" :description="`${modelDisplayName(selected)} / ${selected?.version} 将作为独立条目加入${targetLabel(selectedTarget)}模型池。此操作不会创建场景，也不会启动运行任务。`" confirm-label="确认分配" :busy="busy" @confirm="save"/>
    <ParametersDialog v-if="parameters" :model="parameters" :read-only="!canAssign" project-mode :initial-platform="parameters.assignment.parameterPlatform" @close="parameters=null;refresh()"/>
    <UiConfirmDialog :open="!!disabling" title="停用项目模型" :description="`停用 ${assignmentName(disabling)} / ${disabling?.modelVersion} 的${targetLabel(disabling?.target ?? 'pc')}条目。场景中已有的引用需要在场景配置中另行处理；在用 PC 流须先停止。`" confirm-label="确认停用" tone="danger" :busy="busy" @update:open="value=>{if(!value)disabling=null}" @confirm="disabling&&disable(disabling)"/>
    <UiConfirmDialog :open="!!removing" title="移除项目模型" :description="`永久移除已停用的 ${assignmentName(removing)} / ${removing?.modelVersion} ${targetLabel(removing?.target ?? 'pc')}条目。`" confirm-label="确认移除" tone="danger" :busy="busy" @update:open="value=>{if(!value)removing=null}" @confirm="removing&&remove(removing)"/>
  </section>
</template>

<style scoped>
.inventory-guide{display:flex;align-items:center;gap:10px;margin:18px 0 16px;padding:12px 16px;border-radius:8px;background:#eaf3ed;color:#264d37}.inventory-guide span{color:#526d5b;line-height:1.55}
.target-pools{display:grid;gap:10px}.target-switch{display:flex;width:max-content;max-width:100%;gap:4px;padding:4px;border-radius:8px;background:#e9eeea}.target-switch button{display:flex;align-items:center;gap:9px;min-height:40px;padding:0 12px;border:0;border-radius:6px;background:transparent;color:var(--color-ink-muted);font:inherit;font-size:12px;font-weight:600;cursor:pointer}.target-switch button[aria-selected="true"]{background:var(--color-surface);color:var(--color-ink);box-shadow:0 1px 4px rgb(20 35 25 / 12%)}.target-switch button:focus-visible{outline:2px solid var(--color-primary);outline-offset:2px}.target-switch-mark{display:grid;place-items:center;min-width:28px;height:24px;padding:0 5px;border-radius:5px;background:#315f43;color:#fff;font-size:9px;font-weight:800}.target-switch button:nth-child(2) .target-switch-mark{background:#365f7d}.target-switch strong{display:grid;place-items:center;min-width:22px;height:22px;padding:0 5px;border-radius:11px;background:#edf0ed;color:#425248;font-size:10px}
.target-pool{overflow:hidden;border:1px solid var(--color-border);border-radius:8px;background:var(--color-surface)}.target-pool-heading{display:flex;align-items:center;justify-content:space-between;gap:14px;padding:12px 16px;background:#f2f6f2;border-bottom:1px solid var(--color-border)}.target-pool.is-mobile .target-pool-heading{background:#f1f5f8}.target-pool-heading h3{font-size:15px}.target-pool-heading span{display:block;margin-top:3px;color:var(--color-ink-muted);font-size:10px;line-height:1.45}.pool-add{margin:0;flex:none}
.inventory-list{padding:0 14px}.inventory-row{display:grid;grid-template-columns:minmax(210px,1.25fr) minmax(230px,1fr) auto;align-items:center;gap:12px;padding:11px 2px;border-bottom:1px solid var(--color-border)}.inventory-row:last-child{border-bottom:0}.inventory-row.is-disabled{background:linear-gradient(90deg,#f8f7f5,transparent);opacity:.82}.inventory-main{display:flex;align-items:center;gap:10px;min-width:0}.inventory-main>div{min-width:0}.inventory-main h4{font-size:13px;overflow-wrap:anywhere}.inventory-main code{font-size:10px;line-height:1.5}.inventory-state{flex:none;padding:4px 7px;border-radius:5px;font-size:10px;font-weight:700}.inventory-state.is-enabled{color:#245c3b;background:#dff0e4}.inventory-state.is-stopped{color:#7c4b42;background:#f5e5e1}
.inventory-meta{display:flex;flex-wrap:wrap;gap:6px 14px;color:var(--color-ink);font-size:10px}.inventory-meta span{display:grid;gap:2px}.inventory-meta small{color:var(--color-ink-muted);font-size:9px}.inventory-actions{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:5px}.inventory-actions button{min-height:29px;padding:0 8px;font-size:10px}.inventory-more{grid-column:1/-1;padding:0 0 0 40px;color:var(--color-ink-muted);font-size:10px}.inventory-more summary{width:max-content;max-width:100%;cursor:pointer;list-style-position:inside}.inventory-more summary span{margin-left:7px;color:var(--color-ink-muted)}.inventory-detail{display:flex;align-items:center;flex-wrap:wrap;gap:8px 18px;padding:7px 0 2px}.inventory-detail p{margin:0}.inventory-detail code{display:inline;overflow-wrap:anywhere}.inventory-artifacts{display:flex;flex-wrap:wrap;gap:6px}.inventory-artifacts>div{display:flex;align-items:center;gap:7px;padding:3px 6px;border-radius:5px;background:#f1f4f1;color:var(--color-ink-muted);font-size:10px}
.assignment-form>label{margin:16px 0}.assignment-preview{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:18px;padding:16px;border-radius:14px;background:#eef5f0}.assignment-preview div{display:grid;gap:4px}.assignment-preview span{color:var(--color-ink-muted);font-size:10px}.assignment-preview p{grid-column:1/-1;margin:4px 0 0;color:#496554;font-size:11px;line-height:1.7}
@media(max-width:980px){.inventory-row{grid-template-columns:minmax(190px,1fr) minmax(190px,1fr);gap:8px 12px}.inventory-actions{grid-column:1/-1;justify-content:flex-start}.inventory-more{grid-column:1/-1}}
@media(max-width:620px){.inventory-guide{align-items:flex-start;flex-direction:column}.target-switch{width:100%}.target-switch button{flex:1;justify-content:center;padding:0 7px}.target-pool-heading{align-items:flex-start;padding:12px;flex-direction:column}.inventory-list{padding:0 10px}.inventory-row{grid-template-columns:1fr;gap:8px;padding:12px 0}.inventory-meta{gap:7px 14px}.inventory-actions{grid-column:auto;justify-content:flex-start}.inventory-more{grid-column:auto;padding-left:0}.inventory-detail{align-items:flex-start;flex-direction:column}.assignment-preview{grid-template-columns:1fr}.assignment-preview p{grid-column:auto}}
</style>
