<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import UiDialog from '../../components/ui/UiDialog.vue'
import { managementApi, type ProjectRecord } from './api'
import { useManagement } from './useManagement'
import './management.css'
const router = useRouter()
const { data, loading, error, notice, busy, mutationError, needsReload, refresh, run, resetMutation } = useManagement({ projects: [] as ProjectRecord[], accounts: [] as Awaited<ReturnType<typeof managementApi.accounts>> }, async signal => {
  const [projects, accounts] = await Promise.all([managementApi.projects(signal), managementApi.accounts(signal)]); return { projects, accounts }
})
const query = ref(''), open = ref(false), target = ref<ProjectRecord>(), action = ref<'create' | 'edit' | 'suspend' | 'archive' | 'restore'>('create')
const draft = reactive({ projectCode: '', displayName: '', ownerAccountId: '' })
const labels = { create: '创建项目', edit: '编辑项目', suspend: '停用项目', archive: '归档项目', restore: '恢复项目' }
const stateLabels = { ACTIVE: '运行中', SUSPENDED: '已停用', ARCHIVED: '已归档' }
const filtered = computed(() => data.value.projects.filter(p => `${p.displayName} ${p.projectCode}`.toLowerCase().includes(query.value.toLowerCase())))
const impact = computed(() => ({ create: '为现有启用账号建立独立项目和负责人关系；平台超级管理员不会自动成为成员。', edit: '仅修改项目名称和代码，项目 ID 及历史数据归属保持不变。', suspend: '停止该项目巡检、运行时与业务写入；保留授权维护和恢复入口。不会删除历史数据。', archive: '冻结项目业务历史，停止普通用户访问及运行、下载和上报。归档不是删除，可由平台恢复。', restore: '恢复项目的正常授权与业务入口。请确认成员及配置仍符合要求；恢复不代表所有视频源已健康运行。' }[action.value]))
function begin(kind: typeof action.value, project?: ProjectRecord) {
  if (busy.value || needsReload.value) return
  action.value = kind; target.value = project ? { ...project } : undefined
  Object.assign(draft, { projectCode: project?.projectCode ?? '', displayName: project?.displayName ?? '', ownerAccountId: '' })
  resetMutation(); open.value = true
}
async function save() {
  await run(signal => {
    if (action.value === 'create') return managementApi.createProject({ ...draft, displayName: draft.displayName.trim() }, signal)
    const project = target.value!
    return action.value === 'edit' ? managementApi.editProject({ ...project, projectCode: draft.projectCode, displayName: draft.displayName.trim() }, signal) : managementApi.lifecycle(project, action.value, signal)
  }, () => { open.value = false })
}
onMounted(refresh)
</script>
<template><section class="management-workspace">
  <div class="management-actions page-actions"><UiButton class="secondary-button" :disabled="loading || busy" @click="refresh">刷新项目列表</UiButton><UiButton class="primary-button" :disabled="loading || busy || needsReload || !!error" @click="begin('create')">创建项目</UiButton></div>
  <p class="management-note">平台操作区 · 此列表只管理项目元数据。查看成员与项目审计时，需要显式进入对应项目。</p>
  <p v-if="notice" role="status" class="management-success">{{ notice }}</p><p v-if="needsReload" role="alert" class="management-error">操作结果或版本需要核验，请刷新项目列表后重新操作。</p>
  <label class="management-search">搜索项目<UiInput v-model="query" placeholder="项目名称或代码" /></label>
  <p v-if="loading" role="status">正在读取项目…</p><p v-else-if="error" role="alert" class="management-error">{{ error }}</p><p v-else-if="!filtered.length">暂无匹配项目。创建时必须指定一位启用的负责人账号。</p>
  <div v-else class="management-grid"><article v-for="project in filtered" :key="project.projectId" class="management-card" :aria-label="project.displayName">
    <div class="management-card-heading"><span class="eyebrow">{{ project.projectCode }}</span><span class="management-state">{{ stateLabels[project.lifecycleState] }}</span></div><h3>{{ project.displayName }}</h3><p class="management-id">ID {{ project.projectId }}</p><p class="management-meta">版本 {{ project.revision }} · 历史数据始终属于此项目</p>
    <div class="management-actions"><UiButton class="secondary-button" :disabled="busy || needsReload" @click="begin('edit', project)">编辑项目</UiButton><UiButton v-if="project.lifecycleState === 'ACTIVE'" class="secondary-button danger-text" :disabled="busy || needsReload" @click="begin('suspend', project)">停用项目</UiButton><UiButton v-if="project.lifecycleState !== 'ARCHIVED'" class="secondary-button danger-text" :disabled="busy || needsReload" @click="begin('archive', project)">归档项目</UiButton><UiButton v-if="project.lifecycleState !== 'ACTIVE'" class="secondary-button" :disabled="busy || needsReload" @click="begin('restore', project)">恢复项目</UiButton></div>
    <div class="management-actions management-card-footer"><UiButton v-if="project.lifecycleState !== 'ARCHIVED'" class="secondary-button" @click="router.push({ name: 'members', query: { project: project.projectId } })">进入项目管理成员</UiButton><UiButton class="secondary-button" @click="router.push({ name: 'project-audit', query: { project: project.projectId } })">进入项目查看审计</UiButton></div>
  </article></div>
  <UiDialog v-model:open="open" :title="labels[action]" :busy="busy"><form class="management-form" @submit.prevent="save">
    <p class="management-note">{{ impact }}</p><p v-if="target"><strong>{{ target.displayName }}</strong> · {{ target.projectCode }} · 版本 {{ target.revision }}</p>
    <fieldset v-if="action === 'create' || action === 'edit'" :disabled="busy || needsReload"><label>项目名称<UiInput v-model="draft.displayName" required maxlength="255" pattern=".*[^ ].*" /></label><label>项目代码<UiInput v-model="draft.projectCode" required minlength="3" maxlength="64" pattern="[a-z][a-z0-9-]{1,62}[a-z0-9]" placeholder="例如 site-alpha" /></label>
      <label v-if="action === 'create'">初始负责人<select v-model="draft.ownerAccountId" required><option value="" disabled>请选择已启用账号</option><option v-for="account in data.accounts.filter(a => a.enabled)" :key="account.accountId" :value="account.accountId">{{ account.username }} · {{ account.accountId }}</option></select></label>
    </fieldset><p v-if="mutationError" role="alert" class="management-error">{{ mutationError }}</p><footer><UiButton type="button" class="secondary-button" :disabled="busy" @click="open = false">取消</UiButton><UiButton class="primary-button" :class="{ 'danger-text': ['suspend', 'archive'].includes(action) }" :disabled="busy || needsReload" :loading="busy">确认{{ labels[action] }}</UiButton></footer>
  </form></UiDialog>
</section></template>
