<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useProjectsStore } from '../../stores/projects'
import { managementApi, type AuditPage } from './api'
import { useManagement } from './useManagement'
import './management.css'
const route = useRoute(), projects = useProjectsStore()
const projectId = route.meta.requiresProject ? projects.current!.projectId : null
const draft = ref({action:'',actorAccountId:'',requestId:'',outcome:'',targetType:'',since:'',until:''})
const filters = ref<Record<string,string>>({}), filterError = ref('')
function search() {
  filterError.value=''
  const value:Record<string,string>={}
  for(const [key,raw] of Object.entries(draft.value)) {
    if(!raw.trim())continue
    if(key==='since'||key==='until') { const date=new Date(raw);if(!Number.isFinite(date.getTime())){filterError.value='请输入有效时间';return};value[key]=date.toISOString() }
    else value[key]=raw.trim()
  }
  if(value.since&&value.until&&value.since>value.until){filterError.value='开始时间不能晚于结束时间';return}
  filters.value=value;reset()
}
function clearFilters(){for(const key of Object.keys(draft.value) as Array<keyof typeof draft.value>)draft.value[key]='';search()}
const cursor = ref<string>(), history = ref<Array<string | undefined>>([])
const { data, loading, error, refresh } = useManagement<AuditPage>({ events: [], nextCursor: null }, signal => managementApi.audit(projectId, cursor.value, signal, filters.value))
const title = computed(() => projectId ? '项目审计' : '平台账号审计')
async function page(next: boolean) { if (loading.value) return; if (next) { history.value.push(cursor.value); cursor.value = data.value.nextCursor! } else cursor.value = history.value.pop(); await refresh() }
function reset() { history.value = []; cursor.value = undefined; void refresh() }
onMounted(refresh)
</script>
<template><section class="management-workspace"><div class="management-actions page-actions"><UiButton class="secondary-button" :disabled="loading" @click="reset">刷新审计</UiButton></div><p class="management-note">仅展示审计元数据、目标和版本变化，不显示密码、凭据或原始业务载荷。按服务端时间与审计 ID 倒序分页。</p>
<form class="management-form management-card" @submit.prevent="search"><div class="management-grid"><label>操作动作<UiInput v-model="draft.action" placeholder="例如 export.alerts" maxlength="128"/></label><label>操作者账号 ID<UiInput v-model="draft.actorAccountId" maxlength="36"/></label><label>请求 ID<UiInput v-model="draft.requestId" maxlength="128"/></label><label>操作结果<UiSelect v-model="draft.outcome"><UiOption value="">全部结果</UiOption><UiOption value="SUCCESS">成功</UiOption><UiOption value="DENIED">拒绝</UiOption><UiOption value="FAILED">失败</UiOption></UiSelect></label><label>目标类型<UiInput v-model="draft.targetType" maxlength="128"/></label><label>开始时间（本地）<UiInput type="datetime-local" v-model="draft.since"/></label><label>结束时间（本地）<UiInput type="datetime-local" v-model="draft.until"/></label></div><p v-if="filterError" role="alert">{{filterError}}</p><footer><UiButton class="secondary-button" type="button" :disabled="loading" @click="clearFilters">清除筛选</UiButton><UiButton class="primary-button" :disabled="loading">查询审计</UiButton></footer></form>
<p v-if="loading" role="status">正在读取审计…</p><p v-else-if="error" role="alert" class="management-error">{{ error }}</p><p v-else-if="!data.events.length">当前页暂无审计记录。</p><ol v-else class="audit-list"><li v-for="entry in data.events" :key="entry.auditId" class="management-card audit-entry"><div class="management-card-heading"><strong>{{ entry.action }}</strong><span class="management-state">{{ { SUCCESS: '成功', DENIED: '拒绝', FAILED: '失败' }[entry.outcome] ?? entry.outcome }}</span></div><p>{{ entry.occurredAt }}</p><dl><dt>操作者</dt><dd>{{ entry.actorAccountId ?? entry.actorServicePrincipalId ?? '系统' }} · {{ entry.platformRole ?? '—' }} / {{ entry.projectRole ?? '—' }}</dd><dt>操作目标</dt><dd>{{ entry.targetType }} / {{ entry.targetId ?? '—' }}</dd><dt>版本变化</dt><dd>{{ entry.previousRevision ?? '—' }} → {{ entry.newRevision ?? '—' }}</dd><dt>请求 ID</dt><dd>{{ entry.requestId ?? '—' }}</dd><dt v-if="entry.failureCode">拒绝原因</dt><dd v-if="entry.failureCode">{{ entry.failureCode }}</dd></dl></li></ol><nav class="management-actions" aria-label="审计分页"><UiButton class="secondary-button" :disabled="loading || !history.length" @click="page(false)">上一页</UiButton><span role="status">第 {{ history.length + 1 }} 页</span><UiButton class="secondary-button" :disabled="loading || !!error || !data.nextCursor" @click="page(true)">下一页</UiButton></nav></section></template>
