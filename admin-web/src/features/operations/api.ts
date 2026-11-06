import { apiClient } from '../../api/client'
import { projectScope } from '../../api/projectScope'
import { ApiError } from '../../api/errors'
export interface ProjectMetrics {projectId:string;streams:{total:number;framesReceived:number;framesProcessed:number;framesDropped:number}}
export interface Rule {
  ruleId:string;name:string;ruleVersion:number;enabled:boolean;subjectKind:string;operator:string
  requires:string[];targetLabels:string[];roiId?:string;roi?:Record<string,unknown>;thresholds:Record<string,unknown>
  severityBands?:Record<string,unknown>[];escalation?:Record<string,unknown>;scope?:Record<string,unknown>
}
export interface Source {sourceId:string;modelId?:string;capabilities:string[]}
export interface Binding extends Source {accepted:boolean;ruleId:string;ruleVersion?:number;code?:string;message?:string;missing?:string[]}
export interface Audit {action:string;ruleId:string;ruleVersion:number;actor:string;timestamp:string;sourceId?:string;code?:string}
export interface DeliveryPolicy {revision:number;enabled:boolean;channels:string[];minimumSeverity:string}
export interface DeliveryStatus {channels:Record<string,{enabled:boolean;subscribers:number}>;pending:number;recent:{deliveryId?:string;delivery_id?:string;channel:string;status:string;attempts:number;errorCode?:string;error_code?:string}[]}
const rulePath = (id:string)=>`/rules/${encodeURIComponent(id)}`
// 服务端对历史规则可能不返回 requires / targetLabels / thresholds，
// 缺省时补齐为空值，避免视图里的 .join() 抛错导致整页卡在加载态。
function normalizeRule(rule:Rule):Rule{
  return {
    ...rule,
    requires:rule.requires ?? [],
    targetLabels:rule.targetLabels ?? [],
    thresholds:rule.thresholds ?? {},
  }
}
export const operationsApi = {
  async rules(signal?:AbortSignal){return (await apiClient.request<{rules:Rule[]}>('/rules',{signal})).rules.map(normalizeRule)},
  rule(id:string,signal?:AbortSignal){return apiClient.request<Rule>(rulePath(id),{signal}).then(normalizeRule)},
  async saveRule(rule:Rule,original?:Rule){
    const {ruleVersion:_version,...json}=rule
    return apiClient.request<Rule>(original?rulePath(rule.ruleId):'/rules',{method:original?'PUT':'POST',json:{...json,expectedRevision:original?.ruleVersion ?? 0}})
  },
  removeRule(id:string,expectedRevision:number){return apiClient.request(rulePath(id),{method:'DELETE',query:{expectedRevision},response:'void'})},
  async bindings(id:string,signal?:AbortSignal){return (await apiClient.request<{bindings:Binding[]}>(rulePath(id)+'/bindings',{signal})).bindings},
  async sources(signal?:AbortSignal){return (await apiClient.request<{sources:Source[]}>('/capabilities/sources',{signal})).sources},
  async audit(signal?:AbortSignal){return (await apiClient.request<{audit:Audit[]}>('/rules/audit',{signal})).audit},
  validate(id:string,source:Source){return apiClient.request<Binding>(rulePath(id)+'/validate',{method:'POST',json:source})},
  bind(id:string,source:Source,expectedRevision:number){return apiClient.request<Binding>(rulePath(id)+'/bindings',{method:'POST',json:{...source,expectedRevision}})},
  unbind(id:string,sourceId:string,expectedRevision:number){return apiClient.request(rulePath(id)+'/bindings/'+encodeURIComponent(sourceId),{method:'DELETE',query:{expectedRevision}})},
  policy(signal?:AbortSignal){return apiClient.request<DeliveryPolicy>('/delivery/policy',{signal})},
  savePolicy(value:DeliveryPolicy){const {enabled,channels,minimumSeverity,revision}=value;return apiClient.request<DeliveryPolicy>('/delivery/policy',{method:'PUT',json:{enabled,channels,minimumSeverity,expectedRevision:revision}})},
  resetPolicy(expectedRevision:number){return apiClient.request<DeliveryPolicy>('/delivery/policy',{method:'DELETE',query:{expectedRevision}})},
  delivery(signal?:AbortSignal){return apiClient.request<DeliveryStatus>('/alerts/delivery/status',{signal})},
  testDelivery(channel:string){const now=Date.now()*1000;return apiClient.request<{accepted:boolean;deliveryIds:string[]}>('/alerts/test-delivery',{method:'POST',json:{channels:[channel],event:{eventId:`admin-test-${crypto.randomUUID()}`,ruleId:'ADMIN_DELIVERY_TEST',sourceId:'admin-console',subjectKey:'test',label:'显式投递测试',state:'CONFIRMED',severity:'MINOR',notifySeverity:'MINOR',startedAtUs:now,confirmedAtUs:now,lastSeenAtUs:now,test:true}}})},
  health(signal?:AbortSignal){return apiClient.request<{status:string;streams:number;database:{configured:boolean;backend?:string;status:string;schema?:string}}>('/healthz',{signal})},
  async projectMetrics(signal?:AbortSignal){if(!projectScope.projectId)throw new ApiError({kind:'cancelled',message:'请先选择项目'});return apiClient.request<ProjectMetrics>(`/projects/${encodeURIComponent(projectScope.projectId)}/metrics`,{signal})},
  metrics(signal?:AbortSignal){return apiClient.request<{system:Record<string,unknown>;streams:ProjectMetrics['streams'];scope:'platform'}>('/metrics',{signal})},
}
