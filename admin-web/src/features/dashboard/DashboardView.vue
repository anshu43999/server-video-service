<script setup lang="ts">
import { useProjectCapabilities } from '../projects/capabilities'
const { streams: canManageStreams, can } = useProjectCapabilities()
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { alertTitle, dispositionPresentation, eventPriority, eventTimestampUs, formatTimestampUs } from '../alerts/presenters'
import { canPreview, percent, streamStatus } from './presenters'
import { useDashboard } from './useDashboard'
import type { StatsRange } from './types'
import './dashboard.css'
import { useProjectsStore } from '../../stores/projects'
import { projectRoleLabel } from '../../api/projects'

const props = withDefaults(defineProps<{ dashboard?: boolean }>(), { dashboard: true })
const projects = useProjectsStore()
const route = useRoute(), router = useRouter()
const range = computed<StatsRange>(() => route.query.range === '7d' || route.query.range === '30d' ? route.query.range : 'today')
const { stats, streams, events, statsError, streamsError, eventsError, loading, refresh } = useDashboard(range)
const latest = computed(() => [...(events.value ?? [])].sort((a, b) => (eventTimestampUs(b) ?? -1) - (eventTimestampUs(a) ?? -1)).slice(0, 4))
const runtimeCounts = computed(() => {
  if (!streams.value) return null
  const result = { online: 0, waiting: 0, error: 0, disabled: 0 }
  for (const stream of streams.value) result[streamStatus(stream).key as keyof typeof result]++
  return result
})
const yoloCount = computed(() => streams.value?.filter(stream => canPreview(stream) && stream.yolo_enabled).length)
const trendMax = computed(() => Math.max(1, ...(stats.value?.trend.map(bucket => bucket.count) ?? [])))
const severityRows = computed(() => Object.entries(stats.value?.severity.total ?? {}).map(([key, total]) => ({ key, total, handled: stats.value?.severity.handled[key] ?? 0 })))
function setRange(value: string | number) { void router.replace({ query: { ...route.query, range: String(value) } }) }
function date(value?: string) { return value && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '不可用' }
function bar(value: number) { return `${Math.max(0, Math.min(100, value))}%` }

const board = ref<HTMLElement>(), screenButton = ref<HTMLButtonElement>(), focused = ref(false)
let previousOverflow = '', disposed = false, requestingFullscreen = false
async function enterScreen() {
  previousOverflow = document.body.style.overflow
  document.body.style.overflow = 'hidden'
  focused.value = true
  await nextTick()
  if (disposed || !focused.value) return
  board.value?.focus()
  const element = board.value
  if (element?.requestFullscreen && !document.fullscreenElement) {
    requestingFullscreen = true
    try { await element.requestFullscreen() } catch { /* Keep the CSS screen mode available if fullscreen is denied. */ }
    finally {
      requestingFullscreen = false
      if ((disposed || !focused.value) && document.fullscreenElement === element) void document.exitFullscreen().catch(() => {})
    }
  }
}
function exitScreen(restoreFocus = true) {
  if (!focused.value) return
  focused.value = false
  document.body.style.overflow = previousOverflow
  if (document.fullscreenElement === board.value) void document.exitFullscreen().catch(() => {})
  if (restoreFocus && !disposed) void nextTick(() => screenButton.value?.focus())
}
function fullscreenChanged() { if (!document.fullscreenElement && !requestingFullscreen) exitScreen() }
function keydown(event: KeyboardEvent) {
  if (!focused.value) return
  if (event.key === 'Escape') { event.preventDefault(); exitScreen() }
  if (event.key === 'Tab') {
    const controls = [...(board.value?.querySelectorAll<HTMLElement>('a[href], button:not(:disabled), [role="combobox"]:not([aria-disabled="true"])') ?? [])]
    const first = controls[0], last = controls.at(-1)
    if (event.shiftKey && (document.activeElement === first || document.activeElement === board.value)) { event.preventDefault(); last?.focus() }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
  }
}
watch(() => props.dashboard, () => exitScreen(false))
onMounted(() => { document.addEventListener('fullscreenchange', fullscreenChanged); window.addEventListener('keydown', keydown) })
onBeforeUnmount(() => { disposed = true; exitScreen(false); document.removeEventListener('fullscreenchange', fullscreenChanged); window.removeEventListener('keydown', keydown) })
</script>

<template>
  <section ref="board" tabindex="-1" class="operations-board" :class="{ 'is-focused': focused }" :aria-label="dashboard ? '数据看板工作区' : '总览工作区'">
    <header class="board-heading">
      <div v-if="focused && projects.current" class="fullscreen-project" role="status"><strong>{{ projects.current.displayName }}</strong> · {{ projectRoleLabel(projects.current) }}</div>
      <div class="board-controls"><label>统计周期<UiSelect :value="range" @change="setRange"><UiOption value="today">今日</UiOption><UiOption value="7d">近 7 天</UiOption><UiOption value="30d">近 30 天</UiOption></UiSelect></label><UiButton class="secondary-button" type="button" :disabled="loading" @click="refresh">{{ loading ? '读取中…' : '刷新看板' }}</UiButton><UiButton v-if="dashboard" ref="screenButton" class="primary-button" type="button" @click="focused ? exitScreen() : enterScreen()">{{ focused ? '退出大屏' : '大屏模式' }}</UiButton><RouterLink v-else-if="canManageStreams" class="primary-button" :to="{ name: 'streams', query: { create: '1' } }">新建视频流</RouterLink></div>
    </header>
    <div class="board-provenance"><span>{{ stats ? `数据源 ${stats.dataSource} · 更新 ${date(stats.generatedAt)}` : statsError ? '统计不可用' : '正在读取真实统计' }}</span><span>每 10 秒刷新 · {{ range === 'today' ? '每 2 小时分桶' : range === '7d' ? '每日分桶' : '每 5 天分桶' }}</span></div>
    <p v-if="statsError" class="board-error" role="status">统计不可用：{{ statsError }}</p>
    <div class="board-kpis" aria-label="业务指标">
      <article><span>告警事件</span><strong>{{ stats?.summary.totalEvents ?? '—' }}</strong><small>{{ stats ? '所选统计周期' : '指标不可用' }}</small></article>
      <article class="kpi-severe"><span>严重 / 重要告警</span><strong>{{ stats?.summary.severeAlerts ?? '—' }}</strong><small>按通知等级统计</small></article>
      <article><span>事件处置率</span><strong>{{ stats ? percent(stats.summary.resolutionRate) : '—' }}</strong><small>{{ stats ? `已处置 ${stats.summary.handledEvents} 条` : '指标不可用' }}</small></article>
      <article><span>平均响应</span><strong>{{ stats?.summary.averageResponseMinutes == null ? '—' : stats.summary.averageResponseMinutes.toFixed(1) }}<em v-if="stats?.summary.averageResponseMinutes != null"> min</em></strong><small>{{ !stats ? '指标不可用' : stats.summary.averageResponseMinutes == null ? '暂无有效响应样本' : '从确认告警到处置' }}</small></article>
    </div>
    <div class="board-grid">
      <section class="board-panel board-trend"><header><h3>告警趋势</h3><span><i class="legend-total"></i>全部 <i class="legend-severe"></i>严重 / 重要</span></header><p v-if="!stats" class="board-empty">{{ statsError ? '趋势不可用' : '正在读取趋势…' }}</p><template v-else><p v-if="!stats.summary.totalEvents" class="board-empty compact">所选周期暂无告警事件</p><div class="trend-chart" role="img" aria-label="告警趋势：每个时间段的全部与严重重要告警数量"><div v-for="(bucket,index) in stats.trend" :key="index" class="trend-bucket" :title="`${bucket.label}：全部 ${bucket.count}，严重重要 ${bucket.severe}`"><span class="trend-count">{{ bucket.count }}</span><div class="trend-track"><div class="trend-total" :style="{ height: bar(bucket.count / trendMax * 100) }"></div><div class="trend-severe" :style="{ height: bar(bucket.severe / trendMax * 100) }"></div></div><span class="trend-label">{{ bucket.label }}</span><span class="sr-only">严重重要 {{ bucket.severe }}</span></div></div><p class="board-note">{{ date(stats.from) }} 至 {{ date(stats.to) }}</p></template></section>
      <section class="board-panel"><header><h3>告警类别</h3><span>数量 / 占比</span></header><p v-if="!stats || !stats.categories.length" class="board-empty">{{ !stats ? '类别统计不可用' : '暂无类别数据' }}</p><div v-for="category in stats?.categories" :key="category.label" class="distribution-row"><div><strong>{{ category.label }}</strong><span>{{ category.count }} · {{ percent(category.percent) }}</span></div><div class="distribution-track"><i :style="{ width: bar(category.percent) }"></i></div></div></section>
      <section v-if="can('project.streams.view')" class="board-panel board-streams"><header><h3>现场流状态</h3><RouterLink :to="{ name: 'streams' }">管理视频流 →</RouterLink></header><p v-if="streamsError" class="board-error" role="status">视频流不可用：{{ streamsError }}</p><template v-if="runtimeCounts"><div class="stream-counts"><span>已配置 <b>{{ streams?.length }}</b></span><span>运行中 <b>{{ runtimeCounts.online }}</b></span><span>等待 / 未运行 <b>{{ runtimeCounts.waiting }}</b></span><span>异常 <b>{{ runtimeCounts.error }}</b></span><span>已停用 <b>{{ runtimeCounts.disabled }}</b></span><span>推理已启用 <b>{{ yoloCount }}</b></span></div><p v-if="!streams?.length" class="board-empty">当前没有视频流会话</p><ul v-else class="board-stream-list"><li v-for="stream in streams" :key="stream.stream_id"><RouterLink :to="{ name: 'streams' }">{{ stream.display_name || stream.stream_id }}</RouterLink><span :class="`stream-tone-${streamStatus(stream).key}`">{{ streamStatus(stream).label }}</span><span>{{ stream.yolo_enabled ? 'YOLO 已启用' : 'YOLO 未启用' }}</span></li></ul></template><p v-else-if="!streamsError" class="board-empty">正在读取视频流…</p></section>
      <section class="board-panel"><header><h3>最新告警</h3><RouterLink :to="{ name: 'alerts' }">告警中心 →</RouterLink></header><p class="board-note">当前可查询事件的最新 4 条，不受统计周期筛选。</p><p v-if="eventsError" class="board-error" role="status">告警不可用：{{ eventsError }}</p><p v-else-if="!events || !latest.length" class="board-empty">{{ events ? '暂无告警事件' : '正在读取告警…' }}</p><RouterLink v-for="event in latest" :key="event.eventId" class="board-alert" :to="{ name: 'alerts', query: { event: event.eventId } }"><div><strong>{{ alertTitle(event) }}</strong><span>{{ eventPriority(event).label }} · {{ dispositionPresentation(event.disposition).label }}</span></div><small>{{ event.sourceId || '来源未标记' }} · {{ formatTimestampUs(event.confirmedAtUs ?? event.startedAtUs) }}</small></RouterLink></section>
      <template v-if="dashboard">
        <section class="board-panel board-project-health"><header><h3>项目运行诊断</h3><RouterLink :to="{name:'project-diagnostics',query:{project:route.query.project}}">诊断 →</RouterLink></header><p v-if="!stats" class="board-empty">项目运行汇总暂不可用</p><dl v-else><div><dt>本项目配置流数</dt><dd>{{stats.streams.total}}</dd></div><div><dt>在线 / 异常</dt><dd>{{stats.streams.online}} / {{stats.streams.errors}}</dd></div></dl><p class="board-note">统计仅限当前项目。服务器资源与全局运行明细位于平台诊断。</p></section>
        <section class="board-panel"><header><h3>分级处置</h3><span>已处置 / 事件数</span></header><p v-if="!stats || !severityRows.length" class="board-empty">{{ stats ? '暂无处置数据' : '处置统计不可用' }}</p><div v-for="row in severityRows" :key="row.key" class="distribution-row"><div><strong>{{ row.key }}</strong><span>{{ row.handled }} / {{ row.total }} · {{ percent(row.total ? row.handled / row.total * 100 : 0) }}</span></div><div class="distribution-track"><i :style="{ width: bar(row.total ? row.handled / row.total * 100 : 0) }"></i></div></div></section>
      </template>
    </div>
  </section>
</template>
