export type ApiErrorKind = 'http' | 'network' | 'timeout' | 'cancelled' | 'invalid-response'

export type FieldIssue = { field: string; message: string }

const SAFE_FALLBACKS: Record<number, string> = {
  401: '登录状态已失效，请重新登录',
  403: '当前账号无权执行此操作',
  404: '请求的资源不存在',
  409: '数据已发生变化，请刷新后重试',
  413: '上传文件超过服务限制',
  422: '提交内容不符合要求',
  429: '服务繁忙，请稍后重试',
  503: '服务暂时不可用',
}

export function redactMessage(value: unknown, fallback = '请求失败', maxLength = 500): string {
  if (typeof value !== 'string' || !value.trim()) return fallback
  return value
    .replace(/Bearer\s+[A-Za-z0-9._~+\/-]+/gi, 'Bearer [REDACTED]')
    .replace(/([?&](?:token|key|password|secret)=)[^&#\s]+/gi, '$1[REDACTED]')
    .replace(/((?:password|token|secret|api[_-]?key)\s*["']?\s*[:=]\s*["']?)[^"',;\s}]+/gi, '$1[REDACTED]')
    .replace(/((?:https?|rtsps?):\/\/)[^/@\s]+@/gi, '$1[REDACTED]@')
    .slice(0, maxLength)
}

export class ApiError extends Error {
  readonly kind: ApiErrorKind
  readonly status?: number
  readonly code: string
  readonly fields: FieldIssue[]
  readonly retryAfterSeconds?: number

  constructor(options: {
    kind?: ApiErrorKind
    status?: number
    code?: string
    message?: string
    fields?: FieldIssue[]
    retryAfterSeconds?: number
  }) {
    const statusFallback = options.status ? SAFE_FALLBACKS[options.status] : undefined
    super(redactMessage(options.message, statusFallback ?? '请求失败'))
    this.name = 'ApiError'
    this.kind = options.kind ?? 'http'
    this.status = options.status
    this.code = options.code ?? (options.status ? `http_${options.status}` : options.kind ?? 'request_failed')
    this.fields = options.fields ?? []
    this.retryAfterSeconds = options.retryAfterSeconds
  }
}

export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError
}

function objectValue(value: unknown): Record<string, unknown> | undefined {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : undefined
}

export function errorFromResponse(status: number, payload: unknown, retryAfter?: string | null): ApiError {
  const root = objectValue(payload)
  const wrapped = objectValue(root?.error)
  const detail = root?.detail
  const detailObject = objectValue(detail)
  const source = wrapped ?? detailObject ?? root
  const fields: FieldIssue[] = []
  if (Array.isArray(detail)) {
    for (const issue of detail) {
      const item = objectValue(issue)
      if (!item) continue
      const location = Array.isArray(item.loc) ? item.loc.filter((part) => part !== 'body').join('.') : ''
      fields.push({ field: location, message: redactMessage(item.msg, '字段值无效') })
    }
  }
  if (Array.isArray(source?.missing)) {
    for (const field of source.missing) fields.push({ field: String(field), message: '缺少必填项' })
  }
  const message = typeof detail === 'string' ? detail : source?.message
  const parsedRetry = retryAfter ? Number.parseInt(retryAfter, 10) : Number.NaN
  return new ApiError({
    status,
    code: typeof source?.code === 'string' ? source.code : undefined,
    message: typeof message === 'string' ? message : undefined,
    fields,
    retryAfterSeconds: Number.isFinite(parsedRetry) ? parsedRetry : undefined,
  })
}
