import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Backend (FastAPI) runs on :8000. Override with BACKEND_URL=http://host:port npm run dev
const backend = process.env.BACKEND_URL || 'http://localhost:8000';

export default defineConfig({
  base: '/',
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: backend, changeOrigin: true },
      '/media': { target: backend, changeOrigin: true },
      '/sim': { target: backend, changeOrigin: true },
      '/ws': { target: backend.replace(/^http/, 'ws'), ws: true, changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    chunkSizeWarningLimit: 900,
  },
});
