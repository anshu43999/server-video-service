<script setup lang="ts">
import { useProjectCapabilities } from '../projects/capabilities'
const { dispose: canDispose, exports: canExport, active } = useProjectCapabilities()
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowLeft, ArrowRight, BellRing, Download, Image, ImageOff, LoaderCircle, RefreshCw, Search } from '@lucide/vue'
import { isApiError } from '../../api/errors'
import UiConfirmDialog from '../../components/ui/UiConfirmDialog.vue'
import UiNoticeStack, { type NoticeItem } from '../../components/ui/UiNoticeStack.vue'
import UiStatePanel from '../../components/ui/UiStatePanel.vue'
import { alertsApi } from './api'
import AlertDetailDialog from './AlertDetailDialog.vue'
import EvidenceImage from './EvidenceImage.vue'
import {
  alertSubject, alertTitle, dispositionPresentation, eventPriority, eventTimestampUs,
  formatTimestampUs, hasEvidence, matchesOriginFilter, originLabel, alertSceneLabel, alertModelLabel,
  type AlertOriginFilter,
} from './presenters'
import { useAlertsStore } from './store'
import type { AlertEvent, AlertSeverityKey, DispositionAction } from './types'

type SeverityFilter = 'all' | AlertSeverityKey
type StatusFilter = 'all' | 'OPEN' | 'ACKNOWLEDGED' | 'FALSE_POSITIVE' | 'CLOSED'

const store = useAlertsStore()
const route = useRoute()
const severityFilter = ref<SeverityFilter>('all')
const statusFilter = ref<StatusFilter>('all')
const originFilter = ref<AlertOriginFilter>('all')
const query = ref('')
const page = ref(1)
const pageSize = ref(10)
const socketStatus = computed(() => store.socketStatus)
const actionBusy = ref(false)
const operationMessage = ref('')
const operationTone = ref<'success' | 'error' | 'info'>('info')
const confirmOpen = ref(false)
const pendingAction = ref<{ action: DispositionAction; note: string } | null>(null)
const notices = ref<NoticeItem[]>([])
let noticeSequence = 0
type ThumbnailPhase = 'loading' | 'ready' | 'empty' | 'error'
type ThumbnailState = { phase: ThumbnailPhase; url?: string }
const thumbnailStates = ref<Record<string, ThumbnailState>>({})
const thumbnailControllers = new Map<string, AbortController>()

const counts = computed(() => {
  const value = { all: store.events.length, critical: 0, important: 0, normal: 0 }
  for (const event of store.events) value[eventPriority(event).key] += 1
  return value
})
const filteredEvents = computed(() => {
  const needle = query.value.trim().toLocaleLowerCase('zh-CN')
  return store.events.filter((event) => {
    if (severityFilter.value !== 'all' && eventPriority(event).key !== severityFilter.value) return false
    if (statusFilter.value !== 'all' && dispositionPresentation(event.disposition).value !== statusFilter.value) return false
    if (!matchesOriginFilter(event.origin, originFilter.value)) return false
    if (!needle) return true
    return [alertTitle(event), event.eventId, event.ruleId, event.sourceId, originLabel(event.origin), alertSubject(event),
      alertSceneLabel(event), alertModelLabel(event)]
      .filter(Boolean).join(' ').toLocaleLowerCase('zh-CN').includes(needle)
  })
})
const pageCount = computed(() => Math.max(1, Math.ceil(filteredEvents.value.length / pageSize.value)))
const visibleEvents = computed(() => filteredEvents.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value))
const rangeStart = computed(() => filteredEvents.value.length ? (page.value - 1) * pageSize.value + 1 : 0)
const rangeEnd = computed(() => Math.min(page.value * pageSize.value, filteredEvents.value.length))
const socketLabel = computed(() => ({
  open: '实时同步', connecting: '正在连接', backoff: '重连中', offline: '网络离线',
  'auth-failed': '实时权限失效', 'rate-limited': '连接受限', missing: '实时通道不可用', stopped: '实时同步已停止', idle: '等待连接',
}[socketStatus.value] ?? '实时状态未知'))
const pendingDescription = computed(() => {
  const event = store.selected
  if (!event || !pendingAction.value) return ''
  return pendingAction.value.action === 'FALSE_POSITIVE'
    ? `将事件“${alertTitle(event)}”标记为误报，并生成可导出的反馈记录。原始事件事实仍会保留。`
    : `确认事件“${alertTitle(event)}”已由人工核实。该操作会写入处置人和服务端时间。`
})

watch([severityFilter, statusFilter, originFilter, query, pageSize], () => { page.value = 1 })
watch(pageCount, (count) => { if (page.value > count) page.value = count })
watch(visibleEvents, (events) => { events.forEach((event) => { void loadThumbnail(event) }) }, { immediate: true })

function pushNotice(title: string, message: string, tone: NoticeItem['tone']) {
  const id = `alert-notice-${++noticeSequence}`
  notices.value = [...notices.value, { id, title, message, tone }].slice(-3)
}

function dismissNotice(id: string) {
  notices.value = notices.value.filter((notice) => notice.id !== id)
}

function thumbnailState(event: AlertEvent): ThumbnailState {
  return thumbnailStates.value[event.eventId] ?? { phase: hasEvidence(event) ? 'loading' : 'empty' }
}

function setThumbnailState(eventId: string, state: ThumbnailState) {
  thumbnailStates.value = { ...thumbnailStates.value, [eventId]: state }
}

async function loadThumbnail(event: AlertEvent) {
  if (!hasEvidence(event) || thumbnailStates.value[event.eventId]) return
  const controller = new AbortController()
  thumbnailControllers.set(event.eventId, controller)
  setThumbnailState(event.eventId, { phase: 'loading' })
  try {
    const blob = await alertsApi.evidence(event.eventId, controller.signal)
    if (controller.signal.aborted) return
    if (!blob.size) {
      setThumbnailState(event.eventId, { phase: 'empty' })
      return
    }
    setThumbnailState(event.eventId, { phase: 'ready', url: URL.createObjectURL(blob) })
  } catch (error) {
    if (controller.signal.aborted || (isApiError(error) && error.kind === 'cancelled')) return
    setThumbnailState(event.eventId, { phase: isApiError(error) && error.status === 404 ? 'empty' : 'error' })
  } finally {
    thumbnailControllers.delete(event.eventId)
  }
}

function failThumbnail(eventId: string) {
  const current = thumbnailStates.value[eventId]
  if (current?.url) URL.revokeObjectURL(current.url)
  setThumbnailState(eventId, { phase: 'error' })
}

async function openEvent(event: AlertEvent) {
  operationMessage.value = ''
  await store.openDetail(event.eventId)
}

function requestDisposition(action: DispositionAction, note: string) {
  if (!canDispose.value) return
  pendingAction.value = { action, note }
  confirmOpen.value = true
}

async function confirmDisposition() {
  const eventId = store.selected?.eventId
  const pending = pendingAction.value
  if (!canDispose.value || !eventId || !pending) return
  actionBusy.value = true
  operationMessage.value = pending.action === 'FALSE_POSITIVE' ? '正在标记误报…' : '正在确认告警…'
  operationTone.value = 'info'
  try {
    await store.dispose(eventId, pending.action, pending.note)
    confirmOpen.value = false
    pendingAction.value = null
    operationMessage.value = pending.action === 'FALSE_POSITIVE' ? '已标记为误报。' : '告警已确认。'
    operationTone.value = 'success'
    pushNotice('处置已记录', operationMessage.value, 'success')
  } catch (error) {
    confirmOpen.value = false
    pendingAction.value = null
    if (isApiError(error) && error.status === 409) {
      await store.openDetail(eventId)
      operationMessage.value = '事件已被其他操作更新；详情已刷新，请核对最新状态后重试。'
    } else {
      operationMessage.value = error instanceof Error ? error.message : '处置请求失败'
    }
    operationTone.value = 'error'
  } finally {
    actionBusy.value = false
  }
}

const exportBusy = ref(false)
async function exportFalsePositives(feedback = true) {
  if (!canExport.value || exportBusy.value) return
  exportBusy.value = true
  try {
    const blob = await (feedback ? alertsApi.exportFalsePositives() : alertsApi.exportAlerts())
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = feedback ? 'aiyolo-false-positives.json' : 'aiyolo-alerts.json'
    anchor.click()
    URL.revokeObjectURL(url)
    pushNotice('导出已开始', '当前项目完整报表由服务端生成，不包含证据图片；不受列表筛选影响。', 'success')
  } catch (error) {
    pushNotice('导出失败', error instanceof Error ? error.message : '无法导出报表', 'error')
  } finally { exportBusy.value = false }
}

onMounted(() => {
  void store.refresh()
  if (typeof route.query.event === 'string' && route.query.event) void store.openDetail(route.query.event)
})
onBeforeUnmount(() => {
  thumbnailControllers.forEach((controller) => controller.abort())
  Object.values(thumbnailStates.value).forEach((state) => { if (state.url) URL.revokeObjectURL(state.url) })
  store.closeDetail()
})
</script>

<template>
  <section class="alerts-page" aria-label="告警中心">
    <header class="alerts-page-header">
      <div>
        <span class="realtime-state" :class="`is-${socketStatus}`"><i aria-hidden="true"></i>{{ socketLabel }}</span>
      </div>
      <div class="alerts-page-actions">
        <UiButton v-if="canExport" class="secondary-button" type="button" :disabled="exportBusy" @click="exportFalsePositives(false)"><Download :size="16" />导出告警</UiButton>
        <UiButton v-if="canExport" class="secondary-button" type="button" :disabled="exportBusy" @click="exportFalsePositives(true)"><Download :size="16" />导出误报</UiButton>
        <UiButton class="icon-button" type="button" title="刷新告警" aria-label="刷新告警" :disabled="store.phase === 'loading'" @click="store.refresh()"><RefreshCw :size="18" :class="{ spinning: store.phase === 'loading' }" /></UiButton>
      </div>
    </header>

    <section class="alert-ledger" aria-label="告警事件列表">
      <div class="alert-summary-bar">
        <div><strong>事件队列</strong><span>严重度统计基于当前取得的 {{ store.events.length }} 条真实事件</span></div>
        <div class="severity-tabs" role="group" aria-label="通知严重度筛选">
          <UiButton v-for="item in ([['all', '全部'], ['critical', '严重'], ['important', '重要'], ['normal', '一般']] as const)" :key="item[0]" type="button" :class="{ active: severityFilter === item[0] }" :aria-pressed="severityFilter === item[0]" @click="severityFilter = item[0]"><span>{{ item[1] }}</span><b>{{ String(counts[item[0]]).padStart(2, '0') }}</b></UiButton>
        </div>
      </div>

      <div class="alert-filters">
        <label class="alert-search"><Search :size="16" aria-hidden="true" /><span class="sr-only">搜索事件</span><UiInput v-model="query" type="search" placeholder="搜索事件、规则、来源或 ID" /></label>
        <label class="alert-origin-filter"><span>告警来源</span><UiSelect v-model="originFilter" data-testid="alert-origin-filter"><UiOption value="all">全部来源</UiOption><UiOption value="SERVER_STREAM">视频流告警</UiOption><UiOption value="MOBILE">移动端本地告警</UiOption></UiSelect></label>
        <label><span>处置状态</span><UiSelect v-model="statusFilter"><UiOption value="all">全部处置状态</UiOption><UiOption value="OPEN">待确认</UiOption><UiOption value="ACKNOWLEDGED">已确认</UiOption><UiOption value="FALSE_POSITIVE">误报</UiOption><UiOption value="CLOSED">已关闭</UiOption></UiSelect></label>
        <label><span>每页</span><UiSelect v-model.number="pageSize"><UiOption :value="10">10 条</UiOption><UiOption :value="20">20 条</UiOption><UiOption :value="50">50 条</UiOption></UiSelect></label>
      </div>

      <UiStatePanel v-if="store.phase === 'loading' && !store.events.length" state="loading" title="正在读取真实告警" message="正在从事件存储取得告警记录。" />
      <UiStatePanel v-else-if="store.phase === 'error' && !store.events.length" state="error" title="告警数据不可用" :message="store.error" @retry="store.refresh()" />
      <UiStatePanel v-else-if="!filteredEvents.length" state="empty" :title="store.events.length ? '当前筛选没有匹配事件' : '当前没有告警事件'" :message="store.events.length ? '调整严重度、处置状态或搜索条件后重试。' : '此处只展示服务端已持久化的真实告警。'" />

      <template v-else>
        <div class="alert-table-head" aria-hidden="true"><span>证据</span><span>事件</span><span>告警来源</span><span>确认时间</span><span>处置状态</span><span>操作</span></div>
        <div class="alert-event-list">
          <UiButton v-for="event in visibleEvents" :key="event.eventId" class="alert-event-row" :class="`severity-${eventPriority(event).key}`" type="button" @click="openEvent(event)">
            <span class="alert-event-grid">
              <span class="evidence-indicator" :class="{ available: thumbnailState(event).phase === 'ready' }">
                <EvidenceImage v-if="thumbnailState(event).phase === 'ready'" :src="thumbnailState(event).url!"
                  :event="event" :alt="`${alertTitle(event)}证据缩略图`" @error="failThumbnail(event.eventId)" />
                <LoaderCircle v-else-if="thumbnailState(event).phase === 'loading'" class="spinning" :size="18" aria-hidden="true" />
                <ImageOff v-else-if="thumbnailState(event).phase === 'empty'" :size="18" aria-hidden="true" />
                <Image v-else :size="18" aria-hidden="true" />
                <small>{{ thumbnailState(event).phase === 'ready' ? '有证据' : thumbnailState(event).phase === 'loading' ? '读取中' : thumbnailState(event).phase === 'empty' ? '无证据' : '读取失败' }}</small>
              </span>
              <span class="alert-event-title"><b>{{ alertTitle(event) }}</b><small><i :class="`is-${eventPriority(event).key}`"></i>通知{{ eventPriority(event).label }} · {{ event.ruleId || '未记录规则' }}</small></span>
              <span class="alert-event-source"><span class="alert-origin-label" :class="matchesOriginFilter(event.origin, 'SERVER_STREAM') ? 'is-stream' : matchesOriginFilter(event.origin, 'MOBILE') ? 'is-mobile' : 'is-unknown'">{{ originLabel(event.origin) }}</span><b :title="alertSceneLabel(event)">{{ alertSceneLabel(event) }}</b><small :title="alertModelLabel(event)">{{ alertModelLabel(event) }}</small></span>
              <span class="alert-event-time">{{ formatTimestampUs(eventTimestampUs(event)) }}</span>
              <UiTag class="disposition-badge" :class="`is-${dispositionPresentation(event.disposition).tone}`">{{ dispositionPresentation(event.disposition).label }}</UiTag>
              <span class="alert-event-action"><span>查看 <ArrowRight :size="14" /></span></span>
            </span>
          </UiButton>
        </div>
        <footer class="alert-pagination">
          <span>已取回 {{ store.events.length }} 条真实事件 · 筛选后 {{ filteredEvents.length }} 条 · 当前 {{ rangeStart }}-{{ rangeEnd }}</span>
          <UiPagination v-model="page" :total="filteredEvents.length" :page-size="pageSize" />
        </footer>
      </template>
    </section>

    <AlertDetailDialog
      :open="Boolean(store.selectedId)"
      :event="store.selected"
      :detail-phase="store.detailPhase"
      :detail-error="store.detailError"
      :busy="actionBusy"
      :operation-message="operationMessage"
      :operation-tone="operationTone"
      @close="store.closeDetail()"
      @retry="store.openDetail"
      @dispose="requestDisposition"
    />
    <UiConfirmDialog
      v-model:open="confirmOpen"
      :title="pendingAction?.action === 'FALSE_POSITIVE' ? '确认标记误报' : '确认告警'"
      :description="pendingDescription"
      :confirm-label="pendingAction?.action === 'FALSE_POSITIVE' ? '确认标记' : '确认告警'"
      :tone="pendingAction?.action === 'FALSE_POSITIVE' ? 'danger' : 'default'"
      :busy="actionBusy"
      @confirm="confirmDisposition"
      @cancel="pendingAction = null"
    />
    <UiNoticeStack :notices="notices" @dismiss="dismissNotice" />
  </section>
</template>
