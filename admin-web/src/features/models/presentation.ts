const modelStatusLabels: Record<string, string> = {
  DRAFT: '草稿',
  CONVERTING: '转换中',
  READY: '就绪',
  PUBLISHED: '已发布',
  DEPRECATED: '已弃用',
  REVOKED: '已撤回',
  UNINSTALLED: '已卸载',
}

/** Display only; callers must retain exact modelId/version for every action. */
export function modelDisplayName(model?: { name?: string | null; modelName?: string | null } | null): string {
  return model?.modelName?.trim() || model?.name?.trim() || '未命名模型'
}

export function modelStatusLabel(status?: string | null): string {
  const value = status?.trim()
  if (!value) return '状态未知'
  return modelStatusLabels[value] ?? `其他状态（${value}）`
}
