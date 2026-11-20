<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, useId } from 'vue'
import UiDialog from '../../components/ui/UiDialog.vue'
import UiConfirmDialog from '../../components/ui/UiConfirmDialog.vue'
import UiStatePanel from '../../components/ui/UiStatePanel.vue'
import { isApiError } from '../../api/errors'
import { errorText, modelsApi } from './api'
import type { ModelAsset, ParameterProfile, Platform } from './types'
import { requiresReload } from '../projects/writeRecovery'
import { scenesApi, type SceneProfileBinding } from '../scenes/api'
import ParameterReadOnly from './ParameterReadOnly.vue'
import './parameter-editor.css'
const needsReload = ref(false)
const props = defineProps<{ model: ModelAsset; readOnly?: boolean; projectMode?: boolean; initialPlatform?: Platform; sceneBinding?:SceneProfileBinding }>()
const emit = defineEmits<{ close: [] }>()
const platform = ref<Platform>(props.initialPlatform ?? 'android'), profile = ref<ParameterProfile | null>(null)
const sceneBinding = computed(() => props.sceneBinding)
const readOnly = computed(() => !!(props.readOnly || props.projectMode || props.sceneBinding))
const publishOpen = ref(false), savedContent = ref('')
const content = (value: ParameterProfile) => JSON.stringify([value.detection, value.alertRules])
const dirty = computed(() => !!profile.value && content(profile.value) !== savedContent.value)
const loading = ref(true), busy = ref(false), message = ref(''), failed = ref(false), loadError = ref(''), query = ref(''), expandAll = ref(false), resetOpen = ref(false)
const unpublished = ref(false)
let controller: AbortController | undefined, disposed = false
const rules = computed(() => profile.value?.alertRules.filter(rule => `${rule.rawLabel} ${rule.displayName} ${rule.eventCode}`.toLowerCase().includes(query.value.toLowerCase().trim())) ?? [])
const searchId = useId()
const enabledRuleCount = computed(() => profile.value?.alertRules.filter(rule => rule.enabled).length ?? 0)
const profileSource = computed(() => ({ default: '默认草稿', platform: '平台发布参数', custom: '平台草稿' } as Record<string, string>)[profile.value?.source ?? ''] || profile.value?.source)
const draftStatus = computed(() => needsReload.value ? '需要重新核验' : dirty.value ? '有未保存编辑' : profile.value?.hasUnpublishedChanges ? '草稿待发布' : profile.value?.publishedRevision == null ? '尚未发布' : '与发布版一致')
const draftHint = computed(() => needsReload.value ? '上次操作结果需要核验，请重新读取档案后再保存或发布。' : dirty.value ? '当前修改尚未保存，保存草稿后才能发布。' : profile.value?.hasUnpublishedChanges ? '草稿尚未发布，发布后各项目的新运行才会使用此修订。' : profile.value?.publishedRevision == null ? '当前目标端尚无已发布参数，请核对草稿后发布。' : '当前草稿与发布版一致；修改并保存后，可发布新的参数修订。')
const severityLabel = (severity: string) => ({ MINOR: '一般', MAJOR: '重要', CRITICAL: '严重' } as Record<string, string>)[severity] || severity
async function load(target = platform.value) {
  if (busy.value) return
  controller?.abort(); controller = new AbortController(); const signal = controller.signal
  platform.value = target; loading.value = true; profile.value = null; message.value = ''; loadError.value = ''; unpublished.value = false
  try { const value = await (sceneBinding.value ? scenesApi.profile(sceneBinding.value,signal) : modelsApi.parameters(props.model.modelId, target, signal, props.model.version)); if (!disposed && !signal.aborted) { profile.value = value; savedContent.value = content(value); needsReload.value = false } }
  catch (e) { if (!disposed && !signal.aborted) { unpublished.value = isApiError(e) && e.code === 'platform_parameters_unpublished'; loadError.value = errorText(e) } }
  finally { if (!signal.aborted) loading.value = false }
}
function validate() {
  const current = profile.value
  if (!current) throw new Error('请先读取参数档案')
  for (const rule of current.alertRules) {
    rule.displayName = rule.displayName.trim(); rule.eventCode = rule.eventCode.trim().toUpperCase()
    if (!rule.displayName || !/^[A-Z][A-Z0-9_]{1,63}$/.test(rule.eventCode)) throw new Error('请填写业务名称和 2–64 位大写事件编码')
    if (rule.enabled && (rule.image.minimumConfidence < current.detection.confidenceThreshold || rule.camera.minimumConfidence < current.detection.confidenceThreshold)) throw new Error('类别告警置信度不能低于识别置信度')
  }
  return current
}
async function save() {
  if (busy.value || needsReload.value || readOnly.value) return
  let value: ParameterProfile
  try { value = validate() } catch (e) { message.value = errorText(e); failed.value = true; return }
  busy.value = true
  try {
    const result = await modelsApi.saveParameters(props.model.modelId, platform.value, value, props.model.version)
    if (!disposed) { profile.value = result; savedContent.value = content(result); message.value = '草稿已保存。发布后，各项目的新运行才会使用此修订。'; failed.value = false }
  }
  catch (e) { if (!disposed) { needsReload.value = requiresReload(e); message.value = `${errorText(e)}。请重新读取档案核验后再编辑。`; failed.value = true } }
  finally { busy.value = false }
}
async function reset() {
  if (busy.value || needsReload.value || readOnly.value || !profile.value) return
  busy.value = true
  try {
    const value = await modelsApi.resetParameters(props.model.modelId, platform.value, profile.value.revision, props.model.version)
    if (!disposed) { profile.value = value; savedContent.value = content(value); resetOpen.value = false; message.value = '草稿已恢复默认值。当前发布版保持不变，请核对后发布。'; failed.value = false }
  }
  catch (e) { if (!disposed) { needsReload.value = requiresReload(e); message.value = errorText(e) + ' 请重新读取档案核验后再操作。'; failed.value = true } }
  finally { busy.value = false }
}
async function publish() {
  if (busy.value || needsReload.value || readOnly.value || dirty.value || !profile.value) return
  busy.value = true
  try {
    const value = await modelsApi.publishParameters(props.model.modelId, platform.value, profile.value, props.model.version)
    if (!disposed) {
      profile.value.publishedRevision = value.revision; profile.value.hasUnpublishedChanges = false
      publishOpen.value = false; message.value = '参数已发布。各项目的新运行使用此修订，正在运行的任务保留启动时参数。'; failed.value = false
    }
  } catch (e) { if (!disposed) { needsReload.value = requiresReload(e); message.value = errorText(e); failed.value = true } }
  finally { busy.value = false }
}
onMounted(() => load())
onBeforeUnmount(() => { disposed = true; controller?.abort() })
</script>
<template>
  <UiDialog :open="true" :title="readOnly ? '查看平台参数' : '模型参数档案'" :busy="busy" @update:open="emit('close')">
    <div class="parameter-content" :class="{'is-readonly':readOnly,'is-editor':!readOnly}">
      <header class="parameter-identity"><div><h3>{{ model.name }}</h3><code>{{ model.modelId }}</code></div><UiTag tone="info">{{ readOnly ? '只读' : '平台维护' }}</UiTag></header>
      <UiTabs class="model-tabs" :model-value="platform" :items="(readOnly || props.sceneBinding) && props.initialPlatform ? [{id:props.initialPlatform,label:props.initialPlatform === 'server' ? '服务端参数' : 'Android 参数'}] : [{id:'android',label:'Android 参数'},{id:'server',label:'服务端参数'}]" :disabled="busy" @update:model-value="value => load(value as Platform)" />
      <p :class="readOnly ? 'parameter-readonly-notice' : 'parameter-editor-notice'">{{ readOnly ? '模型文件和运行参数由平台统一维护；项目负责使用模型和管理场景方案。' : '分别维护 Android 与服务端参数。保存草稿后需明确发布；发布影响各项目的新运行。切换目标端或重新读取会放弃未保存编辑。' }}</p>
      <UiStatePanel v-if="loading" state="loading" />
      <div v-else-if="unpublished">
        <UiStatePanel state="empty" title="平台参数尚未发布" :message="`模型版本 ${model.version} 的${platform === 'android' ? 'Android' : '服务端'}参数尚未发布。请联系平台管理员在平台模型资产中核对并发布该版本、该目标端的参数。模型文件已发布不代表运行参数已发布；项目只读使用发布版。`" />
        <div class="model-actions"><UiButton type="button" class="secondary-button" @click="load()">重新读取档案</UiButton></div>
      </div>
      <UiStatePanel v-else-if="loadError" state="error" :message="loadError" @retry="load()" />
      <template v-else-if="profile && readOnly">
        <p v-if="profile.modelVersion !== model.version" class="operation-feedback" role="alert">所选模型版本为 {{ model.version }}，返回的参数版本为 {{ profile.modelVersion }}；请重新读取档案核验。</p>
        <ParameterReadOnly :profile="profile"/>
        <footer class="parameter-readonly-actions"><p>如需调整参数，请联系平台管理员。</p><UiButton type="button" class="secondary-button" :disabled="busy" @click="load()">重新读取档案</UiButton></footer>
      </template>
      <form v-else-if="profile" class="model-form parameter-editor-form" :aria-busy="busy" @submit.prevent="save">
        <dl class="parameter-editor-meta" aria-label="草稿与发布信息">
          <div><dt>模型版本</dt><dd>{{ profile.modelVersion }}</dd></div>
          <div><dt>草稿修订</dt><dd>r{{ profile.revision }}</dd></div>
          <div><dt>已发布修订</dt><dd>{{ profile.publishedRevision == null ? '尚未发布' : 'r' + profile.publishedRevision }}</dd></div>
          <div><dt>参数来源</dt><dd>{{ profileSource }}</dd></div>
        </dl>
        <div class="parameter-editor-state" role="status">
          <UiTag :tone="needsReload ? 'danger' : dirty || profile.hasUnpublishedChanges ? 'warning' : profile.publishedRevision == null ? 'info' : 'success'">{{ draftStatus }}</UiTag>
          <p>{{ draftHint }}</p>
        </div>
        <p v-if="profile.modelVersion !== model.version" class="operation-feedback">所选资产是 {{ model.version }}，当前参数接口对应 {{ profile.modelVersion }}；以下修改作用于该当前档案。</p>
        <fieldset class="parameter-editor-section" :disabled="busy">
          <legend>识别基础参数</legend>
          <div class="parameter-editor-basics">
            <div><label>识别置信度<UiInput :disabled="busy||readOnly" v-model.number="profile.detection.confidenceThreshold" type="number" min="0.01" max="0.99" step="0.01" required /></label><p>低于该数值的检测结果将被过滤。</p></div>
            <div><label>IoU 阈值<UiInput :disabled="busy||readOnly" v-model.number="profile.detection.iouThreshold" type="number" min="0.1" max="0.9" step="0.01" required /></label><p>检测框重叠过滤阈值。</p></div>
            <div><label>最大检测结果<UiInput :disabled="busy||readOnly" v-model.number="profile.detection.maxDetections" type="number" min="1" max="300" step="1" required /></label><p>单次最多保留的检测结果数量。</p></div>
          </div>
        </fieldset>
        <fieldset class="parameter-editor-section" :disabled="busy">
          <legend>类别与告警规则<span>共 {{ profile.alertRules.length }} 类 · 已启用 {{ enabledRuleCount }} 类</span></legend>
          <div v-if="profile.alertRules.length" class="parameter-editor-toolbar"><label :for="searchId">搜索类别<UiInput :id="searchId" :disabled="busy" v-model="query" placeholder="类别、名称或编码" /></label><UiButton class="secondary-button" type="button" :disabled="!rules.length" @click="expandAll = !expandAll">{{ expandAll ? '全部收起' : '全部展开' }}</UiButton></div>
          <p class="parameter-editor-hint">每类只有一个识别与告警开关。关闭后不显示检测框、不计数、不跟踪，也不产生该类告警；启用后仍需满足下方条件。修改参数无需重新下载模型。</p>
          <p v-if="!profile.alertRules.length" class="parameter-editor-empty" role="status">当前参数档案未配置类别规则。</p>
          <p v-else-if="!rules.length" class="parameter-editor-empty" role="status">未找到匹配的类别，请尝试其他名称或编码。</p>
          <UiCollapse v-for="rule in rules" :key="rule.rawLabel" class="parameter-editor-rule" :open="expandAll">
            <template #title><div class="parameter-editor-rule-title"><span class="parameter-editor-rule-name"><strong>{{ rule.displayName }}</strong><code>{{ rule.rawLabel }}</code></span><span class="parameter-editor-rule-badges"><UiTag :tone="rule.enabled ? 'success' : 'info'">{{ rule.enabled ? '识别与告警已启用' : '识别与告警已关闭' }}</UiTag><UiTag :tone="rule.severity === 'CRITICAL' ? 'danger' : rule.severity === 'MAJOR' ? 'warning' : 'info'">{{ severityLabel(rule.severity) }}告警</UiTag></span></div></template>
            <div class="parameter-editor-rule-toggle"><label class="model-check"><UiInput :disabled="busy||readOnly" v-model="rule.enabled" type="checkbox" />启用识别与告警</label><p>关闭时保留以下参数，便于后续重新启用。</p></div>
            <div class="parameter-editor-rule-fields">
              <label>业务名称<UiInput :disabled="busy||readOnly" v-model="rule.displayName" required maxlength="80" /></label>
              <label>事件编码<UiInput :disabled="busy||readOnly" v-model="rule.eventCode" required minlength="2" maxlength="64" pattern="[A-Za-z][A-Za-z0-9_]+" /></label>
              <label>严重度<UiSelect :disabled="busy||readOnly" v-model="rule.severity"><UiOption value="MINOR">一般</UiOption><UiOption value="MAJOR">重要</UiOption><UiOption value="CRITICAL">严重</UiOption></UiSelect></label>
            </div>
            <div class="parameter-editor-groups">
              <section class="parameter-editor-group" :aria-label="`${rule.rawLabel} 拍照识别`">
                <h4>拍照识别</h4><div class="parameter-editor-fields">
                  <label>图片告警置信度<UiInput :disabled="busy||readOnly" v-model.number="rule.image.minimumConfidence" type="number" min="0.01" max="0.99" step="0.01" required /></label>
                  <label>图片冷却时间（毫秒）<UiInput :disabled="busy||readOnly" v-model.number="rule.image.cooldownMs" type="number" min="0" max="86400000" step="1" required /></label>
                </div>
              </section>
              <section class="parameter-editor-group" :aria-label="`${rule.rawLabel} 相机巡检`">
                <h4>相机巡检</h4><div class="parameter-editor-fields">
                  <label>视频告警置信度<UiInput :disabled="busy||readOnly" v-model.number="rule.camera.minimumConfidence" type="number" min="0.01" max="0.99" step="0.01" required /></label>
                  <label>最少连续帧<UiInput :disabled="busy||readOnly" v-model.number="rule.camera.minimumConsecutiveFrames" type="number" min="1" max="120" step="1" required /></label>
                  <label>最少停留时间（毫秒）<UiInput :disabled="busy||readOnly" v-model.number="rule.camera.minimumDwellTimeMs" type="number" min="0" max="600000" step="1" required /></label>
                  <label>视频冷却时间（毫秒）<UiInput :disabled="busy||readOnly" v-model.number="rule.camera.cooldownMs" type="number" min="0" max="86400000" step="1" required /></label>
                </div>
              </section>
            </div>
          </UiCollapse>
        </fieldset>
        <p v-if="message" class="operation-feedback" :class="{'is-error':failed,'is-success':!failed}" :role="failed ? 'alert' : 'status'">{{ message }}</p>
        <UiCollapse class="parameter-editor-audit"><template #title>修改审计</template><p v-if="!profile.audit?.length" class="parameter-editor-hint">暂无修改记录</p><ul v-else><li v-for="(entry,index) in profile.audit" :key="index"><strong>{{ entry.action }} · 修订 {{ entry.revision }}</strong><span>{{ entry.actor }} · {{ entry.at }}</span></li></ul></UiCollapse>
        <footer class="parameter-editor-actions">
          <div class="parameter-editor-operation-note"><strong>保存草稿后，再明确发布</strong><p>保存不会替换已发布参数；发布只影响各项目的新运行。</p></div>
          <div class="parameter-editor-button-groups">
            <div><UiButton v-if="!readOnly&&!props.sceneBinding" type="button" class="secondary-button" :disabled="busy||needsReload" @click="resetOpen=true">重置草稿</UiButton><UiButton type="button" class="secondary-button" :disabled="busy" @click="load()">重新读取档案</UiButton></div>
            <div><UiButton v-if="!readOnly" type="submit" class="primary-button" :disabled="busy||needsReload">保存草稿</UiButton><UiButton v-if="!readOnly" type="button" class="primary-button" :disabled="busy||needsReload||dirty||!profile.hasUnpublishedChanges" @click="publishOpen=true">发布参数</UiButton></div>
          </div>
        </footer>
      </form>
    </div>
    <UiConfirmDialog v-model:open="resetOpen" title="重置参数草稿" description="草稿恢复为初始值，并记录审计；当前发布版不会改变。" confirm-label="确认恢复" cancel-label="取消恢复" :busy="busy" @confirm="reset" />
    <UiConfirmDialog v-model:open="publishOpen" title="发布平台参数" description="各项目的新运行将自动使用此修订；正在运行的任务保留启动时参数。无需重新下载模型文件。" confirm-label="确认发布" :busy="busy" @confirm="publish" />
  </UiDialog>
</template>

<style scoped>
.is-readonly .parameter-identity{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}
.is-readonly .parameter-identity>div{min-width:0}.is-readonly .parameter-identity h3{font-size:18px;line-height:1.6;overflow-wrap:anywhere}
.is-readonly .parameter-identity code{margin-top:4px;white-space:normal;overflow-wrap:anywhere}.is-readonly .parameter-identity>.ui-tag{flex-shrink:0;margin-top:4px}
.is-readonly :deep(.model-tabs){margin:18px 0 14px}
.parameter-readonly-notice{margin:0;padding:10px 12px;border-left:3px solid var(--color-primary);border-radius:0 6px 6px 0;background:var(--color-primary-soft);color:var(--color-primary);font-size:12px;line-height:1.8;overflow-wrap:anywhere}
.parameter-readonly-actions{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:12px;margin-top:20px;padding-top:16px;border-top:1px solid var(--color-border)}
.parameter-readonly-actions p{flex:1 1 180px;margin:0;color:var(--color-ink-muted);font-size:12px;line-height:1.7}
.parameter-readonly-actions button{flex-shrink:0;min-height:36px}
</style>
