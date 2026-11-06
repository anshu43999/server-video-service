import { describe, expect, it } from 'vitest'
import { backendTarget, buildSettings } from '../build-settings'

describe('deployment settings', () => {
  it('keeps preview and stable assets in separate bases and directories', () => {
    expect(buildSettings('production')).toEqual({ base: '/admin/', outDir: 'dist' })
    expect(buildSettings('preview')).toEqual({ base: '/admin-next/', outDir: 'dist-preview' })
    expect(buildSettings('development').base).toBe('/admin-next/')
  })
  it('proxies only to an origin and never exposes upstream credentials', () => {
    expect(backendTarget()).toBe('http://127.0.0.1:8080')
    expect(backendTarget('https://backend.example:8443/')).toBe('https://backend.example:8443')
    for (const value of ['https://user:pass@backend', 'file:///tmp', 'http://backend/api', 'http://backend/?key=secret', 'http://backend/#key']) {
      expect(() => backendTarget(value)).toThrow()
    }
  })
})

