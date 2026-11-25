import { apiClient } from '../../api/client'
import { projectScope } from '../../api/projectScope'
import { ApiError } from '../../api/errors'
export interface ProjectMetrics {projectId:string;streams:{total:number;framesReceived:number;framesProcessed:number;framesDropped:number}}
export interface DeliveryPolicy {revision:number;enabled:boolean;channels:string[];minimumSeverity:string}
export interface DeliveryStatus {channels:Record<string,{enabled:boolean;subscribers:number}>;pending:number;recent:{deliveryId?:string;delivery_id?:string;channel:string;status:string;attempts:number;errorCode?:string;error_code?:string}[]}
export const operationsApi = {
  policy(signal?:AbortSignal){return apiClient.request<DeliveryPolicy>('/delivery/policy',{signal})},
  savePolicy(value:DeliveryPolicy){const {enabled,channels,minimumSeverity,revision}=value;return apiClient.request<DeliveryPolicy>('/delivery/policy',{method:'PUT',json:{enabled,channels,minimumSeverity,expectedRevision:revision}})},
  resetPolicy(expectedRevision:number){return apiClient.request<DeliveryPolicy>('/delivery/policy',{method:'DELETE',query:{expectedRevision}})},
  delivery(signal?:AbortSignal){return apiClient.request<DeliveryStatus>('/alerts/delivery/status',{signal})},
  testDelivery(channel:string){const now=Date.now()*1000;return apiClient.request<{accepted:boolean;deliveryIds:string[]}>('/alerts/test-delivery',{method:'POST',json:{channels:[channel],event:{eventId:`admin-test-${crypto.randomUUID()}`,ruleId:'ADMIN_DELIVERY_TEST',sourceId:'admin-console',subjectKey:'test',label:'显式投递测试',state:'CONFIRMED',severity:'MINOR',notifySeverity:'MINOR',startedAtUs:now,confirmedAtUs:now,lastSeenAtUs:now,test:true}}})},
  health(signal?:AbortSignal){return apiClient.request<{status:string;streams:number;database:{configured:boolean;backend?:string;status:string;schema?:string}}>('/healthz',{signal})},
  async projectMetrics(signal?:AbortSignal){if(!projectScope.projectId)throw new ApiError({kind:'cancelled',message:'请先选择项目'});return apiClient.request<ProjectMetrics>(`/projects/${encodeURIComponent(projectScope.projectId)}/metrics`,{signal})},
  metrics(signal?:AbortSignal){return apiClient.request<{system:Record<string,unknown>;streams:ProjectMetrics['streams'];scope:'platform'}>('/metrics',{signal})},
}
