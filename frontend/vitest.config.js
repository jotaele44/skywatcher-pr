import path from 'node:path';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./tests/setup.js'],
    include: ['./tests/unit/**/*.test.{js,jsx}'],
    clearMocks: true,
    restoreMocks: true,
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json-summary', 'html'],
      reportsDirectory: './coverage',
      include: [
        'src/components/console/BlankOfflineStyle.js',
        'src/components/console/BasemapRegistry.js',
        'src/components/console/LayerRegistry.js',
        'src/components/console/RuntimeResourceLedger.js',
        'src/components/console/WebGLCapabilityProbe.js',
        'src/components/console/OfflineRequestGuard.js',
        'src/components/console/MapRuntimeAdapter.js',
        'src/components/console/ConsoleApiClient.js',
        'src/components/console/consoleDefaults.js',
        'src/components/console/capabilityPolicy.js',
        'src/components/console/consoleState.js',
      ],
      exclude: ['src/components/console/index.js'],
      thresholds: {
        statements: 95,
        branches: 95,
        functions: 95,
        lines: 95,
      },
    },
  },
});
