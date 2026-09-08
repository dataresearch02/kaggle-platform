import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './integration',
  outputDir: 'hub-test-results',
  workers: 1,
  timeout: 300_000,
  expect: { timeout: 30_000 },
  use: {
    baseURL: 'http://127.0.0.1:8080',
    viewport: { width: 1440, height: 1000 },
    trace: 'retain-on-failure',
  },
});
