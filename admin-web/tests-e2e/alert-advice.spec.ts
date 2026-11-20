import { expect, test, type BrowserContext } from '@playwright/test'
import { adminPath } from './helpers/navigation'
import { fixtureProject, fixtureProjectId, fixtureUser } from './helpers/project-fixture'

const project = { ...fixtureProject, capabilities: [...fixtureProject.capabilities,
  'project.alert_knowledge.read', 'project.alert_knowledge.manage', 'project.alert_advice.generate',
  'project.alert_advice.read', 'project.alert_advice.history.read'] }
const now = '2026-10-27T10:00:00Z'
const reference = { referenceId: 'helmet-rule-1', documentTitle: '作业现场安全管理制度',
  documentNumber: 'MOCK-SAFE-01', documentVersion: '演示版 v1', chapter: '个体防护',
  clauseId: '第 3.2 条', excerpt: '进入作业区域应正确佩戴安全帽。',
  sourceName: 'AI YOLO 演示模拟知识库', sourceType: 'MOCK_KNOWLEDGE_BASE', effectiveDate: null }
const knowledge: any = { entryId: 'mock-ppe-no-helmet-head', projectId: fixtureProjectId,
  matchKey: { alertTypeId: 'PPE_NO_HELMET', recognitionCategoryId: 'HEAD' }, status: 'ACTIVE', revision: 1,
  title: '未佩戴安全帽模拟处置资料', riskDescription: '头部暴露于坠落物和碰撞风险。',
  adviceTemplate: { title: '安全帽告警处置建议', steps: [
    { stepId: 'stop', order: 1, title: '暂停相关作业', instruction: '通知人员离开风险区域并暂停作业。' },
    { stepId: 'ppe', order: 2, title: '核验防护用品', instruction: '确认安全帽完好并正确佩戴。' }],
    cautions: ['本内容为模拟建议，不构成违规认定。'] }, references: [reference],
  applicability: '适用于作业区域内未佩戴安全帽告警。', sourceType: 'MOCK_KNOWLEDGE_BASE',
  createdBy: 'owner', updatedBy: 'owner', createdAt: now, updatedAt: now }

function event(eventId: string, name: string) { return { eventId, projectId: fixtureProjectId,
  displayName: name, ruleId: 'PPE_NO_HELMET', alertTypeId: 'PPE_NO_HELMET',
  recognitionCategoryId: 'HEAD', label: 'HEAD', sourceId: 'camera-gate', origin: 'SERVER_STREAM',
  state: 'CONFIRMED', severity: 'MAJOR', notifySeverity: 'MAJOR', confirmedAtUs: 1750000123456789,
  evidence: {}, disposition: { status: 'OPEN', actor: null, actedAtUs: null } } }
const events = [event('advice-generated', '安全帽告警 · 成功'), event('advice-partial', '安全帽告警 · 部分结果'),
  event('advice-no-match', '安全帽告警 · 无匹配'), event('advice-failure', '安全帽告警 · 请求失败')]

function result(eventId: string, status: string, sequence: number): any {
  const hasAdvice = status === 'GENERATED', hasReferences = hasAdvice || status === 'PARTIAL'
  return { contractVersion: '1.0', generationId: eventId + '-g-' + sequence, projectId: fixtureProjectId,
    eventId, requestedBy: 'fixture-admin', idempotencyKey: '11111111-1111-4111-8111-111111111111',
    retryOfGenerationId: null, status, matchKey: { alertTypeId: 'PPE_NO_HELMET', recognitionCategoryId: 'HEAD' },
    advice: hasAdvice ? knowledge.adviceTemplate : null, references: hasReferences ? [reference] : [],
    knowledgeRevision: hasReferences ? 1 : null, retrievalProvider: 'SIMULATED_KNOWLEDGE_BASE',
    generationProvider: 'SIMULATED_LLM', sourceNotice: '这是模拟知识资料与模拟大模型生成结果，仅供流程演示。',
    reasonCode: status === 'NO_MATCH' ? 'KNOWLEDGE_NOT_MATCHED' : status === 'PARTIAL' ? 'GENERATION_FAILED' : null,
    error: status === 'PARTIAL' ? { code: 'GENERATION_FAILED', message: '模拟生成失败' } : null,
    createdAt: now, completedAt: now }
}

async function mockIdentity(context: BrowserContext) {
  await context.route('**/aiyoloapi/auth/status', route => route.fulfill({ json: { setupRequired: false,
    authenticated: true, user: { username: 'visual-admin', role: 'admin' } } }))
  await context.route('**/aiyoloapi/auth/me', route => route.fulfill({ json: fixtureUser() }))
  await context.route('**/aiyoloapi/auth/projects', route => route.fulfill({ json: { contractVersion: 'm33-v1', projects: [project] } }))
  await context.route('**/aiyoloapi/projects/' + fixtureProjectId, route => route.fulfill({ json: project }))
}

async function mockKnowledge(context: BrowserContext) {
  let draft = { ...structuredClone(knowledge), origin: 'SYSTEM', projectId: 'system', systemVersion: null }
  let published = { ...structuredClone(knowledge), entryId: 'system:' + knowledge.entryId, origin: 'SYSTEM', systemVersion: 1 }
  let revision = 1, version = 1, projectWrites = 0
  const versions = [{ version, catalogRevision: revision, notes: 'Initial', publishedBy: 'admin', publishedAt: now, entryCount: 1 }]
  const revisions: any[] = [{ revision: 1, action: 'CREATE', actor: 'admin', createdAt: now, snapshot: structuredClone(draft) }]
  await context.route('**/aiyoloapi/projects/' + fixtureProjectId + '/alert-advice/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname
    if (path.endsWith('/match-preview')) return route.fulfill({ json: { matched: published.status === 'ACTIVE', matchKey: published.matchKey, entry: published.status === 'ACTIVE' ? published : null } })
    if (request.method() !== 'GET') { projectWrites++; return route.fulfill({ status: 410, json: { detail: { code: 'PROJECT_KNOWLEDGE_READ_ONLY' } } }) }
    if (path.endsWith('/revisions')) return route.fulfill({ json: { revisions: [{ revision: published.revision, action: 'PUBLISHED', actor: 'admin', createdAt: now, snapshot: published }] } })
    if (path.endsWith('/knowledge-entries')) return route.fulfill({ json: { entries: [published], systemVersion: version } })
    return route.fulfill({ json: published })
  })
  await context.route('**/aiyoloapi/platform/alert-advice/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname
    if (path.endsWith('/versions')) return route.fulfill({ json: { versions } })
    if (path.endsWith('/publish')) {
      expect(request.postDataJSON().expectedRevision).toBe(revision)
      version++; revision++
      published = { ...structuredClone(draft), entryId: 'system:' + draft.entryId, projectId: fixtureProjectId, systemVersion: version }
      versions.push({ version, catalogRevision: revision - 1, notes: 'Published', publishedBy: 'admin', publishedAt: now, entryCount: 1 })
      return route.fulfill({ json: { ...versions.at(-1), entries: [published] } })
    }
    if (path.endsWith('/status')) {
      expect(request.postDataJSON().expectedRevision).toBe(draft.revision)
      draft = { ...draft, status: request.postDataJSON().status, revision: draft.revision + 1 }; revision++
      revisions.push({ revision: draft.revision, action: 'DEACTIVATE', actor: 'admin', createdAt: now, snapshot: structuredClone(draft) })
      return route.fulfill({ json: draft })
    }
    if (request.method() === 'PUT') {
      draft = { ...draft, ...request.postDataJSON(), revision: draft.revision + 1 }; revision++
      return route.fulfill({ json: draft })
    }
    if (path.endsWith('/revisions')) return route.fulfill({ json: { revisions } })
    return route.fulfill({ json: { entries: [draft], revision } })
  })
  return { projectWrites: () => projectWrites }
}

async function mockAlerts(context: BrowserContext) {
  const posts = new Map<string, number>(), histories = new Map<string, any[]>(); let dispositionWrites = 0
  await context.route('**/aiyoloapi/projects/' + fixtureProjectId + '/alerts**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname
    const prefix = '/aiyoloapi/projects/' + fixtureProjectId + '/alerts'
    if (path === prefix) return route.fulfill({ json: { events } })
    const match = path.slice(prefix.length).match(/^\/([^/]+)(?:\/(.*))?$/)
    const eventId = match ? decodeURIComponent(match[1]) : '', suffix = match?.[2] ?? ''
    const alert = events.find(item => item.eventId === eventId)
    if (!alert) return route.fulfill({ status: 404, json: { detail: { code: 'EVENT_NOT_FOUND' } } })
    if (suffix === 'evidence') return route.fulfill({ status: 404, json: { detail: { code: 'evidence_not_found' } } })
    if (suffix === 'verification') return route.fulfill({ json: { eventId, status: 'UNREVIEWED', verdict: null } })
    if (suffix === 'acknowledge' || suffix === 'false-positive') { dispositionWrites += 1; return route.fulfill({ json: alert }) }
    if (suffix === 'advice-generations' && request.method() === 'POST') { const count = (posts.get(eventId) ?? 0) + 1
      posts.set(eventId, count); if (eventId === 'advice-failure' && count === 1) return route.fulfill({ status: 503,
        json: { detail: { code: 'ADVICE_UNAVAILABLE', message: '模拟服务暂不可用' } } })
      const status = eventId === 'advice-no-match' ? 'NO_MATCH' : eventId === 'advice-partial' && count === 1 ? 'PARTIAL' : 'GENERATED'
      const item = result(eventId, status, count); histories.set(eventId, [item, ...(histories.get(eventId) ?? [])])
      return route.fulfill({ status: 201, json: item }) }
    if (suffix === 'advice-generations' && request.method() === 'GET') return route.fulfill({ json: { generations: histories.get(eventId) ?? [] } })
    if (suffix === 'advice-generations/latest') {
      const latest = histories.get(eventId)?.[0]
      return latest ? route.fulfill({ json: latest }) : route.fulfill({ status: 404, json: { detail: { code: 'ADVICE_GENERATION_NOT_FOUND' } } })
    }
    return route.fulfill({ json: alert })
  })
  return { posts, dispositionWrites: () => dispositionWrites }
}

for (const width of [1440, 390]) test('production knowledge readonly at ' + width + 'px', async ({ context, page }, testInfo) => {
  await page.setViewportSize({ width, height: width === 390 ? 844 : 960 }); await mockIdentity(context); const calls = await mockKnowledge(context)
  await page.goto(adminPath('/alert-knowledge')); await expect(page.getByRole('heading', { name: 'AI 知识资料', exact: true })).toBeVisible()
  const card = page.locator('.knowledge-card').filter({ hasText: '未佩戴安全帽模拟处置资料' })
  await expect(card).toContainText('PPE_NO_HELMET'); await expect(card).toContainText('系统统一 V1')
  await expect(page.getByRole('button', { name: /编辑|停用|启用|新增|升级|覆盖|发布系统/ })).toHaveCount(0)
  await card.getByRole('button', { name: '查看详情' }).click(); await expect(page.getByRole('dialog')).toContainText('作业现场安全管理制度')
  await page.keyboard.press('Escape')
  await card.getByRole('button', { name: '版本' }).click(); await expect(page.getByRole('dialog')).toContainText('PUBLISHED')
  await page.keyboard.press('Escape'); await page.getByLabel('告警类型 ID').fill('PPE_NO_HELMET')
  await page.getByLabel('识别分类 ID').fill('HEAD'); await page.getByRole('button', { name: '匹配预览' }).click()
  await expect(page.getByRole('dialog')).toContainText('找到精确匹配资料')
  expect(calls.projectWrites()).toBe(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('knowledge.png'), fullPage: true, animations: 'disabled' })
})

test('production knowledge system maintenance and global publication', async ({ context, page }) => {
  await mockIdentity(context); const calls = await mockKnowledge(context)
  await page.goto(adminPath('/platform/alert-knowledge'))
  const card = page.locator('.knowledge-card')
  await card.getByRole('button', { name: '编辑', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('资料标题', { exact: true }).fill('统一系统资料更新')
  await dialog.getByRole('button', { name: '保存资料' }).click()
  await expect(card).toContainText('统一系统资料更新')
  await card.getByRole('button', { name: '停用', exact: true }).click(); await expect(card).toContainText('已停用')
  await page.goto(adminPath('/alert-knowledge'))
  await expect(card).toContainText('未佩戴安全帽模拟处置资料'); await expect(card).toContainText('参与匹配')
  await page.goto(adminPath('/platform/alert-knowledge'))
  await page.getByRole('button', { name: '发布系统版本' }).click()
  await page.getByLabel('发布说明').fill('对所有项目生效')
  await page.getByRole('button', { name: '确认发布' }).click()
  await expect(page.getByRole('status')).toContainText('已发布系统版本')
  await page.goto(adminPath('/alert-knowledge'))
  await expect(card).toContainText('统一系统资料更新'); await expect(card).toContainText('已停用'); await expect(card).toContainText('系统统一 V2')
  expect(calls.projectWrites()).toBe(0)
})

for (const width of [1440, 390]) test('production advice states at ' + width + 'px', async ({ context, page }) => {
  await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 }); await mockIdentity(context); const calls = await mockAlerts(context)
  await page.goto(adminPath('/alerts'))
  async function open(name: string) { await page.locator('.alert-event-row').filter({ hasText: name }).click(); return page.getByRole('dialog', { name }) }
  let detail = await open('安全帽告警 · 成功'); await expect(detail.getByText('打开详情只读取已保存结果；仅点击生成或重新生成才调用生成服务。')).toBeVisible()
  expect(calls.posts.get('advice-generated') ?? 0).toBe(0); await detail.getByRole('button', { name: '生成建议', exact: true }).click()
  await expect(detail.getByText('已生成')).toBeVisible(); await expect(detail.getByRole('heading', { name: '可能相关的制度依据' })).toBeVisible()
  await detail.getByRole('button', { name: '历史' }).click(); await expect(page.getByRole('region', { name: 'AI 建议历史' })).toContainText('GENERATED')
  await page.getByRole('button', { name: '关闭建议历史' }).click(); await detail.getByRole('button', { name: '关闭告警详情' }).click()
  detail = await open('安全帽告警 · 成功'); await expect(detail.getByText('已生成', { exact: true })).toBeVisible()
  expect(calls.posts.get('advice-generated')).toBe(1)
  await detail.getByRole('button', { name: '重新生成' }).click()
  await expect(detail.getByRole('button', { name: '重新生成' })).toBeVisible()
  await detail.getByRole('button', { name: '历史', exact: true }).click()
  await expect(page.locator('.advice-history article')).toHaveCount(2)
  expect(calls.posts.get('advice-generated')).toBe(2)
  await page.getByRole('button', { name: '关闭建议历史' }).click(); await detail.getByRole('button', { name: '关闭告警详情' }).click()
  detail = await open('安全帽告警 · 部分结果'); await detail.getByRole('button', { name: '生成建议', exact: true }).click()
  await expect(detail.getByText('部分结果', { exact: true })).toBeVisible(); await detail.getByRole('button', { name: '重试生成' }).click(); await expect(detail.getByText('已生成', { exact: true })).toBeVisible()
  await detail.getByRole('button', { name: '关闭告警详情' }).click(); detail = await open('安全帽告警 · 无匹配')
  await detail.getByRole('button', { name: '生成建议', exact: true }).click(); await expect(detail.getByText('无精确匹配')).toBeVisible()
  await detail.getByRole('button', { name: '关闭告警详情' }).click(); detail = await open('安全帽告警 · 请求失败')
  await detail.getByRole('button', { name: '生成建议', exact: true }).click(); await expect(detail.getByText('建议请求失败')).toBeVisible()
  await detail.getByRole('button', { name: '重试请求' }).click(); await expect(detail.getByText('已生成')).toBeVisible()
  expect(calls.dispositionWrites()).toBe(0); expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: '../evidence/M41/M41-T09-advice-' + width + '.png', fullPage: true, animations: 'disabled' })
})
