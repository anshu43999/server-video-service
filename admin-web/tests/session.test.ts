import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from '../src/api/client'
import type { ApiError } from '../src/api/errors'
import { subscriptionRegistry } from '../src/api/realtime'
import { connectSessionToApi, useSessionStore } from '../src/stores/session'
import { authApi } from '../src/api/auth'

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
}

describe('session store', () => {
  beforeEach(() => setActivePinia(createPinia()))
  afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

  it('cannot resurrect a logged-out session from an in-flight identity check', async () => {
    let resolve!: (value: { username: string; role: 'admin' }) => void
    vi.spyOn(authApi, 'me').mockReturnValue(new Promise(done => { resolve = done }))
    vi.spyOn(authApi, 'logout').mockResolvedValue({ ok: true })
    const store = useSessionStore()
    const pending = store.verifyAfterUnauthorized()
    await store.logout()
    resolve({ username: 'old-admin', role: 'admin' })
    expect(await pending).toBe('unknown'); expect(store.user).toBeNull(); expect(store.phase).toBe('anonymous')
  })

  it('restores an admin through status + me and never persists the returned token', async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(json({ setupRequired: false, authenticated: true, user: { username: 'admin', role: 'admin' } }))
      .mockResolvedValueOnce(json({ username: 'admin', role: 'admin', platformRole: 'PLATFORM_ADMIN' }))
    vi.stubGlobal('fetch', fetch)
    const store = useSessionStore()
    await store.restore()
    expect(store.phase).toBe('authenticated')
    expect(store.isAdmin).toBe(true)
    expect('accessToken' in store).toBe(false)
    expect(fetch).toHaveBeenCalledTimes(2)
  })

  it('uses setup exactly once and retains no password or access token', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(json({
      accessToken: 'server-secret-token', tokenType: 'Bearer', expiresIn: 100,
      user: { username: 'admin', role: 'admin' },
    })).mockResolvedValueOnce(json({ username: 'admin', role: 'admin', accountId: 'a', platformRole: 'PLATFORM_ADMIN', contractVersion: 'm33-v1' })))
    const store = useSessionStore()
    store.setupRequired = true
    await store.submit('admin', 'correct-horse-1')
    expect(store.user).toMatchObject({ username: 'admin', role: 'admin', contractVersion: 'm33-v1' })
    expect(JSON.stringify(store.$state)).not.toContain('server-secret-token')
    expect(JSON.stringify(store.$state)).not.toContain('correct-horse-1')
    expect(store.setupRequired).toBe(false)
  })

  it('clears the prior identity after a failed login instead of staying restoring', async () => {
    const store = useSessionStore()
    store.user = { username: 'old-admin', role: 'admin', accountId: 'old', platformRole: 'PLATFORM_ADMIN', contractVersion: 'm33-v1' }
    store.phase = 'authenticated'
    let rejectLogin!: (reason: Error) => void
    vi.spyOn(authApi, 'login').mockReturnValue(new Promise((_, reject) => { rejectLogin = reject }))
    const pending = store.submit('new-user', 'not-a-real-password')
    const rejected = expect(pending).rejects.toThrow('login unavailable')
    expect(store.phase).toBe('restoring')
    rejectLogin(new Error('login unavailable'))
    await rejected
    expect(store.user).toBeNull()
    expect(store.phase).toBe('anonymous')
    expect(store.isAdmin).toBe(false)
  })

  it('deduplicates identity checks for simultaneous business 401 responses', async () => {
    let meCount = 0
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith('/auth/me')) {
        meCount += 1
        await new Promise((resolve) => setTimeout(resolve, 5))
        return json({ username: 'operator', role: 'operator' })
      }
      return json({ detail: { code: 'authentication_required', message: 'admin required' } }, 401)
    }))
    const store = useSessionStore()
    connectSessionToApi(store)
    const errors = await Promise.all([
      apiClient.request('/rules').catch((error) => error),
      apiClient.request('/dashboard/stats').catch((error) => error),
    ]) as ApiError[]
    expect(meCount).toBe(1)
    expect(errors.map((error) => error.status)).toEqual([403, 403])
    expect(store.phase).toBe('authenticated')
  })

  it('stops subscriptions even when logout cannot be confirmed', async () => {
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce(json({ setupRequired: false, authenticated: true, user: { username: 'admin', role: 'admin' } }))
      .mockResolvedValueOnce(json({ username: 'admin', role: 'admin' }))
      .mockResolvedValueOnce(json({ detail: 'service unavailable' }, 503)))
    const store = useSessionStore()
    await store.restore()
    const closable = { stop: vi.fn() }
    subscriptionRegistry.add(closable)
    await expect(store.logout()).rejects.toThrow()
    expect(closable.stop).toHaveBeenCalledOnce()
    expect(store.logoutUnconfirmed).toBe(true)
    expect(store.message).toContain('退出未确认')
    expect(store.user?.username).toBe('admin')
  })

  it('expires the local session and subscriptions after a confirmed business 401', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith('/auth/me')) return json({ detail: 'session expired' }, 401)
      return json({ detail: 'admin required' }, 401)
    }))
    const store = useSessionStore()
    connectSessionToApi(store)
    const closable = { stop: vi.fn() }
    subscriptionRegistry.add(closable)
    const error = await apiClient.request<never>('/rules').catch((reason) => reason as ApiError)
    expect(error.code).toBe('session_expired')
    expect(store.phase).toBe('anonymous')
    expect(store.user).toBeNull()
    expect(closable.stop).toHaveBeenCalledOnce()
  })
})
