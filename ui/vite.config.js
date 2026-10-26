import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In dev (npm run dev) API calls are proxied to the Flask server.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { '/api': 'http://127.0.0.1:5050' } }
})
