import { defineConfig } from 'vitest/config';
import path from 'path';

export default defineConfig({
  test: {
    include: ['src/**/__tests__/**/*.test.ts'],
    environment: 'node',
    alias: {
      // Mock electron module so tests that transitively import config.ts
      // (which uses `app` from electron) do not crash.
      electron: path.resolve(__dirname, 'src/main/__tests__/__mocks__/electron.ts'),
    },
  },
});
