<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import UiButton from '../../components/ui/UiButton.vue'
import { ApiError } from '../../api/errors'
import { appUpdatesApi as api, externalFields, formatBytes, PACKAGE, parseNotes, updateError, type Artifact, type Configuration } from './api'

const props = defineProps<{ configuration: Configuration }>()
const emit = defineEmits<{ created: [id: string]; close: []; denied: [message: string]; busy: [value: boolean] }>()
const form = reactive({ versionName: '', versionCode: '', url: '', hosts: '', scope: props.configuration.scopes.length === 1 ? 0 : -1, importance: 'normal' as 'normal' | 'important', notes: '', reason: '' })
const busy = ref(false), polling = ref(false), pending = ref(false), confirmed = ref(false), error = ref(''), registeredId = ref(''), artifact = ref<Artifact>(), failed = ref(false), needsReload = ref(false)
watch(busy, value => emit('busy', value), { flush: 'sync' })
const scope = computed(() => props.configuration.scopes[form.scope])
const mismatch = computed(() => artifact.value && artifact.value.state === 'verified'
  ? artifact.value.details.versionCode !== Number(form.versionCode) || artifact.value.details.versionName !== form.versionName.trim()
    ? `填写的版本与 APK 不一致。实际版本为 ${artifact.value.details.versionName}，版本码 ${artifact.value.details.versionCode}。请核对后修改版本信息。` : '' : '')
const ready = computed(() => confirmed.value && artifact.value?.state === 'verified' && !polling.value && !pending.value && !failed.value && !mismatch.value)
const controller = new AbortController()
let active = true, registeredVerified = false, timer: ReturnType<typeof setTimeout> | undefined
const keys = new Map<string, string>()
function key(body: unknown) {
  const signature = JSON.stringify(body)
  if (!keys.has(signature)) keys.set(signature, crypto.randomUUID())
  return keys.get(signature)!
}
function handleError(e: unknown) {
  error.value = updateError(e)
  if (e instanceof ApiError && [401, 403].includes(e.status ?? 0)) { controller.abort(); clearTimeout(timer); emit('denied', error.value) }
  if (e instanceof ApiError && [409, 410].includes(e.status ?? 0)) needsReload.value = true
}
function validate() {
  if (!form.versionName.trim() || !/^[1-9]\d*$/.test(form.versionCode) || !Number.isSafeInteger(Number(form.versionCode)) || Number(form.versionCode) > 2147483647) throw new Error('请填写版本名称及 1～2147483647 的整数版本码。')
  if (!scope.value) throw new Error('请选择发布范围。')
  if (!form.reason.trim()) throw new Error('请填写操作原因。')
  parseNotes(form.notes)
}
async function verify() {
  if (busy.value || registeredId.value || needsReload.value) return
  error.value = ''
  let body
  try {
    validate()
    const url = form.url.trim()
    const host = new URL(url).hostname
    body = { packageName: PACKAGE, ...externalFields(url, host + '\n' + form.hosts), reason: form.reason.trim() }
  } catch (e) { error.value = e instanceof TypeError ? '请填写有效的公开 HTTPS APK 直链。' : (e as Error).message; return }
  busy.value = true
  try {
    const result = await api.external({ ...body, idempotencyKey: key(body) }, controller.signal)
    if (!active) return
    registeredId.value = result.resourceId
    registeredVerified = result.state === 'verified'
    await check()
  } catch (e) { if (active) handleError(e) }
  finally { if (active) busy.value = false }
}
async function check() {
  if (!active || polling.value || !registeredId.value || needsReload.value) return
  clearTimeout(timer); polling.value = true; confirmed.value = false; error.value = ''
  try {
    let value = await api.artifact(registeredId.value, controller.signal)
    // A duplicate registration keeps its original placeholder and resolves to
    // the already verified artifact only when its own external job succeeds.
    const job = registeredVerified ? undefined : value.details.jobs?.find(j => j.kind === 'external' && !j.targetArtifactId)
    if (job?.state === 'succeeded' && job.resolvedArtifactId && job.resolvedArtifactId !== value.resourceId) value = await api.artifact(job.resolvedArtifactId, controller.signal)
    if (!active) return
    pending.value = !!job && ['queued', 'receiving', 'processing', 'retryable'].includes(job.state)
    failed.value = job?.state === 'failed' || (!pending.value && value.state === 'failed')
    artifact.value = value
    confirmed.value = !failed.value && !pending.value && value.state === 'verified'
    if (failed.value) error.value = 'APK 核验失败。请检查直链、包身份、递增版本码及批准签名，修正后重新登记。'
    else if (pending.value || ['pending', 'verifying'].includes(value.state)) timer = setTimeout(() => { void check() }, 5000)
  } catch (e) { if (active) handleError(e) }
  finally { if (active) polling.value = false }
}
async function createDraft() {
  if (busy.value || !ready.value || needsReload.value) return
  error.value = ''
  let body
  try {
    validate()
    if (scope.value!.publisherId !== artifact.value!.details.publisherId) throw new Error('发布范围与 APK 发布者不匹配，请联系运维核对配置。')
    body = { ...scope.value!, artifactId: artifact.value!.resourceId, importance: form.importance, notes: parseNotes(form.notes), reason: form.reason.trim() }
  } catch (e) { error.value = (e as Error).message; return }
  busy.value = true
  try {
    const result = await api.draft({ ...body, idempotencyKey: key(body) }, controller.signal)
    if (active) emit('created', result.resourceId)
  } catch (e) { if (active) handleError(e) }
  finally { if (active) busy.value = false }
}
onBeforeUnmount(() => { active = false; controller.abort(); clearTimeout(timer); keys.clear() })
</script>

<template>
  <form class="update-form update-release-wizard" @submit.prevent="registeredId ? createDraft() : verify()">
    <ol class="update-release-steps" aria-label="新建版本步骤"><li class="active">1 填写版本与直链</li><li :class="{ active: registeredId }">2 核验 APK</li><li :class="{ active: ready }">3 确认草稿</li></ol>
    <p class="update-help">请先自行打包并上传至 MinIO 或第三方托管空间，再填写公开 HTTPS 文件直链。App 下载时直接连接该地址。</p>
    <fieldset :disabled="busy || needsReload">
      <div class="update-version-fields"><label>版本名称<input v-model="form.versionName" required maxlength="200" placeholder="例如 1.1.0" /></label><label>版本码（versionCode）<input v-model="form.versionCode" type="number" min="1" max="2147483647" step="1" required placeholder="全局递增的整数" /></label></div>
      <label>新版 APK 下载地址<input v-model="form.url" type="url" required maxlength="4096" :readonly="!!registeredId" placeholder="https://files.example.com/app-2.apk" autocomplete="off" /></label>
      <details v-if="!registeredId" class="update-release-advanced"><summary>高级设置 · 重定向域名</summary><label>额外允许的重定向域名<textarea v-model="form.hosts" rows="2" maxlength="3500" placeholder="原始下载域名自动添加，仅在跨域跳转时补充"></textarea></label></details>
      <label v-if="configuration.scopes.length > 1">发布范围<select v-model="form.scope" required><option :value="-1" disabled>请选择发布范围</option><option v-for="(item, i) in configuration.scopes" :key="i" :value="i">{{ item.deploymentId }} / {{ item.channel }} · {{ item.publisherId }}</option></select></label>
      <p v-else class="update-help">发布范围：{{ scope?.deploymentId }} / {{ scope?.channel }}</p>
      <label>提醒级别<select v-model="form.importance"><option value="normal">普通更新 · 可稍后</option><option value="important">重要推荐 · 明显提示</option></select></label>
      <label>更新说明<textarea v-model="form.notes" rows="4" maxlength="60029" placeholder="每行一条，最多 30 条，每条最多 2000 字"></textarea></label>
      <label>操作原因<textarea v-model="form.reason" rows="2" required maxlength="1000" placeholder="记录到版本操作审计"></textarea></label>
    </fieldset>
    <section v-if="registeredId" class="update-release-result" aria-live="polite">
      <h4>{{ ready ? 'APK 核验通过，请确认版本草稿' : failed ? 'APK 核验失败' : artifact?.state === 'verified' && !polling ? '请核对版本信息' : '已登记，等待完整 APK 核验' }}</h4>
      <p class="update-help">服务器会完整读取一次 APK，核验大小、SHA-256、包名、真实版本和批准签名。关闭窗口不会取消已登记的服务端作业，可在安装包台账查看。</p>
      <dl v-if="artifact?.state === 'verified'" class="update-facts"><div><dt>实际版本</dt><dd>{{ artifact.details.versionName }} / CODE {{ artifact.details.versionCode }}</dd></div><div><dt>APK 大小</dt><dd>{{ formatBytes(artifact.details.sizeBytes) }}</dd></div><div class="wide"><dt>SHA-256</dt><dd class="update-hash">{{ artifact.details.sha256 }}</dd></div><div class="wide"><dt>签名证书 SHA-256</dt><dd class="update-hash">{{ artifact.details.signerSha256 }}</dd></div></dl>
      <p v-if="mismatch" class="update-error" role="alert">{{ mismatch }}</p>
    </section>
    <p v-if="error" class="update-error" role="alert">{{ error }}</p>
    <p class="update-help">核验通过后只创建草稿；核对下载来源并确认发布后，App 才会发现更新。兼容门禁在发布时设置。</p>
    <footer class="update-detail-actions"><UiButton type="button" class="secondary-button" :disabled="busy" @click="emit('close')">关闭</UiButton><UiButton v-if="registeredId && !ready && !failed" type="button" class="secondary-button" :disabled="polling || busy || needsReload" @click="check">刷新核验状态</UiButton><UiButton type="submit" class="primary-button" :disabled="busy || needsReload || (!!registeredId && !ready)">{{ busy ? '正在提交…' : registeredId ? '创建版本草稿' : '核验 APK' }}</UiButton></footer>
  </form>
</template>
