// Keep deployment bases finite: history routes and static assets must agree.
export function buildSettings(mode: string) {
  const preview = mode === 'preview' || mode === 'development'
  return { base: preview ? '/admin-next/' : '/admin/', outDir: preview ? 'dist-preview' : 'dist' }
}

export function backendTarget(value?: string) {
  const url = new URL(value || 'http://127.0.0.1:8080')
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.pathname !== '/' || url.search || url.hash) {
    throw new Error('ADMIN_API_TARGET must be an HTTP(S) origin without credentials, path, query or fragment')
  }
  return url.origin
}
