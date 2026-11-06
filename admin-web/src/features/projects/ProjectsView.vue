<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'
import { useProjectsStore } from '../../stores/projects'
import { projectRoleLabel, type AccessibleProject } from '../../api/projects'
const projects = useProjectsStore(), router = useRouter(), route = useRoute()
async function select(project: AccessibleProject) {
  if (projects.current?.projectId === project.projectId && projects.phase === 'ready') {
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : ''
    const target = redirect.startsWith('/') && !redirect.startsWith('//') ? router.resolve(redirect) : null
    const allowed = target && target.name !== 'projects' && target.matched.some(r => r.meta.requiresProject)
    await router.replace({ name: allowed ? target.name! : 'overview', query: { ...(allowed ? target.query : {}), project: project.projectId } })
    return
  }
  await projects.enter(project.projectId)
  if (projects.phase !== 'ready') return
  const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : ''
  const target = redirect.startsWith('/') && !redirect.startsWith('//') ? router.resolve(redirect) : null
  const allowed = target && target.name !== 'projects' && target.matched.some(r => r.meta.requiresProject)
  await router.replace({ name: allowed ? target.name! : 'overview', query: { ...(allowed ? target.query : {}), project: project.projectId } })
}
</script>

<template>
  <section class="project-picker" aria-label="项目空间" :aria-busy="projects.busy">
    <p v-if="projects.message" role="alert" class="shell-alert">{{ projects.message }}</p>
    <p v-if="projects.busy" role="status">正在验证账号与项目…</p>
    <div v-else-if="projects.projects.length" class="project-grid">
      <article v-for="project in projects.projects" :key="project.projectId" class="project-card">
        <p class="eyebrow">{{ project.projectCode }}</p>
        <h3>{{ project.displayName }}</h3>
        <p>{{ projectRoleLabel(project) }}</p>
        <span class="project-state" :class="{ frozen: project.lifecycleState !== 'ACTIVE' }">{{ { ACTIVE: '运行中', SUSPENDED: '已停用 · 受限访问', ARCHIVED: '已归档 · 历史只读' }[project.lifecycleState] }}</span>
        <p v-if="project.platformEntry" class="project-entry-note">以平台管理身份进入；项目访问由服务器记录审计。</p>
        <UiButton class="primary-button" @click="select(project)">进入 {{ project.displayName }}</UiButton>
      </article>
    </div>
    <p v-else-if="projects.phase === 'empty'" role="status">请联系平台超级管理员或项目负责人分配项目成员权限。账号登录成功不代表已拥有项目权限。</p>
    <UiButton v-if="!projects.busy" class="secondary-button" @click="projects.enter(undefined, true)">重新验证项目</UiButton>
  </section>
</template>
