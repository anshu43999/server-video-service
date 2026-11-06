<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Box, RefreshCw } from '@lucide/vue'
import UiDialog from '../../components/ui/UiDialog.vue'
import UiStatePanel from '../../components/ui/UiStatePanel.vue'
import { errorText, formatBytes, modelsApi } from './api'
import { removalSummary, removalOutcome, type RemovalImpact } from './lifecycle'
import { isApiError } from '../../api/errors'
import type { ModelAsset, ModelTarget } from './types'
import { targetLabel, targetStatus, targetReady, supportedTargets } from './capabilities'
import ParametersDialog from './ParametersDialog.vue'
import CalibrationPane from './CalibrationPane.vue'
import ConversionPane from './ConversionPane.vue'
import './models.css'
const route = useRoute(), router = useRouter()
const pane = computed(() => ['upload', 'calibration'].includes(String(route.query.pane)) ? String(route.query.pane) : 'catalog')
const models = ref<ModelAsset[]>([])
const phase = ref<'loading' | 'ready' | 'error'>('loading'), error = ref(''), message = ref(''), tone = ref('success')
const query = ref(''), scenario = ref(''), busy = ref(false), registerOpen = ref(false), manifest = ref('')
const detailOpen = ref(false), detail = ref<ModelAsset | null>(null), detailTarget = ref<ModelAsset | null>(null), detailError = ref(''), detailBusy = ref(false)
const parameterModel = ref<ModelAsset | null>(null), removeTarget = ref<ModelAsset | null>(null)
const removalImpact=ref<RemovalImpact|null>(null),removalKey=ref(''),removalChecked=ref(false)
async function beginRemoval(model:ModelAsset){
  if(busy.value)return
  busy.value=true;removalImpact.value=null;removalChecked.value=false
  try{const impact=await modelsApi.impact(model.modelId,model.version);if(disposed)return;removalImpact.value=impact;removalKey.value=crypto.randomUUID();removeTarget.value=model}
  catch(error){if(!disposed)notice(errorText(error),true)}finally{busy.value=false}
}
const publishTarget=ref<ModelAsset|null>(null), publishPc=ref(false), publishMobile=ref(false), licenseApproved=ref(false), publishReason=ref('')
function beginPublish(model:ModelAsset){publishTarget.value=model;publishPc.value=targetReady(model,'pc');publishMobile.value=targetReady(model,'mobile');licenseApproved.value=false;publishReason.value=''}
async function publish(){
  const model=publishTarget.value;const targets:ModelTarget[]=[]
  if(publishPc.value)targets.push('pc');if(publishMobile.value)targets.push('mobile')
  if(!model||!licenseApproved.value||!publishReason.value.trim()||!targets.length)return
  if(await operate(()=>modelsApi.publish(model,targets,publishReason.value.trim()),'所选目标端已通过发布门禁。'))publishTarget.value=null
}
let controller: AbortController | undefined, detailController: AbortController | undefined, disposed = false
const families = computed(() => [...new Map(models.value.map(m => [m.modelId, m])).values()])
const scenarios = computed(() => [...new Set(models.value.map(m => m.scenario).filter(Boolean))] as string[])
const filtered = computed(() => models.value.filter(m => (!scenario.value || m.scenario === scenario.value) && `${m.modelId} ${m.name} ${m.version} ${(m.labels ?? []).join(' ')}`.toLowerCase().includes(query.value.trim().toLowerCase())))
function notice(text: string, failed = false) { message.value = text; tone.value = failed ? 'error' : 'success' }
async function refresh() {
  controller?.abort(); controller = new AbortController(); const signal = controller.signal
  const results = await Promise.allSettled([modelsApi.list(signal)])
  if (disposed || signal.aborted) return
  const [catalog] = results
  if (catalog.status === 'fulfilled') { models.value = catalog.value; phase.value = 'ready'; error.value = '' }
  else { phase.value = 'error'; error.value = errorText(catalog.reason) }
}
async function operate(action: () => Promise<unknown>, text: string) {
  if (busy.value) return false
  busy.value = true
  try { await action(); if (!disposed) { notice(text); await refresh() }; return true }
  catch (e) { if (!disposed) { notice(errorText(e), true); await refresh() }; return false }
  finally { busy.value = false }
}
async function openDetail(model: ModelAsset, version = model.version) {
  detailController?.abort(); detailController = new AbortController(); const signal = detailController.signal
  detailOpen.value = true; detailTarget.value = model; detail.value = null; detailError.value = ''; detailBusy.value = true
  try { const value = await modelsApi.detail(model.modelId, version, signal); if (!disposed && !signal.aborted) detail.value = value }
  catch (e) { if (!signal.aborted && !disposed) detailError.value = errorText(e) }
  finally { if (!signal.aborted) detailBusy.value = false }
}
async function register() {
  if (await operate(() => modelsApi.register(manifest.value.trim()), 'Manifest 已通过校验并登记。')) { registerOpen.value = false; manifest.value = '' }
}
async function remove() {
  const target = removeTarget.value; if (!target||busy.value) return
  const impact=removalImpact.value;if(!impact?.safeToRemove||!removalChecked.value)return
  busy.value=true
  try{
    const result=removalOutcome(await modelsApi.remove(target.modelId,target.version,impact.expectedRevision,removalKey.value))
    if(!disposed){message.value=result.text;tone.value=result.pending?'warning':'success';removeTarget.value=null;detailOpen.value=false;await refresh()}
  }catch(error){
    if(!disposed){
      const conflict=isApiError(error)&&error.status===409
      notice(`${errorText(error)} ${conflict?'请重新预览影响后再操作。':'结果尚未确认，可保持窗口使用同一操作标识重试。'}`,true)
      if(conflict)removeTarget.value=null
      await refresh()
    }
  }finally{busy.value=false}
}
function activate(model: ModelAsset) { void operate(() => modelsApi.activate(model.modelId), '已设置新流默认模型，已有视频流绑定保持不变。') }
function validatePcRuntime(model: ModelAsset) { void operate(() => modelsApi.validatePcRuntime(model), 'PC runtime 验证通过，可以继续发布。') }
function testInProject(model: ModelAsset) {
  const target = router.resolve({ name: 'project-models', query: { modelId: model.modelId, version: model.version } })
  void router.push({ name: 'projects', query: { redirect: target.fullPath } })
}
function download(artifactId: string) { const model = detail.value; if (model) void operate(() => modelsApi.download(model, artifactId), '产物下载已开始。') }
onMounted(refresh)
onBeforeUnmount(() => { disposed = true; controller?.abort(); detailController?.abort() })
</script>
<template>
  <section class="models-page model-workspace">
    <div class="model-actions page-actions"><UiButton class="secondary-button" @click="refresh"><RefreshCw :size="16" />刷新目录</UiButton></div>
    <UiTabs class="model-tabs" aria-label="模型工作区" :model-value="pane" :items="[{id:'catalog',label:'模型目录'},{id:'upload',label:'上传与处理'},{id:'calibration',label:'校准集'}]" @update:model-value="value => router.replace({query:{...route.query,pane:value}})" />
    <p v-if="message" class="operation-feedback" :class="`is-${tone}`" role="status">{{ message }}</p>
    <template v-if="pane === 'catalog'">
      <div class="model-toolbar"><label class="model-search"><span class="sr-only">搜索模型</span><UiInput v-model="query" placeholder="搜索名称、ID、类别" /></label><label>场景<UiSelect v-model="scenario"><UiOption value="">全部场景</UiOption><UiOption v-for="s in scenarios" :key="s" :value="s">{{ s }}</UiOption></UiSelect></label><UiButton class="primary-button" :disabled="busy" @click="registerOpen = true">登记 Manifest</UiButton></div>
      <UiStatePanel v-if="phase !== 'ready'" :state="phase" title="模型目录" :message="error || '正在读取模型资产…'" @retry="refresh" />
      <UiStatePanel v-else-if="!filtered.length" state="empty" title="暂无匹配的模型" message="上传训练模型或登记已有 Manifest 后，真实资产会显示在这里。" />
      <div v-else class="model-grid">
        <article v-for="model in filtered" :key="`${model.modelId}:${model.version}`" class="model-card">
          <div class="model-card-title"><Box :size="22" /><div><h3>{{ model.name }}</h3><code>{{ model.modelId }} / {{ model.version }}</code></div><UiTag v-if="model.active" class="model-badge ready" tone="success">新流默认</UiTag></div>
          <div class="model-tags"><UiTag class="model-badge">{{ model.status || '状态未知' }}</UiTag><UiTag>{{ model.scenario || '未分类' }}</UiTag></div>
          <p class="target-classification">{{ targetLabel(model) }}<small v-if="model.supportedTargetsSource==='legacy-derived'">历史产物派生</small></p>
          <dl class="model-readiness"><div><dt>PC 端</dt><dd :class="{ready:targetReady(model,'pc')}">{{ targetStatus(model,'pc') }}</dd></div><div><dt>移动端</dt><dd :class="{ready:targetReady(model,'mobile')}">{{ targetStatus(model,'mobile') }}</dd></div><div><dt>移动签名</dt><dd>{{ supportedTargets(model).includes('mobile') ? model.signatureStatus || 'unsigned' : '不适用' }}</dd></div></dl>
          <p v-if="supportedTargets(model).includes('pc')" class="model-muted">PC 运行验证：{{ model.serverValidated && model.serverValidationSha256?.toLowerCase() === model.sha256?.toLowerCase() ? '已通过当前产物验证' : '尚未通过或验证已过期' }}</p>
          <UiButton v-if="supportedTargets(model).includes('pc')" class="secondary-button" :disabled="busy||!targetReady(model,'pc')" @click="validatePcRuntime(model)">验证 PC 运行时</UiButton>
          <UiButton v-if="['READY','PUBLISHED'].includes(model.status||'')" class="secondary-button" :disabled="busy||(!targetReady(model,'pc')&&!targetReady(model,'mobile'))" @click="beginPublish(model)">按端发布</UiButton>
          <p class="model-labels">{{ (model.labels ?? []).join(' · ') || '暂无类别信息' }}</p>
          <p v-if="!model.serverBindable" class="model-muted">当前版本不可新绑定。版本状态、产物完整性和绑定投影以服务端为准。</p>
          <div class="model-actions"><UiButton class="secondary-button" @click="openDetail(model)">版本详情</UiButton><UiButton class="secondary-button" @click="parameterModel = model">参数档案</UiButton><UiButton class="secondary-button" :disabled="busy || model.active || !model.serverBindable" @click="activate(model)">设为新流默认</UiButton><UiButton class="secondary-button danger-text" :disabled="busy || model.status === 'UNINSTALLED'" @click="beginRemoval(model)">卸载</UiButton></div>
        </article>
      </div>
      <section class="model-panel"><header><h3>项目模型使用</h3></header><p class="model-muted">此处维护全局模型资产，不读取任何项目的视频流。请显式进入项目后，在项目视频流中查看和维护绑定。</p><UiButton class="secondary-button" @click="router.push({ name: 'projects' })">进入项目空间</UiButton></section>
    </template>
    <ConversionPane v-else-if="pane === 'upload'" :families="families" @changed="refresh" />
    <CalibrationPane v-else @changed="refresh" />
    <UiDialog v-model:open="registerOpen" title="登记模型 Manifest" :busy="busy"><form class="model-form" @submit.prevent="register"><p class="model-muted">填写服务器 models 目录内已有 Manifest 的受控路径，登记时会校验产物与哈希。</p><label>Manifest 路径<UiInput v-model="manifest" required maxlength="512" /></label><footer><UiButton type="button" class="secondary-button" :disabled="busy" @click="registerOpen=false">取消</UiButton><UiButton class="primary-button" :disabled="busy">{{ busy ? '校验中…' : '校验并登记' }}</UiButton></footer><p v-if="tone === 'error'" class="operation-feedback is-error">{{ message }}</p></form></UiDialog>
    <UiDialog v-model:open="detailOpen" title="模型版本详情" :busy="busy"><div class="model-detail"><UiStatePanel v-if="detailBusy" state="loading" /><UiStatePanel v-else-if="detailError" state="error" :message="detailError" @retry="detailTarget && openDetail(detailTarget)" /><template v-else-if="detail"><h3>{{ detail.name }}</h3><code>{{ detail.modelId }} / {{ detail.version }}</code><label>查看版本<UiSelect :value="detail.version" @change="value => detail && openDetail(detail, String(value))"><UiOption v-for="v in detail.availableVersions || [detail.version]" :key="v" :value="v">{{ v }}</UiOption></UiSelect></label><p>版本状态：{{ detail.status }} · 签名：{{ detail.signatureStatus }} · 输入：{{ detail.inputSize ?? '未知' }}</p><p>商业发布：{{ detail.releaseEligible ? '符合发布门禁' : '尚未满足发布门禁' }}</p><p v-if="detail.revokeReason">撤回原因：{{ detail.revokeReason }}</p><p class="model-muted">原始类别：{{ (detail.labels ?? []).join(' · ') || '暂无' }}</p><pre v-if="detail.license">{{ JSON.stringify(detail.license, null, 2) }}</pre><article v-for="artifact in detail.artifacts" :key="artifact.artifactId" class="artifact-row"><strong>{{ artifact.artifactId }} · {{ artifact.platform }} / {{ artifact.format }}</strong><p>{{ formatBytes(artifact.sizeBytes) }} · {{ artifact.exists && artifact.hashValid ? '文件校验通过' : '文件缺失或校验失败' }}</p><code>{{ artifact.sha256 }}</code><UiButton class="secondary-button" :disabled="busy || !artifact.exists || !artifact.hashValid" @click="download(artifact.artifactId)">下载产物</UiButton></article></template><p v-if="tone === 'error'" class="operation-feedback is-error">{{ message }}</p></div></UiDialog>
    <ParametersDialog v-if="parameterModel" :model="parameterModel" @close="parameterModel=null" />
    <UiDialog :open="!!publishTarget" title="按目标端发布模型" :busy="busy" @update:open="value=>{if(!value)publishTarget=null}"><form class="model-form" @submit.prevent="publish">
      <p>{{publishTarget?.name}} / {{publishTarget?.version}}</p><p class="model-muted">PC 发布不要求移动转换或签名。移动端需独立复验与受信任发布签名；服务器会再次校验许可证和产物。</p>
      <label class="model-check"><UiInput v-model="publishPc" type="checkbox" :disabled="busy||!publishTarget||!targetReady(publishTarget,'pc')"/>发布 PC 端</label>
      <label class="model-check"><UiInput v-model="publishMobile" type="checkbox" :disabled="busy||!publishTarget||!targetReady(publishTarget,'mobile')"/>发布移动端</label>
      <label>发布原因<UiInput v-model="publishReason" required maxlength="512" :disabled="busy"/></label><label class="model-check"><UiInput v-model="licenseApproved" type="checkbox" :disabled="busy"/>确认来源及分发许可证已审核</label>
      <p v-if="tone==='error'" role="alert">{{message}}</p><footer><UiButton type="button" class="secondary-button" :disabled="busy" @click="publishTarget=null">取消</UiButton><UiButton class="primary-button" :disabled="busy||!licenseApproved||!publishReason.trim()||(!publishPc&&!publishMobile)">确认发布</UiButton></footer>
    </form></UiDialog>
    <UiDialog :open="!!removeTarget" title="卸载模型版本：影响确认" :busy="busy" @update:open="open=>{if(!open)removeTarget=null}"><form class="model-form" @submit.prevent="remove">
      <p>{{removeTarget?.modelId}} / {{removeTarget?.version}} · 修订 {{removalImpact?.expectedRevision}}</p><p v-if="removalImpact">{{removalSummary(removalImpact)}}</p>
      <p>卸载包含云端模型版本退役及其未共享产物的物理回收；不是单纯停用。已停用但尚未删除的场景仍然阻止卸载，请先调整或删除依赖。</p><p>不会远程擦除 App 已下载文件，也不会删除其他版本、共享产物或历史告警证据。</p>
      <p v-if="removalImpact&&!removalImpact.safeToRemove" role="alert">当前存在依赖，不能卸载；调整后请关闭并重新预览。</p>
      <label class="model-check"><UiInput v-model="removalChecked" type="checkbox" :disabled="busy||!removalImpact?.safeToRemove"/>我已确认云端物理回收范围</label><p v-if="tone==='error'" role="alert">{{message}}</p>
      <footer><UiButton type="button" class="secondary-button" :disabled="busy" @click="removeTarget=null">取消</UiButton><UiButton class="primary-button" :disabled="busy||!removalChecked||!removalImpact?.safeToRemove">确认卸载</UiButton></footer>
    </form></UiDialog>
  </section>
</template>
