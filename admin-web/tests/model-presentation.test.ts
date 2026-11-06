import { describe, expect, it } from 'vitest'
import { modelDisplayName, modelStatusLabel } from '../src/features/models/presentation'

it('uses uploaded display names and never invents a title from a technical ID', () => {
  expect(modelDisplayName({modelName:' 安全帽检测 '})).toBe('安全帽检测')
  expect(modelDisplayName({name:'ppe'})).toBe('ppe')
  expect(modelDisplayName({name:' ',modelName:''})).toBe('未命名模型')
  expect(modelDisplayName()).toBe('未命名模型')
})

describe('modelStatusLabel', () => {
  it.each([
    ['DRAFT', '草稿'],
    ['CONVERTING', '转换中'],
    ['READY', '就绪'],
    ['PUBLISHED', '已发布'],
    ['DEPRECATED', '已弃用'],
    ['REVOKED', '已撤回'],
    ['UNINSTALLED', '已卸载'],
  ])('translates %s', (status, label) => {
    expect(modelStatusLabel(status)).toBe(label)
  })

  it('handles missing and future status values in Chinese', () => {
    expect(modelStatusLabel()).toBe('状态未知')
    expect(modelStatusLabel('FUTURE_STATUS')).toBe('其他状态（FUTURE_STATUS）')
  })
})
