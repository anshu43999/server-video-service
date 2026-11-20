import { describe, expect, it } from 'vitest'
import { planCapability, planStatus } from '../src/features/scenes/presentation'
import type { Scene, ScenePlan } from '../src/features/scenes/api'

function fixture(execution: 'sync' | 'async') {
  const plan: ScenePlan = { planId: 'joint', name: '联合视频', execution, inputTypes: ['image', 'video'], memberIds: ['a', 'b'], enabled: true }
  const scene: Scene = {
    projectId: 'p', sceneId: 's', name: '安全巡检', revision: 1, inputTypes: ['image', 'video'],
    enabled: true, approved: true, available: true, executionSupported: false, plans: [plan],
    models: ['a', 'b'].map((id, position) => ({ memberId: id, projectModelId: `pm-${id}`, modelId: id,
      version: '1', target: 'mobile', position, inputTypes: ['image', 'video'], execution: 'single',
      available: true, executionReady: true, parameterRevision: 1 })),
  }
  return { scene, plan }
}

describe.each(['sync', 'async'] as const)('%s mobile video capability', execution => {
  it('labels shared inputs without claiming installed-client support', () => {
    const { scene, plan } = fixture(execution)
    expect(planCapability(scene, plan)).toBe('mobile-image-video')
    expect(planStatus(scene, plan)).toBe('新版 App 双模型联合 · 需在线预检')
    expect(planCapability(scene, { ...plan, inputTypes: ['image'] })).toBe('mobile-image')
    expect(planCapability(scene, { ...plan, inputTypes: ['video'] })).toBe('mobile-video')
    expect(planCapability({ ...scene, models: scene.models.map(m => ({ ...m, inputTypes: undefined })) }, plan)).toBe('mobile-image-video')
  })
  it.each(['image', 'pc', 'mixed', 'member-image', 'scene-image', 'one', 'three', 'duplicate', 'missing'] as const)('rejects unsupported %s configuration', change => {
    const { scene, plan } = fixture(execution)
    if (change === 'image') { plan.inputTypes = ['image']; scene.models[0]!.inputTypes = ['video'] }
    if (change === 'pc') scene.models.forEach(m => { m.target = 'pc' })
    if (change === 'mixed') scene.models[1]!.target = 'pc'
    if (change === 'member-image') { scene.models[1]!.inputTypes = ['image']; plan.inputTypes=['video'] }
    if (change === 'scene-image') { scene.inputTypes = ['image']; plan.inputTypes=['video'] }
    if (change === 'one') plan.memberIds = ['a']
    if (change === 'three') { scene.models.push({ ...scene.models[0]!, memberId: 'c' }); plan.memberIds.push('c') }
    if (change === 'duplicate') plan.memberIds = ['a', 'a']
    if (change === 'missing') plan.memberIds = ['a', 'unknown']
    expect(planCapability(scene, plan)).toBe('unsupported')
    expect(planStatus(scene, plan)).not.toContain('新版 App 仅视频')
  })
  it('keeps approval, enabled and ready checks ahead of capability', () => {
    const { scene, plan } = fixture(execution)
    expect(planStatus({ ...scene, approved: false }, plan)).toBe('已配置 · 待批准')
    expect(planStatus({ ...scene, enabled: false }, plan)).toBe('已配置 · 已停用')
    expect(planStatus(scene, { ...plan, enabled: false })).toBe('已配置 · 已停用')
    expect(planStatus({ ...scene, available: false }, plan)).toBe('已配置 · 待核验')
    scene.models[1]!.executionReady = false
    expect(planStatus(scene, plan)).toBe('已配置 · 待核验')
  })
})
