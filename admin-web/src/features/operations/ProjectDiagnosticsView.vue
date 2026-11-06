<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import UiStatePanel from '../../components/ui/UiStatePanel.vue'
import { operationsApi, type ProjectMetrics } from './api'
import { errorText } from '../models/api'
import '../models/models.css'
const value = ref<ProjectMetrics | null>(null)
const phase = ref<'loading'|'ready'|'error'>('loading'), error = ref('')
let controller: AbortController | undefined, disposed = false
async function load() {
  controller?.abort(); controller = new AbortController(); phase.value = 'loading'
  const signal = controller.signal
  try { const result = await operationsApi.projectMetrics(signal); if (!disposed && !signal.aborted) { value.value = result; phase.value = 'ready' } }
  catch (e) { if (!disposed && !signal.aborted) { error.value = errorText(e); phase.value = 'error' } }
}
onMounted(load); onBeforeUnmount(() => { disposed = true; controller?.abort() })
</script>
<template><section class="model-workspace"><div class="model-actions page-actions"><UiButton class="secondary-button" @click="load">刷新诊断</UiButton></div><UiStatePanel v-if="phase !== 'ready'" :state="phase" :message="error" @retry="load"/><template v-else-if="value"><section class="model-panel"><header><h3>当前项目运行汇总</h3><span>{{ value.projectId || '当前项目' }}</span></header><dl class="model-readiness"><div><dt>运行会话数</dt><dd>{{ value.streams.total }}</dd></div><div><dt>已接收帧</dt><dd>{{ value.streams.framesReceived }}</dd></div><div><dt>已处理帧</dt><dd>{{ value.streams.framesProcessed }}</dd></div><div><dt>丢弃帧</dt><dd>{{ value.streams.framesDropped }}</dd></div></dl><p class="model-muted">平台健康检查、数据库拓扑和服务器资源属于平台诊断，仅平台超级管理员可查看。</p></section></template></section></template>
