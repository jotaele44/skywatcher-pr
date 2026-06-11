import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Vite configuration for the PRIIS frontend. This config enables React support
// and sets a default development port. Additional configuration can be added
// here for proxying API requests or customizing the build.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
  },
});