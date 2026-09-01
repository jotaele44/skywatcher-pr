import path from 'node:path';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  logLevel: 'error',
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  plugins: [react()],
  server: {
    proxy: {
      // The app calls a relative /api (see src/lib/app-params.js) because in
      // production and in the desktop wrapper a single origin serves both the
      // built UI and the API. Split dev puts the API on its own port, so
      // forward it. Target matches the `backend` entry in .claude/launch.json.
      '/api': {
        target: process.env.VITE_API_PROXY_TARGET || 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
});
