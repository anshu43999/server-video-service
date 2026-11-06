import { apiClient } from '../../api/client'
import { removalHeaders, type RemovalImpact } from '../models/lifecycle'
import type { ModelTarget, ParameterProfile } from '../models/types'
export type SceneInputType = 'image' | 'video'
export type SceneExecution = 'single' | 'sync' | 'async'
export interface CameraPolicy {frameInterval:number;batchTimeoutMs:number;resultMaxAgeMs:number;overlayHoldMs:number}
export interface SceneMember {memberId?:string;projectModelId:string;modelId:string;modelName?:string;version:string;target:ModelTarget;position:number;inputTypes?:SceneInputType[];execution:SceneExecution;available?:boolean;executionReady?:boolean;parameterSnapshot?:ParameterProfile;pendingParameterSnapshot?:ParameterProfile;parameterRevision:number}
export interface SceneMemberWrite {memberId?:string;projectModelId:string;position:number;inputTypes?:SceneInputType[];execution:SceneExecution;parameterRevision:number}
export interface ScenePlan {planId:string;name:string;inputTypes:SceneInputType[];memberIds:string[];execution:SceneExecution;enabled:boolean;cameraPolicy?:CameraPolicy;implicit?:boolean;executionSupported?:boolean;parameterSources?:{memberId:string;planId?:string;parameterSnapshot:ParameterProfile}[]}
export interface Scene {projectId:string;sceneId:string;name:string;inputTypes:SceneInputType[];models:SceneMember[];plans?:ScenePlan[];enabled:boolean;approved:boolean;revision:number;available?:boolean;executionSupported?:boolean;executionSupportByTarget?:Partial<Record<ModelTarget,boolean>>}
export interface SceneCreate {sceneId:string;name:string;inputTypes:SceneInputType[];models:SceneMemberWrite[];plans?:ScenePlan[];enabled:boolean;expectedRevision:number}
export interface ScenePatch {name?:string;inputTypes?:SceneInputType[];enabled?:boolean;plans?:ScenePlan[];expectedRevision:number}
const path=(id:string)=>`/scenes/${encodeURIComponent(id)}`
export interface SceneProfileBinding {sceneId:string;memberId:string;revision:number}
const profilePath=(binding:SceneProfileBinding)=>`${path(binding.sceneId)}/members/${encodeURIComponent(binding.memberId)}/parameter-profile`
export const scenesApi={
  impact(id:string,signal?:AbortSignal){return apiClient.request<RemovalImpact>(path(id)+'/removal-impact',{signal})},
  remove(id:string,revision:number,key:string,signal?:AbortSignal){return apiClient.request(path(id),{method:'DELETE',headers:removalHeaders(revision,key),signal})},
  profile(binding:SceneProfileBinding,signal?:AbortSignal){return apiClient.request<ParameterProfile>(profilePath(binding),{query:{sceneRevision:binding.revision},signal})},
  saveProfile(binding:SceneProfileBinding,profile:ParameterProfile){return apiClient.request<ParameterProfile>(profilePath(binding),{method:'PUT',query:{sceneRevision:binding.revision},json:{schemaVersion:2,expectedRevision:profile.revision,detection:profile.detection,alertRules:profile.alertRules}})},
  async list(signal?:AbortSignal){return (await apiClient.request<{scenes:Scene[]}>('/scenes',{signal})).scenes},
  create(value:SceneCreate,signal?:AbortSignal){return apiClient.request<Scene>('/scenes',{method:'POST',json:value,signal})},
  patch(id:string,value:ScenePatch,signal?:AbortSignal){return apiClient.request<Scene>(path(id),{method:'PATCH',json:value,signal})},
  members(id:string,models:SceneMemberWrite[],expectedRevision:number,signal?:AbortSignal){return apiClient.request<Scene>(path(id)+'/models',{method:'PUT',json:{models,expectedRevision},signal})},
  plans(id:string,plans:ScenePlan[],expectedRevision:number,signal?:AbortSignal){return apiClient.request<Scene>(path(id)+'/plans',{method:'PUT',json:{plans,expectedRevision},signal})},
  approve(id:string,approved:boolean,expectedRevision:number,reason:string,signal?:AbortSignal){return apiClient.request<Scene>(path(id)+'/approval',{method:'POST',json:{approved,expectedRevision,reason},signal})},
}
