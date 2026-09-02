import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src')
    }
  },
  build: {
    outDir: '../app/static/dist',
    emptyOutDir: true,
    manifest: true,
    rollupOptions: {
      output: {
        entryFileNames: 'assets/[name]-[hash].js',
        chunkFileNames: 'assets/[name]-[hash].js',
        assetFileNames: 'assets/[name]-[hash].[ext]'
      }
    }
  },
  server: {
    port: 5173,
    proxy: {
      '/acesso': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        bypass: (req) => {
          if (req.method === 'GET' && req.headers.accept && req.headers.accept.includes('text/html')) {
            return '/index.html'
          }
        }
      },
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      },
      '/static': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      },
      '/login': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        bypass: (req) => {
          if (req.method === 'GET' && req.headers.accept && req.headers.accept.includes('text/html')) {
            return '/index.html'
          }
        }
      },
      '/logout': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      },
      '/admin': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        bypass: (req) => {
          if (req.method === 'GET' && req.headers.accept && req.headers.accept.includes('text/html') && !req.headers.accept.includes('application/json')) {
            return '/index.html'
          }
        }
      },
      '/portaria': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        bypass: (req) => {
          if (req.method === 'GET' && req.headers.accept && req.headers.accept.includes('text/html') && !req.headers.accept.includes('application/json')) {
            return '/index.html'
          }
        }
      },
      '/validador': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        bypass: (req) => {
          if (req.method === 'GET' && req.headers.accept && req.headers.accept.includes('text/html') && !req.headers.accept.includes('application/json')) {
            return '/index.html'
          }
        }
      },
      '/resgate': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        bypass: (req) => {
          if (req.method === 'GET' && req.headers.accept && req.headers.accept.includes('text/html') && !req.headers.accept.includes('application/json')) {
            return '/index.html'
          }
        }
      },
      '/sucesso': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        bypass: (req) => {
          if (req.method === 'GET' && req.headers.accept && req.headers.accept.includes('text/html') && !req.headers.accept.includes('application/json')) {
            return '/index.html'
          }
        }
      },
      '/health': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      }
    }
  }
})
