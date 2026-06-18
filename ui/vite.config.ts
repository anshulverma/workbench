// ui/vite.config.ts
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'

export default defineConfig(({ mode }) => {
  // Dev API proxy target. Defaults to the local mock backend (dev-mock-server.mjs
  // on :8421). Set VITE_PROXY_TARGET to proxy /api + /health to a real backend
  // instead — inline (`VITE_PROXY_TARGET=https://[::1]:44201 npm run dev`) or via
  // ui/.env.local. For the Meta HTTPS deployment use `https://[::1]:44201`: the
  // backend binds IPv6 only (so [::1], not 127.0.0.1), and `secure: false` is
  // required because its Rootcanal cert is issued for the devserver's fbinfra.net
  // name, not the loopback address the proxy connects on.
  const env = loadEnv(mode, process.cwd(), '')
  const apiTarget =
    process.env.VITE_PROXY_TARGET || env.VITE_PROXY_TARGET || 'http://127.0.0.1:8421'
  const proxyEntry = { target: apiTarget, changeOrigin: true, secure: false }

  return {
    plugins: [react(), tailwindcss()],
    base: '/ui/',
    resolve: {
      alias: { '@': path.resolve(__dirname, 'src') },
    },
    build: { outDir: 'dist' },
    server: {
      // Reachable via Meta's x2p edge proxy and devserver hostnames, not just localhost.
      // Leading-dot entries allow the domain and all subdomains.
      allowedHosts: ['.facebook.net', '.fbinfra.net', 'localhost'],
      proxy: {
        '/api': proxyEntry,
        '/health': proxyEntry,
      },
    },
  }
})
