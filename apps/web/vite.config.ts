import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

const nodeEnvironment = (
  globalThis as typeof globalThis & {
    process?: { env?: Record<string, string | undefined> }
  }
).process?.env

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': nodeEnvironment?.VITE_CATEX_API_URL ?? 'http://127.0.0.1:8000',
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    css: true,
  },
})
