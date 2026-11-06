import { apiClient } from '../../api/client'
import type { ModelAsset, ModelTarget, ParameterProfile, Platform } from './types'
export interface Assignment {
  projectModelId: string
  assignmentId?: string
  projectId?: string
  modelId: string
  modelName?: string
  modelVersion: string
  target: ModelTarget
  parameterPlatform: Platform
  parameterRevision: number
  parameterProfileKey?: string | null
  enabled: boolean
  revision: number
}
export interface AssignedModel extends ModelAsset {
  assignment: Assignment
  assignments?: Assignment[]
  effectiveParametersByTarget?: Partial<Record<ModelTarget, ParameterProfile>>
}
export interface AvailableModel extends ModelAsset {parameterProfiles: Partial<Record<Platform, ParameterProfile>>}
export interface AssignmentWrite {
  modelId: string
  modelVersion: string
  target: ModelTarget
  parameterRevision: number
  enabled: boolean
  expectedRevision: number
}
export const projectModelsApi = {
  async models(signal?: AbortSignal) { return (await apiClient.request<{models:AssignedModel[]}>('/models', {signal})).models },
  async available(signal?: AbortSignal) { return (await apiClient.request<{models:AvailableModel[]}>('/models/available', {signal})).models },
  async assignments(signal?: AbortSignal, target?: ModelTarget) {
    const query = target ? `?target=${encodeURIComponent(target)}` : ''
    return (await apiClient.request<{assignments:Assignment[]}>(`/model-assignments${query}`, {signal})).assignments
  },
  save(value:AssignmentWrite, signal?:AbortSignal) {
    return apiClient.request<Assignment>('/model-assignments', {method:'PUT',json:value,signal})
  },
  remove(projectModelId:string, expectedRevision:number, signal?:AbortSignal) {
    return apiClient.request<{removed:boolean;projectModelId:string}>(
      `/model-assignments/${encodeURIComponent(projectModelId)}?expectedRevision=${expectedRevision}`,
      {method:'DELETE',signal},
    )
  },
}
