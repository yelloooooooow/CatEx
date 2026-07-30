import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

const nodeEnvironment = (
  globalThis as typeof globalThis & {
    process?: { env?: Record<string, string | undefined> }
  }
).process?.env

export default defineConfig({
  plugins: [react()],
  build: {
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules/weas') || id.includes('node_modules/three')) {
            return 'molecular-viewer'
          }
          if (id.includes('node_modules/@xyflow')) return 'workflow-graph'
          if (id.includes('node_modules/react')) return 'react-runtime'
          return undefined
        },
      },
    },
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': nodeEnvironment?.VITE_CATEX_API_URL ?? 'http://127.0.0.1:8765',
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    css: true,
  },
})
