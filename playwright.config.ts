import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright config for the Samana Builders ERP.
 * The Django dev server must be running on http://127.0.0.1:8000
 * (`python manage.py runserver`) for these tests to exercise the app.
 */
export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : 4,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: 'http://127.0.0.1:8000',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    // Default authenticated context = admin. Role-specific specs override via test.use().
    storageState: 'tests/.auth/admin.json',
  },
  projects: [
    {
      // Auth setup project — logs in as each role and writes tests/.auth/*.json.
      // Must also use system Chrome (no browser download needed) and start unauthenticated.
      name: 'setup',
      testMatch: /setup\/.*\.setup\.ts/,
      use: {
        ...devices['Desktop Chrome'],
        channel: 'chrome',
        storageState: { cookies: [], origins: [] },
      },
    },
    {
      name: 'chromium',
      // Use the system-installed Google Chrome. The Playwright browser CDN
      // (cdn.playwright.dev) is blocked on this network, so
      // `npx playwright install` times out — channel 'chrome' needs no download.
      use: { ...devices['Desktop Chrome'], channel: 'chrome' },
      dependencies: ['setup'],
    },
  ],
});
