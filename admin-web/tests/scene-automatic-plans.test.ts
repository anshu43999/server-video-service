import { describe, expect, it } from 'vitest'
import { automaticScenePlans } from '../src/features/scenes/automaticPlans'
import type { SceneMember } from '../src/features/scenes/api'

const member = (id: string, target: 'pc' | 'mobile' = 'mobile'): SceneMember => ({
  memberId: id, projectModelId: `pm-${id}`, modelId: id, version: '1', target,
  position: 0, execution: 'single', inputTypes: ['image', 'video'], parameterRevision: 1,
})

it('does not create an empty plan and keeps single-model image/video support', () => {
  expect(automaticScenePlans([], ['image', 'video'], 'sync').plans).toEqual([])
  const result = automaticScenePlans([member('a', 'pc')], ['image', 'video'], 'async')
  expect(result.issue).toBe('')
  expect(result.plans).toEqual([expect.objectContaining({ execution: 'single', memberIds: ['a'], inputTypes: ['image', 'video'] })])
})

describe.each(['sync', 'async'] as const)('%s default joint plan', execution => {
  it('includes every member once in scene order and never mutates source members', () => {
    const members = [member('b'), member('a')], before = structuredClone(members)
    const result = automaticScenePlans(members, ['video'], execution)
    expect(result.issue).toBe('')
    expect(result.plans).toEqual([expect.objectContaining({
      planId: 'plan-joint', execution, memberIds: ['b', 'a'], inputTypes: ['video'],
      cameraPolicy: expect.objectContaining({ frameInterval: 5 }),
    })])
    expect(members).toEqual(before)
  })
  it('keeps every selected supported input with both ordered members', () => {
    for (const inputs of [['image'], ['image', 'video']] as const) {
      const result = automaticScenePlans([member('a'), member('b')], [...inputs], execution)
      expect(result.issue).toBe('')
      expect(result.plans[0]).toMatchObject({ execution, memberIds:['a','b'], inputTypes:inputs })
      if (inputs.length === 1) expect(result.plans[0]).not.toHaveProperty('cameraPolicy')
    }
  })
  it.each(['partial', 'pc', 'mixed', 'three', 'member-image', 'no-input'] as const)('blocks unsupported %s instead of dropping members', kind => {
    const members = [member('a'), member('b')]
    let inputs: ('image' | 'video')[] = ['video']
    if (kind === 'partial') { inputs = ['image','video']; members[0]!.inputTypes = ['video'] }
    if (kind === 'pc') members.forEach(row => { row.target = 'pc' })
    if (kind === 'mixed') members[0]!.target = 'pc'
    if (kind === 'three') members.push(member('c'))
    if (kind === 'member-image') members[0]!.inputTypes = ['image']
    if (kind === 'no-input') inputs = []
    const result = automaticScenePlans(members, inputs, execution)
    expect(result.issue).not.toBe('')
    expect(result.plans).toHaveLength(1)
    expect(result.plans[0]!.execution).toBe(execution)
    expect(result.plans[0]!.memberIds).toEqual(members.map(row => row.memberId))
  })
})

it('recomputes the joint set on add/remove/reorder and returns to single only with one member', () => {
  const a = member('a'), b = member('b')
  const pair = automaticScenePlans([a, b], ['video'], 'sync').plans[0]!
  const reordered = automaticScenePlans([b, a], ['video'], 'sync').plans[0]!
  expect(reordered.planId).toBe(pair.planId)
  expect(reordered.memberIds).toEqual(['b', 'a'])
  const single = automaticScenePlans([b], ['image'], 'sync').plans[0]!
  expect(single).toMatchObject({ execution: 'single', memberIds: ['b'], inputTypes: ['image'] })
  expect(single).not.toHaveProperty('cameraPolicy')
})
