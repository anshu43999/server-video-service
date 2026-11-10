import { createRouter, createWebHistory, type RouteRecordRaw, type Router } from 'vue-router'
import AdminLayout from '../layouts/AdminLayout.vue'
import LoginView from '../features/auth/LoginView.vue'
import RestrictedView from '../features/auth/RestrictedView.vue'
import NotFoundView from '../features/navigation/NotFoundView.vue'
import AlertsView from '../features/alerts/AlertsView.vue'
import StreamsView from '../features/streams/StreamsView.vue'
import ModelsView from '../features/models/ModelsView.vue'
import RulesView from '../features/operations/RulesView.vue'
import PushView from '../features/operations/PushView.vue'
import DiagnosticsView from '../features/operations/DiagnosticsView.vue'
import DashboardView from '../features/dashboard/DashboardView.vue'
import type { UserRole } from '../api/auth'
import type { useSessionStore } from '../stores/session'
import ProjectsView from '../features/projects/ProjectsView.vue'
import PlatformProjectsView from '../features/management/PlatformProjectsView.vue'
import AccountsView from '../features/management/AccountsView.vue'
import MembersView from '../features/management/MembersView.vue'
import AuditView from '../features/management/AuditView.vue'
import { useProjectsStore } from '../stores/projects'
import ProjectModelsView from '../features/models/ProjectModelsView.vue'
import ScenesView from '../features/scenes/ScenesView.vue'
import ProjectDiagnosticsView from '../features/operations/ProjectDiagnosticsView.vue'
import KnowledgeView from '../features/advice/KnowledgeView.vue'
import AppUpdatesView from '../features/appUpdates/AppUpdatesView.vue'
import { adminHistoryBase } from './deploymentPaths'

type SessionStore = ReturnType<typeof useSessionStore>

export type NavigationIcon = 'overview' | 'dashboard' | 'streams' | 'alerts' | 'push' | 'rules' | 'models' | 'diagnostics' | 'knowledge' | 'platformProjects' | 'accounts' | 'members' | 'audit' | 'appUpdates'

declare module 'vue-router' {
  interface RouteMeta {
    title?: string
    eyebrow?: string
    description?: string
    icon?: NavigationIcon
    public?: boolean
    requiresAdmin?: boolean
    roles?: UserRole[]
    navigation?: boolean
    requiresProject?: boolean
    platformOnly?: boolean
    capability?: string
    maintenance?: boolean
  }
}

export const consoleRoutes: RouteRecordRaw[] = [
  { path: 'overview', name: 'overview', component: DashboardView, props: { dashboard: false }, meta: { title: '总览', eyebrow: 'SITE PULSE / 01', description: '现场运行摘要、关键指标与待关注事项。', icon: 'overview', roles: ['admin'], navigation: true } },
  { path: 'dashboard', name: 'dashboard', component: DashboardView, props: { dashboard: true }, meta: { title: '数据看板', eyebrow: 'OPERATIONS BOARD / 07', description: '巡检指标、告警趋势、流状态与资源负载。', icon: 'dashboard', roles: ['admin'], navigation: true } },
  { path: 'streams', name: 'streams', component: StreamsView, meta: { title: '视频流', eyebrow: 'STREAM REGISTRY / 02', description: '视频流会话、模型绑定、诊断预览与实时检测。', icon: 'streams', roles: ['admin'], navigation: true } },
  { path: 'alerts', name: 'alerts', component: AlertsView, meta: { title: '告警中心', eyebrow: 'ALERT CENTER / 03', description: '告警查询、证据查看与处置。', icon: 'alerts', roles: ['admin'], navigation: true } },
  { path: 'push', name: 'push', component: PushView, meta: { title: '报警推送', eyebrow: 'DELIVERY CHANNELS / 08', description: '报警推送渠道、投递状态与历史记录。', icon: 'push', roles: ['admin'], navigation: true } },
  { path: 'rules', name: 'rules', component: RulesView, meta: { title: '规则配置', eyebrow: 'RULE STUDIO / 04', description: '识别规则、模型结果组合、绑定关系与审计记录。', icon: 'rules', roles: ['admin'], navigation: true } },
  { path: 'models', name: 'models', component: ModelsView, meta: { title: '模型资产', eyebrow: 'MODEL CATALOG / 05', description: '模型版本、转换任务、参数档案与校准集。', icon: 'models', roles: ['admin'], navigation: true } },
  { path: 'diagnostics', name: 'diagnostics', component: DiagnosticsView, meta: { title: '系统诊断', eyebrow: 'SYSTEM HEALTH / 06', description: '服务健康、依赖状态与运行资源诊断。', icon: 'diagnostics', roles: ['admin'], navigation: true } },
]
const routeCapabilities: Record<string, string> = { overview: 'project.read', dashboard: 'project.read', streams: 'project.streams.view', alerts: 'project.alerts.read', push: 'project.read', rules: 'project.read' }
for (const route of consoleRoutes) {
  route.meta = { ...route.meta, requiresProject: Boolean(routeCapabilities[String(route.name)]), platformOnly: ['models', 'diagnostics'].includes(String(route.name)), capability: routeCapabilities[String(route.name)] }
}

export const managementRoutes: RouteRecordRaw[] = [
  { path: 'platform/alert-knowledge', name: 'system-alert-knowledge', component: KnowledgeView, props: { system: true }, meta: { title: '系统 AI 知识资料', description: '维护系统基础资料并发布固定版本，供项目继承。', icon: 'knowledge', platformOnly: true, navigation: true } },
  { path: 'platform/app-updates', name: 'app-updates', component: AppUpdatesView, meta: { title: 'App 版本管理', description: '登记、核验、发布和回退移动端安装包。', icon: 'appUpdates', platformOnly: true, navigation: true } },
  { path: 'scenes', name: 'scenes', component: ScenesView, meta: { title: '识别场景', description: '从项目模型中选择成员，配置可复用方案并管理审批状态。', icon: 'rules', requiresProject: true, capability: 'project.read', navigation: true } },
  { path: 'project-models', name: 'project-models', component: ProjectModelsView, meta: { title: '项目模型', description: '管理当前项目可用的精确模型版本，PC 与移动端清单相互独立。', icon: 'models', requiresProject: true, capability: 'project.read', navigation: true } },
  { path: 'project-diagnostics', name: 'project-diagnostics', component: ProjectDiagnosticsView, meta: { title: '项目诊断', description: '查看当前项目的运行会话、处理帧数与服务状态。', icon: 'diagnostics', requiresProject: true, capability: 'project.read', navigation: true } },
  { path: 'alert-knowledge', name: 'alert-knowledge', component: KnowledgeView, meta: { title: 'AI 知识资料', description: '维护告警类型与识别分类对应的处置参考资料。', icon: 'knowledge', requiresProject: true, capability: 'project.alert_knowledge.read', navigation: true } },
  { path: 'platform/projects', name: 'platform-projects', component: PlatformProjectsView, meta: { title: '平台项目', description: '创建项目、指定负责人并管理项目生命周期。', icon: 'platformProjects', platformOnly: true, navigation: true } },
  { path: 'platform/accounts', name: 'accounts', component: AccountsView, meta: { title: '平台账号', description: '管理平台账号身份与全局访问状态。', icon: 'accounts', platformOnly: true, navigation: true } },
  { path: 'platform/audit', name: 'platform-audit', component: AuditView, meta: { title: '平台审计', description: '查询平台账号变更、管理操作与访问拒绝记录。', icon: 'audit', platformOnly: true, navigation: true } },
  { path: 'members', name: 'members', component: MembersView, meta: { title: '项目成员', description: '维护当前项目成员、角色与负责人关系。', icon: 'members', requiresProject: true, capability: 'project.members.manage', maintenance: true, navigation: true } },
  { path: 'project-audit', name: 'project-audit', component: AuditView, meta: { title: '项目审计', description: '查询当前项目范围内的业务变更与访问记录。', icon: 'audit', requiresProject: true, capability: 'project.audit.read', maintenance: true, navigation: true } },
]
export function projectNavigationItems(capabilities: string[], platformAdmin: boolean) {
  return [...consoleRoutes, ...managementRoutes].filter(r => !r.meta?.platformOnly && capabilities.includes(r.meta?.capability ?? ''))
}

export function platformNavigationItems(platformAdmin: boolean) {
  if (!platformAdmin) return []
  return [...consoleRoutes, ...managementRoutes].filter(r => r.meta?.platformOnly)
}

export function visibleNavigationItems(role?: UserRole) {
  return consoleRoutes.filter((route) => route.meta?.navigation && role && route.meta.roles?.includes(role))
}

export function createAdminRouter() {
  return createRouter({
    history: createWebHistory(adminHistoryBase()),
    routes: [
      { path: '/login', name: 'login', component: LoginView, meta: { public: true } },
      { path: '/restricted', name: 'restricted', component: RestrictedView },
      {
        path: '/',
        component: AdminLayout,
        children: [
          { path: '', redirect: { name: 'overview' } },
          { path: 'projects', name: 'projects', component: ProjectsView, meta: { title: '项目空间', description: '选择已授权项目并验证进入权限。' } },
          ...consoleRoutes,
          ...managementRoutes,
          { path: 'engineering', redirect: { name: 'overview' } },
          { path: ':pathMatch(.*)*', name: 'unavailable', component: NotFoundView, meta: { title: '页面不存在', description: '该地址没有对应的管理后台页面。', roles: ['admin'] } },
        ],
      },
    ],
  })
}

export const router = createAdminRouter()

const guardedRouters = new WeakSet<Router>()
export function installSessionGuard(target: Router, session: SessionStore) {
  if (guardedRouters.has(target)) return
  guardedRouters.add(target)
  target.beforeEach(async (to) => {
    if (session.phase === 'idle') await session.restore()
    if (to.meta.public) {
      if (session.phase === 'authenticated') return { name: 'overview' }
      if (session.phase === 'restricted') return { name: 'restricted' }
      return true
    }
    if (!session.user) return { name: 'login', query: { redirect: to.fullPath } }
    const projects = useProjectsStore()
    if (to.meta.platformOnly) {
      if (!session.isAdmin) return { name: 'projects' }
      if (!await projects.leaveForPlatform() || !session.isAdmin || !projects.contractReady()) return { name: 'projects' }
      return true
    }
    if (to.name === 'projects') {
      if (projects.phase === 'ready') await projects.revalidate()
      else if (!['choosing', 'empty', 'unavailable', 'error'].includes(projects.phase)) await projects.enter(undefined, true)
      return true
    }
    if (to.meta.requiresProject) {
      if (to.query.project !== undefined && (typeof to.query.project !== 'string' || !to.query.project)) {
        projects.invalidate('项目链接无效，请重新选择项目')
        return { name: 'projects' }
      }
      await projects.ensure(typeof to.query.project === 'string' ? to.query.project : undefined)
      if (projects.phase !== 'ready' || !projects.current) return { name: 'projects', query: { redirect: to.fullPath } }
      if (!projects.current.capabilities.includes(to.meta.capability ?? '')) {
        if (to.name === 'overview') { projects.invalidate('当前项目没有可用权限，请联系管理员'); return { name: 'projects' } }
        return { name: 'overview', query: { project: projects.current.projectId } }
      }
      if (to.query.project !== projects.current.projectId) return { path: to.path, query: { ...to.query, project: projects.current.projectId }, hash: to.hash, replace: true }
    }
    return true
  })
}
