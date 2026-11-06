import { ApiError } from '../../api/errors'
import { apiClient } from '../../api/client'
import type { StreamItem, StreamModel } from './types'
import type { Scene } from '../scenes/api'

export interface StreamPlanOption {key:string;sceneId:string;planId:string;sceneRevision:number;label:string}

export function streamPlanOptions(scenes: Scene[]): StreamPlanOption[] {
  return scenes.flatMap((scene) => (scene.plans ?? [])
    .filter((plan) => scene.approved && scene.enabled && plan.enabled && plan.execution === 'single'
      && plan.inputTypes.includes('video') && plan.memberIds.length === 1
      && scene.models.some((member) => member.memberId === plan.memberIds[0] && member.target === 'pc'
        && member.available !== false && member.executionReady !== false))
    .map((plan) => ({
      key: `${scene.sceneId}::${plan.planId}::${scene.revision}`,
      sceneId: scene.sceneId, planId: plan.planId, sceneRevision: scene.revision,
      label: `${scene.name} · ${plan.name} · 修订 ${scene.revision}`,
    })))
}

function record(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function parseStream(value: unknown): StreamItem {
  if (!record(value) || typeof value.stream_id !== 'string' || !value.stream_id.trim()) {
    throw new ApiError({ kind: 'invalid-response', code: 'invalid_stream', message: '服务返回了无效的视频流' })
  }
  // The source address is write-only in the UI, even if a server returns it.
  const { source_url: _source, ...publicFields } = value
  return publicFields as unknown as StreamItem
}

function streamPath(streamId: string, suffix = '') {
  return `/streams/${encodeURIComponent(streamId)}${suffix}`
}

export const streamsApi = {
  async list(signal?: AbortSignal) {
    const value = await apiClient.request<unknown>('/streams', { signal })
    if (!Array.isArray(value)) throw new ApiError({ kind: 'invalid-response', code: 'invalid_stream_list', message: '服务返回了无效的视频流列表' })
    return value.map(parseStream)
  },
  async create(input: { stream_id: string; display_name?: string; source_type?: string; source_url?: string; sceneId: string; planId: string; sceneRevision: number }) {
    return parseStream(await apiClient.request<unknown>('/streams', { method: 'POST', json: input }))
  },
  async update(streamId: string, input: { display_name?: string; confidence?: number; max_fps?: number; overlay_enabled?: boolean; sceneId?: string; planId?: string; sceneRevision?: number }) {
    return parseStream(await apiClient.request<unknown>(streamPath(streamId, '/config'), { method: 'PATCH', json: input }))
  },
  async setEnabled(streamId: string, enabled: boolean) {
    return parseStream(await apiClient.request<unknown>(streamPath(streamId, '/config'), { method: 'PATCH', json: { enabled } }))
  },
  async setYolo(streamId: string, enabled: boolean) {
    return apiClient.request<{ stream_id: string; yolo_enabled: boolean }>(streamPath(streamId, '/yolo'), { method: 'POST', json: { enabled } })
  },
  async selectPlan(streamId: string, selection: { sceneId: string; planId: string; sceneRevision: number }) {
    return apiClient.request<{ stream_id: string; model: StreamModel }>(streamPath(streamId, '/model'), { method: 'PUT', json: selection })
  },
  async remove(streamId: string) {
    return apiClient.request<void>(streamPath(streamId), { method: 'DELETE', response: 'void' })
  },
  previewUrl(streamId: string, connection: number) {
    return `/aiyoloapi${streamPath(streamId, '/preview')}?connection=${connection}`
  },
}
