import type { Scene, SceneMember, ScenePlan } from './api'
import { defaultCameraPolicy } from './cameraPolicy'

/** Describes the new App, not the installed device or an authorization decision. */
export function planCapability(scene: Pick<Scene, 'models' | 'inputTypes'>, plan: ScenePlan): 'single' | 'mobile-image' | 'mobile-video' | 'mobile-image-video' | 'unsupported' {
  const members = plan.memberIds.map(id => scene.models.find(member => member.memberId === id))
  if (!members.length || members.some(member => !member) || new Set(plan.memberIds).size !== members.length) return 'unsupported'
  if (plan.execution === 'single') return members.length === 1 ? 'single' : 'unsupported'
  if ((plan.execution === 'sync' || plan.execution === 'async') && members.length === 2 &&
      members.every(member => member?.target === 'mobile')) {
    const supported = (['image', 'video'] as const).filter(input =>
      scene.inputTypes.includes(input) && plan.inputTypes.includes(input) &&
      members.every(member => (member?.inputTypes ?? scene.inputTypes).includes(input)))
    if (supported.length === 2) return 'mobile-image-video'
    if (supported[0] === 'image') return 'mobile-image'
    if (supported[0] === 'video') return 'mobile-video'
  }
  return 'unsupported'
}

/** A catalog status is not a device capability declaration or runtime grant. */
export function planStatus(scene: Scene, plan: ScenePlan) {
  if (!scene.enabled || !plan.enabled) return '已配置 · 已停用'
  if (!scene.approved) return '已配置 · 待批准'
  const members = plan.memberIds.map(id => scene.models.find(member => member.memberId === id))
  if (scene.available !== true || members.some(member => !member || member.available !== true || member.executionReady !== true)) return '已配置 · 待核验'
  const capability = planCapability(scene, plan)
  if (capability === 'unsupported') return '已配置 · 客户端未支持'
  return capability.startsWith('mobile-') ? '新版 App 双模型联合 · 需在线预检' : '可使用 · 需在线预检'
}

export function planParameter(plan: ScenePlan, member: SceneMember) {
  return plan.parameterSources?.find(source => source.memberId === member.memberId)?.parameterSnapshot ?? member.parameterSnapshot
}

/** Never send catalog projections, artifact URLs or approval snapshots as input. */
export function memberPayload(member: SceneMember, position: number, id: string, inputTypes: SceneMember['inputTypes']) {
  return { memberId: id, projectModelId: member.projectModelId, position, inputTypes, execution: member.execution }
}
export function planPayload(plan: ScenePlan) {
  return { planId: plan.planId, name: plan.name, inputTypes: [...plan.inputTypes], memberIds: [...plan.memberIds], execution: plan.execution, enabled: plan.enabled, ...(plan.cameraPolicy ? {cameraPolicy:{...plan.cameraPolicy}} : plan.inputTypes.includes('video') ? {cameraPolicy:defaultCameraPolicy()} : {}) }
}
