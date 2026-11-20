<script setup lang="ts">
import { computed, ref, useId } from 'vue'
import type { AlertParameter, ParameterProfile } from './types'

const props = defineProps<{ profile: ParameterProfile }>()
const query = ref(''), expandAll = ref(false), searchId = useId()
const rules = computed(() => {
  const term = query.value.trim().toLowerCase()
  return props.profile.alertRules.filter(rule => `${rule.rawLabel} ${rule.displayName} ${rule.eventCode}`.toLowerCase().includes(term))
})
const enabledCount = computed(() => props.profile.alertRules.filter(rule => rule.enabled).length)
const sourceLabel = computed(() => ({ default: '默认草稿', platform: '平台发布参数', custom: '平台草稿' } as Record<string, string>)[props.profile.source] || props.profile.source)
const severityLabel = (severity: AlertParameter['severity']) => ({ MINOR: '一般', MAJOR: '重要', CRITICAL: '严重' })[severity]
const severityTone = (severity: AlertParameter['severity']) => severity === 'CRITICAL' ? 'danger' : severity === 'MAJOR' ? 'warning' : 'info'
</script>

<template>
  <div class="parameter-readonly">
    <dl class="parameter-profile-meta" aria-label="参数档案信息">
      <div><dt>模型版本</dt><dd>{{ profile.modelVersion }}</dd></div>
      <div><dt>参数修订</dt><dd>r{{ profile.revision }}</dd></div>
      <div><dt>参数来源</dt><dd>{{ sourceLabel }}</dd></div>
      <div v-if="profile.sceneRevision != null"><dt>场景修订</dt><dd>r{{ profile.sceneRevision }}</dd></div>
    </dl>

    <section class="parameter-readonly-section" aria-label="识别基础参数">
      <header><h4>识别基础参数</h4><p>用于筛选模型的检测结果</p></header>
      <dl class="parameter-detection-values">
        <div><dt>识别置信度</dt><dd>{{ profile.detection.confidenceThreshold }}</dd></div>
        <div><dt>IoU 阈值</dt><dd>{{ profile.detection.iouThreshold }}</dd></div>
        <div><dt>最大检测结果</dt><dd>{{ profile.detection.maxDetections }}<span> 项</span></dd></div>
      </dl>
    </section>

    <section class="parameter-readonly-section" aria-label="类别识别与告警规则">
      <header><h4>类别与告警规则</h4><p>共 {{ profile.alertRules.length }} 类 · 已启用 {{ enabledCount }} 类</p></header>
      <div v-if="profile.alertRules.length" class="parameter-readonly-toolbar">
        <label :for="searchId">搜索类别<UiInput :id="searchId" v-model="query" placeholder="类别、名称或事件编码" /></label>
        <UiButton class="secondary-button" type="button" :disabled="!rules.length" @click="expandAll = !expandAll">{{ expandAll ? '全部收起' : '全部展开' }}</UiButton>
      </div>
      <p v-if="profile.alertRules.length" class="parameter-readonly-hint">关闭的类别不输出检测结果或告警；启用后仍需满足各自的告警条件。</p>
      <p v-if="!profile.alertRules.length" class="parameter-rules-empty" role="status">当前参数档案未配置类别规则。</p>
      <p v-else-if="!rules.length" class="parameter-rules-empty" role="status">未找到匹配的类别，请尝试其他名称或编码。</p>
      <UiCollapse v-for="rule in rules" :key="rule.rawLabel" class="parameter-readonly-rule" :open="expandAll">
        <template #title>
          <div class="parameter-rule-title">
            <span class="parameter-rule-name"><strong>{{ rule.displayName }}</strong><code>{{ rule.rawLabel }}</code></span>
            <span class="parameter-rule-badges"><UiTag :tone="rule.enabled ? 'success' : 'info'">{{ rule.enabled ? '识别与告警已启用' : '识别与告警已关闭' }}</UiTag><UiTag :tone="severityTone(rule.severity)">{{ severityLabel(rule.severity) }}告警</UiTag></span>
          </div>
        </template>
        <dl class="parameter-event-code"><dt>事件编码</dt><dd><code>{{ rule.eventCode }}</code></dd></dl>
        <p v-if="!rule.enabled" class="parameter-readonly-hint">此类别已关闭识别与告警，以下为保留的参数。</p>
        <div class="parameter-rule-groups">
          <section class="parameter-rule-group" :aria-label="`${rule.displayName} 拍照识别`">
            <h4>拍照识别</h4>
            <dl class="parameter-value-list">
              <div><dt>告警置信度</dt><dd>{{ rule.image.minimumConfidence }}</dd></div>
              <div><dt>冷却时间</dt><dd>{{ rule.image.cooldownMs }}<span> 毫秒</span></dd></div>
            </dl>
          </section>
          <section class="parameter-rule-group" :aria-label="`${rule.displayName} 相机巡检`">
            <h4>相机巡检</h4>
            <dl class="parameter-value-list">
              <div><dt>告警置信度</dt><dd>{{ rule.camera.minimumConfidence }}</dd></div>
              <div><dt>最少连续帧</dt><dd>{{ rule.camera.minimumConsecutiveFrames }}<span> 帧</span></dd></div>
              <div><dt>最少停留时间</dt><dd>{{ rule.camera.minimumDwellTimeMs }}<span> 毫秒</span></dd></div>
              <div><dt>冷却时间</dt><dd>{{ rule.camera.cooldownMs }}<span> 毫秒</span></dd></div>
            </dl>
          </section>
        </div>
      </UiCollapse>
    </section>

    <UiCollapse class="parameter-readonly-audit">
      <template #title>修改审计</template>
      <p v-if="!profile.audit?.length" class="parameter-readonly-hint">暂无修改记录</p>
      <ul v-else><li v-for="(entry, index) in profile.audit" :key="index"><strong>{{ entry.action }} · 修订 {{ entry.revision }}</strong><span>{{ entry.actor }} · {{ entry.at }}</span></li></ul>
    </UiCollapse>
  </div>
</template>

<style scoped>
.parameter-readonly{min-width:0}
.parameter-readonly dl,.parameter-readonly dd{margin:0}
.parameter-profile-meta{display:flex;flex-wrap:wrap;gap:14px 32px;padding:16px 0;border-bottom:1px solid var(--color-border)}
.parameter-profile-meta>div{min-width:0;flex:1 1 120px}
.parameter-profile-meta dt,.parameter-detection-values dt,.parameter-event-code dt,.parameter-value-list dt{color:var(--color-ink-muted);font-size:12px}
.parameter-profile-meta dd{margin-top:4px;font-size:13px;font-weight:600;overflow-wrap:anywhere}
.parameter-readonly-section{margin-top:24px}
.parameter-readonly-section>header{display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;gap:6px 16px;margin-bottom:12px}
.parameter-readonly-section>header h4{font-size:14px}.parameter-readonly-section>header p{margin:0;color:var(--color-ink-muted);font-size:12px}
.parameter-detection-values{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
.parameter-detection-values>div{min-width:0;padding:14px 16px;border:1px solid var(--color-border);border-radius:8px;background:var(--color-surface-subtle)}
.parameter-detection-values dd{margin-top:6px;color:var(--color-ink);font-size:22px;font-weight:600;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
.parameter-detection-values dd span{font-size:12px;font-weight:400;color:var(--color-ink-muted)}
.parameter-readonly-toolbar{display:flex;align-items:flex-end;flex-wrap:wrap;gap:12px}
.parameter-readonly-toolbar>label{flex:1;min-width:min(180px,100%)}.parameter-readonly-toolbar>button{flex-shrink:0;min-height:34px}
.parameter-readonly-hint{margin:10px 0 0;color:var(--color-ink-muted);font-size:12px;line-height:1.7}
.parameter-rules-empty{margin:12px 0 0;padding:20px 16px;border-radius:8px;background:var(--color-surface-subtle);color:var(--color-ink-muted);font-size:13px}
.parameter-readonly-rule{margin-top:12px;padding:0 16px;border:1px solid var(--color-border);border-radius:8px;overflow-wrap:anywhere}
.parameter-readonly-rule :deep(>.el-collapse-item:last-child){margin-bottom:0}
.parameter-readonly-rule :deep(.el-collapse-item__header){min-height:64px;gap:12px;line-height:1.6;border:0}
.parameter-readonly-rule :deep(.el-collapse-item__wrap){border:0}
.parameter-readonly-rule :deep(.el-collapse-item__content){padding-bottom:16px}
.parameter-rule-title{display:flex;flex:1;min-width:0;flex-wrap:wrap;align-items:center;gap:8px 16px;padding:12px 0}
.parameter-rule-name{flex:1 1 160px;min-width:0}.parameter-rule-name strong{display:block;font-size:13px;font-weight:600;overflow-wrap:anywhere}
.parameter-rule-name code{margin-top:3px;white-space:normal;overflow-wrap:anywhere;font-size:11px;font-weight:400}
.parameter-rule-badges{display:flex;flex-wrap:wrap;align-items:center;gap:6px}
.parameter-event-code{display:grid;grid-template-columns:auto minmax(0,1fr);gap:12px;padding:12px 0;border-top:1px solid var(--color-border)}
.parameter-event-code code{line-height:1.7;white-space:normal;overflow-wrap:anywhere}
.parameter-rule-groups{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.parameter-rule-group{min-width:0;padding:14px;border-radius:6px;background:var(--color-surface-subtle)}
.parameter-rule-group h4{margin:0 0 12px;font-size:12px;font-weight:600}
.parameter-value-list{display:grid;gap:10px}.parameter-value-list>div{display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;gap:4px 12px}
.parameter-value-list dd{font-size:13px;font-weight:600;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
.parameter-value-list dd span{color:var(--color-ink-muted);font-size:11px;font-weight:400}
.parameter-readonly-audit{margin-top:24px;font-size:12px;overflow-wrap:anywhere}
.parameter-readonly-audit ul{list-style:none;padding:0;margin:0}.parameter-readonly-audit li{display:grid;gap:4px;padding:10px 0;border-top:1px solid var(--color-border)}
.parameter-readonly-audit li strong{font-weight:500}.parameter-readonly-audit li span{color:var(--color-ink-muted)}
@media(max-width:600px){.parameter-profile-meta{gap:12px 20px}.parameter-profile-meta>div{flex-basis:90px}.parameter-detection-values{gap:8px}.parameter-detection-values>div{padding:12px 8px}.parameter-detection-values dt{font-size:11px}.parameter-detection-values dd{font-size:19px}.parameter-rule-groups{grid-template-columns:minmax(0,1fr)}.parameter-readonly-rule{padding:0 12px}.parameter-readonly-section{margin-top:20px}}
</style>
