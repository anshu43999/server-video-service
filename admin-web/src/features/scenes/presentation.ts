import type { Scene, SceneMember, ScenePlan } from './api'
import { defaultCameraPolicy } from './cameraPolicy'

/** A catalog status is not a device capability declaration or runtime grant. */
export function planStatus(scene: Scene, plan: ScenePlan) {
  if (!scene.enabled || !plan.enabled) return '已配置 · 已停用'
  if (!scene.approved) return '已配置 · 待批准'
  const members = plan.memberIds.map(id => scene.models.find(member => member.memberId === id))
  if (scene.available !== true || members.some(member => !member || member.available !== true || member.executionReady !== true)) return '已配置 · 待核验'
  if (plan.execution !== 'single' || members.length !== 1) return '已配置 · 客户端未支持'
  return '可使用 · 需在线预检'
}

export function planParameter(plan: ScenePlan, member: SceneMember) {
  return plan.parameterSources?.find(source => source.memberId === member.memberId)?.parameterSnapshot ?? member.parameterSnapshot
}

/** Never send catalog projections, artifact URLs or approval snapshots as input. */
export function memberPayload(member: SceneMember, position: number, id: string, inputTypes: SceneMember['inputTypes']) {
  return { memberId: id, projectModelId: member.projectModelId, position, inputTypes, execution: member.execution, parameterRevision: member.parameterSnapshot?.inventoryRevision ?? member.parameterRevision }
}
export function planPayload(plan: ScenePlan) {
  return { planId: plan.planId, name: plan.name, inputTypes: [...plan.inputTypes], memberIds: [...plan.memberIds], execution: plan.execution, enabled: plan.enabled, ...(plan.cameraPolicy ? {cameraPolicy:{...plan.cameraPolicy}} : plan.inputTypes.includes('video') ? {cameraPolicy:defaultCameraPolicy()} : {}) }
}
