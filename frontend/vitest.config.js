import path from 'node:path';
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// Modelled on thehub-pr/server/frontend/vitest.config.js. Deliberately a
// local file rather than a rendered federation template: templating it
// would make every JSX frontend drifted until all five had the harness,
// which would block landing tests one repo at a time.
//
// Separate from vite.config.js rather than merging it — the build config
// carries offline-export plumbing a test run neither needs nor should
// depend on.
//
// Tests are co-located with the code they cover. The shared eslint config
// lints src/components/**, so import describe/it/expect from 'vitest'
// explicitly rather than relying on `globals: true`, or the lint gate will
// flag them as undefined.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.js',
    css: false,
    include: ['src/**/*.test.{js,jsx}'],
  },
});
