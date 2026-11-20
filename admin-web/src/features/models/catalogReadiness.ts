import { targetPublished, targetReady, targetStatus } from './capabilities'
import type { ModelAsset, ModelTarget, Platform } from './types'

export function catalogReadiness(model: ModelAsset, target: ModelTarget) {
  const platform: Platform = target === 'pc' ? 'server' : 'android'
  const label = target === 'pc' ? 'PC 端' : '移动端'
  const parameterName = target === 'pc' ? '服务端参数' : 'Android 参数'
  const publication = model.parameterPublication?.[platform]
  const published = publication?.state === 'published' && Number.isInteger(publication.publishedRevision)
    && (publication.publishedRevision ?? -1) >= 0
  const missing = publication?.state === 'unpublished'
  const filesPublished = model.status === 'PUBLISHED' && !!model.releaseEligible && targetPublished(model, target)
  const parameters = published ? `已发布 r${publication!.publishedRevision}${publication!.hasUnpublishedChanges ? ' · 有新草稿' : ''}`
    : missing ? '尚未发布' : '状态待核实'
  let status = '暂不可添加', tone: 'success' | 'warning' | 'info' = 'warning', hint: string
  if (!['READY', 'PUBLISHED', 'DRAFT', 'CONVERTING'].includes(model.status ?? '')) {
    hint = '该模型版本当前不可分配到项目，请先核查版本状态。'
  } else if (!filesPublished) {
    hint = `${targetReady(model, target) ? '请先按端发布模型文件' : '请先完成该端产物处理并按端发布模型文件'}${missing ? `，并核对、发布${parameterName}` : ''}。`
  } else if (missing) {
    status = '待发布参数'
    hint = `尚未出现在项目“添加模型”中：请在参数档案中核对并发布${parameterName}。`
  } else if (!published) {
    status = '状态待核实'; tone = 'info'
    hint = '参数状态暂时无法核实，请刷新目录或打开参数档案检查。'
  } else {
    status = '项目可添加'; tone = 'success'
    hint = publication!.hasUnpublishedChanges
      ? `项目仍使用已发布参数 r${publication!.publishedRevision}；新草稿发布后才会用于新运行。`
      : '模型文件和运行参数均已发布，可在项目中添加此端模型。'
  }
  return { platform, label, status, tone, files: targetStatus(model, target), parameters, hint,
    action: `${missing ? '去发布' : '查看'}${parameterName}` }
}
