<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { Boxes, FileCheck2, History, Upload, Link2, ShieldCheck, RefreshCw } from '@lucide/vue'
import { useSessionStore } from '../../stores/session'
import UiButton from '../../components/ui/UiButton.vue'
import UiDialog from '../../components/ui/UiDialog.vue'
import UiStatePanel from '../../components/ui/UiStatePanel.vue'
import { ApiError } from '../../api/errors'
import { appUpdatesApi as api, externalFields, formatBytes, PACKAGE, parseNotes, updateError, type Artifact, type Audit, type Configuration, type Release, type Scope, type Source } from './api'
import './appUpdates.css'
import RollbackControl from './RollbackControl.vue'
import ExternalReleaseWizard from './ExternalReleaseWizard.vue'

type Tab = 'releases' | 'artifacts' | 'audit'
type Action = 'upload' | 'external' | 'source' | 'draft' | 'publish' | 'stop'
const session = useSessionStore()
const allowed = computed(() => session.isAdmin && session.phase === 'authenticated')
const config = ref<Configuration>()
const wizardOpen = ref(false), wizardBusy = ref(false)
const tab = ref<Tab>('releases')
const releases = ref<Release[]>([]), artifacts = ref<Artifact[]>([]), audits = ref<Audit[]>([])
const loading = ref(false), loadingMore = ref(false), error = ref(''), notice = ref('')
const cursor = ref<string | null>(null)
const detailOpen = ref(false), detailLoading = ref(false), detailError = ref('')
const artifact = ref<Artifact>(), release = ref<Release>(), sources = ref<Source[]>([]), sourceCursor = ref<string | null>(null)
const editOpen = ref(false), action = ref<Action>('upload'), busy = ref(false), mutationError = ref(''), needsReload = ref(false)
const progress = ref<number | null>(null), sending = ref(false), file = ref<File>()
const form = reactive({ reason: '', url: '', hosts: '', scope: 0, importance: 'normal' as 'normal' | 'important', notes: '', sourceId: '', floor: 1, capabilities: [] as string[] })
const selectedScope = computed(() => config.value?.scopes[form.scope])
const titles: Record<Action, string> = { upload: '上传 APK 至自有存储', external: '登记第三方 APK', source: '新增同包下载来源', draft: '创建版本草稿', publish: '发布版本', stop: '停止分发' }
const stateNames: Record<string, string> = { pending: '待核验', verifying: '核验中', verified: '已核验', failed: '核验失败', draft: '草稿', published: '已发布', stopped: '已停止', queued: '排队中', processing: '核验中', retryable: '等待重试', succeeded: '已完成', receiving: '接收中' }
let controller = new AbortController(), detailController = new AbortController(), mutationController = new AbortController()
let generation = 0, detailGeneration = 0, poll: ReturnType<typeof setTimeout> | undefined
let retrySignature = '', retryKey = ''
const rowCount = computed(() => tab.value === 'releases' ? releases.value.length : tab.value === 'artifacts' ? artifacts.value.length : audits.value.length)
const usableSources = computed(() => sources.value.filter(s => s.state === 'verified' && s.details.availabilityState === 'available'))
const hasPending = computed(() => artifact.value?.state === 'pending' || artifact.value?.state === 'verifying' || artifact.value?.details.jobs?.some(j => ['queued', 'receiving', 'processing', 'retryable'].includes(j.state)))
const date = (value?: string | null) => value ? new Date(value).toLocaleString('zh-CN') : '—'
const level = (value: Release) => value.details.minSupportedVersionCode > 1 ? '兼容门禁' : value.details.importance === 'important' ? '重要推荐' : '普通更新'
const scopeLabel = (scope: Omit<Scope, 'contractVersion'>) => `${scope.deploymentId} / ${scope.channel}`
function scopeOf(value: Release): Scope { return { contractVersion: 'app-update/v1', packageName: PACKAGE, publisherId: value.details.publisherId, channel: value.details.channel, deploymentId: value.details.deploymentId } }

function invalidate() {
  generation++; detailGeneration++; controller.abort(); detailController.abort(); mutationController.abort(); clearTimeout(poll)
  wizardOpen.value = false; wizardBusy.value = false; editOpen.value = false; detailOpen.value = false; busy.value = false; sending.value = false
  config.value = undefined; releases.value = []; artifacts.value = []; audits.value = []; artifact.value = undefined; release.value = undefined; sources.value = []
}
watch([allowed, () => session.user?.accountId], ([value]) => { invalidate(); if (value) void load() })
async function load(append = false) {
  if (!allowed.value || busy.value) return
  controller.abort(); controller = new AbortController()
  const stamp = ++generation, kind = tab.value
  if (append) loadingMore.value = true
  else { loading.value = true; error.value = ''; cursor.value = null }
  try {
    const [settings, page] = await Promise.all([config.value ?? api.configuration(controller.signal), api.list(kind, append ? cursor.value : null, controller.signal)])
    if (stamp !== generation || !allowed.value) return
    config.value = settings
    const unique = <T extends { resourceId: string }>(items: T[]) => [...new Map(items.map(r => [r.resourceId, r])).values()]
    if (kind === 'releases') releases.value = unique([...(append ? releases.value : []), ...page.items as Release[]])
    if (kind === 'artifacts') artifacts.value = unique([...(append ? artifacts.value : []), ...page.items as Artifact[]])
    if (kind === 'audit') audits.value = unique([...(append ? audits.value : []), ...page.items as Audit[]])
    cursor.value = page.nextCursor
  } catch (e) { if (stamp === generation && allowed.value) error.value = updateError(e) }
  finally { if (stamp === generation) { loading.value = false; loadingMore.value = false } }
}
function changeTab(value: Tab) { if (busy.value || loadingMore.value) return; tab.value = value; void load() }
function rollbackChanged() { detailOpen.value = false; void load() }
async function wizardCreated(id: string) {
  wizardOpen.value = false; wizardBusy.value = false
  notice.value = '版本草稿已创建，请核对下载来源并确认发布。'
  tab.value = 'releases'; await load(); if (allowed.value) await inspect('release', id)
}
function wizardDenied(message: string) { invalidate(); error.value = message }
async function inspect(kind: 'artifact' | 'release', id: string) {
  clearTimeout(poll); detailController.abort(); detailController = new AbortController()
  const stamp = ++detailGeneration
  detailOpen.value = true; detailLoading.value = true; detailError.value = ''; artifact.value = undefined; release.value = undefined; sources.value = []; sourceCursor.value = null
  try {
    if (kind === 'artifact') {
      const [a, page] = await Promise.all([api.artifact(id, detailController.signal), api.sources(id, null, detailController.signal)])
      if (stamp !== detailGeneration || !allowed.value) return
      artifact.value = a; sources.value = page.items; sourceCursor.value = page.nextCursor
    } else {
      const r = await api.release(id, detailController.signal)
      const [a, page] = await Promise.all([api.artifact(r.details.artifactId, detailController.signal), api.sources(r.details.artifactId, null, detailController.signal)])
      if (stamp !== detailGeneration || !allowed.value) return
      release.value = r; artifact.value = a; sources.value = page.items; sourceCursor.value = page.nextCursor
    }
    schedulePoll()
  } catch (e) { if (stamp === detailGeneration && allowed.value) detailError.value = updateError(e) }
  finally { if (stamp === detailGeneration) detailLoading.value = false }
}
function schedulePoll() {
  clearTimeout(poll)
  if (detailOpen.value && hasPending.value && !editOpen.value) poll = setTimeout(async () => {
    if (!artifact.value || !allowed.value || !detailOpen.value) return
    const stamp = detailGeneration
    try {
      const a = await api.artifact(artifact.value.resourceId, detailController.signal)
      const page = await api.sources(a.resourceId, null, detailController.signal)
      if (stamp !== detailGeneration || !allowed.value) return
      artifact.value = a; sources.value = page.items; sourceCursor.value = page.nextCursor
      if (!hasPending.value) await load()
      schedulePoll()
    } catch (e) { if (stamp === detailGeneration) detailError.value = updateError(e) }
  }, 5000)
}
watch(detailOpen, open => { if (!open) { detailGeneration++; detailController.abort(); clearTimeout(poll) } })
async function moreSources() {
  if (!artifact.value || !sourceCursor.value || detailLoading.value) return
  detailLoading.value = true
  const stamp = detailGeneration
  try { const page = await api.sources(artifact.value.resourceId, sourceCursor.value, detailController.signal); if (stamp === detailGeneration && allowed.value) { sources.value = [...sources.value, ...page.items]; sourceCursor.value = page.nextCursor } }
  catch (e) { if (stamp === detailGeneration) detailError.value = updateError(e) }
  finally { if (stamp === detailGeneration) detailLoading.value = false }
}
function begin(value: Action) {
  if (!allowed.value || busy.value || !config.value) return
  action.value = value; mutationError.value = ''; needsReload.value = false; retrySignature = ''; retryKey = ''; progress.value = null; file.value = undefined
  Object.assign(form, { reason: '', url: '', hosts: '', scope: 0, importance: 'normal', notes: '', sourceId: usableSources.value[0]?.resourceId ?? '', floor: 1, capabilities: [] })
  clearTimeout(poll); editOpen.value = true
}
watch(editOpen, open => { if (!open) { mutationError.value = ''; if (needsReload.value) { detailOpen.value = false; config.value = undefined; void load() } else schedulePoll() } })
function chooseFile(event: Event) { file.value = (event.target as HTMLInputElement).files?.[0] }
function mutationKey(body: unknown) {
  const signature = JSON.stringify(body)
  if (signature !== retrySignature) { retrySignature = signature; retryKey = crypto.randomUUID() }
  return retryKey
}
async function submit() {
  if (!allowed.value || busy.value || needsReload.value) return
  mutationError.value = ''
  const reason = form.reason.trim()
  if (!reason) { mutationError.value = '请填写操作原因。'; return }
  let payload: Record<string, unknown> = { reason }
  try {
    if (action.value === 'upload') {
      if (!file.value || !file.value.name.toLowerCase().endsWith('.apk') || file.value.size < 1 || file.value.size > (config.value?.maxApkBytes ?? 0)) throw new Error('请选择大小符合限制的 APK 文件。')
      payload.file = { name: file.value.name, size: file.value.size, modified: file.value.lastModified }
    } else if (action.value === 'external' || action.value === 'source') {
      payload = { ...payload, packageName: PACKAGE, ...externalFields(form.url.trim(), form.hosts) }
      if (action.value === 'source') { if (!artifact.value?.details.sha256) throw new Error('请先刷新已核验工件。'); payload.expectedArtifactSha256 = artifact.value.details.sha256 }
    } else if (action.value === 'draft') {
      if (!selectedScope.value || !artifact.value || artifact.value.state !== 'verified' || selectedScope.value.publisherId !== artifact.value.details.publisherId) throw new Error('发布范围与工件发布者不匹配，请联系平台运维核对配置。')
      payload = { ...payload, ...selectedScope.value, artifactId: artifact.value.resourceId, importance: form.importance, notes: parseNotes(form.notes) }
    } else {
      if (!release.value) throw new Error('请重新打开版本详情。')
      payload = { ...payload, ...scopeOf(release.value), releaseId: release.value.resourceId, expectedPolicyRevision: release.value.revision }
      if (action.value === 'publish') {
        const source = usableSources.value.find(s => s.resourceId === form.sourceId)
        if (!source) throw new Error('请选择已核验且可用的下载来源。')
        if (!Number.isInteger(form.floor) || form.floor < 1 || form.floor > (artifact.value?.details.versionCode ?? 0) || (form.floor > 1) !== !!form.capabilities.length) throw new Error('兼容门槛不能高于目标版本，门槛大于 1 时必须选择受限在线能力。')
        payload = { ...payload, sourceId: source.resourceId, sourceRevision: source.revision, minSupportedVersionCode: form.floor, restrictedCapabilities: form.capabilities }
      }
    }
  } catch (e) { mutationError.value = e instanceof TypeError ? '直链格式无效，请检查 HTTPS 地址。' : e instanceof Error ? e.message : '填写内容无效。'; return }
  const idempotencyKey = mutationKey({ action: action.value, target: artifact.value?.resourceId, ...payload })
  mutationController = new AbortController(); const signal = mutationController.signal
  busy.value = true
  try {
    let result
    if (action.value === 'upload') { sending.value = true; result = await api.upload(file.value!, { idempotencyKey, reason }, { signal, onProgress: v => { progress.value = v } }); sending.value = false }
    else if (action.value === 'external') result = await api.external({ ...payload, idempotencyKey } as Parameters<typeof api.external>[0], signal)
    else if (action.value === 'source') result = await api.addSource(artifact.value!.resourceId, { ...payload, idempotencyKey } as Parameters<typeof api.addSource>[1], signal)
    else if (action.value === 'draft') result = await api.draft({ ...payload, idempotencyKey } as Parameters<typeof api.draft>[0], signal)
    else if (action.value === 'publish') result = await api.publish({ ...payload, idempotencyKey } as Parameters<typeof api.publish>[0], signal)
    else result = await api.stop({ ...payload, idempotencyKey } as Parameters<typeof api.stop>[0], signal)
    if (!allowed.value || signal.aborted) return
    const completedAction = action.value
    busy.value = false; editOpen.value = false
    notice.value = ['upload', 'external', 'source'].includes(completedAction) ? '请求已登记，后台将核验完整 APK。核验通过前不能发布。' : completedAction === 'draft' ? '版本草稿已创建，核对下载来源后可发布。' : completedAction === 'publish' ? '发布策略已生效，App 将在下一次检查时发现更新。' : '已停止新下载地址和安装许可签发。已公开的文件链接及已交接的安装操作无法追回。'
    tab.value = ['upload', 'external', 'source'].includes(completedAction) ? 'artifacts' : 'releases'
    await load()
    await inspect(tab.value === 'artifacts' ? 'artifact' : 'release', result.resourceId)
  } catch (e) {
    if (allowed.value && signal.aborted) mutationError.value = '上传已中断，请刷新台账确认服务端状态后再试。'
    if (allowed.value && !signal.aborted) { mutationError.value = updateError(e); needsReload.value = e instanceof ApiError && (e.status === 409 || e.status === 410); if (e instanceof ApiError && [401, 403].includes(e.status ?? 0)) { editOpen.value = false; detailOpen.value = false; releases.value = []; artifacts.value = []; audits.value = []; error.value = updateError(e) } }
  } finally { busy.value = false; sending.value = false }
}
onMounted(() => { void load() })
onBeforeUnmount(invalidate)
</script>

<template>
  <section v-if="allowed" class="app-updates-workspace">
    <div class="update-toolbar page-actions"><UiButton class="secondary-button" type="button" :disabled="loading || busy" @click="load()"><RefreshCw :size="16" />刷新台账</UiButton><UiButton class="primary-button" type="button" :disabled="!config?.externalEnabled || busy" @click="wizardOpen = true"><Link2 :size="16" />新建版本</UiButton></div>
    <details class="update-release-advanced"><summary>其他安装包操作</summary><div class="update-toolbar"><UiButton class="secondary-button" type="button" :disabled="!config?.externalEnabled || busy" @click="begin('external')"><Link2 :size="16" />登记外链</UiButton><UiButton class="secondary-button" type="button" :disabled="!config?.uploadEnabled || busy" @click="begin('upload')"><Upload :size="16" />上传 APK</UiButton></div></details>
    <div class="update-identity"><ShieldCheck :size="21" /><div><strong>{{ PACKAGE }}</strong><span>首正式版本码 1 · 同包名、同批准证书覆盖安装 · 后续版本码全局递增</span></div><span class="update-identity-tag">平台管理员</span></div>
    <p v-if="notice" class="update-notice" role="status">{{ notice }}</p>
    <div class="update-tabs" role="group" aria-label="版本管理台账"><UiButton type="button" :class="{ active: tab === 'releases' }" :aria-pressed="tab === 'releases'" :disabled="busy" @click="changeTab('releases')"><Boxes :size="17" />发布版本</UiButton><UiButton type="button" :class="{ active: tab === 'artifacts' }" :aria-pressed="tab === 'artifacts'" :disabled="busy" @click="changeTab('artifacts')"><FileCheck2 :size="17" />安装包与来源</UiButton><UiButton type="button" :class="{ active: tab === 'audit' }" :aria-pressed="tab === 'audit'" :disabled="busy" @click="changeTab('audit')"><History :size="17" />操作审计</UiButton></div>
    <UiStatePanel v-if="loading" state="loading" title="正在读取版本台账" />
    <UiStatePanel v-else-if="error" state="error" title="版本台账暂不可用" :message="error" @retry="load()" />
    <UiStatePanel v-else-if="!rowCount" state="empty" :title="tab === 'releases' ? '尚未发布 App 版本' : tab === 'artifacts' ? '暂无安装包' : '暂无操作记录'" :message="tab === 'releases' ? '点击新建版本，填写新版信息和已托管的 APK 直链。' : tab === 'artifacts' ? '支持自有 MinIO 和第三方公开 HTTPS 直链。' : '上传、来源登记及发布操作会留下审计记录。'" />
    <div v-else class="update-ledger">
<template v-if="tab === 'releases'"><article v-for="row in releases" :key="row.resourceId" class="update-row"><div class="update-row-mark" :class="row.state"><Boxes :size="22" /></div><div class="update-row-main"><header><span class="update-state" :class="row.state">{{ stateNames[row.state] }}</span><strong>{{ scopeLabel(row.details) }}</strong><span class="update-level">{{ level(row) }}</span></header><p class="update-id">{{ row.resourceId }}</p><p class="update-row-copy">{{ row.details.notes[0] || '暂无更新说明' }}</p><small>{{ date(row.details.publishedAt || row.details.createdAt) }} · 策略修订 {{ row.revision }}<template v-if="row.details.minSupportedVersionCode > 1"> · 兼容门槛 {{ row.details.minSupportedVersionCode }}</template></small></div><UiButton type="button" class="secondary-button" @click="inspect('release', row.resourceId)">版本详情</UiButton></article></template>
      <template v-else-if="tab === 'artifacts'"><article v-for="row in artifacts" :key="row.resourceId" class="update-row"><div class="update-row-mark" :class="row.state"><FileCheck2 :size="22" /></div><div class="update-row-main"><header><span class="update-state" :class="row.state">{{ stateNames[row.state] }}</span><strong>{{ row.details.versionName || '待解析版本' }}</strong><span class="update-version">CODE {{ row.details.versionCode ?? '—' }}</span></header><p class="update-id">{{ row.resourceId }}</p><p>{{ formatBytes(row.details.sizeBytes) }} · {{ row.details.abis.join(' / ') || '待解析设备兼容性' }}</p><small>{{ row.details.errorCode ? '核验异常：' + row.details.errorCode : date(row.details.createdAt) }}</small></div><UiButton type="button" class="secondary-button" @click="inspect('artifact', row.resourceId)">安装包详情</UiButton></article></template>
      <template v-else><article v-for="row in audits" :key="row.resourceId" class="update-audit-row"><div><strong>{{ row.details.action }}</strong><span class="update-state">{{ row.details.result }}</span><p>{{ row.details.reason }}</p><small>{{ row.details.actorId }} · {{ date(row.details.createdAt) }}</small></div><div class="update-audit-ref"><code>{{ row.details.resourceId }}</code><small>策略 {{ row.details.beforeRevision ?? '—' }} → {{ row.details.afterRevision ?? '—' }}</small></div></article></template>
    </div>
    <footer v-if="cursor && !error" class="update-pagination"><span>当前已加载 {{ rowCount }} 条</span><UiButton type="button" class="secondary-button" :loading="loadingMore" @click="load(true)">加载更多</UiButton></footer>

    <UiDialog v-model:open="wizardOpen" title="新建 App 版本" :busy="wizardBusy"><ExternalReleaseWizard v-if="wizardOpen && config" :configuration="config" @busy="wizardBusy = $event" @close="wizardOpen = false" @created="wizardCreated" @denied="wizardDenied" /></UiDialog>
    <UiDialog v-model:open="detailOpen" :title="release ? '版本详情' : '安装包详情'" :busy="busy">
      <div class="update-detail"><p v-if="detailError" class="update-error" role="alert">{{ detailError }}</p><p v-if="detailLoading" role="status">正在读取详情…</p>
        <template v-if="artifact"><header class="update-detail-header"><div><span class="eyebrow">{{ release ? scopeLabel(release.details) : 'APK / 完整字节身份' }}</span><h3>{{ artifact.details.versionName || '等待解析 APK' }} <small>CODE {{ artifact.details.versionCode ?? '—' }}</small></h3></div><span class="update-state" :class="release?.state || artifact.state">{{ stateNames[release?.state || artifact.state] }}</span></header>
          <dl class="update-facts"><div><dt>包名</dt><dd>{{ artifact.details.packageName }}</dd></div><div><dt>大小</dt><dd>{{ formatBytes(artifact.details.sizeBytes) }}</dd></div><div><dt>SDK / ABI</dt><dd>API {{ artifact.details.minSdk ?? '—' }}+ · {{ artifact.details.abis.join(' / ') || '待解析' }}</dd></div><div><dt>服务协议 / 数据 schema</dt><dd>{{ artifact.details.serverContractRange.min ?? '—' }}～{{ artifact.details.serverContractRange.max ?? '—' }} / {{ artifact.details.dataSchemaVersion ?? '—' }}</dd></div><div class="wide"><dt>SHA-256</dt><dd class="update-hash">{{ artifact.details.sha256 || '完整核验后生成' }}</dd></div><div class="wide"><dt>APK 签名证书 SHA-256</dt><dd class="update-hash">{{ artifact.details.signerSha256 || '完整核验后生成' }}</dd></div><div class="wide"><dt>工件 ID</dt><dd class="update-hash">{{ artifact.resourceId }}</dd></div></dl>
          <section v-if="artifact.details.jobs?.length" class="update-detail-section"><h4>核验作业</h4><article v-for="job in artifact.details.jobs" :key="job.jobId" class="update-job"><strong>{{ job.kind === 'external' ? '第三方完整核验' : '自有存储上传' }} · {{ stateNames[job.state] || job.state }}</strong><span v-if="job.errorCode">错误码：{{ job.errorCode }}</span><span v-if="job.resolvedArtifactId && job.resolvedArtifactId !== artifact.resourceId">重复文件已复用已有工件。<UiButton type="button" class="secondary-button" @click="inspect('artifact', job.resolvedArtifactId!)">查看已核验工件</UiButton></span><small v-if="job.targetArtifactId">本作业为同一工件新增下载来源。</small></article><p v-if="hasPending" class="update-help">此窗口每 5 秒刷新一次核验状态；上传完成不代表核验成功。</p></section>
          <section v-if="release" class="update-detail-section"><h4>发布策略 · 修订 {{ release.revision }}</h4><p>{{ level(release) }} · {{ release.details.minSupportedVersionCode > 1 ? '兼容门禁：低于 CODE ' + release.details.minSupportedVersionCode : '无兼容门禁' }}</p><p v-if="release.details.restrictedCapabilities.length" class="update-hash">受限在线能力：{{ release.details.restrictedCapabilities.join('、') }}</p><p v-if="release.details.sourceBinding" class="update-hash">选定来源：{{ release.details.sourceBinding.sourceId }} / REV {{ release.details.sourceBinding.sourceRevision }}</p><h4>更新说明</h4><ol class="update-notes"><li v-for="(note, i) in release.details.notes" :key="i">{{ note }}</li></ol><p v-if="!release.details.notes.length">暂无更新说明。</p></section>
          <section class="update-detail-section"><header class="update-section-header"><h4>下载来源</h4><UiButton v-if="artifact.state === 'verified' && config?.externalEnabled" type="button" class="secondary-button" :disabled="busy || detailLoading" @click="begin('source')">新增外链来源</UiButton></header><p v-if="!sources.length" class="update-help">暂无已登记来源；完成核验及存储后才可选择发布。</p><article v-for="source in sources" :key="source.resourceId" class="update-source"><div><strong>{{ source.details.storageMode === 'internal' ? '自有 MinIO' : '第三方 HTTPS' }}</strong><span class="update-state">{{ stateNames[source.state] }} · REV {{ source.revision }}</span></div><code>{{ source.resourceId }}</code><p>{{ source.details.allowedDownloadHosts.join('、') }} · {{ formatBytes(source.details.sizeBytes) }}</p><small>{{ source.details.availabilityState === 'available' ? '核验时可用' : '来源待检查或不可用' }} · {{ source.details.storageMode === 'external' ? 'App 直连文件源' : '固定对象版本的签名地址' }}</small></article><UiButton v-if="sourceCursor" type="button" class="secondary-button" :disabled="detailLoading" @click="moreSources">加载更多来源</UiButton></section>
          <footer class="update-detail-actions"><UiButton v-if="!release && artifact.state === 'verified'" type="button" class="primary-button" :disabled="busy || detailLoading || !!detailError" @click="begin('draft')">创建版本草稿</UiButton><UiButton v-if="release?.state === 'draft'" type="button" class="primary-button" :disabled="busy || detailLoading || !!detailError || !usableSources.length" @click="begin('publish')">配置并发布</UiButton><UiButton v-if="release?.state === 'published'" type="button" class="danger-button" :disabled="busy" @click="begin('stop')">停止分发</UiButton><RollbackControl v-if="release && ['published', 'stopped'].includes(release.state) && !detailLoading && !detailError" :key="release.resourceId" :release="release" @applied="rollbackChanged" /><UiButton type="button" class="secondary-button" :disabled="busy" @click="detailOpen = false">关闭详情</UiButton></footer>
        </template>
      </div>
    </UiDialog>

    <UiDialog v-model:open="editOpen" :title="titles[action]" :busy="busy"><form class="update-form" @submit.prevent="submit"><fieldset :disabled="busy || needsReload">
      <template v-if="action === 'upload'"><label>APK 安装包<input type="file" accept=".apk,application/vnd.android.package-archive" required @change="chooseFile" /></label><p class="update-help">最多 {{ formatBytes(config?.maxApkBytes) }}。服务器将读取完整文件，核验版本、大小、摘要及 APK 签名证书。</p></template>
      <template v-if="action === 'external' || action === 'source'"><p class="update-help">公开 HTTPS 文件直链。核验完成后 App 直接从文件源下载。{{ action === 'source' ? '仅允许与当前工件完全相同的字节；替换包需要新的版本码。' : '' }}</p><label>APK 直链<input v-model="form.url" type="url" required maxlength="4096" placeholder="https://files.example.com/app.apk" autocomplete="off" /></label><label>允许的下载及重定向域名<textarea v-model="form.hosts" required rows="2" placeholder="files.example.com，每行或逗号分隔" maxlength="4000"></textarea></label></template>
      <template v-if="action === 'draft'"><label>发布范围<select v-model="form.scope" required><option v-for="(scope, i) in config?.scopes" :key="i" :value="i">{{ scopeLabel(scope) }} · {{ scope.publisherId }}</option></select></label><label>提醒级别<select v-model="form.importance"><option value="normal">普通更新 · 可稍后</option><option value="important">重要推荐 · 明显提示</option></select></label><label>更新说明<textarea v-model="form.notes" rows="6" maxlength="60029" placeholder="每行一条，最多 30 条，每条最多 2000 字"></textarea></label><p class="update-help">更新说明按纯文本显示。创建草稿后，可在发布时配置兼容门禁。</p></template>
      <template v-if="action === 'publish'"><p class="update-help">将按详情中的策略修订 {{ release?.revision }} 发布；如其他管理员已修改，服务会拒绝覆盖。</p><label>下载来源<select v-model="form.sourceId" required><option v-for="source in usableSources" :key="source.resourceId" :value="source.resourceId">{{ source.details.storageMode === 'internal' ? '自有 MinIO' : '第三方 HTTPS' }} · REV {{ source.revision }} · {{ source.details.allowedDownloadHosts.join('、') }}</option></select></label><label>最低支持版本码<input v-model.number="form.floor" type="number" min="1" :max="artifact?.details.versionCode || 1" step="1" required /></label><p class="update-help">1 表示无门禁。提高门槛时，仅限制已声明的不兼容在线能力，保留本地数据、诊断、退出及升级入口；始终由用户点击安装。</p><div v-if="config?.gateCapabilities.length" class="update-capabilities"><span>门禁限制的在线能力</span><label v-for="capability in config.gateCapabilities" :key="capability"><input v-model="form.capabilities" type="checkbox" :value="capability" />{{ capability }}</label></div><p v-else class="update-help">服务未开放可限制能力，当前只能发布无门禁更新。</p></template>
      <template v-if="action === 'stop'"><div class="update-stop-note"><strong>停止签发新的下载地址与安装许可</strong><p>此操作不会卸载 App 或清除历史数据。公开文件链接和已经交接到系统安装器的操作无法追回。已安装设备恢复需要更高版本码的恢复包。</p></div><p>当前策略修订：{{ release?.revision }} · {{ release && scopeLabel(release.details) }}</p></template>
      <label>操作原因<textarea v-model="form.reason" rows="2" required maxlength="1000" placeholder="请说明本次操作原因，记录到操作审计"></textarea></label>
    </fieldset><div v-if="busy && action === 'upload'" class="update-transfer" role="status"><progress :value="progress ?? undefined" max="100"></progress><span>{{ progress === 100 ? '文件已发送，等待服务端登记…' : progress === null ? '正在发送 APK…' : '正在发送 ' + Math.floor(progress) + '%' }}</span></div><p v-else-if="busy" role="status">正在提交，请稍候…</p><p v-if="mutationError" class="update-error" role="alert">{{ mutationError }}</p><footer class="update-detail-actions"><UiButton type="button" class="secondary-button" :disabled="busy" @click="editOpen = false">{{ needsReload ? '关闭并重新确认' : '取消' }}</UiButton><UiButton v-if="sending" type="button" class="secondary-button" @click="mutationController.abort()">中断上传</UiButton><UiButton type="submit" :class="action === 'stop' ? 'danger-button' : 'primary-button'" :disabled="busy || needsReload">{{ action === 'publish' ? '确认发布' : action === 'stop' ? '确认停止分发' : action === 'draft' ? '创建草稿' : '提交核验' }}</UiButton></footer></form></UiDialog>
  </section>
  <UiStatePanel v-else state="empty" title="需要平台管理员权限" message="当前账号不能管理 App 安装包和发布策略。" />
</template>
