// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import ExternalReleaseWizard from '../src/features/appUpdates/ExternalReleaseWizard.vue'
import { appUpdatesApi as api, PACKAGE, type Artifact } from '../src/features/appUpdates/api'
import { ApiError } from '../src/api/errors'

const scope = { contractVersion: 'app-update/v1' as const, publisherId: 'test', packageName: PACKAGE, channel: 'stable', deploymentId: 'test' }
const artifact = { resourceId: 'apk-2', state: 'verified', revision: 1, resourceType: 'artifact', details: { versionName: '1.1.0', versionCode: 2, publisherId: 'test', sha256: 'a'.repeat(64), signerSha256: 'b'.repeat(64), sizeBytes: 120, jobs: [] } } as unknown as Artifact
let wrapper: VueWrapper
afterEach(() => { wrapper?.unmount(); vi.restoreAllMocks(); vi.useRealTimers() })
async function setup(scopes = [scope]) {
  wrapper = mount(ExternalReleaseWizard, { props: { configuration: { scopes, gateCapabilities: [], maxApkBytes: 10000, uploadEnabled: false, externalEnabled: true } }, global: { stubs: { UiButton: { props: ['type', 'disabled'], template: '<button :type="type" :disabled="disabled"><slot /></button>' } } } })
  const inputs = wrapper.findAll('input')
  await inputs[0]!.setValue('1.1.0'); await inputs[1]!.setValue('2'); await inputs[2]!.setValue('https://cdn.example.com/app.apk')
  await wrapper.findAll('textarea').at(-1)!.setValue('手工托管发布')
}
it('registers external bytes without MinIO, compares real versions, then explicitly creates only a draft', async () => {
  const external = vi.spyOn(api, 'external').mockResolvedValue({ resourceId: 'apk-2', state: 'pending', revision: 1 })
  vi.spyOn(api, 'artifact').mockResolvedValue(artifact)
  const draft = vi.spyOn(api, 'draft').mockResolvedValue({ resourceId: 'release-2', state: 'draft', revision: 1 })
  await setup(); await wrapper.find('form').trigger('submit'); await flushPromises()
  expect(external.mock.calls[0]![0]).toMatchObject({ downloadUrl: 'https://cdn.example.com/app.apk', allowedDownloadHosts: ['cdn.example.com'] })
  expect(draft).not.toHaveBeenCalled(); expect(wrapper.text()).toContain('APK 核验通过')
  await wrapper.findAll('input')[1]!.setValue('3'); await wrapper.find('form').trigger('submit'); await flushPromises()
  expect(wrapper.text()).toContain('与 APK 不一致'); expect(draft).not.toHaveBeenCalled()
  await wrapper.findAll('input')[1]!.setValue('2'); await wrapper.find('form').trigger('submit'); await flushPromises()
  expect(draft.mock.calls[0]![0]).toMatchObject({ ...scope, artifactId: 'apk-2', importance: 'normal' })
  expect(wrapper.emitted('created')![0]).toEqual(['release-2'])
})
it('reuses idempotency after uncertain transport and does not duplicate a busy request', async () => {
  const external = vi.spyOn(api, 'external').mockRejectedValueOnce(new ApiError({ kind: 'network' })).mockResolvedValue({ resourceId: 'apk-2', state: 'pending', revision: 1 })
  vi.spyOn(api, 'artifact').mockResolvedValue(artifact)
  await setup(); await wrapper.find('form').trigger('submit'); await flushPromises()
  await wrapper.find('form').trigger('submit'); await wrapper.find('form').trigger('submit'); await flushPromises()
  expect(external).toHaveBeenCalledTimes(2)
  expect(external.mock.calls[0]![0].idempotencyKey).toBe(external.mock.calls[1]![0].idempotencyKey)
})
it('follows a completed duplicate job and releases polling on unmount', async () => {
  vi.useFakeTimers()
  vi.spyOn(api, 'external').mockResolvedValue({ resourceId: 'placeholder', state: 'pending', revision: 1 })
  const read = vi.spyOn(api, 'artifact').mockResolvedValueOnce({ ...artifact, resourceId: 'placeholder', state: 'pending', details: { ...artifact.details, jobs: [{ jobId: 'j', kind: 'external', state: 'queued', resolvedArtifactId: null, targetArtifactId: null, errorCode: null, createdAt: '' }] } }).mockResolvedValueOnce({ ...artifact, resourceId: 'placeholder', state: 'failed', details: { ...artifact.details, jobs: [{ jobId: 'j', kind: 'external', state: 'succeeded', resolvedArtifactId: 'apk-2', targetArtifactId: null, errorCode: null, createdAt: '' }] } }).mockResolvedValue(artifact)
  await setup(); await wrapper.find('form').trigger('submit'); await flushPromises()
  expect(wrapper.text()).toContain('等待完整 APK 核验')
  await vi.advanceTimersByTimeAsync(5000); await flushPromises()
  expect(read).toHaveBeenLastCalledWith('apk-2', expect.any(AbortSignal)); expect(wrapper.text()).toContain('APK 核验通过')
  wrapper.unmount(); const count = read.mock.calls.length
  await vi.advanceTimersByTimeAsync(15000); expect(read).toHaveBeenCalledTimes(count)
})
it('denies draft creation on failed verification and current permission loss', async () => {
  vi.spyOn(api, 'external').mockResolvedValue({ resourceId: 'apk-2', state: 'pending', revision: 1 })
  const read = vi.spyOn(api, 'artifact').mockResolvedValue({ ...artifact, state: 'failed' })
  const draft = vi.spyOn(api, 'draft')
  await setup(); await wrapper.find('form').trigger('submit'); await flushPromises()
  expect(wrapper.text()).toContain('APK 核验失败'); expect(draft).not.toHaveBeenCalled()
  read.mockRejectedValue(new ApiError({ status: 403 }))
  await wrapper.findAll('button').find(b => b.text() === '刷新核验状态')?.trigger('click'); await flushPromises()
  // Failed jobs require a corrected new registration; no silent retry.
  expect(read).toHaveBeenCalledTimes(1)
  wrapper.unmount(); await setup(); await wrapper.find('form').trigger('submit'); await flushPromises()
  expect(wrapper.emitted('denied')).toHaveLength(1); expect(draft).not.toHaveBeenCalled()
})
it('ignores a late registration response after leaving the wizard', async () => {
  let finish!: (value: { resourceId: string; state: 'pending'; revision: number }) => void
  const external = vi.spyOn(api, 'external').mockImplementation(() => new Promise(resolve => { finish = resolve }))
  const read = vi.spyOn(api, 'artifact')
  await setup(); await wrapper.find('form').trigger('submit'); await flushPromises()
  const signal = external.mock.calls[0]![1]!
  wrapper.unmount(); expect(signal.aborted).toBe(true)
  finish({ resourceId: 'apk-2', state: 'pending', revision: 1 }); await flushPromises()
  expect(read).not.toHaveBeenCalled(); expect(wrapper.emitted('created')).toBeUndefined()
})
it('requires explicit scope with multiple deployments and locks conflicted drafts', async () => {
  const external = vi.spyOn(api, 'external').mockResolvedValue({ resourceId: 'apk-2', state: 'verified', revision: 1 })
  // A replay can return a canonical artifact with unrelated old failed jobs.
  vi.spyOn(api, 'artifact').mockResolvedValue({ ...artifact, details: { ...artifact.details, jobs: [{ jobId: 'old', kind: 'external', state: 'failed', errorCode: null, resolvedArtifactId: null, targetArtifactId: null, createdAt: '' }] } })
  const draft = vi.spyOn(api, 'draft').mockRejectedValue(new ApiError({ status: 409, code: 'policy_revision_conflict' }))
  await setup([scope, { ...scope, deploymentId: 'second' }]); await wrapper.find('form').trigger('submit'); await flushPromises()
  expect(external).not.toHaveBeenCalled(); expect(wrapper.text()).toContain('请选择发布范围')
  await wrapper.findAll('select')[0]!.setValue('1'); await wrapper.find('form').trigger('submit'); await flushPromises()
  await wrapper.find('form').trigger('submit'); await flushPromises()
  expect(draft.mock.calls[0]![0].deploymentId).toBe('second'); expect(wrapper.text()).toContain('策略已被其他操作修改')
  await wrapper.find('form').trigger('submit'); await flushPromises(); expect(draft).toHaveBeenCalledTimes(1)
})
