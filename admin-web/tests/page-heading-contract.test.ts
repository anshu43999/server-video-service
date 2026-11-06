// @vitest-environment happy-dom
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const source = (path: string) => readFileSync(resolve(import.meta.dirname, '../src', path), 'utf8')

describe('page heading ownership', () => {
  it('keeps the current route title and description in the shell header', () => {
    const layout = source('layouts/AdminLayout.vue')
    expect(layout).toContain('<h1>{{ pageTitle }}</h1>')
    expect(layout).toContain('{{ pageDescription }}')
  })

  it('does not repeat route titles in main page headers', () => {
    const pages = [
      ['features/dashboard/DashboardView.vue', '现场总览'],
      ['features/streams/StreamsView.vue', '视频流工作台'],
      ['features/alerts/AlertsView.vue', '事件处置'],
      ['features/models/ModelsView.vue', '模型资产工作台'],
      ['features/models/ProjectModelsView.vue', '项目模型'],
      ['features/scenes/ScenesView.vue', '项目场景'],
      ['features/management/AccountsView.vue', '平台账号管理'],
      ['features/management/MembersView.vue', '项目成员管理'],
      ['features/management/PlatformProjectsView.vue', '平台项目管理'],
      ['features/management/AuditView.vue', '项目审计'],
      ['features/operations/RulesView.vue', '规则配置'],
      ['features/operations/PushView.vue', '报警推送'],
      ['features/operations/DiagnosticsView.vue', '系统诊断'],
      ['features/operations/ProjectDiagnosticsView.vue', '项目诊断'],
      ['features/advice/KnowledgeView.vue', 'AI 告警知识资料'],
      ['features/appUpdates/AppUpdatesView.vue', '让每一次升级都有据可查'],
      ['features/projects/ProjectsView.vue', '选择项目空间'],
    ] as const
    for (const [path, duplicate] of pages) {
      const view = source(path)
      const pageHeadings = [...view.matchAll(/<h[12][^>]*>([\s\S]*?)<\/h[12]>/g)].map(match => match[1]?.replace(/<[^>]+>/g, '').trim())
      expect(pageHeadings, path).not.toContain(duplicate)
    }
  })
})
