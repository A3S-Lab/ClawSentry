import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: '/ui/',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) {
            return undefined
          }
          if (
            id.includes('victory-vendor') ||
            id.includes('recharts-scale') ||
            id.includes('d3-') ||
            id.includes('internmap') ||
            id.includes('lodash')
          ) {
            return 'd3-vendor'
          }
          if (
            id.includes('recharts')
          ) {
            return 'charts'
          }
          if (id.includes('lucide-react')) {
            return 'icons'
          }
          return undefined
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/report': 'http://127.0.0.1:8080',
      '/ahp': 'http://127.0.0.1:8080',
      '/health': 'http://127.0.0.1:8080',
    },
  },
})
