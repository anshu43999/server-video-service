import { ApiError, errorFromResponse } from './errors'
import { projectScope } from './projectScope'

export type QueryValue = string | number | boolean | null | undefined | Array<string | number | boolean>
export type ResponseKind = 'json' | 'text' | 'blob' | 'void'
export type SessionCheck = 'active' | 'expired' | 'unknown'

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  query?: Record<string, QueryValue>
  json?: unknown
  body?: BodyInit | null
  response?: ResponseKind
  signal?: AbortSignal
  timeoutMs?: number
  headers?: HeadersInit
  skipSessionCheck?: boolean
}

type UnauthorizedHandler = () => Promise<SessionCheck>

function queryString(query?: Record<string, QueryValue>): string {
  const params = new URLSearchParams()
  for (const [key, raw] of Object.entries(query ?? {})) {
    if (raw === undefined || raw === null) continue
    const values = Array.isArray(raw) ? raw : [raw]
    for (const value of values) params.append(key, String(value))
  }
  const encoded = params.toString()
  return encoded ? `?${encoded}` : ''
}

function endpointPath(endpoint: string): string {
  if (!endpoint.startsWith('/') || endpoint.startsWith('//') || endpoint.includes('://')) {
    throw new TypeError('API endpoint must be a same-origin absolute path')
  }
  return endpoint.startsWith('/aiyoloapi/') || endpoint === '/healthz'
    ? endpoint
    : `/aiyoloapi${endpoint}`
}

async function errorPayload(response: Response): Promise<unknown> {
  const contentType = response.headers.get('content-type') ?? ''
  if (contentType.includes('json')) {
    try { return await response.json() } catch { return undefined }
  }
  try { return { detail: await response.text() } } catch { return undefined }
}

function linkedController(signal?: AbortSignal, timeoutMs = 15_000) {
  const controller = new AbortController()
  let callerCancelled = false
  const abort = () => { callerCancelled = true; controller.abort(signal?.reason) }
  if (signal?.aborted) abort()
  else signal?.addEventListener('abort', abort, { once: true })
  const timeout = setTimeout(() => controller.abort(new DOMException('timeout', 'TimeoutError')), timeoutMs)
  return {
    controller,
    callerCancelled: () => callerCancelled,
    cleanup: () => { clearTimeout(timeout); signal?.removeEventListener('abort', abort) },
  }
}

export class ApiClient {
  private unauthorized?: UnauthorizedHandler
  constructor(private readonly fetchImpl?: typeof fetch) {}

  setUnauthorizedHandler(handler: UnauthorizedHandler) {
    this.unauthorized = handler
  }

  private async responseError(status: number, payload: unknown, retryAfter?: string | null, skipSessionCheck = false) {
    if (status === 401 && !skipSessionCheck && this.unauthorized) {
      const result = await this.unauthorized()
      if (result === 'active') return new ApiError({ status: 403, code: 'permission_denied', message: '当前账号无权访问此管理功能' })
      if (result === 'expired') return new ApiError({ status: 401, code: 'session_expired', message: '登录状态已失效，请重新登录' })
      return new ApiError({ status: 401, code: 'authentication_check_failed', message: '暂时无法确认登录状态' })
    }
    return errorFromResponse(status, payload, retryAfter)
  }

  async request<T = unknown>(endpoint: string, options: RequestOptions = {}): Promise<T> {
    const rawPath = endpointPath(endpoint)
    const scoped = projectScope.enabled && !rawPath.startsWith('/aiyoloapi/auth/')
    const generation = projectScope.generation
    const path = projectScope.path(rawPath)
    const method = options.method ?? 'GET'
    const headers = new Headers(options.headers)
    let body = options.body
    if (options.json !== undefined) {
      headers.set('Content-Type', 'application/json')
      body = JSON.stringify(options.json)
    }
    const linked = linkedController(options.signal, options.timeoutMs)
    const unregister = scoped ? projectScope.register(() => linked.controller.abort()) : () => {}
    const assertCurrent = () => { if (scoped) projectScope.assertCurrent(generation) }
    let response: Response
    try {
      response = await (this.fetchImpl ?? globalThis.fetch)(`${path}${queryString(options.query)}`, {
        method,
        headers,
        body,
        signal: linked.controller.signal,
        credentials: 'same-origin',
        cache: 'no-store',
      })
      assertCurrent()
      if (!response.ok) {
        const payload = await errorPayload(response)
        assertCurrent()
        const error = await this.responseError(response.status, payload, response.headers.get('retry-after'), options.skipSessionCheck)
        assertCurrent()
        if (scoped && [401, 403, 404].includes(response.status)) projectScope.onDenied?.()
        throw error
      }
      const kind = options.response ?? 'json'
      if (kind === 'void' || response.status === 204) return undefined as T
      let value: unknown
      try {
        value = kind === 'text' ? await response.text() : kind === 'blob' ? await response.blob() : await response.json()
      } catch {
        assertCurrent()
        if (linked.controller.signal.aborted) throw new DOMException('aborted', 'AbortError')
        throw new ApiError({ kind: 'invalid-response', code: 'invalid_response', message: '服务返回了无法解析的数据' })
      }
      assertCurrent()
      return value as T
    } catch (error) {
      if (error instanceof ApiError) throw error
      assertCurrent()
      if (linked.controller.signal.aborted) {
        throw new ApiError({
          kind: linked.callerCancelled() ? 'cancelled' : 'timeout',
          code: linked.callerCancelled() ? 'request_cancelled' : 'request_timeout',
          message: linked.callerCancelled() ? '请求已取消' : '请求超时',
        })
      }
      throw new ApiError({ kind: 'network', code: 'network_unavailable', message: '无法连接服务' })
    } finally {
      linked.cleanup()
      unregister()
    }
  }

  upload<T>(endpoint: string, file: Blob, options: Omit<RequestOptions, 'method' | 'body' | 'json'> = {}) {
    const headers = new Headers(options.headers)
    headers.set('Content-Type', 'application/octet-stream')
    return this.request<T>(endpoint, { ...options, method: 'POST', body: file, headers })
  }

  uploadWithProgress<T>(endpoint: string, file: Blob, options: {
    query?: Record<string, QueryValue>; signal?: AbortSignal; onProgress?: (percent: number | null) => void
  } = {}): Promise<T> {
    const path = projectScope.path(endpointPath(endpoint)) + queryString(options.query)
    const generation = projectScope.generation
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      const unregister = projectScope.enabled ? projectScope.register(() => xhr.abort()) : () => {}
      const cleanup = () => { options.signal?.removeEventListener('abort', abort); unregister() }
      const fail = (kind: 'network' | 'timeout' | 'cancelled', message: string) => { cleanup(); reject(new ApiError({ kind, message })) }
      const abort = () => xhr.abort()
      if (options.signal?.aborted) { fail('cancelled', '上传已取消'); return }
      xhr.open('POST', path)
      xhr.timeout = 310_000
      xhr.setRequestHeader('Content-Type', 'application/octet-stream')
      xhr.upload.onprogress = event => options.onProgress?.(event.lengthComputable ? Math.min(100, event.loaded / event.total * 100) : null)
      xhr.onabort = () => fail('cancelled', '上传已取消；请先刷新任务确认服务端状态')
      xhr.onerror = () => fail('network', '上传连接中断；请先刷新任务确认服务端状态')
      xhr.ontimeout = () => fail('timeout', '上传超时；请先刷新任务确认服务端状态')
      xhr.onload = async () => {
        try {
          projectScope.assertCurrent(generation)
          let payload: unknown
          try { payload = JSON.parse(xhr.responseText) } catch { payload = { detail: xhr.responseText } }
          if (xhr.status < 200 || xhr.status >= 300) {
            const error = await this.responseError(xhr.status, payload, xhr.getResponseHeader('retry-after'))
            projectScope.assertCurrent(generation)
            if ([403, 404].includes(xhr.status)) projectScope.onDenied?.()
            reject(error); return
          }
          resolve(JSON.parse(xhr.responseText) as T)
        } catch (error) { reject(error instanceof ApiError ? error : new ApiError({ kind: 'invalid-response', message: '上传响应无效；请先刷新任务确认服务端状态' })) }
        finally { cleanup() }
      }
      options.signal?.addEventListener('abort', abort, { once: true })
      xhr.send(file)
    })
  }
}

export const apiClient = new ApiClient()
