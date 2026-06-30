import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 1678,
    host: true,
    proxy: {
      '/api': {
        target: 'http://localhost:11678',
        changeOrigin: true,
      },
    },
  },
  preview: {
    port: 1678,
  },
})
