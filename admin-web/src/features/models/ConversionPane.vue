<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import UiStatePanel from '../../components/ui/UiStatePanel.vue'
import UiDialog from '../../components/ui/UiDialog.vue'
import { conversionApi, errorText, formatBytes, saveBlob } from './api'
import { isApiError, redactMessage } from '../../api/errors'
import type { CalibrationDataset, ConversionConfig, ConversionJob, ModelAsset, ModelTarget } from './types'
import { createCatalogChangeTracker } from './catalogChanges'
import { VisiblePoller } from '../../api/visiblePoller'
const props = defineProps<{ families: ModelAsset[]; trackCatalogChanges?: (jobs: ConversionJob[]) => boolean }>()
const emit = defineEmits<{ changed: []; pending: [value: boolean] }>()
const config = ref<ConversionConfig | null>(null), datasets = ref<CalibrationDataset[]>([]), jobs = ref<ConversionJob[]>([])
const phase = ref<'loading'|'ready'|'error'>('loading'), loadError = ref(''), jobError = ref(''), message = ref(''), failed = ref(false)
const busy = ref(false), uploading = ref(false), file = ref<File | null>(null), fileInput = ref<{ clear: () => void }>(), progress = ref<number | null>(null)
const maxBytes = ref<number | null>(null), calibrationId = ref(''), family = ref('new'), now = ref(Date.now() / 1000)
const form = reactive({name:'',version:'1.0.0',scenario:'general-detection',modelId:''})
const uploadTargets=ref<'pc'|'mobile'|'dual'>('pc')
const logOpen = ref(false), logText = ref(''), logBusy = ref(false), logId = ref('')
let controller: AbortController | undefined, uploadController: AbortController | undefined
let disposed = false
const readyDatasets = computed(() => datasets.value.filter(d => d.status === 'ready'))
const labels = {queued:'排队中',running:'执行中',succeeded:'完成',failed:'失败',interrupted:'已中断'}
const actions = {check:'环境检测',inspect:'PT 验证',mobile:'移动端转换'}
const catalogChanged = props.trackCatalogChanges ?? createCatalogChangeTracker()
const jobPoller = new VisiblePoller({
  read: conversionApi.jobs,
  enabled: () => phase.value === 'ready' && !busy.value && !uploading.value,
  delay: value => value.some(job => ['queued', 'running'].includes(job.status)) ? 3000 : 30000,
  accept: value => {
    const changed = catalogChanged(value)
    jobs.value = value; jobError.value = ''; now.value = Date.now()/1000
    emit('pending', value.some(job => job.action !== 'check' && ['queued', 'running'].includes(job.status)))
    if (changed) emit('changed')
  },
  error: e => { jobError.value = errorText(e); if (isApiError(e) && [401,403].includes(e.status ?? 0)) phase.value = 'error' },
})
function poll() { return jobPoller.refresh() }
function notice(text: string, error = false) { message.value = text; failed.value = error }
async function initialize() {
  jobPoller.pause()
  controller?.abort(); controller = new AbortController(); const signal = controller.signal
  phase.value = 'loading'; loadError.value = ''
  try {
    const [settings, calibration] = await Promise.all([conversionApi.config(signal), conversionApi.datasets(signal)])
    if (disposed || signal.aborted) return
    config.value = settings.config; maxBytes.value = settings.max_upload_bytes; datasets.value = calibration.datasets
    calibrationId.value = settings.config.default_calibration_dataset_id; phase.value = 'ready'
    jobPoller.start(); await jobPoller.resume()
  } catch (e) { if (!disposed && !signal.aborted) { phase.value = 'error'; loadError.value = errorText(e) } }
}
async function operate(action: () => Promise<unknown>, success: string) {
  if (busy.value || uploading.value) return
  jobPoller.pause(); busy.value = true
  try { await action(); if (!disposed) notice(success) }
  catch (e) { if (!disposed) notice(errorText(e), true) }
  finally { busy.value = false; if (!disposed) await jobPoller.resume() }
}
async function saveConfig() {
  const current = config.value; if (!current) return
  if (current.mode === 'remote') {
    try {
      const url = new URL(current.remote_endpoint)
      if (url.username || url.password || url.search || url.hash || !['https:', ...(current.remote_allow_insecure_http ? ['http:'] : [])].includes(url.protocol)) throw new Error('远程地址必须使用 HTTPS，且不能包含凭据、查询参数或片段')
      if (!/^[A-Za-z_][A-Za-z0-9_]{0,99}$/.test(current.remote_token_env)) throw new Error('请填写令牌的环境变量名，不填写令牌明文')
    } catch (e) { notice(errorText(e), true); return }
  }
  await operate(async () => { const saved = await conversionApi.configure({...current,calibration_data:''}); if (!disposed) config.value = saved.config }, '配置已保存。新任务使用此配置，执行中的任务保持原配置。')
}
function selectFile(value?: File) {
  file.value = value ?? null
  if (file.value && !form.name) form.name = file.value.name.replace(/\.pt$/i, '')
}
async function upload() {
  if (busy.value || uploading.value || !file.value || maxBytes.value === null) return
  if (!file.value.name.toLowerCase().endsWith('.pt') || !file.value.size || file.value.size > maxBytes.value) { notice('请选择有效 .pt 文件，大小必须在服务端上传限制内。', true); return }
  const id = family.value === 'new' ? form.modelId.trim() : family.value
  if (id && !/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(id)) { notice('模型 ID 只能包含字母、数字、点、下划线和连字符。', true); return }
  uploading.value = true; progress.value = null; uploadController = new AbortController(); jobPoller.pause()
  try {
    const targets:ModelTarget[]=uploadTargets.value==='dual'?['pc','mobile']:[uploadTargets.value]
    await conversionApi.upload(file.value, { name:form.name.trim(), version:form.version.trim(), scenario:form.scenario.trim(), modelId:id || undefined, supportedTargets:targets }, uploadController.signal, value => { progress.value = value })
    if (!disposed) { file.value = null; fileInput.value?.clear(); form.name = ''; progress.value = null; notice('上传完成，PT 验证已排队。验证成功后才会登记模型。') }
  } catch (e) { if (!disposed) notice(errorText(e), true) }
  finally { uploading.value = false; progress.value = null; if (!disposed) await jobPoller.resume() }
}
function canConvert(job: ConversionJob) {
  if(job.metadata.supported_targets&&!job.metadata.supported_targets.includes('mobile'))return false
  return job.action === 'inspect' && job.status === 'succeeded' && !!job.metadata.upload_id && !jobs.value.some(other => other.action === 'mobile' && other.metadata.upload_id === job.metadata.upload_id)
}
function duration(job: ConversionJob) {
  const seconds = Math.max(0, Math.floor((job.completed_at || now.value) - (job.started_at || job.created_at)))
  return `${job.status === 'queued' ? '等待' : job.completed_at ? '耗时' : '已运行'} ${Math.floor(seconds/60)} 分 ${seconds%60} 秒`
}
function exactProgress(job: ConversionJob) { return typeof job.progress === 'number' && Number.isFinite(job.progress) ? Math.max(0, Math.min(100, job.progress)) : undefined }
async function openLog(job: ConversionJob) {
  logOpen.value = true; logBusy.value = true; logText.value = ''; logId.value = job.id
  try { const text = await conversionApi.log(job.id); if (!disposed && logId.value === job.id) logText.value = text }
  catch (e) { if (!disposed && logId.value === job.id) logText.value = errorText(e) }
  finally { if (logId.value === job.id) logBusy.value = false }
}
function check() { void operate(() => conversionApi.check(), '环境检测已排队，请查看任务结果。') }
function retry(job: ConversionJob) { void operate(() => conversionApi.retry(job.id), '任务已按当前配置重新排队。') }
function mobile(job: ConversionJob) { const uploadId = job.metadata.upload_id; const id = calibrationId.value; if (uploadId) void operate(() => conversionApi.mobile(uploadId, id), '移动端转换已排队，校准集版本与哈希已冻结。') }
function downloadLog() { saveBlob(new Blob([logText.value], {type:'text/plain;charset=utf-8'}), `conversion-${logId.value}.txt`) }
onMounted(initialize)
onBeforeUnmount(() => { disposed = true; jobPoller.stop(); controller?.abort(); uploadController?.abort() })
</script>
<template>
  <div class="conversion-pane">
    <UiStatePanel v-if="phase !== 'ready'" :state="phase" title="转换服务" :message="loadError || jobError || '正在读取转换配置…'" @retry="initialize" />
    <template v-else-if="config">
      <p v-if="message" class="operation-feedback" :class="{'is-error':failed,'is-success':!failed}" role="status">{{ message }}</p>
      <section class="model-panel"><header><h3>上传训练模型</h3><span>原始 PT · 上限 {{ formatBytes(maxBytes ?? undefined) }}</span></header>
        <label>支持目标端<UiSelect v-model="uploadTargets" :disabled="busy||uploading"><UiOption value="pc">仅 PC 端</UiOption><UiOption value="mobile">仅移动端</UiOption><UiOption value="dual">PC / 移动双端</UiOption></UiSelect></label>
        <form class="model-form" @submit.prevent="upload"><fieldset :disabled="busy || uploading"><div class="model-fields"><label>模型族<UiSelect v-model="family"><UiOption value="new">新建模型族</UiOption><UiOption v-for="asset in families" :key="asset.modelId" :value="asset.modelId">{{ asset.name }} · {{ asset.modelId }}</UiOption></UiSelect></label><label v-if="family === 'new'">新模型 ID（留空自动生成）<UiInput v-model="form.modelId" maxlength="128" /></label><label>模型名称<UiInput v-model="form.name" required maxlength="100" /></label><label>模型版本<UiInput v-model="form.version" required maxlength="50" /></label><label>应用场景<UiInput v-model="form.scenario" required maxlength="100" /></label><label class="wide">训练权重 .pt<UiInput ref="fileInput" type="file" accept=".pt" required @change="selectFile" /></label></div><p v-if="file" class="selected-file">已选择 {{ file.name }} · {{ formatBytes(file.size) }}</p><p class="model-muted">上传后先验证服务端模型；移动端 INT8 转换单独执行。文件传输完成不代表模型就绪。</p></fieldset><div v-if="uploading" class="upload-progress"><UiProgress :value="progress" label="训练模型上传进度" /><span>{{ progress === null ? '正在上传' : `${Math.round(progress)}%` }}{{ progress === 100 ? ' · 等待服务端接收确认' : '' }}</span><UiButton class="secondary-button" type="button" @click="uploadController?.abort()">中止上传</UiButton></div><UiButton class="primary-button" :disabled="busy || uploading || !file">上传并验证 PT</UiButton></form>
      </section>
      <UiCollapse class="model-panel conversion-settings"><template #title>转换环境配置 · {{ config.mode }}</template><form class="model-form" @submit.prevent="saveConfig"><fieldset :disabled="busy || uploading"><div class="model-fields"><label>执行模式<UiSelect v-model="config.mode"><UiOption value="local">本地 Python</UiOption><UiOption value="wsl">WSL</UiOption><UiOption value="remote">远程服务</UiOption></UiSelect></label><label>Python 路径<UiInput v-model="config.python_path" maxlength="512" :required="config.mode === 'remote'" /></label><label v-if="config.mode === 'wsl' || (config.mode === 'remote' && config.remote_verifier_mode === 'wsl')">WSL 发行版<UiInput v-model="config.distribution" required maxlength="100" /></label><label>输入尺寸<UiSelect v-model.number="config.input_size"><UiOption :value="320">320</UiOption><UiOption :value="416">416</UiOption><UiOption :value="640">640</UiOption></UiSelect></label><label>超时（秒）<UiInput v-model.number="config.timeout_seconds" type="number" min="30" max="7200" step="1" required /></label><label>默认校准集<UiSelect v-model="config.default_calibration_dataset_id" required><UiOption v-for="dataset in readyDatasets" :key="dataset.datasetId" :value="dataset.datasetId">{{ dataset.name }} / {{ dataset.version }}</UiOption></UiSelect></label><label class="model-check"><UiInput v-model="config.auto_convert" type="checkbox" />PT 验证后自动转换移动端</label></div><div v-if="config.mode === 'remote'" class="model-fields remote-settings"><label class="wide">远程服务地址<UiInput v-model="config.remote_endpoint" type="url" required maxlength="512" /></label><label>令牌环境变量名<UiInput v-model="config.remote_token_env" required maxlength="100" /></label><label>产物本地复验模式<UiSelect v-model="config.remote_verifier_mode"><UiOption value="wsl">WSL</UiOption><UiOption value="local">本地 Python</UiOption></UiSelect></label><label>远程轮询（秒）<UiInput v-model.number="config.remote_poll_interval_seconds" type="number" min="0.5" max="30" step="0.5" required /></label><label class="model-check"><UiInput v-model="config.remote_allow_insecure_http" type="checkbox" />允许开发环境 HTTP</label><p class="model-muted wide">凭据配置在服务器环境变量中。此处仅填写变量名；远程产物仍须本地复验，不能直接认定可用。</p></div></fieldset><div class="model-actions"><UiButton class="primary-button" :disabled="busy || uploading">保存转换配置</UiButton><UiButton class="secondary-button" type="button" :disabled="busy || uploading" @click="check()">检测转换环境</UiButton></div></form></UiCollapse>
      <section class="model-panel"><header><h3>转换任务</h3><UiButton class="secondary-button" :disabled="busy||uploading" @click="poll">刷新任务</UiButton></header><label class="job-calibration">本次移动端转换校准集<UiSelect v-model="calibrationId"><UiOption v-for="dataset in readyDatasets" :key="dataset.datasetId" :value="dataset.datasetId">{{ dataset.name }} / {{ dataset.version }}</UiOption></UiSelect></label><p class="model-muted">转换会冻结所选校准集的版本与哈希。活跃任务每 3 秒、空闲每 30 秒刷新；隐藏时暂停，读取失败逐步退避。重试转换仍须手动操作。以下是服务端最近 100 个任务。</p><p v-if="jobError" class="operation-feedback is-error" role="status">{{ jobError }} · 当前任务状态可能已过期</p><p v-if="!jobs.length && !jobError" class="model-muted">暂无任务。上传 PT 或检测转换环境后，真实任务会显示在这里。</p>
        <article v-for="job in jobs" :key="job.id" class="conversion-job"><header><div><strong>{{ actions[job.action] }} · {{ job.metadata.name || job.metadata.model_id || '转换环境' }}</strong><code>{{ job.id }}</code></div><UiTag class="model-badge" :tone="job.status === 'succeeded' ? 'success' : ['failed','interrupted'].includes(job.status) ? 'danger' : 'info'">{{ labels[job.status] }}</UiTag></header><p class="model-muted">{{ new Date(job.created_at * 1000).toLocaleString() }} · 第 {{ job.attempt }} 次 · {{ duration(job) }}<span v-if="job.queue_position"> · 队列第 {{ job.queue_position }} 位</span></p><p v-if="job.metadata.calibration_dataset" class="model-muted">校准集：{{ job.metadata.calibration_dataset.name }} / {{ job.metadata.calibration_dataset.version }} · {{ job.metadata.calibration_dataset.contentSha256 }}</p><div v-if="['queued','running'].includes(job.status)" class="job-progress"><div><strong>{{ redactMessage(job.stage_label || labels[job.status]) }}</strong><span>{{ exactProgress(job) === undefined ? '处理中' : `${exactProgress(job)}%` }}</span></div><UiProgress :value="exactProgress(job)" :label="job.stage_label || labels[job.status]" /><p v-if="job.progress_message" class="model-muted">{{ redactMessage(job.progress_message) }}</p></div><p v-if="job.result?.server_ready">服务端已验证 · {{ job.result.android_ready ? '移动端就绪' : job.result.android_converted ? '移动端已转换 / 尚未满足就绪门禁' : '移动端需单独处理' }}</p><p v-if="job.error || job.result?.auto_conversion_error || job.result?.message" class="operation-feedback" :class="{'is-error':job.error}">{{ redactMessage(job.error || job.result?.auto_conversion_error || job.result?.message) }}</p><div class="model-actions"><UiButton v-if="['failed','interrupted'].includes(job.status)" class="secondary-button" :disabled="busy || uploading || !!jobError" @click="retry(job)">按当前配置重试</UiButton><UiButton v-if="canConvert(job)" class="secondary-button" :disabled="busy || uploading || !!jobError || !readyDatasets.some(d => d.datasetId === calibrationId)" @click="mobile(job)">生成移动端模型</UiButton><UiButton class="secondary-button" @click="openLog(job)">查看日志</UiButton></div></article>
      </section>
    </template>
    <UiDialog v-model:open="logOpen" title="转换任务日志"><div class="model-detail"><UiStatePanel v-if="logBusy" state="loading" /><template v-else><pre class="job-log">{{ logText }}</pre><UiButton class="secondary-button" @click="downloadLog()">下载日志</UiButton></template></div></UiDialog>
  </div>
</template>
