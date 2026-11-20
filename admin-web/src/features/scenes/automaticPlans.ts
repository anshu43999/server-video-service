import type { SceneInputType, SceneMember, ScenePlan } from './api'
import { defaultCameraPolicy } from './cameraPolicy'

/** Creation defaults only. Existing and explicitly customized plans are authoritative. */
export function automaticScenePlans(members: SceneMember[], inputs: SceneInputType[], execution: 'sync' | 'async') {
  const commonInputs = inputs.filter(input => members.every(member => (member.inputTypes ?? inputs).includes(input)))
  const joint = members.length > 1
  const plans: ScenePlan[] = members.length ? [{
    planId: joint ? 'plan-joint' : `plan-${members[0]!.memberId}`,
    name: joint ? '全部模型联合识别' : '单模型识别',
    inputTypes: commonInputs,
    memberIds: members.map(member => member.memberId!),
    execution: joint ? execution : 'single',
    enabled: true,
    ...(commonInputs.includes('video') ? { cameraPolicy: defaultCameraPolicy() } : {}),
  }] : []
  let issue = ''
  if (joint) {
    if (members.length !== 2) issue = `当前联合识别仅支持 2 个模型，已选择 ${members.length} 个；不会自动拆成单模型方案。`
    else if (members.some(member => member.target !== 'mobile')) issue = '当前联合识别仅支持两个移动端模型，PC 端或跨端组合尚未开放。请调整模型目标端；不会只运行其中一个模型。'
    else if (!commonInputs.length) issue = '两个模型没有共同支持的图片或视频输入。请调整场景用途或成员输入能力。'
    else if (commonInputs.length !== inputs.length) issue = `两个模型仅共同支持${commonInputs.includes('image') ? '图片' : '视频'}。请调整场景用途或成员输入能力后保存。`
  }
  return { plans, issue }
}
