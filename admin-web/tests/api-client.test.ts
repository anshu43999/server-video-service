import { describe, expect, it, vi } from 'vitest'
import { ApiClient } from '../src/api/client'
import { ApiError, redactMessage } from '../src/api/errors'

async function rejected(promise: Promise<unknown>): Promise<ApiError> {
  try { await promise } catch (error) {
    if (error instanceof ApiError) return error
    throw error
  }
  throw new Error('Expected request to reject')
}

describe('ApiClient', () => {
  it('keeps requests same-origin and supports queries, JSON, FormData, Blob and 204', async () => {
    const calls: Array<[RequestInfo | URL, RequestInit | undefined]> = []
    const responses = [
      new Response(JSON.stringify({ ok: true }), { headers: { 'Content-Type': 'application/json' } }),
      new Response('download', { headers: { 'Content-Type': 'application/octet-stream' } }),
      new Response(null, { status: 204 }),
    ]
    const client = new ApiClient(async (input, init) => { calls.push([input, init]); return responses.shift()! })
    expect(await client.request('/items', { method: 'POST', query: { page: 2, tag: ['a', 'b'], absent: null }, json: { name: 'camera' } })).toEqual({ ok: true })
    expect(await client.request<Blob>('/files/one', { response: 'blob' })).toBeInstanceOf(Blob)
    expect(await client.request('/items/one', { method: 'DELETE', response: 'void' })).toBeUndefined()
    expect(calls[0][0]).toBe('/aiyoloapi/items?page=2&tag=a&tag=b')
    expect(new Headers(calls[0][1]?.headers).get('content-type')).toBe('application/json')
    expect(calls[0][1]?.credentials).toBe('same-origin')
    const form = new FormData(); form.append('name', 'asset')
    const formClient = new ApiClient(async (_input, init) => {
      expect(init?.body).toBe(form)
      expect(new Headers(init?.headers).has('content-type')).toBe(false)
      return new Response(JSON.stringify({ id: 1 }), { headers: { 'Content-Type': 'application/json' } })
    })
    await formClient.request('/forms', { method: 'POST', body: form })
    await expect(client.request('https://outside.example/data')).rejects.toThrow(TypeError)
  })

  it('maps Pydantic and wrapped errors without exposing credentials', async () => {
    const response = new Response(JSON.stringify({ detail: [
      { loc: ['body', 'username'], msg: 'required' },
      { loc: ['body', 'endpoint'], msg: 'bad https://user:password@example.test/?token=secret' },
    ] }), { status: 422, headers: { 'Content-Type': 'application/json', 'Retry-After': '9' } })
    const client = new ApiClient(async () => response)
    const error = await rejected(client.request('/probe'))
    expect(error).toBeInstanceOf(ApiError)
    expect(error.status).toBe(422)
    expect(error.fields).toEqual([
      { field: 'username', message: 'required' },
      { field: 'endpoint', message: 'bad https://[REDACTED]@example.test/?token=[REDACTED]' },
    ])
    expect(error.retryAfterSeconds).toBe(9)
    expect(redactMessage('Bearer abc.secret and ?key=my-key')).toBe('Bearer [REDACTED] and ?key=[REDACTED]')
    expect(redactMessage('password=plain token:abc')).toBe('password=[REDACTED] token:[REDACTED]')
  })

  it('distinguishes permission denial, expired sessions and an inconclusive check', async () => {
    for (const [result, expectedStatus, expectedCode] of [
      ['active', 403, 'permission_denied'],
      ['expired', 401, 'session_expired'],
      ['unknown', 401, 'authentication_check_failed'],
    ] as const) {
      const client = new ApiClient(async () => new Response(JSON.stringify({ detail: 'admin required' }), { status: 401, headers: { 'Content-Type': 'application/json' } }))
      client.setUnauthorizedHandler(async () => result)
      const error = await rejected(client.request('/rules'))
      expect([error.status, error.code]).toEqual([expectedStatus, expectedCode])
    }
  })

  it('distinguishes caller cancellation, timeout and network failure', async () => {
    const pendingFetch = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')), { once: true })
    }))
    const client = new ApiClient(pendingFetch as typeof fetch)
    const controller = new AbortController()
    const cancelled = client.request('/slow', { signal: controller.signal, timeoutMs: 200 })
    controller.abort()
    expect((await rejected(cancelled)).kind).toBe('cancelled')
    expect((await rejected(client.request('/slow', { timeoutMs: 5 }))).kind).toBe('timeout')
    const offline = new ApiClient(async () => { throw new TypeError('failed') })
    expect((await rejected(offline.request('/slow'))).kind).toBe('network')
  })
})
