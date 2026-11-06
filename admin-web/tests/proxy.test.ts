import { createHash } from 'node:crypto'
import { createServer as createHttpServer, request } from 'node:http'
import type { AddressInfo } from 'node:net'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import { expect, it } from 'vitest'

it('development proxy preserves API paths, cookies, errors and WebSocket upgrades', async () => {
  const upstream = createHttpServer((req, res) => {
    res.setHeader('Content-Type', 'application/json')
    res.setHeader('Set-Cookie', 'aiyolo_session=test-session; Path=/; HttpOnly; SameSite=Lax')
    if (req.url?.includes('denied')) res.statusCode = 401
    res.end(JSON.stringify({ path: req.url, cookie: req.headers.cookie }))
  })
  let socketPath: string | undefined
  let socketCookie: string | undefined
  upstream.on('upgrade', (req, socket) => {
    socketPath = req.url
    socketCookie = req.headers.cookie
    const accept = createHash('sha1').update(String(req.headers['sec-websocket-key']) + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest('base64')
    socket.write(`HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ${accept}\r\n\r\n`)
    socket.on('error', () => {})
    socket.on('end', () => socket.end())
  })
  await new Promise<void>((resolve) => upstream.listen(0, '127.0.0.1', resolve))
  const oldTarget = process.env.ADMIN_API_TARGET
  process.env.ADMIN_API_TARGET = `http://127.0.0.1:${(upstream.address() as AddressInfo).port}`
  const vite = await createServer({
    root: fileURLToPath(new URL('../', import.meta.url)),
    configFile: fileURLToPath(new URL('../vite.config.ts', import.meta.url)),
    mode: 'development',
    server: { port: 0, strictPort: false },
  })
  try {
    await vite.listen()
    const port = (vite.httpServer!.address() as AddressInfo).port
    for (const path of ['/aiyoloapi/auth/me?check=1', '/healthz', '/aiyoloapi/denied']) {
      const response = await fetch(`http://127.0.0.1:${port}${path}`, { headers: { Cookie: 'aiyolo_session=test-session' } })
      expect(response.status).toBe(path.endsWith('denied') ? 401 : 200)
      expect(await response.json()).toEqual({ path, cookie: 'aiyolo_session=test-session' })
      expect(response.headers.get('set-cookie')).toContain('HttpOnly')
    }
    await new Promise<void>((resolve, reject) => {
      const req = request({ host: '127.0.0.1', port, path: '/aiyoloapi/alerts/ws', headers: {
        Connection: 'Upgrade', Upgrade: 'websocket', 'Sec-WebSocket-Version': '13',
        'Sec-WebSocket-Key': 'dGhlIHNhbXBsZSBub25jZQ==', Cookie: 'aiyolo_session=test-session',
      } })
      req.setTimeout(5000, () => { req.destroy(); reject(new Error('WebSocket upgrade timed out')) })
      req.on('error', reject)
      req.on('upgrade', (res, socket) => {
        try {
          expect(res.statusCode).toBe(101)
          expect(socketPath).toBe('/aiyoloapi/alerts/ws')
          expect(socketCookie).toBe('aiyolo_session=test-session')
          socket.end()
          resolve()
        } catch (error) { socket.destroy(); reject(error) }
      })
      req.end()
    })
  } finally {
    await vite.close()
    upstream.closeAllConnections()
    await new Promise<void>((resolve) => upstream.close(() => resolve()))
    if (oldTarget === undefined) delete process.env.ADMIN_API_TARGET
    else process.env.ADMIN_API_TARGET = oldTarget
  }
}, 20000)
