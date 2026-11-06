<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import UiButton from '../../components/ui/UiButton.vue'
import UiDialog from '../../components/ui/UiDialog.vue'
import { appUpdatesApi as api, updateError, type Release, type RollbackOperation, type RollbackPlan, type RollbackPreview } from './api'
import { ApiError } from '../../api/errors'

const props = defineProps<{ release: Release }>()
const emit = defineEmits<{ applied: [] }>()
const open = ref(false), busy = ref(false), error = ref(''), conflict = ref(false)
const choices = ref<Release[]>([]), affected = ref<string[]>([]), stable = ref(''), recovery = ref(''), reason = ref('')
const preview = ref<RollbackPreview>(), result = ref<RollbackOperation>(), queryId = ref('')
const applied = ref(false)
let controller = new AbortController(), generation = 0, retryBody: (RollbackPlan & { reason: string; idempotencyKey: string; previewFingerprint: string }) | undefined
const history = computed(() => (props.release.details as unknown as { rollbackOperationIds?: string[] }).rollbackOperationIds ?? [])
const blockers: Record<string, string> = { affected_release_not_active: '问题版本未发布，或不属于待恢复操作', stable_release_not_active: '稳定版本必须是已发布的普通版本', stable_version_not_lower: '稳定版本码必须低于全部问题版本', uncovered_newer_release: '还有更高的活跃版本，需一并纳入问题版本', recovery_not_draft: '恢复包必须是尚未发布的普通草稿', recovery_version_not_higher: '恢复包版本码必须高于全部问题版本', recovery_data_incompatible: '恢复包不能兼容问题版的数据 schema', recovery_evidence_missing: '缺少绑定这些 APK 摘要的可信恢复验证证据', build_compatibility_missing: '缺少可信构建的服务协议或数据兼容证据', recovery_device_incompatible: '已联系的问题版设备不能安装此恢复包，或需要重新检查' }
const stages: Record<string, string> = { not_discovered: '尚未发现恢复包', discovered: '已发现', downloading: '下载中', downloaded: '已下载', verified: '已校验', waiting_install: '等待用户安装', installer_opened: '已打开安装器', started_pending_health: '新包启动待健康', healthy: '已报告健康', failed: '失败', canceled: '已取消', superseded: '已被新尝试替代' }
watch([affected, stable, recovery, reason], () => { preview.value = undefined; retryBody = undefined }, { deep: true })
watch(open, value => { if (!value) { generation++; controller.abort(); if (applied.value || conflict.value) emit('applied') } })
onBeforeUnmount(() => { generation++; controller.abort() })
function plan(): RollbackPlan {
  const d = props.release.details
  return { contractVersion: 'app-update/v1', packageName: d.packageName, publisherId: d.publisherId, deploymentId: d.deploymentId, channel: d.channel, expectedPolicyRevision: props.release.revision, affectedReleaseIds: [...affected.value].sort(), stableReleaseId: stable.value, recoveryReleaseId: recovery.value || null }
}
async function run(work: (signal: AbortSignal) => Promise<void>) {
  if (busy.value) return
  controller.abort(); controller = new AbortController(); const stamp = ++generation
  busy.value = true; error.value = ''
  try { await work(controller.signal) }
  catch (e) { if (stamp === generation) { error.value = updateError(e); conflict.value = e instanceof ApiError && [409, 410].includes(e.status ?? 0) } }
  finally { if (stamp === generation) busy.value = false }
}
async function begin() {
  open.value = true; busy.value = false; applied.value = false; conflict.value = false; preview.value = undefined; result.value = undefined; choices.value = []
  affected.value = [props.release.resourceId]; stable.value = ''; recovery.value = ''; reason.value = ''; retryBody = undefined
  await run(async signal => {
    let cursor: string | null = null
    const rows: Release[] = []
    do {
      const page = await api.list('releases', cursor, signal)
      rows.push(...page.items as Release[]); cursor = page.nextCursor
      if (rows.length > 3000) throw new ApiError({ kind: 'invalid-response', message: '请缩小版本范围' })
    } while (cursor)
    if (!signal.aborted) choices.value = rows.filter(r => r.details.policyId === props.release.details.policyId)
  })
}
async function inspect() {
  if (!stable.value || !affected.value.length) { error.value = '请选择问题版本和稳定版本。'; return }
  await run(async signal => { const p = await api.rollbackPreview(plan(), signal); if (!signal.aborted) preview.value = p })
}
async function submit() {
  if (!preview.value?.ready || !reason.value.trim() || conflict.value) return
  if (Date.parse(preview.value.expiresAt) <= Date.now()) { preview.value = undefined; error.value = '预览已过期，请重新预览。'; return }
  retryBody ??= { ...plan(), reason: reason.value.trim(), previewFingerprint: preview.value.previewFingerprint, idempotencyKey: crypto.randomUUID() }
  await run(async signal => {
    const value = await api.rollback(retryBody!, signal)
    if (!signal.aborted) { result.value = value; queryId.value = value.operationId; preview.value = undefined; applied.value = true }
  })
}
async function refresh(id = queryId.value) {
  if (!id.trim()) return
  await run(async signal => { const value = await api.rollbackOperation(id.trim(), signal); if (!signal.aborted) { result.value = value; queryId.value = value.operationId } })
}
</script>

<template>
  <UiButton type="button" class="danger-button" @click="begin">快速回退与恢复</UiButton>
  <UiDialog v-model:open="open" title="快速回退与恢复" :busy="busy">
    <div class="update-form">
      <div class="update-stop-note"><strong>先预览影响，再原子提交策略</strong><p>停止问题版本并恢复稳定推荐。已安装问题版需要更高版本码的恢复包，始终由用户点击安装，不卸载或清除数据。</p></div>
      <template v-if="!result">
        <fieldset :disabled="busy || conflict">
          <div class="update-capabilities"><span>问题版本（可多选）</span><label v-for="r in choices.filter(v => ['published', 'stopped'].includes(v.state))" :key="r.resourceId"><input v-model="affected" type="checkbox" :value="r.resourceId" />{{ r.resourceId }} · {{ r.state === 'stopped' ? '已停止' : '已发布' }}</label></div>
          <label>恢复推荐的稳定版本<select v-model="stable" required><option value="">请选择已发布的稳定版本</option><option v-for="r in choices.filter(v => v.state === 'published' && v.details.releasePurpose === 'normal' && !affected.includes(v.resourceId))" :key="r.resourceId" :value="r.resourceId">{{ r.resourceId }} · {{ r.details.notes[0] || '无说明' }}</option></select></label>
          <label>更高版本码的恢复包<select v-model="recovery"><option value="">尚无恢复包 · 先停止分发</option><option v-for="r in choices.filter(v => v.state === 'draft' && !affected.includes(v.resourceId))" :key="r.resourceId" :value="r.resourceId">{{ r.resourceId }} · {{ r.details.notes[0] || '无说明' }}</option></select></label>
          <p class="update-help">恢复包使用已核验且可用的最新来源修订；具体来源固定在预览指纹中。兼容验证证据由受控 CI 配置提供。</p>
          <label>回退原因<textarea v-model="reason" required maxlength="1000" rows="2"></textarea></label>
        </fieldset>
        <UiButton type="button" class="secondary-button" :disabled="busy || conflict || !choices.length" @click="inspect">预览影响</UiButton>
        <section v-if="preview" class="update-detail-section" aria-label="回退影响预览"><h4>{{ preview.ready ? '预览通过' : '存在阻塞，不能提交' }}</h4><p>已联系 {{ preview.contactedDevices }} 台；当前问题版 {{ preview.affectedDevices }} 台。未联系设备数量未知。</p><p>设备恢复：{{ preview.recoveryState === 'ready' ? '恢复包已就绪' : '待恢复包就绪' }}；兼容门禁将清除。</p><p class="update-help">有效期至 {{ new Date(preview.expiresAt).toLocaleString('zh-CN') }}</p><ul v-if="preview.blockers.length"><li v-for="code in preview.blockers" :key="code">{{ blockers[code] || code }}</li></ul></section>
      </template>
      <section v-else class="update-detail-section" aria-label="回退操作结果"><h4>策略阶段：{{ result.status === 'applied' ? '已生效' : result.status === 'failed' ? '失败' : '已受理' }}</h4><p>有效策略修订 {{ result.effectivePolicyRevision ?? '—' }}</p><p>设备恢复阶段：{{ result.recoveryState === 'ready' ? '恢复包已就绪，等待设备发现及用户安装' : '待恢复包就绪' }}</p><p class="update-hash">操作 ID：{{ result.operationId }}</p><dl class="update-facts"><div v-for="(count, stage) in result.deviceCounts" :key="stage"><dt>{{ stages[stage] || stage }}</dt><dd>{{ count }}</dd></div></dl><p class="update-help">仅统计已联系且与本次问题版或恢复尝试关联的设备。已打开安装器不代表安装成功，健康结果为客户端回执。</p><p v-if="result.errorCode" class="update-error">{{ result.errorCode }}</p><UiButton type="button" class="secondary-button" :disabled="busy" @click="refresh()">刷新恢复进度</UiButton></section>
      <details><summary>查询历史恢复操作</summary><div class="update-form"><UiButton v-for="id in history" :key="id" type="button" class="secondary-button update-hash" :disabled="busy" @click="refresh(id)">{{ id }}</UiButton><label>操作 ID<input v-model="queryId" maxlength="128" /></label><UiButton type="button" class="secondary-button" :disabled="busy || !queryId.trim()" @click="refresh()">查询操作</UiButton></div></details>
      <p v-if="busy" role="status">正在读取或提交，请稍候…</p><p v-if="error" class="update-error" role="alert">{{ error }}</p>
      <footer class="update-detail-actions"><UiButton type="button" class="secondary-button" :disabled="busy" @click="open = false">关闭</UiButton><UiButton v-if="!result" type="button" class="danger-button" :disabled="busy || conflict || !preview?.ready || !reason.trim()" @click="submit">确认执行回退</UiButton></footer>
    </div>
  </UiDialog>
</template>
