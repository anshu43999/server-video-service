<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import UiStatePanel from '../../components/ui/UiStatePanel.vue'
import UiDialog from '../../components/ui/UiDialog.vue'
import UiConfirmDialog from '../../components/ui/UiConfirmDialog.vue'
import { conversionApi, errorText, formatBytes } from './api'
import type { CalibrationDataset } from './types'
const emit = defineEmits<{ changed: [] }>()
const datasets = ref<CalibrationDataset[]>([]), phase = ref<'loading'|'ready'|'error'>('loading'), error = ref(''), message = ref(''), failed = ref(false)
const file = ref<File | null>(null), input = ref<{ clear: () => void }>(), busy = ref(false), progress = ref<number | null>(null), maxBytes = ref<number | null>(null)
const form = reactive({name:'',version:'1',scenario:'general-detection'})
const target = ref<CalibrationDataset | null>(null), detail = ref<CalibrationDataset | null>(null), detailOpen = ref(false), detailError = ref(''), detailBusy = ref(false)
let controller: AbortController | undefined, uploadController: AbortController | undefined, detailController: AbortController | undefined, disposed = false
async function refresh() {
  controller?.abort(); controller = new AbortController(); const signal = controller.signal
  try { const result = await conversionApi.datasets(signal); if (!disposed && !signal.aborted) { datasets.value = result.datasets; maxBytes.value = result.max_upload_bytes; phase.value = 'ready'; error.value = '' } }
  catch (e) { if (!disposed && !signal.aborted) { phase.value = 'error'; error.value = errorText(e) } }
}
async function upload() {
  if (busy.value || !file.value || maxBytes.value === null) return
  if (!file.value.name.toLowerCase().endsWith('.zip') || !file.value.size || file.value.size > maxBytes.value) { message.value = '请选择有效 ZIP 文件，大小必须在服务端上传限制内。'; failed.value = true; return }
  busy.value = true; progress.value = null; uploadController = new AbortController()
  try {
    await conversionApi.uploadDataset(file.value, {name:form.name.trim(),version:form.version.trim(),scenario:form.scenario.trim()}, uploadController.signal, value => { progress.value = value })
    if (!disposed) { file.value = null; input.value?.clear(); form.name = ''; progress.value = null; message.value = '校准集已上传并校验。'; failed.value = false; await refresh(); emit('changed') }
  } catch (e) { if (!disposed) { message.value = errorText(e); failed.value = true } }
  finally { busy.value = false; progress.value = null }
}
async function remove() {
  if (!target.value || busy.value) return
  busy.value = true
  try { await conversionApi.removeDataset(target.value.datasetId); if (!disposed) { target.value = null; message.value = '校准集已删除。'; failed.value = false; await refresh(); emit('changed') } }
  catch (e) { if (!disposed) { message.value = errorText(e); failed.value = true; target.value = null } }
  finally { busy.value = false }
}
async function showDetail(dataset: CalibrationDataset) {
  detailController?.abort(); detailController = new AbortController(); const signal = detailController.signal
  detailOpen.value = true; detailBusy.value = true; detail.value = null; detailError.value = ''
  try { const value = await conversionApi.dataset(dataset.datasetId, signal); if (!disposed && !signal.aborted) detail.value = value }
  catch (e) { if (!disposed && !signal.aborted) detailError.value = errorText(e) }
  finally { if (!signal.aborted) detailBusy.value = false }
}
onMounted(refresh)
onBeforeUnmount(() => { disposed = true; controller?.abort(); uploadController?.abort(); detailController?.abort() })
</script>
<template>
  <div class="calibration-pane">
    <section class="model-panel"><header><h3>校准集版本</h3><UiButton class="secondary-button" @click="refresh">刷新校准集</UiButton></header><p class="model-muted">INT8 转换使用固定版本和内容哈希。内置 COCO8 仅用于功能验证；业务校准集应匹配现场数据。</p><UiStatePanel v-if="phase !== 'ready'" :state="phase" :message="error || '正在读取校准集…'" @retry="refresh" /><div v-else class="dataset-list"><article v-for="dataset in datasets" :key="dataset.datasetId" class="dataset-row"><div><h4>{{ dataset.name }}</h4><code>{{ dataset.datasetId }} / {{ dataset.version }}</code><p>{{ dataset.scenario }} · {{ dataset.imageCount }} 张 · {{ formatBytes(dataset.sizeBytes) }} · {{ dataset.status }}</p></div><div class="model-actions"><UiButton class="secondary-button" @click="showDetail(dataset)">详情</UiButton><UiButton class="secondary-button danger-text" :disabled="busy || dataset.builtin || dataset.deletable === false" @click="target=dataset">删除校准集</UiButton></div></article></div></section>
    <section class="model-panel"><header><h3>上传校准图片 ZIP</h3><span>{{ maxBytes === null ? '等待服务端限制' : `上限 ${formatBytes(maxBytes)}` }}</span></header><form class="model-form" @submit.prevent="upload"><fieldset :disabled="busy || phase !== 'ready'"><div class="model-fields"><label>校准集名称<UiInput v-model="form.name" required maxlength="100" /></label><label>校准集版本<UiInput v-model="form.version" required maxlength="50" /></label><label>校准集场景<UiInput v-model="form.scenario" required maxlength="100" /></label><label>校准图片 ZIP<UiInput ref="input" type="file" accept=".zip" required @change="value => file = value ?? null" /></label></div><p v-if="file" class="selected-file">已选择 {{ file.name }} · {{ formatBytes(file.size) }}</p></fieldset><div v-if="busy" class="upload-progress"><UiProgress :value="progress" label="校准集上传进度" /><span>{{ progress === null ? '正在上传' : `${Math.round(progress)}%` }}{{ progress === 100 ? ' · 等待校验' : '' }}</span><UiButton type="button" class="secondary-button" @click="uploadController?.abort()">中止上传</UiButton></div><p v-if="message" class="operation-feedback" :class="{'is-error':failed,'is-success':!failed}" role="status">{{ message }}</p><UiButton class="primary-button" :disabled="busy || phase !== 'ready' || !file">上传并校验校准集</UiButton></form></section>
    <UiDialog v-model:open="detailOpen" title="校准集详情"><div class="model-detail"><UiStatePanel v-if="detailBusy" state="loading" /><p v-else-if="detailError" class="operation-feedback is-error">{{ detailError }}</p><template v-else-if="detail"><h3>{{ detail.name }}</h3><dl class="dataset-facts"><div v-for="(value,key) in detail" :key="key"><dt>{{ key }}</dt><dd>{{ value }}</dd></div></dl></template></div></UiDialog>
    <UiConfirmDialog :open="!!target" title="删除校准集版本" :description="`将删除 ${target?.name} / ${target?.version}。被模型或转换任务引用的校准集不能删除。`" confirm-label="确认删除" tone="danger" :busy="busy" @update:open="open => { if (!open) target=null }" @confirm="remove" />
  </div>
</template>
