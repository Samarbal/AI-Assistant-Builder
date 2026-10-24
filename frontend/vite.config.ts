import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'
import { publicAuthConfig } from './src/auth/config.ts'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // Fail before bundling an accidentally configured privileged key.
  publicAuthConfig(loadEnv(mode, process.cwd(), 'VITE_'))
  return { plugins: [react()], cacheDir: `node_modules/.vite-${mode}`, server: { host: '127.0.0.1', proxy: {
    '/api': { target: 'http://127.0.0.1:8000', rewrite: path => path.replace(/^\/api/, '') },
    '/public': { target: 'http://127.0.0.1:8000' },
  } } }
})
