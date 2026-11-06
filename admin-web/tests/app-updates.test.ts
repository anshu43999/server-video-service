// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { appUpdatesApi as api, externalFields, parseNotes, updateError, PACKAGE } from '../src/features/appUpdates/api'
import { ApiError } from '../src/api/errors'
import { projectScope } from '../src/api/projectScope'
import { createAdminRouter, platformNavigationItems, projectNavigationItems } from '../src/app/router'

const scope = { contractVersion: 'app-update/v1' as const, publisherId: 'test', packageName: PACKAGE, channel: 'stable', deploymentId: 'test' }
const ok = { resourceId: 'release-a', state: 'published', revision: 7 }
afterEach(() => { projectScope.clear(); projectScope.enabled = false; vi.restoreAllMocks(); vi.unstubAllGlobals() })

describe('App release administration', () => {
  it('binds rollback preview and query to exact revision and fingerprint', async () => {
    const preview = { expectedPolicyRevision: 7, previewFingerprint: 'a'.repeat(64), expiresAt: '2026-10-29T12:00:00Z', ready: true, blockers: [], contactedDevices: 3, affectedDevices: 2, recoveryState: 'pending' }
    const operation = { operationId: 'op-a', status: 'applied', effectivePolicyRevision: 8, recoveryState: 'pending', deviceCounts: { installer_opened: 1 }, lastContactBefore: null, errorCode: null }
    const fetcher = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(preview)))
      .mockResolvedValueOnce(new Response(JSON.stringify(operation))).mockResolvedValueOnce(new Response(JSON.stringify(operation)))
    vi.stubGlobal('fetch', fetcher)
    const plan = { ...scope, expectedPolicyRevision: 7, affectedReleaseIds: ['bad-a'], stableReleaseId: 'stable-a', recoveryReleaseId: null }
    expect(await api.rollbackPreview(plan)).toEqual(preview)
    await api.rollback({ ...plan, idempotencyKey: 'retry', reason: 'halt', previewFingerprint: preview.previewFingerprint })
    expect((await api.rollbackOperation('op-a')).deviceCounts).toEqual({ installer_opened: 1 })
    expect(JSON.parse(fetcher.mock.calls[1]![1].body)).toMatchObject({ ...plan, previewFingerprint: 'a'.repeat(64) })
    expect(fetcher.mock.calls[2]![0]).toBe('/aiyoloapi/admin/app-updates/rollbacks/op-a')
  })
  it('exposes a platform route with no project-role menu', () => {
    expect(createAdminRouter().resolve('/platform/app-updates').meta.platformOnly).toBe(true)
    expect(platformNavigationItems(true).map(r => r.name)).toContain('app-updates')
    expect(platformNavigationItems(false)).toEqual([])
    expect(projectNavigationItems(['project.read', 'project.settings.manage'], false).map(r => r.name)).not.toContain('app-updates')
  })
  it('sends scope, source revision, policy CAS and stable idempotency directly to same-origin APIs', async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify(ok), { headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetcher); projectScope.enable(); projectScope.enter('project-a')
    const body = { ...scope, releaseId: 'release-a', expectedPolicyRevision: 6, sourceId: 'source-a', sourceRevision: 2, minSupportedVersionCode: 1, restrictedCapabilities: [], idempotencyKey: 'retry-key', reason: 'release' }
    await api.publish(body); await api.publish(body)
    const calls = fetcher.mock.calls as unknown as [string, RequestInit][]
    expect(calls[0]![0]).toBe('/aiyoloapi/admin/app-updates/releases/release-a/publish')
    expect(JSON.parse(String(calls[0]![1].body))).toEqual(body)
    expect(calls[0]![1].body).toBe(calls[1]![1].body)
    expect(calls[0]![1].credentials).toBe('same-origin')
    await api.addSource('apk-a', { packageName: PACKAGE, ...externalFields('https://cdn.example/a.apk', 'cdn.example'), expectedArtifactSha256: 'a'.repeat(64), reason: 'mirror', idempotencyKey: 'mirror-key' })
    expect(JSON.parse(String(calls[2]![1].body)).expectedArtifactSha256).toBe('a'.repeat(64))
  })
  it('rejects malformed list/details before rendering and accepts retired sources', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ items: [{}], nextCursor: null })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ resourceId: 'a', revision: 1, state: 'verified', resourceType: 'artifact', details: {} })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: [{ resourceId: 's', revision: 1, state: 'retired', resourceType: 'source', details: { allowedDownloadHosts: ['cdn.example'], storageMode: 'external' } }], nextCursor: null })))
    vi.stubGlobal('fetch', fetcher)
    await expect(api.list('artifacts')).rejects.toMatchObject({ kind: 'invalid-response' })
    await expect(api.artifact('a')).rejects.toMatchObject({ kind: 'invalid-response' })
    expect((await api.sources('a')).items[0]!.state).toBe('retired')
  })
  it('keeps notes plain text with bounded lines and validates public HTTPS fields', () => {
    expect(parseNotes(' one\r\n\n<script>plain</script> ')).toEqual(['one', '<script>plain</script>'])
    expect(() => parseNotes('x\n'.repeat(31))).toThrow()
    expect(() => parseNotes('x'.repeat(2001))).toThrow()
    for (const url of ['http://cdn.example/a.apk', 'https://u:p@cdn.example/a.apk', 'https://cdn.example/a.apk#x', 'https://cdn.example:444/a.apk', 'https://other.example/a.apk']) expect(() => externalFields(url, 'cdn.example')).toThrow()
    expect(externalFields('https://cdn.example/a.apk', 'cdn.example，mirror.example\ncdn.example').allowedDownloadHosts).toEqual(['cdn.example', 'mirror.example'])
  })
  it('does not echo submitted URLs and explains CAS conflicts', () => {
    expect(updateError(new ApiError({ status: 500, message: 'https://secret.example/a.apk?secret=abc' }))).not.toContain('secret')
    expect(updateError(new ApiError({ status: 409, code: 'policy_revision_conflict' }))).toContain('刷新')
  })
})

class FakeXHR {
  static latest: FakeXHR
  upload: { onprogress?: (e: any) => void } = {}
  onabort?: () => void; onload?: () => void; onerror?: () => void; ontimeout?: () => void
  responseText = JSON.stringify(ok); status = 202; timeout = 0
  method = ''; url = ''; body?: FormData
  constructor() { FakeXHR.latest = this }
  open(method: string, url: string) { this.method = method; this.url = url }
  send(body: FormData) { this.body = body }
  abort() { this.onabort?.() }
  getResponseHeader() { return null }
}
describe('multipart APK transfer', () => {
  it('sends native form fields, reports bytes, and waits for a real response after 100%', async () => {
    vi.stubGlobal('XMLHttpRequest', FakeXHR)
    const progress = vi.fn(), file = new File(['apk'], 'release.apk')
    const promise = api.upload(file, { idempotencyKey: 'upload-key', reason: 'test' }, { onProgress: progress })
    const xhr = FakeXHR.latest
    expect(xhr.url).toBe('/aiyoloapi/admin/app-updates/artifacts/upload')
    expect(xhr.body!.get('idempotencyKey')).toBe('upload-key')
    expect(xhr.body!.get('reason')).toBe('test')
    expect((xhr.body!.get('apk') as File).name).toBe('release.apk')
    xhr.upload.onprogress!({ lengthComputable: true, loaded: 5, total: 10 }); expect(progress).toHaveBeenLastCalledWith(50)
    let settled = false; void promise.then(() => { settled = true })
    xhr.upload.onprogress!({ lengthComputable: true, loaded: 10, total: 10 }); await Promise.resolve(); expect(settled).toBe(false)
    xhr.onload!(); await expect(promise).resolves.toEqual(ok)
  })
  it('cancels uploads on user abort and identity changes', async () => {
    vi.stubGlobal('XMLHttpRequest', FakeXHR)
    const controller = new AbortController()
    const pending = api.upload(new File(['x'], 'a.apk'), { idempotencyKey: 'a', reason: 'test' }, { signal: controller.signal })
    controller.abort(); await expect(pending).rejects.toMatchObject({ kind: 'cancelled' })
    projectScope.enable()
    const next = api.upload(new File(['x'], 'a.apk'), { idempotencyKey: 'b', reason: 'test' })
    projectScope.clear(); await expect(next).rejects.toMatchObject({ kind: 'cancelled' })
  })
})
