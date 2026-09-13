import { test as setup, expect } from '@playwright/test';
import { ROLES, RoleName } from '../helpers/auth';

/**
 * Global auth setup: logs in as each role and persists a storageState so authenticated
 * specs can `test.use({ storageState })` instead of logging in per test.
 * Run automatically via the `setup` project (see playwright.config.ts).
 */
for (const [role, creds] of Object.entries(ROLES)) {
  setup(`authenticate ${role}`, async ({ page }) => {
    await page.goto('/login/');
    await page.getByRole('textbox', { name: 'Username' }).fill(creds.username);
    await page.getByRole('textbox', { name: 'Password' }).fill(creds.password);
    await page.getByRole('button', { name: 'Sign In' }).click();
    await expect(page).toHaveURL(creds.landing);
    await page.context().storageState({ path: `tests/.auth/${role}.json` });
  });
}
