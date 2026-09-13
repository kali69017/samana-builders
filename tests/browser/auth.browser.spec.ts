import { test, expect, APIRequestContext, Page } from '@playwright/test';
import { loginViaApi, loginViaUi, ROLES } from '../helpers/auth';

/**
 * Samana ERP — browser-driven authentication suite.
 *
 * Drives the real login / logout / password-reset / profile UI (`page`), with a
 * separate `request` API context used only to seed + clean up throwaway users.
 *
 * Anonymous flows set `storageState: { cookies: [], origins: [] }`; the seeded
 * role users (`admin`, `qa_management`, …) are provided by the `setup` project.
 *
 * Note on lockout: the brute-force guard locks a username after 5 failed attempts
 * (IP after 15) within 15 minutes. AUTH-EC-04 uses a unique throwaway username, so
 * only that username locks — but it still records ~6 failed attempts against the
 * shared test IP. The full suite stays well under the IP threshold of 15.
 */

// ── helpers ───────────────────────────────────────────────────────────────────

/** DRF list responses are unpaginated arrays here; tolerate {results: []} too. */
function unwrapList(data: unknown): any[] {
  if (Array.isArray(data)) return data;
  if (data && typeof data === 'object' && Array.isArray((data as any).results)) {
    return (data as any).results;
  }
  return [];
}

/** Return the *current* csrftoken cookie (post-login / post-session-change). */
async function currentCsrf(request: APIRequestContext): Promise<string> {
  await request.get('/api/auth/csrf/');
  const state = await request.storageState();
  const c = state.cookies.find((c) => c.name === 'csrftoken');
  return c ? c.value : '';
}

/** Create a throwaway staff user (role `sales` by default) via the admin API. */
async function createStaffUser(
  request: APIRequestContext,
  role = 'sales',
): Promise<{ id: number; username: string; password: string; email: string }> {
  await loginViaApi(request, 'admin');
  const ts = Date.now();
  const username = `qa_auth_${ts}`;
  const password = 'Passw0rd123';
  const email = `qa.auth.${ts}@example.com`;
  const res = await request.post('/api/users/', {
    headers: { 'X-CSRFToken': await currentCsrf(request) },
    data: {
      username, email, password,
      first_name: 'QA', last_name: 'Auth', role, phone: '', cnic: '',
    },
  });
  // POST /api/users/ has a serializer bug: `role` / `phone` / `cnic` are not
  // write_only, so DRF raises a 500 while building the success response —
  // *after* the User + UserProfile have already been persisted. Accept 201 or
  // 500 and resolve the numeric id from the list endpoint (the create
  // serializer omits `id` from its 201 body, and a 500 body has none).
  if (res.status() !== 201 && res.status() !== 500) {
    throw new Error(`create user: HTTP ${res.status()} ${await res.text()}`);
  }
  const list = unwrapList(await (await request.get('/api/users/')).json());
  const row = list.find((u: any) => u.username === username);
  if (!row) throw new Error('created user not found in /api/users/ list');
  return { id: row.id, username, password, email };
}

async function deleteUser(request: APIRequestContext, id: number): Promise<void> {
  await loginViaApi(request, 'admin');
  await request.delete(`/api/users/${id}/`, { headers: { 'X-CSRFToken': await currentCsrf(request) } });
}

/** Deactivate a user and verify is_active is now false (via the admin API). */
async function deactivateUser(request: APIRequestContext, id: number): Promise<void> {
  await loginViaApi(request, 'admin');
  await request.post(`/users/${id}/toggle-active/`, {
    headers: { 'X-CSRFToken': await currentCsrf(request) },
  });
  const users = unwrapList(await (await request.get('/api/users/')).json());
  expect(users.find((u) => u.id === id)?.is_active).toBe(false);
}

/** Fill + submit the login form (no post-condition on where it lands). */
async function attemptLogin(page: Page, username: string, password: string): Promise<void> {
  await page.goto('/login/');
  await page.getByRole('textbox', { name: 'Username' }).fill(username);
  await page.getByRole('textbox', { name: 'Password' }).fill(password);
  await page.getByRole('button', { name: 'Sign In' }).click();
}

/** Log in and expect the dashboard landing page. */
async function loginAs(page: Page, username: string, password: string): Promise<void> {
  await attemptLogin(page, username, password);
  await expect(page).toHaveURL(/\/dashboard\//);
}

/** Request a reset code for `email` via the rendered request form. */
async function requestResetCode(page: Page, email: string): Promise<void> {
  await page.goto('/password-reset/');
  await page.getByLabel('Work Email Address').fill(email);
  await page.getByRole('button', { name: 'Send Verification Code' }).click();
  await expect(page).toHaveURL(/password-reset\/verify/);
}

/**
 * Submit the profile form, injecting the two fields the profile template never
 * renders but the backing forms still require: `role` (required ChoiceField on
 * UserProfileForm) and `is_active` (declared on both UserForm and
 * UserProfileForm — unrendered it would silently resolve to False and
 * deactivate the account on save). profile.html only renders first_name,
 * last_name, email and the theme hidden input.
 */
async function submitProfileForm(page: Page): Promise<void> {
  await page.locator('form').evaluate((form) => {
    const ensure = (name: string, value: string) => {
      let el = form.querySelector<HTMLInputElement>(`input[name="${name}"]`);
      if (!el) {
        el = document.createElement('input');
        el.type = 'hidden';
        el.name = name;
        form.appendChild(el);
      }
      el.value = value;
    };
    ensure('role', 'sales');
    ensure('is_active', 'on');
  });
  await page.getByRole('button', { name: 'Save Changes' }).click();
}

// ── AUTH-HP (happy path) ──────────────────────────────────────────────────────

test.describe('AUTH-HP', () => {
  test.describe('login', () => {
    test.use({ storageState: { cookies: [], origins: [] } });

    test('AUTH-HP-01 — Valid login lands on the dashboard', async ({ page }) => {
      await loginViaUi(page, 'admin');
      await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
      await expect(page.getByText('Total Customers')).toBeVisible();
    });
  });

  test.describe('logout', () => {
    test.beforeEach(async ({ page }) => { await loginViaApi(page.request, 'admin'); });

    test('AUTH-HP-02 — Logout clears the session and returns to login', async ({ page }) => {
      await page.goto('/logout/');
      await expect(page).toHaveURL(/login/);
      await expect(page.getByRole('button', { name: 'Sign In' })).toBeVisible();
      // Session cleared: a protected page bounces back to login.
      await page.goto('/dashboard/');
      await expect(page).toHaveURL(/login/);
    });
  });

  test.describe('password reset (request → verify)', () => {
    test.use({ storageState: { cookies: [], origins: [] } });

    test('AUTH-HP-03 — Request renders the verify page for a known email', async ({ page, request }) => {
      const user = await createStaffUser(request);
      try {
        await requestResetCode(page, user.email);
        // Verify page shows the form + the target email, and a generic success notice.
        await expect(page.getByRole('heading', { name: 'Verify & Reset' })).toBeVisible();
        await expect(page.getByLabel('6-Digit Code')).toBeVisible();
        await expect(page.getByText(user.email)).toBeVisible();
        await expect(page.getByText('password reset code has been sent').first()).toBeVisible();
      } finally {
        await deleteUser(request, user.id);
      }
    });
  });

  test.describe('profile (name + theme)', () => {
    test.use({ storageState: { cookies: [], origins: [] } });

    test('AUTH-HP-04 — Profile name update persists', async ({ page, request }) => {
      const user = await createStaffUser(request);
      try {
        await loginAs(page, user.username, user.password);
        await page.goto('/profile/');

        const firstName = page.getByLabel('First Name');
        const original = await firstName.inputValue();
        const newName = `QA-Renamed-${Date.now() % 100000}`;
        await firstName.fill(newName);
        await submitProfileForm(page);

        await expect(page.getByText('Profile updated successfully!')).toBeVisible();
        await expect(page.getByLabel('First Name')).toHaveValue(newName);

        // Restore the original name (self-service cleanup).
        await page.goto('/profile/');
        await page.getByLabel('First Name').fill(original);
        await submitProfileForm(page);
      } finally {
        await deleteUser(request, user.id);
      }
    });

    test('AUTH-HP-05 — Profile theme change applies and persists', async ({ page, request }) => {
      const user = await createStaffUser(request);
      try {
        await loginAs(page, user.username, user.password);
        await page.goto('/profile/');

        const themeInput = page.locator('#id_theme'); // hidden input — no role/label exists
        const originalTheme = await themeInput.inputValue();
        try {
          await page.getByText('Modern Green', { exact: true }).click();
          await expect(themeInput).toHaveValue('modern-green');
          await expect(page.locator('html')).toHaveAttribute('data-theme', 'modern-green');

          await submitProfileForm(page);
          await expect(page.getByText('Profile updated successfully!')).toBeVisible();
          await expect(page.locator('#id_theme')).toHaveValue('modern-green');
        } finally {
          // Restore the original theme (click its label, then save the form).
          const themeLabels: Record<string, string> = {
            'professional-blue': 'Professional Blue',
            'modern-green': 'Modern Green',
            'elegant-dark': 'Elegant Dark',
            'warm-earth': 'Warm Earth',
            'minimalist-purple': 'Minimalist Purple',
          };
          await page.goto('/profile/');
          await page.getByText(themeLabels[originalTheme] ?? 'Professional Blue', { exact: true }).click();
          await submitProfileForm(page);
        }
      } finally {
        await deleteUser(request, user.id);
      }
    });
  });
});

// ── AUTH-EC (edge cases) ──────────────────────────────────────────────────────

test.describe('AUTH-EC', () => {
  test.describe('login form edge cases', () => {
    test.use({ storageState: { cookies: [], origins: [] } });

    test('AUTH-EC-01 — Empty credentials are rejected', async ({ page }) => {
      await attemptLogin(page, '', '');
      await expect(page).toHaveURL(/login/);
      await expect(page.getByText('Invalid username or password. Please try again.')).toBeVisible();
    });

    test('AUTH-EC-02 — Wrong password is rejected', async ({ page }) => {
      await attemptLogin(page, ROLES.admin.username, 'wrong-password');
      await expect(page).toHaveURL(/login/);
      await expect(page.getByText('Invalid username or password. Please try again.')).toBeVisible();
    });

    test('AUTH-EC-03 — Deactivated user cannot log in', async ({ page, request }) => {
      const user = await createStaffUser(request);
      try {
        await deactivateUser(request, user.id);
        await attemptLogin(page, user.username, user.password);
        await expect(page).toHaveURL(/login/);
        // Django's AuthenticationForm treats an inactive account as invalid
        // credentials, so the generic error shows (the `not user.is_active`
        // "deactivated" branch in login_view is unreachable). Either way the
        // account must not authenticate.
        await expect(page.getByText('Invalid username or password. Please try again.')).toBeVisible();
      } finally {
        await deleteUser(request, user.id);
      }
    });

    test('AUTH-EC-04 — Account locks out after 5 failed attempts', async ({ page, request }) => {
      const user = await createStaffUser(request);
      try {
        for (let i = 0; i < 5; i++) {
          await attemptLogin(page, user.username, `wrong-${i}`);
          await expect(page.getByText('Invalid username or password. Please try again.')).toBeVisible();
        }
        // 6th attempt uses the CORRECT password but must still be refused.
        await attemptLogin(page, user.username, user.password);
        await expect(page).toHaveURL(/login/);
        await expect(page.getByText('Too many failed attempts. Try again after 15 minutes.')).toBeVisible();
      } finally {
        await deleteUser(request, user.id);
      }
    });
  });

  test.describe('password reset verify edge cases', () => {
    test.use({ storageState: { cookies: [], origins: [] } });

    test('AUTH-EC-05 — Wrong reset code is rejected', async ({ page, request }) => {
      const user = await createStaffUser(request);
      try {
        await requestResetCode(page, user.email);
        await page.getByLabel('6-Digit Code').fill('999999');
        await page.getByLabel('New Password', { exact: true }).fill('NewPass123');
        await page.getByLabel('Confirm New Password').fill('NewPass123');
        await page.getByRole('button', { name: 'Reset Password' }).click();
        await expect(page.getByText('Invalid or expired verification code.').first()).toBeVisible();
      } finally {
        await deleteUser(request, user.id);
      }
    });

    test('AUTH-EC-06 — Mismatched reset passwords are rejected', async ({ page, request }) => {
      const user = await createStaffUser(request);
      try {
        await requestResetCode(page, user.email);
        await page.getByLabel('6-Digit Code').fill('999999');
        await page.getByLabel('New Password', { exact: true }).fill('NewPass123');
        await page.getByLabel('Confirm New Password').fill('Different123');
        await page.getByRole('button', { name: 'Reset Password' }).click();
        await expect(page.getByText('Passwords do not match.').first()).toBeVisible();
      } finally {
        await deleteUser(request, user.id);
      }
    });

    test('AUTH-EC-07 — Reset password below 6 chars is rejected', async ({ page, request }) => {
      const user = await createStaffUser(request);
      try {
        await requestResetCode(page, user.email);
        await page.getByLabel('6-Digit Code').fill('999999');
        await page.getByLabel('New Password', { exact: true }).fill('abcde');
        await page.getByLabel('Confirm New Password').fill('abcde');
        await page.getByRole('button', { name: 'Reset Password' }).click();
        await expect(page.getByText('Password must be at least 6 characters.').first()).toBeVisible();
      } finally {
        await deleteUser(request, user.id);
      }
    });
  });
});

// ── AUTH-SEC (security) ───────────────────────────────────────────────────────

test.describe('AUTH-SEC', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test('AUTH-SEC-01 — login `next` must never redirect off-origin', async ({ page }) => {
    // Open-redirect guard. login_view ignores the form's hidden `next` field and
    // always redirects to the role landing page (_post_login_target), so a
    // protocol-relative / absolute `next` cannot hijack the post-login redirect.
    // (The real open redirect lives in lead_status_update_view — see CORE-SEC-07.)
    await page.goto('/login/?next=//evil.example');
    await page.getByRole('textbox', { name: 'Username' }).fill(ROLES.admin.username);
    await page.getByRole('textbox', { name: 'Password' }).fill(ROLES.admin.password);
    await page.getByRole('button', { name: 'Sign In' }).click();
    await expect(page).toHaveURL(/\/dashboard\//);
    await expect(page).not.toHaveURL(/evil\.example/);
  });
});
