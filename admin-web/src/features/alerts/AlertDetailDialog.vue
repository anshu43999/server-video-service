<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useVisibleElement } from '../../api/useVisibleElement'
import { projectScope } from '../../api/projectScope'
import { evidenceRequests } from './evidenceRequests'
import { Bot, CheckCircle2, FileWarning, ImageOff, LoaderCircle, ShieldAlert, X } from '@lucide/vue'
import { isApiError } from '../../api/errors'
import { alertsApi } from './api'
import EvidenceImage from './EvidenceImage.vue'
import { useProjectCapabilities } from '../projects/capabilities'
const { dispose: canDispose } = useProjectCapabilities()
import {
  alertSubject, alertTitle, dispositionPresentation, eventFactSeverity, eventPriority,
  eventTimestampUs, formatTimestampUs, originLabel, alertSceneLabel, alertModelLabel,
} from './presenters'
import type { AdviceGeneration, AlertEvent, DetailPhase, DispositionAction } from './types'

const props = withDefaults(defineProps<{
  open: boolean
  event: AlertEvent | null
  detailPhase: DetailPhase
  detailError?: string
  busy?: boolean
  operationMessage?: string
  operationTone?: 'success' | 'error' | 'info'
}>(), { detailError: '', busy: false, operationMessage: '', operationTone: 'info' })
const emit = defineEmits<{
  close: []
  retry: [eventId: string]
  dispose: [action: DispositionAction, note: string]
}>()

const dialog = ref<HTMLElement>()
const closeButton = ref<HTMLButtonElement>()
const note = ref('')
const evidencePhase = ref<'idle' | 'loading' | 'ready' | 'empty' | 'error'>('idle')
const evidenceUrl = ref('')
const evidenceElement = ref<HTMLElement>(), evidenceVisible = useVisibleElement(evidenceElement)
const requestingOriginal = ref(false)
const originalMessage = ref('')
let originalOperation: { eventId: string; revision: number; id: string } | undefined
let returnFocus: HTMLElement | null = null
let evidenceController: AbortController | undefined
let showingOriginalVersion: number | undefined
let evidenceDisposed = false
let viewGeneration = 0
const advicePhase = ref<'idle' | 'reading' | 'read-error' | 'loading' | 'ready' | 'error'>('idle')
const advice = ref<AdviceGeneration>()
const adviceError = ref('')
const adviceOperation = ref('')
const adviceHistoryOpen = ref(false)
const adviceHistory = ref<AdviceGeneration[]>([])
let adviceController: AbortController | undefined
let latestAdviceController: AbortController | undefined
const historyPhase = ref<'loading' | 'ready' | 'error'>('ready')
const historyError = ref('')

const title = computed(() => props.event ? alertTitle(props.event) : '告警详情')
const priority = computed(() => props.event ? eventPriority(props.event) : eventPriority({ eventId: '' }))
const factSeverity = computed(() => props.event ? eventFactSeverity(props.event) : eventFactSeverity({ eventId: '' }))
const disposition = computed(() => dispositionPresentation(props.event?.disposition))
const isClosed = computed(() => disposition.value.value === 'CLOSED')

function releaseEvidence() {
  evidenceController?.abort()
  evidenceController = undefined
  if (evidenceUrl.value) URL.revokeObjectURL(evidenceUrl.value)
  evidenceUrl.value = ''
}

async function loadEvidence(eventId: string, originalVersion?: number) {
  releaseEvidence()
  showingOriginalVersion = originalVersion
  if (evidenceDisposed || !evidenceVisible.value || !props.open) { evidencePhase.value = 'idle'; return }
  const controller = new AbortController()
  evidenceController = controller
  evidencePhase.value = 'loading'
  try {
    const blob = await evidenceRequests.run(signal => originalVersion
      ? alertsApi.originalEvidence(eventId, originalVersion, signal)
      : alertsApi.evidence(eventId, signal), controller.signal)
    if (controller.signal.aborted) return
    if (!blob.size) { evidencePhase.value = 'empty'; return }
    evidenceUrl.value = URL.createObjectURL(blob)
    evidencePhase.value = 'ready'
  } catch (error) {
    if (controller.signal.aborted || (isApiError(error) && error.kind === 'cancelled')) return
    evidencePhase.value = isApiError(error) && error.status === 404 ? 'empty' : 'error'
  }
}

const mobileCapture = computed(() => ['MOBILE_CAMERA', 'MOBILE_IMAGE'].includes(props.event?.origin ?? ''))
const serverOriginalVersion = computed(() => {
  if (props.event?.origin !== 'SERVER_STREAM') return undefined
  const originals = props.event.evidence?.original
  if (!originals || typeof originals !== 'object' || Array.isArray(originals)) return undefined
  const versions = Object.keys(originals).map(Number).filter(Number.isInteger).filter(value => value > 0)
  return versions.length ? Math.max(...versions) : undefined
})
const originalStatus = computed(() => {
  const request = props.event?.originalRequest
  if (!request) return '默认展示缩略图；需要细节时可请求原采集设备补传原图。'
  if (request.status === 'PENDING') return '原图待补传：等待原采集设备联网并验证项目权限，无需现场用户再次确认。'
  if (request.status === 'UPLOADED') return '原图已上传，可通过受鉴权接口查看。'
  const reasons: Record<string, string> = {
    producer_unregistered: '旧告警未登记原采集归属，无法自动派发补传请求',
    no_local_capture: '原采集设备没有保存图片', local_file_missing: '本地原图已丢失',
    local_media_purged: '用户已明确清理本地原图', invalid_local_evidence: '本地图片无法上传',
  }
  return `原图不可用：${reasons[request.unavailableReason ?? ''] ?? '原采集设备无法提供图片'}。告警处置仍有效。`
})

async function requestOriginal() {
  const event = props.event
  if (!event || requestingOriginal.value) return
  const revision = event.dispositionRevision ?? 0
  if (!originalOperation || originalOperation.eventId !== event.eventId || originalOperation.revision !== revision) {
    originalOperation = { eventId: event.eventId, revision, id: crypto.randomUUID() }
  }
  const operation = originalOperation
  const generation = viewGeneration
  requestingOriginal.value = true
  originalMessage.value = ''
  try {
    await alertsApi.requestOriginal(event.eventId, revision, operation.id)
    if (generation !== viewGeneration || !props.open || props.event?.eventId !== event.eventId) return
    originalOperation = undefined
    originalMessage.value = '原图请求已保存；手机离线时会等待恢复，不代表图片已经上传。'
    emit('retry', event.eventId)
  } catch (error) {
    if (generation !== viewGeneration || !props.open || props.event?.eventId !== event.eventId) return
    originalMessage.value = isApiError(error) && error.status === 409
      ? '事件已更新，请刷新详情后重新请求。'
      : error instanceof Error ? error.message : '原图请求失败，请重试'
    if (isApiError(error) && error.status === 409) { originalOperation = undefined; emit('retry', event.eventId) }
  } finally {
    if (generation === viewGeneration && props.event?.eventId === event.eventId) requestingOriginal.value = false
  }
}

function resetAdvice() {
  latestAdviceController?.abort(); latestAdviceController = undefined
  adviceController?.abort(); adviceController = undefined
  advicePhase.value = 'idle'; advice.value = undefined; adviceError.value = ''; adviceOperation.value = ''
  adviceHistory.value = []; adviceHistoryOpen.value = false
}
async function loadLatestAdvice() {
  const event = props.event
  if (!event || !props.open) return
  latestAdviceController?.abort()
  const controller = new AbortController()
  latestAdviceController = controller
  const generation = viewGeneration
  advicePhase.value = 'reading'; adviceError.value = ''
  try {
    const result = await alertsApi.latestAdvice(event.eventId, controller.signal)
    if (controller.signal.aborted || generation !== viewGeneration || !props.open) return
    advice.value = result; advicePhase.value = 'ready'
  } catch (error) {
    if (controller.signal.aborted || generation !== viewGeneration || !props.open) return
    if (isApiError(error) && error.status === 404 && error.code === 'ADVICE_GENERATION_NOT_FOUND') {
      advicePhase.value = 'idle'
    } else {
      adviceError.value = error instanceof Error ? error.message : '已保存建议读取失败'
      advicePhase.value = 'read-error'
    }
  }
}
async function generateAdvice(retry = false) {
  const event = props.event
  if (!event || ['loading', 'reading'].includes(advicePhase.value)) return
  const generation = viewGeneration
  const retryOf = retry ? advice.value?.generationId : undefined
  adviceHistoryOpen.value = false
  adviceController?.abort()
  adviceOperation.value = crypto.randomUUID()
  advicePhase.value = 'loading'; adviceError.value = ''
  try {
    const result = await alertsApi.generateAdvice(event.eventId, adviceOperation.value, retryOf)
    if (generation !== viewGeneration || props.event?.eventId !== event.eventId) return
    advice.value = result; advicePhase.value = 'ready'
  } catch (error) {
    if (generation !== viewGeneration || props.event?.eventId !== event.eventId) return
    adviceError.value = error instanceof Error ? error.message : 'AI 处置建议生成失败'
    advicePhase.value = 'error'
  }
}
async function loadAdviceHistory() {
  const event = props.event
  if (!event || ['loading', 'reading'].includes(advicePhase.value)) return
  adviceHistoryOpen.value = true; adviceHistory.value = []
  historyPhase.value = 'loading'; historyError.value = ''
  adviceController?.abort()
  const controller = new AbortController()
  adviceController = controller
  const generation = viewGeneration
  try {
    const history = await alertsApi.adviceHistory(event.eventId, controller.signal)
    if (!controller.signal.aborted && generation === viewGeneration && props.open) {
      adviceHistory.value = history.generations; historyPhase.value = 'ready'
    }
  } catch (error) {
    if (!controller.signal.aborted && generation === viewGeneration && props.open) {
      historyError.value = error instanceof Error ? error.message : '建议历史读取失败'
      historyPhase.value = 'error'
    }
  }
}

// Watch the scalar identity, not a newly allocated array on every list snapshot.
watch([() => props.open, () => props.event?.projectId, () => props.event?.eventId], async ([open, , eventId], previous) => {
  const generation = ++viewGeneration
  note.value = ''
  originalMessage.value = ''
  requestingOriginal.value = false
  originalOperation = undefined
  resetAdvice()
  showingOriginalVersion = undefined
  releaseEvidence()
  evidencePhase.value = 'idle'
  if (!open || !eventId) return
  if (!previous?.[0]) returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
  await nextTick()
  if (generation !== viewGeneration) return
  closeButton.value?.focus({ preventScroll: true })
  if (evidenceVisible.value && !evidenceController) void loadEvidence(eventId)
  void loadLatestAdvice()
}, { immediate: true })
watch(evidenceVisible, visible => {
  if (visible && props.open && props.event) void loadEvidence(props.event.eventId, showingOriginalVersion)
  else { releaseEvidence(); evidencePhase.value = 'idle' }
})
const releaseScope = projectScope.onClear(() => { evidenceDisposed = true; releaseEvidence(); evidencePhase.value = 'idle' })

// A late thumbnail upload is a media update, not a reason to reset the dialog.
watch([() => props.open, () => props.event?.projectId, () => props.event?.eventId,
  () => JSON.stringify([props.event?.evidence?.snapshotUri, props.event?.evidence?.thumbnail])],
([open, projectId, eventId, evidence], previous) => {
  if (open && eventId && previous && previous[0] && previous[1] === projectId && previous[2] === eventId &&
    previous[3] !== evidence && showingOriginalVersion === undefined) void loadEvidence(eventId)
})

function requestClose() {
  if (props.busy) return
  emit('close')
  void nextTick(() => returnFocus?.focus({ preventScroll: true }))
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') { event.preventDefault(); requestClose(); return }
  if (event.key !== 'Tab' || !dialog.value) return
  const focusable = [...dialog.value.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])')]
  if (!focusable.length) return
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
}

onBeforeUnmount(() => { evidenceDisposed = true; releaseScope(); ++viewGeneration; releaseEvidence(); resetAdvice() })
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="dialog-backdrop alert-dialog-backdrop" @mousedown.self="requestClose">
      <section ref="dialog" class="alert-detail-dialog" role="dialog" aria-modal="true" aria-labelledby="alert-detail-title" @keydown="onKeydown">
        <header class="alert-detail-header">
          <div>
            <p class="eyebrow">EVENT EVIDENCE / {{ event?.eventId }}</p>
            <h2 id="alert-detail-title">{{ title }}</h2>
            <div class="alert-detail-badges"><span :class="`severity-badge is-${priority.key}`">通知 {{ priority.label }}</span><span :class="`disposition-badge is-${disposition.tone}`">{{ disposition.label }}</span></div>
          </div>
          <UiButton ref="closeButton" class="icon-button" type="button" aria-label="关闭告警详情" :disabled="busy" @click="requestClose"><X :size="21" /></UiButton>
        </header>

        <div v-if="detailPhase === 'error'" class="detail-error" role="alert"><FileWarning :size="20" /><span><strong>详情加载失败</strong>{{ detailError }}</span><UiButton class="secondary-button" type="button" @click="event && $emit('retry', event.eventId)">重新加载</UiButton></div>

        <div v-if="event" class="alert-detail-body" :aria-busy="detailPhase === 'loading'">
          <section ref="evidenceElement" class="evidence-section" aria-label="事件证据图片">
            <EvidenceImage v-if="evidencePhase === 'ready'" :key="`${event.projectId}:${event.eventId}:${evidenceUrl}`"
              :src="evidenceUrl" :event="event" :alt="`${title}事件证据`" @error="evidencePhase = 'error'" />
            <div v-else class="evidence-placeholder" :class="`is-${evidencePhase}`">
              <LoaderCircle v-if="evidencePhase === 'loading'" class="spinning" :size="26" aria-hidden="true" />
              <ImageOff v-else :size="27" aria-hidden="true" />
              <strong>{{ evidencePhase === 'idle' ? '待显示时读取证据' : evidencePhase === 'loading' ? '正在读取证据' : evidencePhase === 'error' ? '证据读取失败' : '没有可用证据' }}</strong>
              <span>{{ evidencePhase === 'error' ? '图片服务暂时不可用，事件事实仍可处置。' : evidencePhase === 'empty' ? '服务端未保存该事件的证据图片。' : '通过受鉴权的证据接口加载。' }}</span>
            </div>
          </section>

          <section v-if="mobileCapture" class="event-facts" aria-label="原图补传状态">
            <p role="status">{{ originalStatus }}</p>
            <p v-if="originalMessage" role="status">{{ originalMessage }}</p>
            <UiButton v-if="canDispose && event.originalRequest?.status !== 'UPLOADED'" class="secondary-button" type="button"
              :disabled="busy || requestingOriginal || detailPhase !== 'ready' || event.originalRequest?.status === 'PENDING'"
              @click="requestOriginal">{{ requestingOriginal ? '正在保存请求…' : event.originalRequest?.status === 'PENDING' ? '等待设备补传' : '请求上传原图' }}</UiButton>
            <UiButton v-if="event.originalRequest?.status === 'UPLOADED' && event.originalRequest.contentVersion" class="secondary-button"
              type="button" @click="loadEvidence(event.eventId, event.originalRequest.contentVersion)">查看已上传原图</UiButton>
          </section>
          <section v-else-if="event.origin === 'SERVER_STREAM'" class="event-facts" aria-label="视频流两级证据状态">
            <p role="status">{{ serverOriginalVersion ? '当前展示告警缩略图；服务端已保存同一告警帧的原图。' : '这是历史单级视频流证据，系统不会伪造原图。' }}</p>
            <UiButton v-if="serverOriginalVersion" class="secondary-button" type="button"
              @click="loadEvidence(event.eventId, serverOriginalVersion)">查看原图</UiButton>
          </section>

          <section class="event-facts" aria-label="事件事实">
            <dl>
              <div><dt>事实级别</dt><dd>{{ factSeverity.label }}</dd></div>
              <div><dt>通知级别</dt><dd>{{ priority.label }}<small v-if="factSeverity.key !== priority.key">已提级</small></dd></div>
              <div><dt>事件状态</dt><dd>{{ event.state || '未记录' }}</dd></div>
              <div><dt>事件来源</dt><dd>{{ originLabel(event.origin) }}</dd></div>
              <div><dt>来源标识</dt><dd>{{ event.sourceId || '未知来源' }}</dd></div>
              <div><dt>识别主体</dt><dd>{{ alertSubject(event) }}</dd></div>
              <div><dt>确认时间</dt><dd class="mono-value">{{ formatTimestampUs(eventTimestampUs(event)) }}</dd></div>
              <div><dt>规则</dt><dd>{{ event.ruleId || '未记录' }}<small v-if="event.ruleVersion">v{{ event.ruleVersion }}</small></dd></div>
              <div><dt>来源场景</dt><dd>{{ alertSceneLabel(event) }}<small v-if="event.provenance?.scene">修订 {{ event.provenance.scene.revision }}</small></dd></div>
              <div><dt>运行方案</dt><dd>{{ event.provenance?.plan?.name || '未记录' }}</dd></div>
              <div><dt>触发模型</dt><dd>{{ alertModelLabel(event) }}</dd></div>
              <div class="event-id-fact"><dt>事件 ID</dt><dd class="mono-value">{{ event.eventId }}</dd></div>
            </dl>
          </section>
        </div>

        <section v-if="event" class="advice-panel" aria-label="AI 处置建议">
          <header><div><span class="advice-icon"><Bot :size="19" /></span><span><strong>AI 处置建议</strong><small>SIMULATED KB + LLM</small></span></div><UiButton type="button" class="secondary-button" :disabled="['reading', 'loading'].includes(advicePhase)" @click="loadAdviceHistory"><FileWarning :size="15" />历史</UiButton></header>
          <div v-if="advicePhase === 'idle'" class="advice-idle"><p>暂无已保存的建议，可按当前告警事实生成处置步骤与可能相关的制度依据。</p><em>打开详情只读取已保存结果；仅点击生成或重新生成才调用生成服务。</em><UiButton type="button" class="advice-generate-button" :disabled="detailPhase !== 'ready'" @click="generateAdvice(false)"><Bot :size="17" />生成建议</UiButton></div>
          <div v-else-if="advicePhase === 'reading'" class="advice-loading" role="status"><LoaderCircle class="spinning" :size="20" /><span>正在读取最近一次已保存的建议…</span></div>
          <div v-else-if="advicePhase === 'read-error'" class="advice-failure" role="alert"><strong>已保存建议读取失败</strong><p>{{ adviceError }}</p><UiButton type="button" class="secondary-button" @click="loadLatestAdvice">重新读取</UiButton></div>
          <div v-else-if="advicePhase === 'loading'" class="advice-loading" role="status"><LoaderCircle class="spinning" :size="20" /><span>正在检索模拟知识资料并生成建议…</span></div>
          <div v-else-if="advicePhase === 'error'" class="advice-failure" role="alert"><strong>建议请求失败</strong><p>{{ adviceError }}</p><UiButton type="button" class="secondary-button" @click="generateAdvice(false)">重试请求</UiButton></div>
          <article v-else-if="advice" class="advice-result" :class="'is-' + advice.status.toLowerCase()">
            <div class="advice-result-head"><span>{{ advice.status === 'GENERATED' ? '已生成' : advice.status === 'NO_MATCH' ? '无精确匹配' : advice.status === 'PARTIAL' ? '部分结果' : '生成失败' }}</span><code v-if="advice.matchKey">{{ advice.matchKey.alertTypeId }} + {{ advice.matchKey.recognitionCategoryId }}</code></div>
            <template v-if="advice.advice"><h3>{{ advice.advice.title }}</h3><ol><li v-for="step in advice.advice.steps" :key="step.stepId"><span>{{ step.order }}</span><div><strong>{{ step.title }}</strong><p>{{ step.instruction }}</p></div></li></ol><ul v-if="advice.advice.cautions.length" class="advice-cautions"><li v-for="item in advice.advice.cautions" :key="item">{{ item }}</li></ul></template>
            <div v-else class="advice-empty"><strong>{{ advice.status === 'NO_MATCH' ? '当前告警没有精确匹配的模拟资料' : '本次未能生成处置步骤' }}</strong><p>{{ advice.reasonCode === 'EVENT_MATCH_KEY_UNAVAILABLE' ? '告警缺少稳定的类型或识别分类，系统不会猜测匹配。' : advice.reasonCode === 'KNOWLEDGE_NOT_MATCHED' ? '可由项目负责人补充项目资料；平台也可维护系统基础资料供项目继承。' : '制度原文如可用仍会保留展示。' }}</p></div>
            <section v-if="advice.references.length" class="policy-references"><h4>可能相关的制度依据</h4><blockquote v-for="reference in advice.references" :key="reference.referenceId"><strong>{{ reference.documentTitle }}<small>{{ reference.clauseId || reference.documentVersion }}</small></strong><p>{{ reference.excerpt }}</p><cite>{{ reference.sourceName }}</cite></blockquote></section>
            <p class="advice-source-notice">{{ advice.sourceNotice }}<span v-if="advice.systemKnowledgeVersion">系统基础 V{{ advice.systemKnowledgeVersion }}</span><span v-if="advice.knowledgeRevision">资料修订 REV {{ advice.knowledgeRevision }}</span></p>
            <footer><UiButton type="button" class="secondary-button" @click="generateAdvice(true)">{{ ['FAILED_RETRIEVAL', 'FAILED_GENERATION', 'PARTIAL'].includes(advice.status) ? '重试生成' : '重新生成' }}</UiButton></footer>
          </article>
        </section>

        <div v-if="adviceHistoryOpen" class="advice-history" role="region" aria-label="AI 建议历史"><header><strong>AI 建议历史</strong><UiButton type="button" class="icon-button" aria-label="关闭建议历史" @click="adviceHistoryOpen = false"><X :size="16" /></UiButton></header><article v-for="item in adviceHistory" :key="item.generationId" tabindex="0" @click="advice = item; advicePhase = 'ready'; adviceHistoryOpen = false" @keydown.enter="advice = item; advicePhase = 'ready'; adviceHistoryOpen = false"><span>{{ item.status }}</span><strong>{{ new Date(item.completedAt).toLocaleString('zh-CN') }}</strong><small>{{ item.generationId }}</small></article><p v-if="historyPhase === 'loading'">正在读取历史记录…</p><p v-else-if="historyPhase === 'error'" role="alert">{{ historyError }}<UiButton type="button" class="secondary-button" @click="loadAdviceHistory">重新读取历史</UiButton></p><p v-else-if="!adviceHistory.length">暂无历史记录</p></div>

        <section v-if="event && canDispose" class="disposition-section">
          <label for="alert-note">处置备注 <span>选填，最多 1000 字</span></label>
          <UiInput type="textarea" id="alert-note" v-model="note" maxlength="1000" :rows="2" :disabled="busy" placeholder="记录判断依据或现场处理情况"></UiInput>
          <p v-if="operationMessage" class="operation-feedback" :class="`is-${operationTone}`" role="status">{{ operationMessage }}</p>
        </section>

        <footer v-if="event && canDispose" class="alert-detail-actions">
          <UiButton class="secondary-button false-positive-button" type="button" :disabled="busy || detailPhase !== 'ready' || isClosed || disposition.value === 'FALSE_POSITIVE'" @click="$emit('dispose', 'FALSE_POSITIVE', note)"><ShieldAlert :size="17" />{{ disposition.value === 'FALSE_POSITIVE' ? '已标记误报' : '标记误报' }}</UiButton>
          <UiButton class="primary-button" type="button" :disabled="busy || detailPhase !== 'ready' || isClosed || disposition.value === 'ACKNOWLEDGED'" @click="$emit('dispose', 'ACKNOWLEDGED', note)"><CheckCircle2 :size="17" />{{ disposition.value === 'ACKNOWLEDGED' ? '已确认' : busy ? '处理中…' : '确认告警' }}</UiButton>
        </footer>
      </section>
    </div>
  </Teleport>
</template>
