import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { resolve } from 'path'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000'
    }
  },
  build: {
    outDir: 'dist',
    emptyOutDir: false,
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'index.html'),
        vision: resolve(__dirname, 'vision.html'),
        market: resolve(__dirname, 'market.html'),
        app: resolve(__dirname, 'app.html'),
        quant: resolve(__dirname, 'quant.html'),
        strategy: resolve(__dirname, 'strategy.html'),
        share: resolve(__dirname, 'share.html'),
      }
    }
  },
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src')
    }
  }
})
