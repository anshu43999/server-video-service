import { afterEach, describe, expect, it, vi } from 'vitest'
import { streamsApi, streamPlanOptions } from '../src/features/streams/api'
import type { Scene } from '../src/features/scenes/api'
import { ApiError } from '../src/api/errors'
import { AdminPreview } from '../src/features/streams/preview'

const stream = { stream_id: 'camera:gate/01', display_name: '北门', enabled: true, source_url: 'rtsp://operator:secret@camera/live' }
function json(body: unknown) { return new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } }) }

afterEach(() => vi.unstubAllGlobals())

describe('stream API contracts', () => {
  it('redacts RTSP credentials and query secrets from failed operation messages', () => {
    const error = new ApiError({ message: 'source failed: rtsps://operator:private@camera/live?token=secret' })
    expect(error.message).not.toContain('operator:private')
    expect(error.message).not.toContain('token=secret')
  })
  it('keeps returned source credentials out of UI state', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json([stream])))
    expect(await streamsApi.list()).toEqual([{ stream_id: stream.stream_id, display_name: '北门', enabled: true }])
  })

  it('encodes stream IDs and sends the existing methods and payloads', async () => {
    const fetch = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => json(stream))
    vi.stubGlobal('fetch', fetch)
    await streamsApi.update(stream.stream_id, { confidence: 0.4, max_fps: 15, overlay_enabled: false })
    await streamsApi.setEnabled(stream.stream_id, false)
    await streamsApi.setYolo(stream.stream_id, true)
    await streamsApi.selectPlan(stream.stream_id, { sceneId: 'site-safety', planId: 'pc-live', sceneRevision: 4 })
    expect(fetch.mock.calls.map(call => [call[0], call[1]?.method])).toEqual([
      ['/aiyoloapi/streams/camera%3Agate%2F01/config', 'PATCH'],
      ['/aiyoloapi/streams/camera%3Agate%2F01/config', 'PATCH'],
      ['/aiyoloapi/streams/camera%3Agate%2F01/yolo', 'POST'],
      ['/aiyoloapi/streams/camera%3Agate%2F01/model', 'PUT'],
    ])
    expect(fetch.mock.calls.map(call => JSON.parse(String(call[1]?.body)))).toEqual([
      { confidence: 0.4, max_fps: 15, overlay_enabled: false }, { enabled: false }, { enabled: true },
      { sceneId: 'site-safety', planId: 'pc-live', sceneRevision: 4 },
    ])
  })

  it('rejects malformed truth instead of rendering invented rows', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json([{ name: 'missing ID' }])))
    await expect(streamsApi.list()).rejects.toMatchObject({ code: 'invalid_stream' })
    vi.stubGlobal('fetch', vi.fn(async () => json({ streams: [] })))
    await expect(streamsApi.list()).rejects.toMatchObject({ code: 'invalid_stream_list' })
  })

  it('does not expose a project-model lookup as a stream binding operation', () => {
    expect(streamsApi).not.toHaveProperty('models')
    expect(streamsApi).not.toHaveProperty('bindModel')
  })

  it('offers only approved PC video single-member plans and pins their revision', () => {
    const scene: Scene = {
      projectId: 'project-a', sceneId: 'safety', name: '安全巡检', inputTypes: ['video'],
      enabled: true, approved: true, revision: 7,
      models: [{ memberId: 'pc-member', projectModelId: 'assignment-a', modelId: 'helmet', version: '2.0.0',
        target: 'pc', position: 0, execution: 'single', parameterRevision: 3, executionReady: true }],
      plans: [
        { planId: 'pc-live', name: 'PC实时识别', inputTypes: ['video'], memberIds: ['pc-member'], execution: 'single', enabled: true },
        { planId: 'image-only', name: '图片方案', inputTypes: ['image'], memberIds: ['pc-member'], execution: 'single', enabled: true },
        { planId: 'multi', name: '多模型方案', inputTypes: ['video'], memberIds: ['pc-member', 'other'], execution: 'sync', enabled: true },
      ],
    }
    expect(streamPlanOptions([scene])).toEqual([{
      key: 'safety::pc-live::7', sceneId: 'safety', planId: 'pc-live', sceneRevision: 7,
      label: '安全巡检 · PC实时识别 · 修订 7',
    }])
    expect(streamPlanOptions([{ ...scene, approved: false }])).toEqual([])
  })

  it('uses the PC-only preview endpoint without generating playback addresses', () => {
    expect(streamsApi.previewUrl(stream.stream_id, 1)).toBe('/aiyoloapi/streams/camera%3Agate%2F01/preview?connection=1')
    expect(streamsApi.previewUrl(stream.stream_id, 2)).not.toBe(streamsApi.previewUrl(stream.stream_id, 1))
    expect(streamsApi).not.toHaveProperty('playback')
  })
})

describe('managed admin preview', () => {
  it('polls with cookie auth and retains old URLs until the next image has loaded', async () => {
    const frames: string[] = []
    const revoked: string[] = []
    let sequence = 0
    const fetch = vi.fn(async () => new Response('jpeg', { headers: { 'Content-Type': 'image/jpeg', 'X-Preview-Mode': 'yolo' } }))
    const mode = vi.fn()
    const preview = new AdminPreview({
      waitForFrameLoad: true,
      fetchImpl: fetch, onMode: mode,
      createObjectURL: () => `blob:${++sequence}`,
      revokeObjectURL: url => revoked.push(url),
      onFrame: url => frames.push(url),
    })
    preview.start('/aiyoloapi/streams/gate/preview?connection=1')
    await vi.waitFor(() => expect(frames).toEqual(['blob:1']))
    expect(fetch).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({ credentials: 'same-origin', cache: 'no-store', headers: { Accept: 'image/jpeg' } }))
    expect(mode).toHaveBeenCalledWith('yolo')
    preview.frameLoaded()
    await vi.waitFor(() => expect(frames).toEqual(['blob:1', 'blob:2']))
    expect(revoked).toEqual([])
    preview.frameLoaded()
    expect(revoked).toEqual(['blob:1'])
    preview.stop()
    expect(revoked).toEqual(['blob:1', 'blob:2'])
  })
  it('clears stale frames on 204 then recovers when the source reconnects', async () => {
    const frames: string[] = []
    const revoked: string[] = []
    let sequence = 0
    const fetch = vi.fn<typeof globalThis.fetch>()
      .mockResolvedValueOnce(new Response('jpeg', { headers: { 'Content-Type': 'image/jpeg' } }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockImplementation(async () => new Response('new-frame', { headers: { 'Content-Type': 'image/jpeg' } }))
    const status = vi.fn()
    const preview = new AdminPreview({
      fetchImpl: fetch, onStatus: status,
      createObjectURL: () => `blob:frame-${++sequence}`,
      revokeObjectURL: url => revoked.push(url),
      onFrame: url => frames.push(url),
    })
    preview.start('/aiyoloapi/streams/gate/preview?connection=1')
    await vi.waitFor(() => expect(frames).toContain('blob:frame-1'))
    await vi.waitFor(() => expect(status).toHaveBeenCalledWith('waiting'))
    expect(frames.at(-1)).toBe('')
    await vi.waitFor(() => expect(frames).toContain('blob:frame-2'))
    preview.stop()
    expect(revoked).toEqual(['blob:frame-1', 'blob:frame-2'])
    expect(frames.at(-1)).toBe('')
  })

  it('aborts the in-flight authenticated fetch when the preview is released', async () => {
    let signal: AbortSignal | undefined
    const preview = new AdminPreview({
      fetchImpl: vi.fn(async (_input, init) => {
        signal = init?.signal as AbortSignal
        return await new Promise<Response>((_resolve, reject) => signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError'))))
      }),
      onFrame: () => {},
    })
    preview.start('/aiyoloapi/streams/gate/preview?connection=1')
    await vi.waitFor(() => expect(signal).toBeInstanceOf(AbortSignal))
    preview.stop()
    expect(signal?.aborted).toBe(true)
  })

  it('rejects preview paths outside the same-origin stream endpoint', () => {
    const preview = new AdminPreview({ onFrame: () => {} })
    expect(() => preview.start('https://camera.invalid/mjpeg')).toThrow(TypeError)
    expect(() => preview.start('/aiyoloapi/streams/gate/mjpeg?connection=1')).toThrow(TypeError)
    expect(() => preview.start('/aiyoloapi/streams/gate/preview?connection=1&token=secret')).toThrow(TypeError)
  })

  it('stops polling after access is revoked and drops late responses on stop', async () => {
    const frame = vi.fn(), status = vi.fn()
    const fetch = vi.fn(async () => new Response(null, { status: 403 }))
    const preview = new AdminPreview({ fetchImpl: fetch, onFrame: frame, onStatus: status })
    preview.start('/aiyoloapi/streams/gate/preview?connection=1')
    await vi.waitFor(() => expect(status).toHaveBeenCalledWith('error', 'HTTP 403'))
    await new Promise(resolve => setTimeout(resolve, 250))
    expect(fetch).toHaveBeenCalledTimes(1)
    preview.stop()
    let resolve!: (value: Response) => void
    const stale = new AdminPreview({ fetchImpl: async () => new Promise(r => { resolve = r }), onFrame: frame, createObjectURL: () => 'blob:stale' })
    stale.start('/aiyoloapi/streams/gate/preview?connection=2')
    stale.stop()
    resolve(new Response('stale', { headers: { 'Content-Type': 'image/jpeg' } }))
    await Promise.resolve(); await Promise.resolve()
    expect(frame).not.toHaveBeenCalled()
  })
})
