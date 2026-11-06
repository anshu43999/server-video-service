import type { ModelAsset, ModelTarget } from './types'
export function supportedTargets(model:ModelAsset):ModelTarget[] {
  if(model.supportedTargets) return model.supportedTargets
  return [model.serverReady?'pc':null,model.androidReady?'mobile':null].filter(Boolean) as ModelTarget[]
}
export function targetLabel(model:ModelAsset) {
  const targets=supportedTargets(model)
  return targets.length===2?'PC / 移动双端':targets[0]==='pc'?'PC 端模型':targets[0]==='mobile'?'移动端模型':'未声明目标端'
}
export function targetReady(model:ModelAsset,target:ModelTarget) {
  return supportedTargets(model).includes(target) && Boolean(model.targetReadiness?.[target]?.ready ?? (target==='pc'?model.serverReady:model.androidReady))
}
export function targetStatus(model:ModelAsset,target:ModelTarget) {
  if(!supportedTargets(model).includes(target))return '不支持'
  const published=model.targetReleaseEligible?.[target] ?? (model.status==='PUBLISHED'&&model.releaseEligible&&targetReady(model,target))
  return published?'已发布':targetReady(model,target)?'已就绪 / 待发布':'产物待就绪'
}

export function targetPublished(model:ModelAsset,target:ModelTarget) {
  return targetReady(model,target) && Boolean(model.targetReleaseEligible?.[target] ?? (model.status==='PUBLISHED' && model.releaseEligible))
}
