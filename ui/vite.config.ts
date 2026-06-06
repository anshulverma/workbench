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
    proxy: { '/api': 'http://localhost:8421' },
  },
})
