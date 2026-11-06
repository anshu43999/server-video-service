<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, reactive, ref, watch } from 'vue'
import UiDialog from '../../components/ui/UiDialog.vue'
import { platformRoleLabel } from '../../api/auth'
import { useSessionStore } from '../../stores/session'
import { useProjectsStore } from '../../stores/projects'
import { managementApi, type AccountRecord, type PlatformRole } from './api'
import { useManagement } from './useManagement'
import './management.css'
const session = useSessionStore(), projects = useProjectsStore()
const { data, loading, error, notice, busy, mutationError, needsReload, refresh, run, resetMutation } = useManagement<AccountRecord[]>([], managementApi.accounts)
const query = ref(''), open = ref(false), original = ref<AccountRecord>()
const draft = reactive({ username: '', password: '', platformRole: 'NORMAL_USER' as PlatformRole, enabled: true })
const filtered = computed(() => data.value.filter(a => `${a.username} ${a.accountId}`.toLowerCase().includes(query.value.toLowerCase())))
function begin(account?: AccountRecord) {
  if (busy.value || needsReload.value) return
  original.value = account ? { ...account } : undefined
  Object.assign(draft, { username: account?.username ?? '', password: '', platformRole: account?.platformRole ?? 'NORMAL_USER', enabled: account?.enabled ?? true }); resetMutation(); open.value = true
}
async function save() {
  const source = original.value
  await run(signal => source ? managementApi.editAccount({ ...source, platformRole: draft.platformRole, enabled: draft.enabled }, signal) : managementApi.createAccount({ username: draft.username.trim(), password: draft.password, platformRole: draft.platformRole }, signal), async () => {
    draft.password = ''; open.value = false
    if (source?.accountId === session.user?.accountId) await projects.revalidate(true)
  })
  // Do not retain a password after any attempted submission, including failures.
  draft.password = ''
}
watch(open, value => { if (!value) draft.password = '' }); onBeforeUnmount(() => { draft.password = '' }); onMounted(refresh)
</script>
  <template><section class="management-workspace"><div class="management-actions page-actions"><UiButton class="secondary-button" :disabled="busy || loading" @click="refresh">刷新账号列表</UiButton><UiButton class="primary-button" :disabled="busy || loading || needsReload || !!error" @click="begin()">创建账号</UiButton></div>
  <p class="management-note">停用账号会影响其所有项目和现有会话。服务器保护最后一位平台超级管理员和项目最后负责人；请先移交职责再停用。</p>
  <p v-if="notice" role="status" class="management-success">{{ notice }}</p><p v-if="needsReload" role="alert" class="management-error">请刷新账号列表核验版本与操作结果。</p><label class="management-search">搜索账号<UiInput v-model="query" placeholder="账号名或 ID" /></label>
  <p v-if="loading" role="status">正在读取账号…</p><p v-else-if="error" role="alert" class="management-error">{{ error }}</p><p v-else-if="!filtered.length">暂无匹配账号。</p>
  <div v-else class="management-grid"><article v-for="account in filtered" :key="account.accountId" class="management-card" :aria-label="account.username"><div class="management-card-heading"><span class="eyebrow">{{ platformRoleLabel(account.platformRole) }}</span><span class="management-state">{{ account.enabled ? '已启用' : '已停用' }}</span></div><h3>{{ account.username }}<small v-if="account.accountId === session.user?.accountId"> · 当前账号</small></h3><p class="management-id">{{ account.accountId }}</p><p class="management-meta">版本 {{ account.revision }} · 账号启用不等于已获得项目权限</p><UiButton class="secondary-button" :disabled="busy || needsReload" @click="begin(account)">管理账号</UiButton></article></div>
  <UiDialog v-model:open="open" :title="original ? '管理账号' : '创建账号'" :busy="busy"><form class="management-form" @submit.prevent="save"><fieldset :disabled="busy || needsReload"><label>账号名称<UiInput v-model="draft.username" :readonly="!!original" required minlength="3" maxlength="128" /></label><label v-if="!original">初始密码<UiInput v-model="draft.password" type="password" autocomplete="new-password" required minlength="8" maxlength="256" /></label><label>平台角色<select v-model="draft.platformRole"><option value="NORMAL_USER">普通平台账号（项目成员/项目负责人使用）</option><option value="PLATFORM_ADMIN">平台超级管理员（管理全平台）</option></select></label><label v-if="original">账号状态<select v-model="draft.enabled"><option :value="true">已启用</option><option :value="false">已停用</option></select></label></fieldset>
    <p class="management-note">{{ draft.platformRole === 'PLATFORM_ADMIN' ? '平台超级管理员可管理全平台项目、账号和模型资产，请仅授予受信任的管理员。' : '普通平台账号用于项目成员或项目负责人登录；具体项目权限通过项目成员关系和项目角色设置，不能维护平台账号和全局模型。' }}</p><p v-if="!draft.enabled" class="management-error">将停止该账号访问所有项目；不会删除账号及业务历史。</p><p v-if="original?.accountId === session.user?.accountId" class="management-note">这是当前登录账号。降权或停用成功后，本页面将重新验证并可能退出。</p><p v-if="mutationError" role="alert" class="management-error">{{ mutationError }}</p><footer><UiButton type="button" class="secondary-button" :disabled="busy" @click="open = false">取消</UiButton><UiButton class="primary-button" :disabled="busy || needsReload" :loading="busy">{{ original ? '确认更新账号' : '确认创建账号' }}</UiButton></footer>
  </form></UiDialog>
</section></template>
