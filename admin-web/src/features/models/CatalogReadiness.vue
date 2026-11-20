<script setup lang="ts">
import { computed } from 'vue'
import { supportedTargets } from './capabilities'
import { catalogReadiness } from './catalogReadiness'
import type { ModelAsset, Platform } from './types'

const props = defineProps<{ model: ModelAsset }>()
const emit = defineEmits<{ parameters: [platform: Platform] }>()
const rows = computed(() => supportedTargets(props.model).map(target => catalogReadiness(props.model, target)))
</script>

<template>
  <section class="catalog-readiness" aria-label="项目添加条件">
    <h4>项目添加条件</h4>
    <p v-if="!rows.length" class="model-muted">尚未声明目标端，请先检查模型产物与目标端配置。</p>
    <div v-for="row in rows" :key="row.platform" class="catalog-readiness-row">
      <div class="catalog-readiness-main">
        <header><strong>{{ row.label }}</strong><UiTag :tone="row.tone">{{ row.status }}</UiTag></header>
        <dl><div><dt>文件</dt><dd>{{ row.files }}</dd></div><div><dt>参数</dt><dd>{{ row.parameters }}</dd></div></dl>
      </div>
      <UiButton class="secondary-button" @click="emit('parameters', row.platform)">{{ row.action }}</UiButton>
      <p v-if="row.status !== '项目可添加' || model.parameterPublication?.[row.platform]?.hasUnpublishedChanges">{{ row.hint }}</p>
    </div>
  </section>
</template>

<style scoped>
.catalog-readiness{padding:10px 12px;border:1px solid var(--color-border);border-radius:6px;background:var(--color-surface-subtle)}
.catalog-readiness h4{font-size:12px;line-height:1.5}
.catalog-readiness-row{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:6px 12px;padding-top:6px;margin-top:6px;border-top:1px solid var(--color-border);min-width:0}
.catalog-readiness-main{min-width:0}
.catalog-readiness-row header{display:flex;align-items:center;flex-wrap:wrap;gap:6px}
.catalog-readiness-row strong{font-size:12px}
.catalog-readiness-row dl{display:flex;flex-wrap:wrap;gap:2px 12px;margin:4px 0 0;font-size:11px;line-height:1.6}
.catalog-readiness-row dl>div{display:flex;gap:5px;min-width:0}
.catalog-readiness-row dt{flex-shrink:0;color:var(--color-ink-muted)}
.catalog-readiness-row dd{margin:0;overflow-wrap:anywhere}
.catalog-readiness-row p{grid-column:1/-1;margin:0;color:var(--color-ink-muted);font-size:11px;line-height:1.6;overflow-wrap:anywhere}
.catalog-readiness-row button{min-height:32px;padding:0 8px;font-size:11px;max-width:100%;white-space:normal;margin:0}
@media(max-width:600px){.catalog-readiness-row{grid-template-columns:minmax(0,1fr)}.catalog-readiness-row button{justify-self:start;grid-row:3}.catalog-readiness-row p{grid-row:2}}
</style>
