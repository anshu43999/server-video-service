<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import UiDialog from '../../components/ui/UiDialog.vue'
import UiConfirmDialog from '../../components/ui/UiConfirmDialog.vue'
import UiStatePanel from '../../components/ui/UiStatePanel.vue'
import { errorText, modelsApi } from './api'
import type { ModelAsset, ParameterProfile, Platform } from './types'
import { requiresReload } from '../projects/writeRecovery'
import { scenesApi, type SceneProfileBinding } from '../scenes/api'
const needsReload = ref(false)
const props = defineProps<{ model: ModelAsset; readOnly?: boolean; projectMode?: boolean; initialPlatform?: Platform; sceneBinding?:SceneProfileBinding }>()
const emit = defineEmits<{ close: [] }>()
const platform = ref<Platform>(props.initialPlatform ?? 'android'), profile = ref<ParameterProfile | null>(null)
const sceneRevision = ref(props.sceneBinding?.revision)
const sceneBinding = computed(() => props.sceneBinding ? {...props.sceneBinding, revision:sceneRevision.value!} : undefined)
const loading = ref(true), busy = ref(false), message = ref(''), failed = ref(false), loadError = ref(''), query = ref(''), expandAll = ref(false), resetOpen = ref(false)
let controller: AbortController | undefined, disposed = false
const rules = computed(() => profile.value?.alertRules.filter(rule => `${rule.rawLabel} ${rule.displayName} ${rule.eventCode}`.toLowerCase().includes(query.value.toLowerCase().trim())) ?? [])
async function load(target = platform.value) {
  if (busy.value) return
  controller?.abort(); controller = new AbortController(); const signal = controller.signal
  platform.value = target; loading.value = true; profile.value = null; message.value = ''; loadError.value = ''
  try { const value = await (sceneBinding.value ? scenesApi.profile(sceneBinding.value,signal) : modelsApi.parameters(props.model.modelId, target, signal, props.model.version)); if (!disposed && !signal.aborted) { profile.value = value; needsReload.value = false } }
  catch (e) { if (!disposed && !signal.aborted) loadError.value = errorText(e) }
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
  if (busy.value || needsReload.value || props.readOnly) return
  let value: ParameterProfile
  try { value = validate() } catch (e) { message.value = errorText(e); failed.value = true; return }
  busy.value = true
  try { const result = await (sceneBinding.value ? scenesApi.saveProfile(sceneBinding.value,value) : modelsApi.saveParameters(props.model.modelId, platform.value, value, props.model.version)); if (!disposed) { profile.value = result; if (result.sceneRevision) sceneRevision.value = result.sceneRevision; message.value = props.sceneBinding ? '场景成员参数已保存，请重新审批该场景后运行。其他场景和独立项目模型保持原参数，无需重新下载模型。' : props.projectMode ? '参数档案已保存。请在项目模型更新分配参数，场景仍使用各自已批准的快照。' : '参数档案已保存。'; failed.value = false } }
  catch (e) { if (!disposed) { needsReload.value = requiresReload(e); message.value = `${errorText(e)}。请重新读取档案核验后再编辑。`; failed.value = true } }
  finally { busy.value = false }
}
async function reset() {
  if (busy.value || needsReload.value || props.readOnly || !profile.value) return
  busy.value = true
  try { const value = await modelsApi.resetParameters(props.model.modelId, platform.value, profile.value.revision, props.model.version); if (!disposed) { profile.value = value; resetOpen.value = false; message.value = props.projectMode ? '已恢复默认参数并记录审计；项目分配的已批准快照保持原值，重新批准后生效。' : '已恢复默认参数并记录审计。'; failed.value = false } }
  catch (e) { if (!disposed) { needsReload.value = requiresReload(e); message.value = errorText(e) + ' 请重新读取档案核验后再操作。'; failed.value = true } }
  finally { busy.value = false }
}
onMounted(() => load())
onBeforeUnmount(() => { disposed = true; controller?.abort() })
</script>
<template>
  <UiDialog :open="true" title="模型参数档案" :busy="busy" @update:open="emit('close')">
    <div class="parameter-content">
      <h3>{{ model.name }}</h3><code>{{ model.modelId }}</code>
      <UiTabs class="model-tabs" :model-value="platform" :items="(props.readOnly || props.sceneBinding) && props.initialPlatform ? [{id:props.initialPlatform,label:props.initialPlatform === 'server' ? '服务端参数' : 'Android 参数'}] : [{id:'android',label:'Android 参数'},{id:'server',label:'服务端参数'}]" :disabled="busy" @update:model-value="value => load(value as Platform)" />
      <p v-if="props.sceneBinding" class="model-muted">这里编辑该场景成员的独立运行参数，不影响其他场景和独立项目模型。保存将撤销该场景的当前审批，请重新审批后运行。</p>
      <p class="model-muted">{{ props.projectMode ? '档案按平台分别保存，巡检使用已批准的参数快照。' : '档案按平台分别保存，项目分配引用经批准的参数快照。' }}切换平台或重新读取会放弃当前未保存的编辑。</p>
      <UiStatePanel v-if="loading" state="loading" /><UiStatePanel v-else-if="loadError" state="error" :message="loadError" @retry="load()" />
      <form v-else-if="profile" class="model-form" @submit.prevent="save">
        <p class="model-muted">当前 API 档案版本 {{ profile.modelVersion }} · 修订 {{ profile.revision }} · {{ ({default:'初始参数', inherited:'继承平台默认', approved:'已批准快照', custom:'项目覆盖'} as Record<string,string>)[profile.source] || profile.source }}</p>
        <p v-if="profile.modelVersion !== model.version" class="operation-feedback">所选资产是 {{ model.version }}，当前参数接口对应 {{ profile.modelVersion }}；以下修改作用于该当前档案。</p>
        <fieldset :disabled="busy"><legend>识别基础参数</legend><div class="model-fields three"><label>识别置信度<UiInput :disabled="busy||props.readOnly" v-model.number="profile.detection.confidenceThreshold" type="number" min="0.01" max="0.99" step="0.01" required /></label><label>IoU 阈值<UiInput :disabled="busy||props.readOnly" v-model.number="profile.detection.iouThreshold" type="number" min="0.1" max="0.9" step="0.01" required /></label><label>最大检测结果<UiInput :disabled="busy||props.readOnly" v-model.number="profile.detection.maxDetections" type="number" min="1" max="300" step="1" required /></label></div>
          <div class="model-toolbar"><label>搜索类别<UiInput :disabled="busy" v-model="query" placeholder="类别、名称或编码" /></label><UiButton class="secondary-button" type="button" @click="expandAll = !expandAll">{{ expandAll ? '全部收起' : '全部展开' }}</UiButton></div>
          <p class="model-muted">每个类别只有一个“启用识别与告警”开关。关闭后不显示检测框、不计数、不跟踪也不产生该类别告警；启用后仍需满足以下告警条件。全关闭时不输出任何检测结果，修改运行参数无需重新下载模型。</p>
          <UiCollapse v-for="rule in rules" :key="rule.rawLabel" class="parameter-rule" :open="expandAll"><template #title><strong>{{ rule.displayName }}</strong><code>{{ rule.rawLabel }}</code><UiTag>{{ rule.enabled ? '识别与告警已启用' : '识别与告警已关闭' }}</UiTag></template><div class="model-fields three"><label class="model-check"><UiInput :disabled="busy||props.readOnly" v-model="rule.enabled" type="checkbox" />启用识别与告警</label><label>业务名称<UiInput :disabled="busy||props.readOnly" v-model="rule.displayName" required maxlength="80" /></label><label>事件编码<UiInput :disabled="busy||props.readOnly" v-model="rule.eventCode" required minlength="2" maxlength="64" pattern="[A-Za-z][A-Za-z0-9_]+" /></label><label>严重度<UiSelect :disabled="busy||props.readOnly" v-model="rule.severity"><UiOption value="MINOR">一般</UiOption><UiOption value="MAJOR">重要</UiOption><UiOption value="CRITICAL">严重</UiOption></UiSelect></label></div>
            <h4>拍照识别</h4><div class="model-fields"><label>图片告警置信度<UiInput :disabled="busy||props.readOnly" v-model.number="rule.image.minimumConfidence" type="number" min="0.01" max="0.99" step="0.01" required /></label><label>图片冷却时间（毫秒）<UiInput :disabled="busy||props.readOnly" v-model.number="rule.image.cooldownMs" type="number" min="0" max="86400000" step="1" required /></label></div>
            <h4>相机巡检</h4><div class="model-fields"><label>视频告警置信度<UiInput :disabled="busy||props.readOnly" v-model.number="rule.camera.minimumConfidence" type="number" min="0.01" max="0.99" step="0.01" required /></label><label>最少连续帧<UiInput :disabled="busy||props.readOnly" v-model.number="rule.camera.minimumConsecutiveFrames" type="number" min="1" max="120" step="1" required /></label><label>最少停留时间（毫秒）<UiInput :disabled="busy||props.readOnly" v-model.number="rule.camera.minimumDwellTimeMs" type="number" min="0" max="600000" step="1" required /></label><label>视频冷却时间（毫秒）<UiInput :disabled="busy||props.readOnly" v-model.number="rule.camera.cooldownMs" type="number" min="0" max="86400000" step="1" required /></label></div>
          </UiCollapse>
        </fieldset>
        <p v-if="message" class="operation-feedback" :class="{'is-error':failed,'is-success':!failed}" role="status">{{ message }}</p>
        <div class="model-actions"><UiButton v-if="!props.readOnly&&!props.sceneBinding" type="button" class="secondary-button" :disabled="busy||needsReload" @click="resetOpen=true">恢复默认</UiButton><UiButton type="button" class="secondary-button" :disabled="busy" @click="load()">重新读取档案</UiButton><UiButton v-if="!props.readOnly" class="primary-button" :disabled="busy||needsReload">保存参数</UiButton></div>
        <UiCollapse class="parameter-audit"><template #title>修改审计</template><p v-if="!profile.audit?.length" class="model-muted">暂无修改记录</p><p v-for="(entry,index) in profile.audit" :key="index">{{ entry.action }} · 修订 {{ entry.revision }} · {{ entry.actor }} · {{ entry.at }}</p></UiCollapse>
      </form>
    </div>
    <UiConfirmDialog v-model:open="resetOpen" title="恢复默认参数" description="当前平台的自定义参数将恢复为初始值，并记录审计。" confirm-label="确认恢复" cancel-label="取消恢复" :busy="busy" @confirm="reset" />
  </UiDialog>
</template>
