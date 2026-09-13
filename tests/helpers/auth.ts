import { APIRequestContext, Page, expect } from '@playwright/test';

/**
 * Shared auth helpers. Role users + the portal customer are seeded idempotently by
 * `tests/fixtures/seed_roles.py` (password 'admin123' for all).
 */
export const ROLES = {
  admin:      { username: 'admin',         password: 'admin123', landing: '/dashboard/' },
  management: { username: 'qa_management', password: 'admin123', landing: '/dashboard/' },
  accounts:   { username: 'qa_accounts',   password: 'admin123', landing: '/dashboard/' },
  sales:      { username: 'qa_sales',      password: 'admin123', landing: '/dashboard/' },
  hr:         { username: 'qa_hr',         password: 'admin123', landing: '/dashboard/' },
  customer:   { username: 'qa_customer',   password: 'admin123', landing: '/portal/' },
} as const;

export type RoleName = keyof typeof ROLES;

/** Log in through the rendered login form and wait for the role's landing page. */
export async function loginViaUi(page: Page, role: RoleName): Promise<void> {
  const creds = ROLES[role];
  await page.goto('/login/');
  await page.getByRole('textbox', { name: 'Username' }).fill(creds.username);
  await page.getByRole('textbox', { name: 'Password' }).fill(creds.password);
  await page.getByRole('button', { name: 'Sign In' }).click();
  await expect(page).toHaveURL(creds.landing);
}

/**
 * Log in through the DRF API and return the CSRF token for subsequent authenticated writes.
 * The returned `request` context keeps the session cookie, so follow-up requests are
 * authenticated. GET requests need no CSRF; unsafe requests should pass the token via
 * `X-CSRFToken`.
 */
export async function loginViaApi(request: APIRequestContext, role: RoleName): Promise<string> {
  const creds = ROLES[role];
  for (let attempt = 0; attempt < 3; attempt++) {
    await request.get('/api/auth/csrf/');
    // Capture the CSRF token set by /api/auth/csrf/ so the login POST can pass it
    // in the X-CSRFToken header (Django requires the token for any unsafe method).
    let token = '';
    try {
      const state = await request.storageState();
      const cookie = state.cookies.find((c) => c.name === 'csrftoken');
      token = cookie ? cookie.value : '';
    } catch {
      token = '';
    }
    const res = await request.post('/api/auth/login/', {
      data: { username: creds.username, password: creds.password },
      headers: token ? { 'X-CSRFToken': token } : {},
    });
    if (res.status() === 200) {
      // Re-read the CSRF cookie AFTER login — Django's login() rotates the token, so
      // any token captured before login is stale for subsequent authenticated writes.
      try {
        const state = await request.storageState();
        const cookie = state.cookies.find((c) => c.name === 'csrftoken');
        if (cookie) token = cookie.value;
      } catch {
        // keep the pre-login token as a fallback
      }
      return token;
    }
    // 403 = intermittent CSRF race under parallel load (cookie not yet settled);
    // retry the csrf + login handshake. Any other status is a real failure.
    if (res.status() !== 403) {
      throw new Error(`Login failed for ${role}: HTTP ${res.status()} ${await res.text()}`);
    }
  }
  throw new Error(`Login failed for ${role} after 3 attempts (CSRF race)`);
}
