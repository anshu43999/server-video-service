<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch, type Component } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import {
  Activity, BellRing, Boxes, ChartNoAxesCombined, ChevronRight, CircleGauge,
  LogOut, Menu, Radio, Send, ShieldCheck, UserRound, Workflow, X, UsersRound, ClipboardList, FolderKanban, BookOpenCheck,
} from '@lucide/vue'
import { platformNavigationItems, projectNavigationItems, type NavigationIcon } from '../app/router'
import { useSessionStore } from '../stores/session'
import { useProjectsStore } from '../stores/projects'
import { projectRoleLabel } from '../api/projects'
import { platformRoleLabel } from '../api/auth'
import ProjectsView from '../features/projects/ProjectsView.vue'
import AlertNotifications from '../features/alerts/AlertNotifications.vue'

const route = useRoute()
const router = useRouter()
const session = useSessionStore()
const projects = useProjectsStore()
const drawerOpen = ref(false)
const loggingOut = ref(false)
const menuButton = ref<HTMLButtonElement>()
const sidebar = ref<HTMLElement>()

const iconMap: Record<NavigationIcon, Component> = {
  overview: CircleGauge,
  dashboard: ChartNoAxesCombined,
  streams: Radio,
  alerts: BellRing,
  push: Send,
  rules: Workflow,
  models: Boxes,
  diagnostics: Activity,
  knowledge: BookOpenCheck,
  platformProjects: FolderKanban,
  accounts: UserRound,
  members: UsersRound,
  audit: ClipboardList,
  appUpdates: Boxes,
}
const navigation = computed(() => projectNavigationItems(projects.current?.capabilities ?? [], session.isAdmin))
const platformNavigation = computed(() => platformNavigationItems(session.isAdmin))
const showPage = computed(() => session.phase === 'authenticated' && (['projects', 'unavailable'].includes(String(route.name)) || (route.meta.platformOnly ? session.isAdmin && projects.platformReady : projects.phase === 'ready' && projects.current?.projectId === route.query.project && projects.current.capabilities.includes(route.meta.capability ?? ''))))
async function chooseProject() { await projects.enter(undefined, true); await router.replace({ name: 'projects' }) }
const pageTitle = computed(() => route.meta.title ?? '管理后台')
const pageDescription = computed(() => route.meta.description ?? '查看当前管理范围内的业务数据与操作状态。')
const isPreview = import.meta.env.BASE_URL === '/admin-next/'

async function setDrawer(open: boolean, restoreFocus = false) {
  drawerOpen.value = open
  await nextTick()
  if (open) sidebar.value?.querySelector<HTMLElement>('.nav-link')?.focus({ preventScroll: true })
  else if (restoreFocus) menuButton.value?.focus()
}

function handleEscape(event: KeyboardEvent) {
  if (event.key === 'Escape' && drawerOpen.value) void setDrawer(false, true)
}

async function logout() {
  loggingOut.value = true
  try {
    await session.logout()
    await router.replace({ name: 'login' })
  } catch {
    // The session store exposes the unconfirmed state without discarding identity.
  } finally {
    loggingOut.value = false
  }
}

watch(() => route.fullPath, () => { drawerOpen.value = false })
watch(drawerOpen, (open) => document.body.classList.toggle('nav-open', open))
onMounted(() => window.addEventListener('keydown', handleEscape))
onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleEscape)
  document.body.classList.remove('nav-open')
})
</script>

<template>
  <div class="admin-shell">
    <UiButton v-if="drawerOpen" class="nav-scrim" type="button" aria-label="关闭导航" @click="setDrawer(false, true)"></UiButton>
    <aside id="primary-navigation" ref="sidebar" class="sidebar" :class="{ 'is-open': drawerOpen }">
      <div class="brand-lockup">
        <span class="brand-symbol" aria-hidden="true"><ShieldCheck :size="22" /></span>
        <span><strong>智慧巡检平台</strong><small>AI 移动巡检管理台</small></span>
        <UiButton class="icon-button sidebar-close" type="button" aria-label="关闭导航" @click="setDrawer(false, true)"><X :size="20" /></UiButton>
      </div>

      <nav class="primary-nav" aria-label="管理后台主导航">
        <RouterLink class="nav-link" :to="{ name: 'projects' }"><Boxes :size="18" aria-hidden="true" /><span>项目空间</span><ChevronRight class="nav-chevron" :size="15" aria-hidden="true" /></RouterLink>
        <section v-if="navigation.length" class="nav-group" aria-label="当前项目菜单">
          <p class="nav-section-label">当前项目</p>
          <RouterLink
            v-for="item in navigation"
            :key="String(item.name)"
            class="nav-link"
            :to="{ name: item.name, query: item.meta?.requiresProject && projects.current ? { project: projects.current.projectId } : {} }"
          >
            <component :is="iconMap[item.meta?.icon as NavigationIcon]" :size="18" aria-hidden="true" />
            <span>{{ item.meta?.title }}</span>
            <ChevronRight class="nav-chevron" :size="15" aria-hidden="true" />
          </RouterLink>
        </section>
        <section v-if="platformNavigation.length" class="nav-group nav-group-platform" aria-label="平台管理菜单">
          <p class="nav-section-label">平台管理</p>
          <RouterLink
            v-for="item in platformNavigation"
            :key="String(item.name)"
            class="nav-link"
            :to="{ name: item.name }"
          >
            <component :is="iconMap[item.meta?.icon as NavigationIcon]" :size="18" aria-hidden="true" />
            <span>{{ item.meta?.title }}</span>
            <ChevronRight class="nav-chevron" :size="15" aria-hidden="true" />
          </RouterLink>
        </section>
      </nav>

      <div class="sidebar-foot">
        <span class="environment-badge"><i aria-hidden="true"></i>{{ isPreview ? '预览构建' : '管理控制台' }}</span>
        <p>数据与操作结果以服务器返回为准。</p>
        <a v-if="isPreview" class="stable-link" href="/admin/">打开正式后台 ↗</a>
      </div>
    </aside>

    <div class="shell-body">
      <header class="topbar">
        <div class="topbar-title">
          <UiButton
            ref="menuButton"
            class="icon-button menu-button"
            type="button"
            aria-label="打开导航"
            aria-controls="primary-navigation"
            :aria-expanded="drawerOpen"
            @click="setDrawer(true)"
          ><Menu :size="21" /></UiButton>
          <div>
            <nav class="breadcrumbs" aria-label="面包屑"><span>管理后台</span><ChevronRight :size="13" aria-hidden="true" /><span aria-current="page">{{ pageTitle }}</span></nav>
            <h1>{{ pageTitle }}</h1>
            <p class="topbar-description">{{ pageDescription }}</p>
          </div>
        </div>
        <div class="account-area">
          <span class="service-state"><i aria-hidden="true"></i>会话已验证</span>
          <span class="account-identity"><UserRound :size="17" aria-hidden="true" /><span><strong>{{ session.user?.username }}</strong><small>{{ platformRoleLabel(session.user?.platformRole) }}</small></span></span>
          <UiButton class="icon-button" type="button" :disabled="loggingOut" :title="loggingOut ? '正在退出' : '退出登录'" aria-label="退出登录" @click="logout"><LogOut :size="18" /></UiButton>
        </div>
      </header>
      <section class="project-context-bar" aria-label="当前项目上下文" aria-live="polite">
        <div><span class="eyebrow">{{ route.meta.platformOnly ? 'PLATFORM / 平台管理区' : 'CURRENT PROJECT / 当前项目' }}</span><strong>{{ projects.current?.displayName ?? (route.meta.platformOnly ? '全局平台资源' : '尚未进入项目') }}</strong><small v-if="projects.current">{{ projectRoleLabel(projects.current) }} · {{ projects.current.projectCode }}</small></div>
        <UiButton class="secondary-button" :disabled="projects.busy" @click="chooseProject">{{ projects.busy ? '正在验证…' : '切换项目' }}</UiButton>
      </section>
      <p v-if="projects.current && projects.current.lifecycleState !== 'ACTIVE'" class="shell-alert" role="status">{{ projects.current.lifecycleState === 'SUSPENDED' ? '项目已停用：可查询历史与维护获准配置，实时播放和业务写入已停止。' : '项目已归档：仅显示获准历史数据，所有维护操作均已关闭。' }}</p>

      <p v-if="session.logoutUnconfirmed" class="shell-alert" role="alert">{{ session.message }}</p>
      <AlertNotifications />
      <main id="main-content" class="page-content" tabindex="-1">
        <RouterView v-if="showPage" v-slot="{ Component }"><component :is="Component" :key="`${projects.epoch}:${route.path}`" /></RouterView>
        <section v-else-if="projects.current && projects.current.lifecycleState !== 'ACTIVE'" class="project-picker" role="status"><h2>项目业务已暂停</h2><p>已停止该项目的实时连接、媒体预览和业务操作。可切换到其他项目，或联系平台超级管理员处理项目状态。</p><UiButton class="secondary-button" @click="chooseProject">返回项目空间</UiButton></section>
        <ProjectsView v-else />
      </main>
    </div>
  </div>
</template>
