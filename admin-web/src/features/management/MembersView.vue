<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import UiDialog from '../../components/ui/UiDialog.vue'
import { useSessionStore } from '../../stores/session'
import { useProjectsStore } from '../../stores/projects'
import { managementApi, type MemberRecord, type ProjectRole, type AccountRecord } from './api'
import { useManagement } from './useManagement'
import './management.css'
const session = useSessionStore(), projects = useProjectsStore()
const projectId = projects.current!.projectId
const canManage = computed(() => projects.current?.projectId === projectId && projects.current.capabilities.includes('project.members.manage'))
const { data, loading, error, notice, busy, mutationError, needsReload, refresh, run, resetMutation } = useManagement({ members: [] as MemberRecord[], accounts: [] as AccountRecord[] }, async signal => {
  const [members, accounts] = await Promise.all([managementApi.members(projectId, signal), session.isAdmin ? managementApi.accounts(signal) : Promise.resolve([])]); return { members, accounts }
})
const open = ref(false), action = ref<'add' | 'edit' | 'remove' | 'transfer'>('add'), original = ref<MemberRecord>()
const draft = reactive({ accountId: '', projectRole: 'PROJECT_USER' as ProjectRole, enabled: true, toAccountId: '' })
const titles = { add: '添加项目成员', edit: '编辑项目成员', remove: '移除项目成员', transfer: '移交负责人' }
const eligibleAccounts = computed(() => data.value.accounts.filter(a => a.enabled && !data.value.members.some(m => m.accountId === a.accountId)))
const targets = computed(() => data.value.members.filter(m => m.enabled && m.accountEnabled && m.accountId !== original.value?.accountId))
const editable = (member: MemberRecord) => canManage.value && (session.isAdmin || member.projectRole === 'PROJECT_USER')
const transferable = (member: MemberRecord) => canManage.value && member.enabled && member.accountEnabled && member.projectRole === 'PROJECT_OWNER' && (session.isAdmin || member.accountId === session.user?.accountId)
function begin(kind: typeof action.value, member?: MemberRecord) {
  if (busy.value || needsReload.value || !canManage.value) return
  if (member && !(kind === 'transfer' ? transferable(member) : editable(member))) return
  action.value = kind; original.value = member ? { ...member } : undefined
  Object.assign(draft, { accountId: member?.accountId ?? '', projectRole: member?.projectRole ?? 'PROJECT_USER', enabled: member?.enabled ?? true, toAccountId: '' })
  resetMutation(); open.value = true
}
async function save() {
  if (!canManage.value) return
  const from = original.value, to = targets.value.find(m => m.accountId === draft.toAccountId)
  if (action.value === 'transfer' && (!from || !to)) return
  await run(signal => {
    if (action.value === 'add') return managementApi.addMember(projectId, { accountId: draft.accountId.trim(), projectRole: session.isAdmin ? draft.projectRole : 'PROJECT_USER' }, signal)
    if (action.value === 'edit') return managementApi.editMember({ ...from!, projectRole: session.isAdmin ? draft.projectRole : 'PROJECT_USER', enabled: draft.enabled }, signal)
    if (action.value === 'remove') return managementApi.removeMember(from!, signal)
    return managementApi.transfer(projectId, from!, to!, signal)
  }, async () => { open.value = false; await projects.revalidate() })
}
onMounted(refresh)
</script>
<template><section class="management-workspace"><div class="management-actions page-actions"><UiButton class="secondary-button" :disabled="busy || loading" @click="refresh">刷新成员列表</UiButton><UiButton class="primary-button" :disabled="!canManage || busy || loading || needsReload || !!error" @click="begin('add')">添加项目成员</UiButton></div>
  <p class="management-note">{{ session.isAdmin ? '已显式进入当前项目，访问与变更由服务端审计。至少保留一位启用账号的有效负责人。' : '您只能维护当前项目的普通用户。不能创建平台账号、授予负责人角色或修改其他负责人；可通过专用流程移交自己的负责人身份。' }}</p>
  <p v-if="notice" role="status" class="management-success">{{ notice }}</p><p v-if="needsReload" role="alert" class="management-error">请刷新成员列表核验版本与操作结果。</p><p v-if="loading" role="status">正在读取成员…</p><p v-else-if="error" role="alert" class="management-error">{{ error }}</p><p v-else-if="!data.members.length">暂无可显示成员，请刷新或联系平台超级管理员核验负责人关系。</p>
  <div v-else class="management-grid"><article v-for="member in data.members" :key="member.accountId" class="management-card" :aria-label="member.username"><div class="management-card-heading"><span class="eyebrow">{{ member.projectRole === 'PROJECT_OWNER' ? '项目负责人' : '项目用户' }}</span><span class="management-state">{{ member.enabled && member.accountEnabled ? '有效成员' : '访问已停止' }}</span></div><h3>{{ member.username }}</h3><p class="management-id">{{ member.accountId }}</p><p class="management-meta">成员关系：{{ member.enabled ? '启用' : '停用' }} · 平台账号：{{ member.accountEnabled ? '启用' : '停用' }} · 版本 {{ member.revision }}</p><div class="management-actions"><UiButton v-if="editable(member)" class="secondary-button" :disabled="busy || needsReload" @click="begin('edit', member)">编辑成员</UiButton><UiButton v-if="editable(member)" class="secondary-button danger-text" :disabled="busy || needsReload" @click="begin('remove', member)">移除成员</UiButton><UiButton v-if="transferable(member)" class="secondary-button" :disabled="busy || needsReload" @click="begin('transfer', member)">移交负责人</UiButton></div></article></div>
  <UiDialog v-model:open="open" :title="titles[action]" :busy="busy"><form class="management-form" @submit.prevent="save">
    <p><strong>{{ projects.current?.displayName }}</strong><span v-if="original"> · {{ original.username }} · 版本 {{ original.revision }}</span></p>
    <fieldset :disabled="busy || needsReload"><template v-if="action === 'add'"><label v-if="session.isAdmin">选择账号<select v-model="draft.accountId" required><option value="" disabled>选择未加入本项目的启用账号</option><option v-for="account in eligibleAccounts" :key="account.accountId" :value="account.accountId">{{ account.username }} · {{ account.accountId }}</option></select></label><label v-else>已有平台账号 ID<UiInput v-model="draft.accountId" required maxlength="36" autocomplete="off" /></label><p v-if="!session.isAdmin" class="management-note">请向平台超级管理员获取已创建账号的准确 ID。此处不会搜索或披露全平台账号。</p><p v-else-if="!eligibleAccounts.length" class="management-note">暂无可添加账号，请先在平台账号管理中创建或启用账号。</p></template>
    <template v-if="action === 'add' || action === 'edit'"><label v-if="session.isAdmin">项目角色<select v-model="draft.projectRole"><option value="PROJECT_USER">项目用户</option><option value="PROJECT_OWNER">项目负责人</option></select></label><p v-else>项目角色：项目用户（只使用获准功能）</p><label v-if="action === 'edit'">成员状态<select v-model="draft.enabled"><option :value="true">启用</option><option :value="false">停用</option></select></label><p class="management-note">{{ draft.projectRole === 'PROJECT_OWNER' ? '负责人可维护项目数据与普通成员，请确认授权范围。' : '用户可使用获准的查看、巡检与告警处置功能，不能维护模型和项目配置。' }}</p><p v-if="!draft.enabled" class="management-error">将停止该账号访问本项目，其他项目成员关系不受影响。</p></template>
    <template v-if="action === 'transfer'"><label>接收负责人<select v-model="draft.toAccountId" required><option value="" disabled>选择已启用的现有成员</option><option v-for="member in targets" :key="member.accountId" :value="member.accountId">{{ member.username }} · 版本 {{ member.revision }}</option></select></label><p class="management-note">一次事务中将接收人提升为负责人，将原负责人降为项目用户。同时校验双方版本，任一冲突均不修改。</p><p v-if="!targets.length">无合格接收人，请先添加并启用成员。</p><p v-if="original?.accountId === session.user?.accountId" class="management-error">您将失去本项目维护权限，成功后会清空旧权限并要求重新选择项目。</p></template>
    <p v-if="action === 'remove'" class="management-error">确认移除此成员与当前项目的关系。将立即停止本项目授权，不删除平台账号或业务历史。重新分配需再次添加成员。</p></fieldset>
    <p v-if="mutationError" role="alert" class="management-error">{{ mutationError }}</p><footer><UiButton type="button" class="secondary-button" :disabled="busy" @click="open = false">取消</UiButton><UiButton class="primary-button" :disabled="busy || needsReload || !canManage || (action === 'transfer' && !draft.toAccountId)" :loading="busy">确认{{ titles[action] }}</UiButton></footer>
  </form></UiDialog>
</section></template>
