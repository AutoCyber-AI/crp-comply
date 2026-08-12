import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8400',
        changeOrigin: true,
      },
      '/v1': {
        target: 'http://localhost:8400',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
    chunkSizeWarningLimit: 800,
    rollupOptions: {
      output: {
        manualChunks(id) {
          // Keep React and its immediate runtime deps together in one chunk to
          // avoid a circular module graph that breaks production loads.
          if (id.includes('node_modules')) {
            if (
              /node_modules[/\\]react[/\\]/.test(id) ||
              /node_modules[/\\]react-dom[/\\]/.test(id) ||
              /node_modules[/\\]scheduler[/\\]/.test(id) ||
              /node_modules[/\\]use-sync-external-store[/\\]/.test(id)
            ) {
              return 'vendor-react'
            }
            if (id.includes('@clerk')) {
              return 'vendor-clerk'
            }
            if (id.includes('@tanstack/react-query')) {
              return 'vendor-query'
            }
            if (id.includes('react-markdown') || id.includes('remark-gfm')) {
              return 'vendor-markdown'
            }
            if (id.includes('lucide-react')) {
              return 'vendor-icons'
            }
            return 'vendor'
          }
        },
      },
    },
  },
})
