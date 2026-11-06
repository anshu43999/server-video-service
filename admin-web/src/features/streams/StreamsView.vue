<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Activity, Camera, CircleAlert, Play, Plus, RefreshCw, Save, ShieldCheck, Trash2, Video, X } from '@lucide/vue'
import { isApiError } from '../../api/errors'
import UiConfirmDialog from '../../components/ui/UiConfirmDialog.vue'
import UiStatePanel from '../../components/ui/UiStatePanel.vue'
import { ElDialog } from 'element-plus'
import { streamsApi, streamPlanOptions } from './api'
import { scenesApi, type Scene } from '../scenes/api'
import { useProjectCapabilities } from '../projects/capabilities'
const { streams: canManage } = useProjectCapabilities()
import { AdminPreview, type PreviewStatus } from './preview'
import { modelDisplayName } from '../models/presentation'
import type { StreamItem, StreamModel } from './types'

type LoadPhase = 'loading' | 'ready' | 'error'
const phase = ref<LoadPhase>('loading')
const events = ref<StreamItem[]>([])
const scenes = ref<Scene[]>([])
const sceneError = ref('')
const listError = ref('')
const selectedId = ref('')
const filter = ref<'all' | 'running' | 'stopped' | 'error'>('all')
const query = ref('')
const createOpen = ref(canManage.value && useRoute().query.create === '1')
const createBusy = ref(false)
const createError = ref('')
const saveBusy = ref(false)
const bindingBusy = ref(false)
const toggleBusy = ref(false)
const pendingDelete = ref(false)
const operationMessage = ref('')
const operationTone = ref<'success' | 'error' | 'info'>('info')
const previewNonce = ref(Date.now())
let disposed = false
let listController: AbortController | undefined
let sceneController: AbortController | undefined
let pollTimer: ReturnType<typeof setTimeout> | undefined
let listVersion = 0
const previewFailed = ref(false)
const previewFrame = ref('')
const previewStatus = ref<PreviewStatus>('idle')
const previewMode = ref<'raw' | 'yolo'>('raw')
const settingsForm = ref<HTMLFormElement>()
const preview = new AdminPreview({
  waitForFrameLoad: true,
  onFrame: (url) => { previewFrame.value = url },
  onStatus: (status) => { previewStatus.value = status; previewFailed.value = status === 'error' },
  onMode: (mode) => { previewMode.value = mode },
})
const baseline = ref('')
const busy = computed(() => createBusy.value || saveBusy.value || bindingBusy.value || toggleBusy.value)
const draftDirty = computed(() => JSON.stringify(draft) !== baseline.value)

const createForm = reactive({ streamId: '', displayName: '', sourceType: 'rtsp', sourceUrl: '', scenePlan: '' })
const draft = reactive({ displayName: '', confidence: 0.25, maxFps: 20, overlayEnabled: true, scenePlan: '' })
const selected = computed(() => events.value.find((item) => item.stream_id === selectedId.value) ?? null)
const scenePlanOptions = computed(() => streamPlanOptions(scenes.value))
const filteredStreams = computed(() => {
  const needle = query.value.trim().toLocaleLowerCase('zh-CN')
  return events.value.filter((item) => {
    const runtime = runtimeKey(item)
    return (filter.value === 'all' || runtime === filter.value)
      && (!needle || `${item.display_name ?? ''} ${item.stream_id} ${item.source_type ?? ''}`.toLocaleLowerCase('zh-CN').includes(needle))
  })
})
const previewUrl = computed(() => selected.value && selected.value.enabled !== false && selected.value.runtime_available !== false
  ? streamsApi.previewUrl(selected.value.stream_id, previewNonce.value)
  : '')

function runtimeKey(stream: StreamItem): 'running' | 'stopped' | 'error' {
  if (stream.runtime_state === 'error') return 'error'
  if (stream.enabled === false || stream.runtime_available === false) return 'stopped'
  return 'running'
}

function runtimeLabel(stream: StreamItem) {
  const key = runtimeKey(stream)
  if (key === 'error') return '恢复异常'
  if (key === 'stopped') return stream.enabled === false ? '配置已停用' : '等待运行'
  return stream.frames_received ? (stream.yolo_enabled ? '识别运行中' : '接收视频中') : '等待首帧'
}

function sourceLabel(sourceType?: string) {
  return ({ rtsp: 'RTSP 摄像机', rtsps: 'RTSPS 摄像机', http: 'HTTP 来源', https: 'HTTPS 来源', camera: '本机摄像头', file: '文件来源', mobile: '历史输入源', websocket: '受保护输入源' } as Record<string, string>)[sourceType ?? ''] ?? sourceType ?? '来源类型未记录'
}

function errorMessage(error: unknown, fallback: string) {
  if (isApiError(error)) return error.message
  return error instanceof Error ? error.message : fallback
}

function showOperation(message: string, tone: 'success' | 'error' | 'info') {
  operationMessage.value = message
  operationTone.value = tone
}

async function loadStreams(silent = false) {
  const version = ++listVersion
  listController?.abort()
  const controller = new AbortController()
  listController = controller
  if (!silent) phase.value = 'loading'
  try {
    const items = await streamsApi.list(controller.signal)
    if (disposed || version !== listVersion) return
    events.value = items
    phase.value = 'ready'
    listError.value = ''
    if (!events.value.some((item) => item.stream_id === selectedId.value)) selectedId.value = events.value[0]?.stream_id ?? ''
    else if (!draftDirty.value) syncDraft(selected.value)
  } catch (error) {
    if (disposed || version !== listVersion || controller.signal.aborted) return
    phase.value = 'error'
    listError.value = errorMessage(error, '无法读取视频流配置')
  } finally {
    if (listController === controller) listController = undefined
  }
}

async function loadScenePlans() {
  sceneController?.abort()
  const controller = new AbortController()
  sceneController = controller
  sceneError.value = ''
  try {
    const result = await scenesApi.list(controller.signal)
    if (!disposed && sceneController === controller) scenes.value = result
  } catch (error) {
    if (!disposed && !controller.signal.aborted) { scenes.value = []; sceneError.value = errorMessage(error, '项目场景不可用') }
  }
}

async function refresh() {
  await Promise.all([loadStreams(), loadScenePlans()])
}

function syncDraft(stream: StreamItem | null) {
  draft.displayName = stream?.display_name ?? stream?.stream_id ?? ''
  draft.confidence = stream?.confidence ?? 0.25
  draft.maxFps = stream?.max_fps ?? 20
  draft.overlayEnabled = stream?.overlay_enabled ?? true
  draft.scenePlan = scenePlanOptions.value.find((item) => item.sceneId === stream?.scene_id && item.planId === stream?.plan_id && item.sceneRevision === stream?.scene_revision)?.key ?? ''
  baseline.value = JSON.stringify(draft)
}

async function saveSettings() {
  const stream = selected.value
  if (!canManage.value || !stream || busy.value || !settingsForm.value?.reportValidity()) return
  invalidateList()
  saveBusy.value = true
  try {
    const updated = await streamsApi.update(stream.stream_id, {
      display_name: draft.displayName.trim() || stream.stream_id,
      confidence: draft.confidence,
      max_fps: draft.maxFps,
      overlay_enabled: draft.overlayEnabled,
    })
    replaceStream(updated)
    syncDraft(updated)
    showOperation('视频流设置已保存。', 'success')
  } catch (error) {
    showOperation(errorMessage(error, '设置保存失败'), 'error')
  } finally { saveBusy.value = false }
}

function replaceStream(value: StreamItem) {
  const index = events.value.findIndex((item) => item.stream_id === value.stream_id)
  if (index >= 0) events.value.splice(index, 1, value)
  else events.value.unshift(value)
}

function onYoloChange(enabled: boolean) {
  void setYolo(enabled)
}

function onPlanChange(value: string | number) {
  void selectScenePlan(String(value))
}

async function setEnabled(enabled: boolean) {
  const stream = selected.value
  if (!canManage.value || !stream || busy.value) return
  invalidateList()
  toggleBusy.value = true
  if (!enabled) releasePreview()
  try {
    replaceStream(await streamsApi.setEnabled(stream.stream_id, enabled))
    showOperation(enabled ? '视频流已启用，正在等待恢复。' : '视频流已停用。', 'success')
  } catch (error) { reconnectPreview(); showOperation(errorMessage(error, '启停操作失败'), 'error') }
  finally { toggleBusy.value = false }
}

async function setYolo(enabled: boolean) {
  const stream = selected.value
  if (!canManage.value || !stream || busy.value) return
  invalidateList()
  toggleBusy.value = true
  try {
    const result = await streamsApi.setYolo(stream.stream_id, enabled)
    stream.yolo_enabled = result.yolo_enabled
    showOperation(enabled ? 'YOLO 检测已开启。' : 'YOLO 检测已关闭。', 'success')
  } catch (error) { showOperation(errorMessage(error, 'YOLO 操作失败'), 'error') }
  finally { toggleBusy.value = false }
}

async function selectScenePlan(key: string) {
  const stream = selected.value
  const option = scenePlanOptions.value.find((item) => item.key === key)
  if (!canManage.value || !stream || !option || busy.value) return
  invalidateList()
  bindingBusy.value = true
  try {
    const result = await streamsApi.selectPlan(stream.stream_id, option)
    replaceStream({ ...stream, scene_id: option.sceneId, plan_id: option.planId, scene_revision: option.sceneRevision, model: result.model })
    draft.scenePlan = key
    baseline.value = JSON.stringify(draft)
    showOperation('视频流运行方案已更新。', 'success')
  } catch (error) { showOperation(errorMessage(error, '运行方案更新失败'), 'error') }
  finally { bindingBusy.value = false; if (selected.value) syncDraft(selected.value) }
}

async function createStream() {
  const option = scenePlanOptions.value.find((item) => item.key === createForm.scenePlan)
  if (!canManage.value || !createForm.streamId.trim() || !option || busy.value) return
  invalidateList()
  createBusy.value = true
  createError.value = ''
  showOperation('', 'info')
  try {
    const created = await streamsApi.create({
      stream_id: createForm.streamId.trim(),
      display_name: createForm.displayName.trim() || undefined,
      source_type: createForm.sourceType,
      source_url: createForm.sourceUrl.trim() || undefined,
      sceneId: option.sceneId,
      planId: option.planId,
      sceneRevision: option.sceneRevision,
    })
    replaceStream(created)
    selectedId.value = created.stream_id
    createForm.streamId = ''
    createForm.displayName = ''
    createForm.sourceUrl = ''
    createForm.scenePlan = ''
    createOpen.value = false
    showOperation('视频流配置已创建。', 'success')
  } catch (error) {
    createError.value = errorMessage(error, '视频流创建失败')
    showOperation(createError.value, 'error')
  }
  finally { createBusy.value = false }
}

async function removeStream() {
  const stream = selected.value
  if (!canManage.value || !stream || busy.value) return
  invalidateList()
  toggleBusy.value = true
  try {
    await streamsApi.remove(stream.stream_id)
    events.value = events.value.filter((item) => item.stream_id !== stream.stream_id)
    selectedId.value = events.value[0]?.stream_id ?? ''
    pendingDelete.value = false
    showOperation('视频流配置已删除。', 'success')
  } catch (error) { showOperation(errorMessage(error, '视频流删除失败'), 'error') }
  finally { toggleBusy.value = false }
}

function invalidateList() {
  listVersion += 1
  listController?.abort()
  if (phase.value === 'loading' && events.value.length) phase.value = 'ready'
}

function closeCreate() {
  if (busy.value) return
  createOpen.value = false
  createError.value = ''
  createForm.sourceUrl = ''
}

function reconnectPreview() {
  previewFailed.value = false
  previewNonce.value += 1
}

function releasePreview() {
  preview.stop()
}

function schedulePoll() {
  pollTimer = setTimeout(async () => {
    if (disposed) return
    if (!busy.value && !listController) {
      await loadStreams(true)
    }
    if (!disposed) schedulePoll()
  }, 5000)
}

function formatMetric(value?: number | null, suffix = '') {
  return value === undefined || value === null ? '—' : `${Number(value).toFixed(suffix === ' ms' ? 1 : 0)}${suffix}`
}

watch(selectedId, (id) => {
  const stream = events.value.find((item) => item.stream_id === id) ?? null
  syncDraft(stream)
  pendingDelete.value = false
})

watch(scenePlanOptions, () => {
  if (!draftDirty.value) syncDraft(selected.value)
})

watch([() => selected.value?.stream_id, () => selected.value?.enabled, () => selected.value?.runtime_available, () => selected.value?.yolo_enabled, () => selected.value?.overlay_enabled, () => selected.value?.model_id, () => selected.value?.scene_id, () => selected.value?.plan_id], () => {
  releasePreview()
  reconnectPreview()
}, { immediate: true })

watch(previewUrl, (url) => {
  releasePreview()
  if (url) preview.start(url)
}, { immediate: true })

onMounted(() => { void refresh(); schedulePoll() })
onBeforeUnmount(() => {
  disposed = true
  releasePreview()
  if (pollTimer) clearTimeout(pollTimer)
  listController?.abort()
  sceneController?.abort()
  createForm.sourceUrl = ''
})
</script>

<template>
  <section class="streams-page" aria-label="视频流">
    <header class="streams-header">
      <div>
        <span class="stream-count">{{ events.length }} 路</span>
      </div>
      <div class="stream-page-actions">
        <UiButton class="icon-button" type="button" title="刷新视频流" aria-label="刷新视频流" :disabled="phase === 'loading' || busy" @click="refresh"><RefreshCw :size="18" :class="{ spinning: phase === 'loading' }" /></UiButton>
        <UiButton v-if="canManage" class="primary-button" type="button" :disabled="busy" @click="createError = ''; createOpen = true"><Plus :size="16" />新增视频流</UiButton>
      </div>
    </header>

    <ElDialog v-model="createOpen" class="stream-create-dialog" width="min(760px, calc(100vw - 32px))" append-to-body :show-close="false" :close-on-click-modal="!busy" :close-on-press-escape="!busy" @closed="createForm.sourceUrl = ''; createError = ''">
      <template #header><div class="panel-heading"><div><p class="eyebrow">NEW SOURCE</p><h3>登记视频流配置</h3></div><UiButton class="icon-button" type="button" :disabled="busy" aria-label="关闭新增视频流表单" @click="closeCreate"><X :size="18" /></UiButton></div></template>
      <form class="stream-create-form" @submit.prevent="createStream">
        <label><span>流 ID</span><UiInput v-model="createForm.streamId" required maxlength="128" pattern="[A-Za-z0-9][A-Za-z0-9._-]{0,127}" placeholder="gate-camera-01" /></label>
        <label><span>显示名称</span><UiInput v-model="createForm.displayName" maxlength="255" placeholder="北门固定摄像机" /></label>
        <label><span>来源类型</span><UiSelect v-model="createForm.sourceType"><UiOption value="rtsp">RTSP</UiOption><UiOption value="rtsps">RTSPS</UiOption><UiOption value="http">HTTP</UiOption><UiOption value="https">HTTPS</UiOption><UiOption value="camera">本机摄像头</UiOption><UiOption value="file">文件</UiOption></UiSelect></label>
        <label class="source-url-field"><span>接入地址 <small>仅提交给服务端，不会在列表或详情回显</small></span><UiInput v-model="createForm.sourceUrl" type="password" autocomplete="new-password" placeholder="rtsp://username:password@host/stream" /></label>
        <label><span>PC 视频运行方案</span><UiSelect v-model="createForm.scenePlan" required :disabled="!scenePlanOptions.length"><UiOption value="" disabled>请选择已批准的场景方案</UiOption><UiOption v-for="option in scenePlanOptions" :key="option.key" :value="option.key">{{ option.label }}</UiOption></UiSelect></label>
        <p v-if="sceneError || !scenePlanOptions.length" class="stream-create-error" role="status">{{ sceneError || '没有可用于视频流的已批准 PC 单成员方案。' }}</p>
        <p v-if="createError" class="stream-create-error" role="alert">{{ createError }}</p>
        <div class="stream-create-actions"><UiButton class="secondary-button" type="button" :disabled="busy" @click="closeCreate">取消</UiButton><UiButton class="primary-button" type="submit" :disabled="busy || !scenePlanOptions.length"><Plus :size="16" />{{ createBusy ? '正在创建…' : '创建配置' }}</UiButton></div>
      </form>
    </ElDialog>

    <div v-if="operationMessage" class="stream-operation" :class="`is-${operationTone}`" role="status"><CircleAlert v-if="operationTone === 'error'" :size="16" /><ShieldCheck v-else :size="16" />{{ operationMessage }}</div>
    <div v-if="phase === 'error' && events.length" class="stream-operation is-error" role="alert">刷新失败：{{ listError }}。以下是上次取得的配置，运行指标可能已过期。<UiButton class="secondary-button" type="button" @click="refresh">重试</UiButton></div>

    <section class="stream-workbench" aria-label="视频流配置与诊断">
      <aside class="stream-registry" aria-label="视频流列表">
        <div class="registry-heading"><div><strong>流配置</strong><span>真实服务端配置 · {{ events.length }}</span></div><Activity :size="18" aria-hidden="true" /></div>
        <label class="stream-search"><span class="sr-only">搜索视频流</span><UiInput v-model="query" type="search" placeholder="搜索名称、ID 或来源类型" /></label>
        <div class="stream-filters" role="group" aria-label="运行状态筛选">
          <UiButton v-for="item in ([['all', '全部'], ['running', '运行'], ['stopped', '停用'], ['error', '异常']] as const)" :key="item[0]" type="button" :aria-pressed="filter === item[0]" :class="{ active: filter === item[0] }" @click="filter = item[0]">{{ item[1] }}</UiButton>
        </div>
        <UiStatePanel v-if="phase === 'loading' && !events.length" state="loading" title="读取视频流" message="正在加载已保存的视频流配置。" />
        <UiStatePanel v-else-if="phase === 'error' && !events.length" state="error" title="视频流不可用" :message="listError" @retry="refresh" />
        <UiStatePanel v-else-if="!filteredStreams.length" state="empty" :title="events.length ? '没有匹配的视频流' : '暂无视频流配置'" :message="events.length ? '调整筛选条件后重试。' : '新建真实流配置后会显示运行状态。'" />
        <div v-else class="stream-list">
          <UiButton v-for="stream in filteredStreams" :key="stream.stream_id" class="stream-list-item" :class="{ selected: selectedId === stream.stream_id }" type="button" :disabled="busy" :aria-pressed="selectedId === stream.stream_id" @click="selectedId = stream.stream_id">
            <span class="stream-state-dot" :class="`is-${runtimeKey(stream)}`"></span>
            <span class="stream-list-copy"><strong>{{ stream.display_name || stream.stream_id }}</strong><small>{{ sourceLabel(stream.source_type) }} · {{ stream.stream_id }}</small></span>
            <span class="stream-list-status">{{ runtimeLabel(stream) }}</span>
          </UiButton>
        </div>
        <p v-if="sceneError" class="model-unavailable">项目场景不可用：{{ sceneError }}</p>
      </aside>

      <UiStatePanel v-if="!selected && phase === 'ready'" class="stream-no-selection" state="empty" title="选择一个视频流" message="选择左侧配置查看现场预览、服务状态和 YOLO 分析指标。" />
      <main v-else-if="selected" class="stream-detail" aria-label="选中视频流详情">
        <header class="stream-detail-header">
          <div><p class="eyebrow">{{ selected.stream_id }}</p><h3>{{ selected.display_name || selected.stream_id }}</h3><span class="detail-source">{{ sourceLabel(selected.source_type) }} · 接入地址已隐藏</span></div>
          <div class="detail-actions">
            <UiButton v-if="canManage" class="secondary-button" type="button" :disabled="busy" @click="setEnabled(selected.enabled === false)"><Play v-if="selected.enabled === false" :size="16" /><X v-else :size="16" />{{ selected.enabled === false ? '启用' : '停用' }}</UiButton>
            <UiButton v-if="canManage" class="icon-button danger-icon" type="button" :disabled="busy" title="删除流配置" aria-label="删除流配置" @click="pendingDelete = true"><Trash2 :size="17" /></UiButton>
          </div>
        </header>

        <div class="stream-live-grid">
          <section class="stream-preview-panel" aria-label="实时视频预览">
            <div class="preview-heading"><span><Video :size="16" />现场预览</span><UiButton v-if="previewUrl" class="icon-button" type="button" aria-label="重连现场预览" @click="reconnectPreview"><RefreshCw :size="14" /></UiButton><span class="preview-state" :class="{ active: previewStatus === 'open' && !!previewFrame }"><i></i>{{ previewFailed ? '预览不可用' : previewStatus === 'connecting' ? '正在连接预览' : previewFrame ? '实时预览 · 同源' : selected.enabled === false ? '流已停用' : '等待视频帧' }}</span></div>
            <div class="stream-preview">
              <img v-if="previewFrame && !previewFailed" :src="previewFrame" alt="选中视频流的实时画面" @load="preview.frameLoaded()" @error="releasePreview(); previewFailed = true" />
              <div v-else class="preview-placeholder"><Camera :size="28" /><strong>{{ previewFailed ? '现场预览不可用' : selected.runtime_state === 'error' ? '流恢复异常' : '暂无实时画面' }}</strong><span>{{ previewFailed ? '检查源状态后使用上方按钮重新连接。' : '配置启用且收到视频帧后，预览会自动连接。' }}</span></div>
              <span v-if="previewFrame" class="preview-overlay-label">{{ previewMode === 'yolo' ? 'YOLO OVERLAY' : 'RAW STREAM' }}</span>
            </div>
          </section>

          <section class="stream-live-metrics" aria-label="实时运行指标">
            <div class="preview-heading"><span><Activity :size="16" />运行指标</span><span class="live-state" :class="`is-${runtimeKey(selected)}`"><i></i>{{ runtimeLabel(selected) }}</span></div>
            <dl>
              <div><dt>接收帧</dt><dd>{{ formatMetric(selected.frames_received) }}</dd></div>
              <div><dt>处理帧</dt><dd>{{ formatMetric(selected.frames_processed) }}</dd></div>
              <div><dt>接收速率</dt><dd>{{ formatMetric(selected.received_fps, ' fps') }}</dd></div>
              <div><dt>处理速率</dt><dd>{{ formatMetric(selected.processed_fps, ' fps') }}</dd></div>
              <div><dt>最近延迟</dt><dd>{{ formatMetric(selected.last_latency_ms, ' ms') }}</dd></div>
              <div><dt>预览通道</dt><dd>后台专用 · 最高 5 fps</dd></div>
              <div><dt>最近检测数</dt><dd>{{ formatMetric(selected.detections_last) }}</dd></div>
              <div><dt>模型状态</dt><dd>{{ selected.model_error || selected.model?.load_error ? '加载异常' : (selected.model?.modelId || selected.model_id ? modelDisplayName(selected.model) : '未绑定') }}</dd></div>
            </dl>
          </section>
        </div>

        <section v-if="canManage" class="stream-config-section" aria-labelledby="stream-config-title">
          <div class="section-heading"><div><p class="eyebrow">CONFIGURATION</p><h4 id="stream-config-title">识别与流配置</h4></div><UiButton class="primary-button" type="button" :disabled="busy" @click="saveSettings"><Save :size="15" />{{ saveBusy ? '保存中…' : '保存设置' }}</UiButton></div>
          <form ref="settingsForm" class="stream-settings" @submit.prevent="saveSettings">
            <label><span>显示名称</span><UiInput v-model="draft.displayName" maxlength="255" /></label>
            <label><span>置信度阈值 <b>{{ Number(draft.confidence).toFixed(2) }}</b></span><UiInput v-model.number="draft.confidence" required type="number" min="0.01" max="0.99" step="0.01" /></label>
            <label><span>最大处理帧率 <b>{{ Number(draft.maxFps).toFixed(0) }} fps</b></span><UiInput v-model.number="draft.maxFps" required type="number" min="1" max="60" step="0.1" /></label>
            <label><span>PC 视频运行方案</span><UiSelect v-model="draft.scenePlan" :disabled="busy || !scenePlanOptions.length" @change="onPlanChange"><UiOption v-if="!scenePlanOptions.some(option => option.key === draft.scenePlan)" :value="draft.scenePlan" disabled>{{ selected.scene_id ? `${selected.scene_id} · ${selected.plan_id}（修订已过期）` : '未选择运行方案' }}</UiOption><UiOption v-for="option in scenePlanOptions" :key="option.key" :value="option.key">{{ option.label }}</UiOption></UiSelect></label>
            <p v-if="selected?.scene_id && !scenePlanOptions.some(option => option.sceneId === selected?.scene_id && option.planId === selected?.plan_id && option.sceneRevision === selected?.scene_revision)" class="runtime-warning" role="status">当前保存的方案修订 {{ selected?.scene_revision }} 已不可用，启用前请重新选择已批准方案。</p>
            <label class="switch-setting"><span><strong>YOLO 检测</strong><small>识别与告警分析开关</small></span><UiInput type="checkbox" :checked="!!selected.yolo_enabled" :disabled="busy" @change="onYoloChange" /></label>
            <label class="switch-setting"><span><strong>画面叠加</strong><small>保存后更新画面标注</small></span><UiInput v-model="draft.overlayEnabled" type="checkbox" /></label>
          </form>
          <p v-if="!scenePlanOptions.length" class="setting-note">{{ sceneError || '当前项目没有可用于视频流的已批准 PC 单成员方案。' }}</p>
        </section>

        <div class="stream-diagnostics-grid">
          <section class="stream-diagnostics" aria-labelledby="stream-diagnostics-title">
            <div class="section-heading"><div><p class="eyebrow">ANALYSIS STATUS</p><h4 id="stream-diagnostics-title">分析与运行诊断</h4></div><span class="diagnostic-publish">{{ runtimeLabel(selected) }}</span></div>
            <p class="setting-note">实时预览仅供当前项目后台查看；关闭预览不会停止 YOLO 分析和告警规则。</p>
            <p v-if="selected.alert_error" class="runtime-warning" role="status">告警保存或通知异常，请检查服务日志。</p>
            <p v-if="selected.runtime_state === 'error' || selected.model_error || selected.model?.load_error" class="runtime-warning" role="status"><CircleAlert :size="16" />{{ selected.model_error || selected.model?.load_error ? '服务端模型未能正常加载。' : '视频流恢复失败；请检查源服务与服务器日志。' }}</p>
          </section>

          <section class="stream-detections" aria-labelledby="stream-detections-title">
            <div class="section-heading"><div><p class="eyebrow">ALERT WORKFLOW</p><h4 id="stream-detections-title">识别与告警</h4></div></div>
            <p class="setting-note">{{ selected.yolo_enabled ? '识别结果可叠加在预览画面中；满足告警规则后，在告警中心新增记录并提示。' : 'YOLO 检测已关闭，仍可查看原始画面。' }}</p>
            <p class="setting-note">逐帧检测不等于正式告警。告警记录、证据与处置请在告警中心查看。</p>
          </section>
        </div>
      </main>
    </section>

    <UiConfirmDialog v-model:open="pendingDelete" title="删除视频流配置" :description="selected ? `将删除“${selected.display_name || selected.stream_id}”的配置并释放运行资源。此操作不可撤销。` : ''" confirm-label="删除配置" tone="danger" :busy="toggleBusy" @confirm="removeStream" />
  </section>
</template>

<style scoped>
.streams-page { display: grid; gap: 18px; min-width: 0; }
.streams-header, .streams-title-line, .stream-page-actions, .detail-actions, .panel-heading, .section-heading, .registry-heading, .preview-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.stream-count, .diagnostic-publish { color: var(--color-ink-muted); font-size: var(--text-xs); font-family: var(--font-mono); }
.stream-page-actions { flex: 0 0 auto; }
.stream-workbench { border: 1px solid var(--color-border); background: var(--color-surface); }
.panel-heading h3 { margin: 2px 0 0; font-size: var(--text-lg); }
.stream-create-form { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); align-items: end; gap: 14px; }
.stream-create-actions { grid-column: 1 / -1; display: flex; justify-content: flex-end; gap: 9px; padding-top: 4px; }
.stream-create-error { grid-column: 1 / -1; margin: 0; color: var(--color-danger); font-size: var(--text-sm); }
.stream-create-form label, .stream-settings > label { display: grid; gap: 6px; color: var(--color-ink-muted); font-size: var(--text-xs); }
.stream-create-form input, .stream-create-form select, .stream-search input, .stream-settings input:not([type=checkbox]), .stream-settings select { width: 100%; min-width: 0; min-height: 38px; border: 1px solid var(--color-border-strong); border-radius: var(--radius-sm); padding: 7px 9px; color: var(--color-ink); background: white; font: inherit; }
.source-url-field small { display: inline; color: var(--color-ink-faint); }
.stream-workbench { display: grid; grid-template-columns: minmax(250px, 310px) minmax(0, 1fr); min-height: 650px; }
.stream-registry { min-width: 0; padding: 15px 12px; border-right: 1px solid var(--color-border); }
.registry-heading { padding: 0 3px 12px; color: var(--color-primary); }
.registry-heading > div { display: grid; gap: 3px; color: var(--color-ink); }
.registry-heading span { color: var(--color-ink-muted); font-size: var(--text-xs); }
.stream-search input { min-height: 36px; font-size: var(--text-sm); }
.stream-filters { display: grid; grid-template-columns: repeat(4, 1fr); gap: 3px; margin: 9px 0; padding: 3px; background: var(--color-surface-subtle); }
.stream-filters button { min-height: 30px; border: 0; color: var(--color-ink-muted); background: transparent; font: inherit; font-size: var(--text-xs); cursor: pointer; }
.stream-filters button.active { color: var(--color-primary); background: white; box-shadow: 0 1px 3px rgb(18 40 26 / 12%); }
.stream-list { display: grid; gap: 4px; }
.stream-list-item { display: block; width: 100%; height: auto; min-height: 65px; margin: 0; border: 1px solid transparent; padding: 9px 7px; text-align: left; white-space: normal; color: inherit; background: transparent; cursor: pointer; }
.stream-list-item :deep(> span) { display: grid; grid-template-columns: 9px minmax(0, 1fr); grid-template-rows: auto auto; gap: 3px 9px; width: 100%; min-width: 0; }
.stream-list-item.selected { border-color: var(--color-border); background: var(--color-primary-soft); }
.stream-state-dot { grid-row: 1 / span 2; align-self: start; width: 8px; aspect-ratio: 1; margin-top: 5px; border-radius: 50%; background: var(--color-ink-faint); }
.stream-state-dot.is-running { background: var(--color-primary); box-shadow: 0 0 0 3px var(--color-primary-soft); }
.stream-state-dot.is-error { background: var(--color-danger); }
.stream-list-copy { display: grid; min-width: 0; gap: 2px; }
.stream-list-copy strong, .stream-list-copy small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.stream-list-copy strong { font-size: var(--text-sm); }
.stream-list-copy small, .stream-list-status { color: var(--color-ink-muted); font-size: 11px; }
.stream-list-status { grid-column: 2; }
.model-unavailable { color: var(--color-danger); font-size: var(--text-xs); }
.stream-no-selection { align-self: center; margin: 24px; }
.stream-detail { display: grid; align-content: start; gap: 14px; min-width: 0; padding: 17px; }
.stream-detail-header { display: flex; justify-content: space-between; align-items: start; gap: 12px; }
.stream-detail-header h3 { margin: 2px 0 4px; font-size: var(--text-xl); }
.detail-source { color: var(--color-ink-muted); font-size: var(--text-xs); }
.danger-icon { color: var(--color-danger); }
.stream-live-grid { display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(240px, .85fr); border: 1px solid var(--color-border); }
.stream-preview-panel, .stream-live-metrics { min-width: 0; }
.stream-preview-panel { border-right: 1px solid var(--color-border); }
.preview-heading { min-height: 38px; padding: 0 10px; border-bottom: 1px solid var(--color-border); color: var(--color-ink-muted); font-size: var(--text-xs); }
.preview-heading > span:first-child { display: inline-flex; align-items: center; gap: 6px; color: var(--color-ink); }
.preview-state, .live-state, .detection-connection { display: inline-flex; align-items: center; gap: 6px; color: var(--color-ink-muted); font-size: 10px; }
.preview-state i, .live-state i, .detection-connection i { width: 6px; aspect-ratio: 1; border-radius: 50%; background: var(--color-ink-faint); }
.preview-state.active i, .live-state.is-running i, .detection-connection.is-open i { background: var(--color-primary); }
.stream-preview { position: relative; display: grid; place-items: center; overflow: hidden; aspect-ratio: 16 / 9; background: #0b1210; }
.stream-preview > img { display: block; width: 100%; height: 100%; object-fit: contain; }
.preview-placeholder { display: grid; justify-items: center; gap: 6px; padding: 14px; text-align: center; color: #c3d2ca; }
.preview-placeholder strong { color: white; font-size: var(--text-sm); }
.preview-placeholder span { font-size: var(--text-xs); }
.preview-overlay-label { position: absolute; left: 9px; bottom: 8px; padding: 2px 5px; color: white; background: rgb(14 27 20 / 78%); font: 10px var(--font-mono); }
.stream-live-metrics dl { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); margin: 0; padding: 6px 10px; }
.stream-live-metrics dl > div { display: grid; gap: 2px; padding: 6px 4px; border-bottom: 1px solid var(--color-border); }
.stream-live-metrics dt { color: var(--color-ink-muted); font-size: 10px; }
.stream-live-metrics dd { overflow-wrap: anywhere; margin: 0; font-size: var(--text-sm); font-weight: 650; }
.stream-config-section, .stream-diagnostics, .stream-detections { min-width: 0; border: 1px solid var(--color-border); padding: 12px; }
.section-heading { align-items: center; margin-bottom: 10px; }
.section-heading h4 { margin: 0; font-size: var(--text-md); }
.section-heading .eyebrow { margin: 0 0 2px; font-size: 9px; }
.section-heading .primary-button { min-height: 32px; padding: 0 9px; font-size: var(--text-xs); }
.stream-settings { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; align-items: end; }
.stream-settings label > span { display: flex; justify-content: space-between; gap: 7px; }
.stream-settings label b { color: var(--color-primary); font-weight: 600; }
.switch-setting { display: flex !important; align-items: center; justify-content: space-between; min-height: 38px; border: 1px solid var(--color-border); padding: 4px 8px; }
.switch-setting > span { display: grid; color: var(--color-ink); }
.stream-settings label.switch-setting > span { display: grid; gap: 2px; }
.switch-setting strong { font-size: var(--text-xs); }
.switch-setting small { color: var(--color-ink-muted); font-size: 9px; }
.switch-setting input { width: 17px; height: 17px; accent-color: var(--color-primary); }
.setting-note { margin: 8px 0 0; color: var(--color-ink-muted); font-size: var(--text-xs); }
.stream-diagnostics-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(250px, .8fr); gap: 12px; }
.runtime-warning { display: flex; align-items: center; gap: 6px; margin: 9px 0 0; color: var(--color-danger); font-size: var(--text-xs); }
.stream-operation { display: flex; align-items: center; gap: 7px; min-height: 34px; padding: 7px 10px; border-left: 3px solid var(--color-primary); color: var(--color-primary); background: var(--color-primary-soft); font-size: var(--text-xs); }
.stream-operation.is-error { border-color: var(--color-danger); color: var(--color-danger); background: var(--color-danger-soft); }
.stream-operation.is-info { border-color: var(--color-info); color: var(--color-info); background: var(--color-info-soft); }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; }
@media (max-width: 1100px) {
  .stream-workbench { grid-template-columns: minmax(220px, 270px) minmax(0, 1fr); }
  .stream-create-form { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .stream-settings { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .stream-live-grid { grid-template-columns: minmax(0, 1fr); }
  .stream-preview-panel { border-right: 0; border-bottom: 1px solid var(--color-border); }
}
@media (min-width: 1101px) and (max-width: 1450px) {
  .stream-create-form { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 760px) {
  .streams-header { align-items: start; }
  .stream-workbench { grid-template-columns: minmax(0, 1fr); }
  .stream-registry { border-right: 0; border-bottom: 1px solid var(--color-border); }
  .stream-list { max-height: 230px; overflow: auto; }
  .stream-detail { padding: 12px; }
  .stream-diagnostics-grid { grid-template-columns: minmax(0, 1fr); }
  .stream-create-form { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .source-url-field { grid-column: 1 / -1; }
}
@media (max-width: 480px) {
  .streams-page { gap: 12px; }
  .streams-header { flex-wrap: wrap; }
  .stream-page-actions { margin-left: auto; }
  .stream-page-actions .primary-button { min-height: 36px; padding: 0 9px; font-size: var(--text-xs); }
  .stream-create-form { grid-template-columns: minmax(0, 1fr); }
  .stream-create-actions, .stream-create-error { grid-column: 1; }
  .source-url-field { grid-column: auto; }
  .stream-detail-header { align-items: center; }
  .stream-detail-header h3 { font-size: var(--text-lg); overflow-wrap: anywhere; }
  .detail-actions { gap: 5px; }
  .detail-actions .secondary-button { min-height: 34px; padding: 0 8px; font-size: 11px; }
  .stream-settings { grid-template-columns: minmax(0, 1fr); }
  .stream-live-metrics dl { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
