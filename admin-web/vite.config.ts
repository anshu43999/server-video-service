import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { backendTarget, buildSettings } from './build-settings.ts'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'ADMIN_')
  const target = backendTarget(env.ADMIN_API_TARGET)
  const { base, outDir } = buildSettings(mode)
  return {
    plugins: [vue()],
    base,
    build: {
      outDir,
      rollupOptions: {
        output: {
          manualChunks(id) {
            if (id.includes('/node_modules/element-plus/')) return 'element-plus'
          },
        },
      },
    },
    server: {
      host: '127.0.0.1',
      port: 5173,
      strictPort: true,
      proxy: {
        '/aiyoloapi': { target, ws: true, changeOrigin: true },
        '/healthz': { target, changeOrigin: true },
      },
    },
    preview: { host: '127.0.0.1', port: 4173, strictPort: true },
  }
})
