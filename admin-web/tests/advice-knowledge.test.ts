// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../src/api/errors'
import { projectScope } from '../src/api/projectScope'
import { adviceError, alertAdviceApi, systemKnowledgeApi, type KnowledgeEntry } from '../src/features/advice/api'
import { createAdminRouter, projectNavigationItems } from '../src/app/router'

const entry: KnowledgeEntry = {
  entryId: 'helmet', projectId: 'project-a', matchKey: { alertTypeId: 'PPE_NO_HELMET', recognitionCategoryId: 'HEAD' }, status: 'ACTIVE', revision: 2,
  title: '安全帽', riskDescription: '风险', adviceTemplate: { title: '建议', steps: [{ stepId: 'one', order: 1, title: '停止', instruction: '停止作业' }], cautions: [] },
  references: [{ referenceId: 'ref', documentTitle: '制度', documentNumber: null, documentVersion: 'v1', chapter: null, clauseId: '1', excerpt: '制度原文', sourceName: '模拟库', sourceType: 'MOCK_KNOWLEDGE_BASE', effectiveDate: null }],
  applicability: '演示', sourceType: 'MOCK_KNOWLEDGE_BASE', createdBy: 'owner', updatedBy: 'owner', createdAt: '2026-01-01T00:00:00Z', updatedAt: '2026-01-01T00:00:00Z',
}
afterEach(() => { projectScope.clear(); projectScope.enabled = false; vi.restoreAllMocks(); vi.unstubAllGlobals() })
describe('alert advice knowledge management', () => {
  it('registers a capability-scoped project route and navigation item', () => {
    expect(createAdminRouter().resolve('/alert-knowledge').name).toBe('alert-knowledge')
    expect(projectNavigationItems(['project.alert_knowledge.read'], false).map(route => route.name)).toContain('alert-knowledge')
    expect(projectNavigationItems(['project.read'], false).map(route => route.name)).not.toContain('alert-knowledge')
    expect(createAdminRouter().resolve('/platform/alert-knowledge').name).toBe('system-alert-knowledge')
  })
  it('keeps system APIs platform-scoped without inheriting the selected project path', async () => {
    projectScope.enable(); projectScope.enter('project-a')
    const fetcher = vi.fn(async (_url: RequestInfo | URL) => new Response(JSON.stringify({ entries: [], revision: 1 }), { headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetcher)
    await systemKnowledgeApi.catalog()
    expect(fetcher.mock.calls[0]?.[0]).toBe('/aiyoloapi/platform/alert-advice/knowledge-entries')
  })
  it('uses project-scoped real APIs and revision CAS without document upload fields', async () => {
    projectScope.enable(); projectScope.enter('project-a')
    const fetcher = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      const body = init?.body ? JSON.parse(String(init.body)) : undefined
      if (String(url).endsWith('/status')) return new Response(JSON.stringify({ ...entry, status: body.status, revision: 3 }), { headers: { 'Content-Type': 'application/json' } })
      if (init?.method === 'PUT') return new Response(JSON.stringify({ ...entry, revision: 3 }), { headers: { 'Content-Type': 'application/json' } })
      return new Response(JSON.stringify({ entries: [entry] }), { headers: { 'Content-Type': 'application/json' } })
    }); vi.stubGlobal('fetch', fetcher)
    expect(await alertAdviceApi.list()).toHaveLength(1)
    await alertAdviceApi.update(entry, { title: entry.title, riskDescription: entry.riskDescription, adviceTemplate: entry.adviceTemplate, references: entry.references, applicability: entry.applicability, sourceType: 'MOCK_KNOWLEDGE_BASE' })
    const update = fetcher.mock.calls[1] as unknown as [string, RequestInit]
    expect(update[0]).toBe('/aiyoloapi/projects/project-a/alert-advice/knowledge-entries/helmet')
    expect(JSON.parse(update[1].body as string).expectedRevision).toBe(2)
    expect(update[1].body).not.toContain('file')
    await alertAdviceApi.status(entry, 'INACTIVE')
    expect(JSON.parse((fetcher.mock.calls[2] as unknown as [string, RequestInit])[1].body as string)).toEqual({ status: 'INACTIVE', expectedRevision: 2 })
  })
  it('explains revision conflicts without implying an overwrite', () => {
    expect(adviceError(new ApiError({ status: 409, code: 'REVISION_CONFLICT' }))).toContain('刷新列表')
  })
})
