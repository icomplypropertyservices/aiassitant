import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
// Web production (aibusinessagent.xyz): base `/agents/`
// Local dev + Capacitor native: base `/`
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiTarget = env.VITE_API_URL || 'http://127.0.0.1:8000'
  const isNative =
    mode === 'native' ||
    mode === 'native.sandbox' ||
    env.VITE_NATIVE === '1' ||
    env.VITE_NATIVE === 'true'
  // Explicit VITE_BASE wins; native always root; production web defaults to /agents/
  let base = env.VITE_BASE || '/'
  if (!env.VITE_BASE && !isNative && mode === 'production') {
    base = '/agents/'
  }
  if (!base.endsWith('/')) base = `${base}/`

  return {
    plugins: [react()],
    base,
    envDir: '.',
    build: {
      outDir: 'dist',
      sourcemap: false,
      chunkSizeWarningLimit: 1500,
      rollupOptions: {
        output: {
          manualChunks: {
            vendor: ['react', 'react-dom', 'react-router-dom'],
            antd: ['antd', '@ant-design/icons'],
          },
        },
      },
    },
    server: {
      port: 5173,
      proxy: {
        '/api': {
          target: apiTarget,
          changeOrigin: true,
          rewrite: (p) => p.replace(/^\/api/, ''),
        },
      },
    },
    preview: {
      port: 4173,
      // Preview path-based app: vite preview --base /agents/
    },
  }
})
