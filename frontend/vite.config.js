import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      '/api': 'http://localhost:8085',
      '/auth': 'http://localhost:8085',
      '/socket.io': { target: 'http://localhost:8085', ws: true },
    },
  },
})
