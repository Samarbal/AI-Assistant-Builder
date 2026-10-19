import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests/browser',
  use: { baseURL: 'http://127.0.0.1:4173', browserName: 'chromium', channel: 'chromium' },
  webServer: { command: 'npm run dev -- --mode browser-test --host 127.0.0.1 --port 4173 --strictPort', url: 'http://127.0.0.1:4173', reuseExistingServer: false,
    env: { VITE_SUPABASE_URL: 'https://auth.example.test', VITE_SUPABASE_PUBLISHABLE_KEY: 'sb_publishable_browser_test_only' } },
})
