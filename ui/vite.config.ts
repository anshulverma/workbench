// ui/vite.config.ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'

export default defineConfig({
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
      '/api': 'http://127.0.0.1:8421',
      '/health': 'http://127.0.0.1:8421',
    },
  },
})
