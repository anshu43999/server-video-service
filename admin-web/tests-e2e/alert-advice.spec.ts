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
  let entry = structuredClone(knowledge)
  const revisions: any[] = [{ revision: 1, action: 'CREATE', actor: 'owner', createdAt: now, snapshot: structuredClone(entry) }]
  await context.route('**/aiyoloapi/projects/' + fixtureProjectId + '/alert-advice/knowledge-entries**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname
    if (path.endsWith('/match-preview')) return route.fulfill({ json: { matched: entry.status === 'ACTIVE', matchKey: entry.matchKey, entry: entry.status === 'ACTIVE' ? entry : null } })
    if (path.endsWith('/revisions')) return route.fulfill({ json: { revisions } })
    if (path.endsWith('/status')) { const body = request.postDataJSON(); entry = { ...entry, status: body.status,
      revision: entry.revision + 1, updatedAt: '2026-10-27T10:05:00Z' }; revisions.push({ revision: entry.revision,
      action: entry.status === 'ACTIVE' ? 'ACTIVATE' : 'DEACTIVATE', actor: 'owner', createdAt: entry.updatedAt,
      snapshot: structuredClone(entry) }); return route.fulfill({ json: entry }) }
    if (request.method() === 'GET' && path.endsWith('/knowledge-entries')) return route.fulfill({ json: { entries: [entry] } })
    return route.fulfill({ json: entry })
  })
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

for (const width of [1440, 390]) test('production knowledge management at ' + width + 'px', async ({ context, page }) => {
  await page.setViewportSize({ width, height: width === 390 ? 844 : 960 }); await mockIdentity(context); await mockKnowledge(context)
  await page.goto(adminPath('/alert-knowledge')); await expect(page.getByRole('heading', { name: 'AI 告警知识资料' })).toBeVisible()
  const card = page.locator('.knowledge-card').filter({ hasText: '未佩戴安全帽模拟处置资料' })
  await expect(card).toContainText('PPE_NO_HELMET'); await expect(card).toContainText('MOCK KB')
  await card.getByRole('button', { name: '停用' }).click(); await expect(card).toContainText('已停用')
  await card.getByRole('button', { name: '版本' }).click(); await expect(page.getByRole('dialog')).toContainText('DEACTIVATE')
  await page.keyboard.press('Escape'); await page.getByLabel('告警类型 ID').fill('PPE_NO_HELMET')
  await page.getByLabel('识别分类 ID').fill('HEAD'); await page.getByRole('button', { name: '匹配预览' }).click()
  await expect(page.getByRole('dialog')).toContainText('未找到精确匹配资料')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: '../evidence/M41/M41-T09-knowledge-' + width + '.png', fullPage: true, animations: 'disabled' })
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
