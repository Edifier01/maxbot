const { defineConfig } = require('@playwright/test');

const baseURL = process.env.BASE_URL || 'http://127.0.0.1:8765';

module.exports = defineConfig({
  testDir: './tests/browser',
  timeout: 30_000,
  expect: { timeout: 5_000 },
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [
    ['list'],
    ['html', { outputFolder: 'playwright-report', open: 'never' }],
  ],
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    {
      name: '390x844',
      use: { viewport: { width: 390, height: 844 } },
    },
    {
      name: '768x1024',
      use: { viewport: { width: 768, height: 1024 } },
    },
    {
      name: '1440x1000',
      use: { viewport: { width: 1440, height: 1000 } },
    },
  ],
});
