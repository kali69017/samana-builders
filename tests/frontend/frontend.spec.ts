import { test, expect, Browser } from '@playwright/test';
import { loginViaUi, loginViaApi } from '../helpers/auth';
import * as fs from 'fs';
import * as path from 'path';

/**
 * Frontend layer suite — templates / static JS / forms / cross-cutting UI risks.
 * Source of truth: specs/frontend.md + docs/qa/findings-confirmed.md.
 *
 * Storage state files are produced by the `setup` project (tests/setup/auth.setup.ts).
 * Public (anonymous) pages override with an empty storage state.
 *
 * RED tests (confirmed defects) assert the CORRECT behaviour and therefore FAIL on the
 * buggy app. They are NOT `fixme` and must stay red (see tests/CONVENTIONS.md).
 */
const BASE = 'http://127.0.0.1:8000';
const SS = {
  admin: 'tests/.auth/admin.json',
  accounts: 'tests/.auth/accounts.json',
  sales: 'tests/.auth/sales.json',
  customer: 'tests/.auth/customer.json',
} as const;
const ANON = { cookies: [], origins: [] } as const;

// --- source readers (for the static/template/JS scenarios) -----------------
const ROOT = path.resolve(__dirname, '..', '..'); // tests/frontend -> repo root
function readSource(rel: string): string {
  return fs.readFileSync(path.join(ROOT, rel), 'utf8');
}
function readTemplates(): string[] {
  const dir = path.join(ROOT, 'templates');
  const out: string[] = [];
  const walk = (d: string) => {
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
      const full = path.join(d, e.name);
      if (e.isDirectory()) walk(full);
      else if (e.name.endsWith('.html')) out.push(fs.readFileSync(full, 'utf8'));
    }
  };
  walk(dir);
  return out;
}

const XSS_PAYLOAD = '<img src=x onerror=window.__xss=1>';

// ============================================================================
// FE-HP — happy path
// ============================================================================
test.describe('FE-HP', () => {
  test.describe('public', () => {
    test.use({ storageState: ANON });

    test('FE-HP-01 — Login page renders', async ({ page }) => {
      const errors: string[] = [];
      page.on('pageerror', (e) => errors.push(e.message));

      await page.goto('/login/');
      const form = page.locator('form[method="post"]');
      await expect(form).toHaveAttribute('action', '/login/');
      await expect(form.locator('input[name="csrfmiddlewaretoken"]')).toHaveCount(1);

      const username = page.getByLabel('Username');
      await expect(username).toBeVisible();
      await expect(username).toHaveAttribute('autocomplete', 'username');
      const password = page.getByLabel('Password');
      await expect(password).toBeVisible();
      await expect(password).toHaveAttribute('autocomplete', 'current-password');

      await expect(page.getByRole('link', { name: /Forgot Password/ })).toBeVisible();
      expect(errors).toEqual([]);
    });

    test('FE-HP-02 — Login submits and lands on the right home', async ({ page }) => {
      // Staff land on /dashboard/
      await loginViaUi(page, 'admin');
      await page.context().clearCookies();

      // Customer lands on /portal/
      await loginViaUi(page, 'customer');
      await page.context().clearCookies();

      // Invalid credentials re-render /login/ with the error, no redirect
      await page.goto('/login/');
      await page.getByLabel('Username').fill('nonexistent-qa-user');
      await page.getByLabel('Password').fill('wrong-password');
      await page.getByRole('button', { name: 'Sign In' }).click();
      await expect(page).toHaveURL(/\/login\//);
      await expect(page.getByText(/Invalid username or password/).first()).toBeVisible();
    });

    test('FE-HP-05 — Corporate home renders (hero, projects, lead form, contact)', async ({ page }) => {
      await page.goto('/');
      await expect(page.locator('.hero-title')).toContainText('Building Trust');
      await expect(page.locator('.hero-badge')).toBeVisible();

      // three project cards with alt images
      await expect(page.locator('.project-card')).toHaveCount(3);
      await expect(page.locator('.project-card img[alt]')).toHaveCount(3);

      // testimonials + titled maps iframe
      await expect(page.locator('#testimonials blockquote')).toBeVisible();
      await expect(page.locator('iframe[title*="Samana Builders"]')).toBeVisible();

      // contact / lead form
      const form = page.locator('#contact form');
      await expect(form).toBeVisible();
      await expect(form.locator('input[name="name"]')).toBeVisible();
      await expect(form.locator('input[name="email"]')).toBeVisible();
      await expect(form.locator('input[name="phone"]')).toBeVisible();
      await expect(form.locator('select[name="interest"]')).toBeVisible();
      await expect(form.locator('textarea[name="message"]')).toBeVisible();
      await expect(form.getByRole('button', { name: 'Send Message' })).toBeVisible();
    });

    test('FE-HP-06 — Corporate lead form submits → creates a Lead', async ({ page, request }) => {
      const token = await loginViaApi(request, 'admin');
      const ts = Date.now();
      const name = `QA-Lead-${ts}`;
      const email = `qa-lead-${ts}@example.com`;

      await page.goto('/');
      const form = page.locator('#contact form');
      await form.locator('input[name="name"]').fill(name);
      await form.locator('input[name="email"]').fill(email);
      await form.locator('input[name="phone"]').fill('03001234567');
      await form.locator('select[name="interest"]').selectOption('residential');
      await form.locator('textarea[name="message"]').fill('QA enquiry');
      await form.locator('button[type="submit"]').click();

      // redirects back to the corporate home (no 403 — CSRF present)
      await expect(page).toHaveURL(/\/$/);

      // verify the Lead row was created (source=strip)
      const res = await request.get('/api/leads/');
      expect(res.ok()).toBeTruthy();
      const body = await res.json();
      const leads = Array.isArray(body) ? body : (body.results || []);
      const created = leads.find((l: any) => l.email === email);
      expect(created).toBeTruthy();
      expect(created.source).toBe('strip');

      // cleanup (data isolation)
      if (created && created.id) {
        await request.delete(`/api/leads/${created.id}/`, { headers: { 'X-CSRFToken': token } });
      }
    });
  });

  test.describe('staff', () => {
    test.use({ storageState: SS.admin });

    test('FE-HP-03 — ERP base layout + sidebar nav render for staff', async ({ page }) => {
      const errors: string[] = [];
      page.on('pageerror', (e) => errors.push(e.message));

      await page.goto('/dashboard/');
      await expect(page.locator('.topbar')).toBeVisible();
      await expect(page.locator('.sidebar')).toBeVisible();
      await expect(page.locator('.main-content')).toBeVisible();
      await expect(page.locator('a.nav-link.active')).toContainText('Dashboard');

      // erp.js loaded with versioned query; Chart.js 4.4.7 script tag present
      const erpSrc = await page.locator('script[src*="erp.js"]').getAttribute('src');
      expect(erpSrc).toContain('?v=2');
      await expect(page.locator('script[src*="chart.js@4.4.7"]')).toHaveCount(1);

      // click through sidebar links (no 404)
      for (const name of ['Customers', 'Properties', 'Bookings']) {
        await page.getByRole('link', { name, exact: true }).first().click();
        await expect(page.locator('.main-content')).toBeVisible();
      }
      expect(errors).toEqual([]);
    });

    test('FE-HP-04 — Sidebar role gating matches server flags', async ({ browser }) => {
      // ---- sales: no Payments/Finance/Expenses/Reports/Manage Users/notification bell
      const salesCtx = await browser.newContext({ storageState: SS.sales, baseURL: BASE });
      const salesPage = await salesCtx.newPage();
      await salesPage.goto('/dashboard/');
      const salesSidebar = salesPage.locator('.sidebar');
      for (const name of ['Payments', 'Expenses', 'Financial Reports', 'Manage Users', 'DB Backup']) {
        await expect(salesSidebar.getByRole('link', { name, exact: true })).toHaveCount(0);
      }
      await expect(salesPage.locator('a[title="Notifications"]')).toHaveCount(0);
      // hitting a hidden URL directly redirects to the dashboard
      await salesPage.goto('/payments/');
      await expect(salesPage).toHaveURL(/\/dashboard\//);
      await salesCtx.close();

      // ---- accounts: sees Payments/Refunds/Ledger/Reports, but no Manage Users/DB Backup
      const accountsCtx = await browser.newContext({ storageState: SS.accounts, baseURL: BASE });
      const accountsPage = await accountsCtx.newPage();
      await accountsPage.goto('/dashboard/');
      const accountsSidebar = accountsPage.locator('.sidebar');
      for (const name of ['Payments', 'Refunds', 'Ledger', 'Financial Reports']) {
        await expect(accountsSidebar.getByRole('link', { name, exact: true })).toHaveCount(1);
      }
      for (const name of ['Manage Users', 'DB Backup']) {
        await expect(accountsSidebar.getByRole('link', { name, exact: true })).toHaveCount(0);
      }
      await accountsCtx.close();
    });

    test('FE-HP-07 — Money renders consistently within a single page', async ({ page }) => {
      await page.goto('/reports/financial/');
      const amounts = await page.evaluate(() => {
        const out: string[] = [];
        document.querySelectorAll('.stat-value, .card-body span, table tbody td').forEach((el) => {
          const t = (el as HTMLElement).textContent?.trim() || '';
          if (/^Rs\./.test(t)) out.push(t);
        });
        return out;
      });
      expect(amounts.length).toBeGreaterThan(0);
      // same pattern everywhere: 'Rs. ' prefix + whole PKR (no decimals), comma grouping only
      for (const a of amounts) {
        expect(a).toMatch(/^Rs\. \d[\d,]*$/);
      }
    });
  });

  test.describe('customer portal', () => {
    test.use({ storageState: SS.customer });

    test('FE-HP-08 — /portal/ is the Django template, not the orphaned React build', async ({ page }) => {
      await page.goto('/portal/');
      await expect(page.locator('.portal-wrap')).toBeVisible();
      await expect(page.locator('.welcome-card')).toBeVisible();
      // Django shell (base.html topbar) is present
      await expect(page.locator('.topbar')).toBeVisible();

      const scripts = await page.locator('script[src]').evaluateAll((els) =>
        els.map((e) => (e as HTMLScriptElement).getAttribute('src') || ''),
      );
      // no React mount / dist bundle
      expect(scripts.some((s) => /assets\/index-|frontend\/dist/.test(s))).toBe(false);
      await expect(page.locator('#root')).toHaveCount(0);
      // erp.js is the loaded JS
      expect(scripts.some((s) => /erp\.js/.test(s))).toBe(true);
    });
  });
});

// ============================================================================
// FE-EC — edge / boundary
// ============================================================================
test.describe('FE-EC', () => {
  test('FE-EC-01 — Money formatting fragmentation across pages', async () => {
    // Record the distinct formatting approaches that coexist in the codebase.
    const propertiesHtml = readSource('templates/properties.html');
    const financialHtml = readSource('templates/financial_reports.html');
    const receiptHtml = readSource('templates/receipt_detail.html');
    const erpJs = readSource('static/js/erp.js');

    expect(propertiesHtml).toContain('|money'); // comma, whole
    expect(financialHtml).toContain('floatformat:0|intcomma'); // comma, whole
    expect(receiptHtml).toContain('floatformat:0'); // NO comma
    expect(erpJs).toContain('toLocaleString'); // browser-locale grouping
    expect(erpJs).toContain("toLocaleString('en-IN')"); // Indian grouping
    // => the same amount is rendered differently depending on page (baseline).
  });

  test('FE-EC-02 — Paisa precision dropped silently', async () => {
    const moneyPy = readSource('properties/templatetags/property_tags.py');
    const receiptHtml = readSource('templates/receipt_detail.html');

    // money filter defaults to decimals=0 → 1,500,000.50 renders as 1,500,000
    expect(moneyPy).toContain('def money(value, decimals=0)');
    expect(moneyPy).toContain("f'{num:,.0f}'");
    // receipt uses floatformat:0 → drops paisa too
    expect(receiptHtml).toContain('floatformat:0');
    // => DB stores 2 decimals, but the UI silently rounds .50 away.
  });

  test('FE-EC-03 — JS toLocaleString grouping follows browser locale', async () => {
    const erpJs = readSource('static/js/erp.js');
    // counter uses toLocaleString() with no locale → follows the browser locale
    expect(erpJs).toContain('toLocaleString()');
    // formatCurrency hard-codes 'en-IN' → grouping inconsistent inside the same product
    expect(erpJs).toContain("toLocaleString('en-IN')");
  });

  test('FE-EC-04 — hr/leaves.html approve/reject action forms are correctly wired', async () => {
    const leavesHtml = readSource('templates/hr/leaves.html');
    // two DISTINCT inline forms: approve vs reject, both posting to hr_leave_approve
    const approveCount = (leavesHtml.match(/value="approve"/g) || []).length;
    const rejectCount = (leavesHtml.match(/value="reject"/g) || []).length;
    expect(approveCount).toBe(1);
    expect(rejectCount).toBe(1);
    expect(leavesHtml).toContain('hr_leave_approve');
  });

  test.describe('staff forms', () => {
    test.use({ storageState: SS.admin });

    test('FE-EC-05 — No client-side double-submit disable (spinner but button stays enabled)', async ({ page }) => {
      await page.goto('/properties/plot/create/');
      const btn = page.locator('form button[type="submit"]').first();
      await expect(btn).toBeVisible();

      // Prevent actual navigation so we can observe the post-submit button state.
      await page.evaluate(() => {
        const form = document.querySelector('form');
        form?.addEventListener('submit', (e) => e.preventDefault());
      });

      await btn.click();
      // erp.js adds .loading + spinner but never disables the button
      await expect(btn).toHaveClass(/loading/);
      await expect(btn).toBeEnabled(); // not disabled → double-submit possible
    });

    test('FE-EC-08 — Stale session: no 401/403 redirect handling on AI fetch', async ({ page }) => {
      await page.route((url) => url.pathname.startsWith('/api/ai/insights'), (route) =>
        route.fulfill({ status: 403, json: { ok: false, error: 'Forbidden' } }),
      );
      await page.goto('/ai/insights/');
      await page.getByRole('button', { name: /Generate Insights/ }).click();

      // The 403 is surfaced inline as an error; the user is NOT redirected to /login/.
      await expect(page.locator('#insightsBox')).toContainText('AI error');
      await expect(page).toHaveURL(/ai\/insights/);
    });

    test('FE-EC-09 — Print CSS hides entry/confirm forms', async () => {
      const erpCss = readSource('static/css/erp.css');
      expect(erpCss).toContain('@media print');
      expect(erpCss).toMatch(/form\s*\{\s*display:\s*none/);
    });
  });

  test.describe('login form', () => {
    test.use({ storageState: ANON });

    test('FE-EC-06 — novalidate disables browser validation (whitespace-only required field)', async ({ page }) => {
      await page.goto('/login/');
      const form = page.locator('form[method="post"]');
      await expect(form).toHaveAttribute('novalidate', '');

      // whitespace-only username + empty password still submit (novalidate bypasses client check)
      await page.locator('#id_username').fill('   ');
      await page.locator('#id_password').fill('');
      await page.getByRole('button', { name: 'Sign In' }).click();
      // server-side validation rejects and re-renders /login/ with the error
      await expect(page).toHaveURL(/\/login\//);
      await expect(page.getByText(/Invalid username or password/).first()).toBeVisible();
    });

    test('FE-EC-07 — Floating-label state on whitespace-only value', async ({ page }) => {
      await page.goto('/login/');
      await page.locator('#id_username').fill('   ');
      await page.locator('#id_username').blur();

      // syncFloatingLabels keys off value.trim() !== '' → whitespace counts as EMPTY
      const filled = await page.evaluate(() =>
        document.querySelector('.floating-group')?.classList.contains('filled'),
      );
      expect(filled).toBe(false);
      // ...but the CSS :not(:placeholder-shown) rule still floats the label (has content)
      const placeholderShown = await page.evaluate(() =>
        (document.querySelector('#id_username') as HTMLInputElement)?.matches(':placeholder-shown'),
      );
      expect(placeholderShown).toBe(false);
      // => label looks "filled" while the JS state + server `required` disagree.
    });
  });
});

// ============================================================================
// FE-SEC — negative & security
// ============================================================================
test.describe('FE-SEC', () => {
  test.describe('staff', () => {
    test.use({ storageState: SS.admin });

    test('FE-SEC-01 — [HIGH] Stored XSS via AI insights preview (innerHTML)', async ({ page }) => {
      // Stub the LLM endpoint so no live model is needed (deterministic repro).
      await page.route((url) => url.pathname.startsWith('/api/ai/insights'), (route) =>
        route.fulfill({ json: { ok: true, result: XSS_PAYLOAD } }),
      );
      await page.goto('/ai/insights/');
      await page.evaluate(() => {
        (window as any).__xss = undefined;
      });
      await page.getByRole('button', { name: /Generate Insights/ }).click();
      await expect(page.locator('#historyList .history-item').first()).toBeVisible();

      // CORRECT behaviour: the history container renders the preview as TEXT.
      // CONFIRMED BUG: docs/qa/findings-confirmed.md F7 — innerHTML sink injects a live <img>.
      expect(await page.locator('#historyList .history-item img').count()).toBe(0); // RED (deterministic)
      await page.waitForFunction(() => (window as any).__xss === 1, undefined, { timeout: 3000 }).catch(() => {});
      expect(await page.evaluate(() => (window as any).__xss)).toBeUndefined(); // RED: will be 1
    });

    test('FE-SEC-02 — Partial-escape XSS in AI HR chat echo (insertAdjacentHTML)', async ({ page }) => {
      await page.route((url) => url.pathname.startsWith('/api/ai/hr/assistant'), (route) =>
        route.fulfill({ json: { ok: true, result: 'safe text' } }),
      );
      await page.goto('/ai/hr/');
      await page.evaluate(() => {
        (window as any).__xss = undefined;
      });
      // The entity-encoded form bypasses the `<`-only escape (the & decodes back to <).
      const payload = '&lt;img src=x onerror=window.__xss=1&gt;';
      await page.locator('#hrChatInput').fill(payload);
      await page.locator('#hrChatInput').press('Enter');
      await expect(page.locator('#hrChat .msg.user')).toHaveCount(1);

      // CORRECT behaviour: the user message is echoed as text.
      // CONFIRMED BUG: docs/qa/findings-confirmed.md F7 — partial escape lets <img> through.
      expect(await page.locator('#hrChat .msg.user img').count()).toBe(0); // RED (deterministic)
      await page.waitForFunction(() => (window as any).__xss === 1, undefined, { timeout: 3000 }).catch(() => {});
      expect(await page.evaluate(() => (window as any).__xss)).toBeUndefined(); // RED: will be 1
    });

    test('FE-SEC-03 — financial_reports.html |safe Python-repr chart data (static note)', async ({ page }) => {
      await page.goto('/reports/financial/');
      await expect(page.locator('#revenue-chart')).toBeVisible();
      // monthly_chart_data is injected via |safe as a Python repr (single-quoted), not JSON.
      const html = await page.content();
      expect(html).toContain('const chartData = ');
    });

    test('FE-SEC-04 — base.html window.SAMANA_THEME interpolation is a valid choice today', async ({ page }) => {
      await page.goto('/dashboard/');
      const theme = await page.evaluate(() => (window as any).SAMANA_THEME);
      const valid = ['professional-blue', 'modern-green', 'elegant-dark', 'warm-earth', 'minimalist-purple'];
      expect(valid).toContain(theme);
      const dataTheme = await page.evaluate(() => document.documentElement.getAttribute('data-theme'));
      expect(dataTheme).toBe(theme);
      // source-level: the interpolation lacks |escapejs — latent (free-text theme would break out)
    });

    test('FE-SEC-05 — erp.js showToast/showConfirm build innerHTML from message (latent)', async ({ page }) => {
      await page.goto('/dashboard/');
      await page.evaluate(() => {
        (window as any).__xss = undefined;
      });
      await page.evaluate(() => {
        (window as any).showToast('<img src=x onerror=window.__xss=1>');
      });
      // current behaviour: the helper interpolates into innerHTML unescaped (latent; callers pass fixed strings)
      const toastXss = await page.evaluate(() => (window as any).__xss);
      expect(toastXss).toBe(1);
      await expect(page.locator('#toastContainer img')).toHaveCount(1);

      await page.evaluate(() => {
        (window as any).__xss = undefined;
      });
      await page.evaluate(() => {
        (window as any).showConfirm('<img src=x onerror=window.__xss=1>', () => {});
      });
      const confirmXss = await page.evaluate(() => (window as any).__xss);
      expect(confirmXss).toBe(1);
    });

    test('FE-SEC-08 — List/detail pages render the XSS payload escaped (positive control)', async ({ page, request }) => {
      const token = await loginViaApi(request, 'admin');
      const ts = Date.now();
      const createRes = await request.post('/api/customers/', {
        data: {
          first_name: XSS_PAYLOAD,
          last_name: 'QA-XSS',
          email: `qa-xss-${ts}@example.com`,
          phone: '03001234567',
        },
        headers: { 'X-CSRFToken': token },
      });
      expect(createRes.status()).toBe(201);
      const created = await createRes.json();
      const cid = created.id;

      try {
        await page.goto('/customers/');
        await page.evaluate(() => {
          (window as any).__xss = undefined;
        });
        expect(await page.locator('img[onerror]').count()).toBe(0);
        expect(await page.evaluate(() => (window as any).__xss)).toBeUndefined();

        await page.goto(`/customers/${cid}/`);
        expect(await page.locator('img[onerror]').count()).toBe(0);
        expect(await page.evaluate(() => (window as any).__xss)).toBeUndefined();
        // the payload renders as escaped text, not markup
        await expect(page.locator('body')).toContainText('img src=x onerror');
      } finally {
        await request.delete(`/api/customers/${cid}/`, { headers: { 'X-CSRFToken': token } });
      }
    });
  });

  test.describe('anonymous', () => {
    test.use({ storageState: ANON });

    test('FE-SEC-06 — Login `next` open-redirect vector', async ({ page }) => {
      await page.goto('/login/?next=https://evil.com');
      // The hidden next field is present; login_view does not pass an arbitrary `next` through
      // (it renders empty), so there is no markup-injection surface in the hidden field.
      await expect(page.locator('input[name="next"]')).toHaveCount(1);

      await page.getByLabel('Username').fill('admin');
      await page.getByLabel('Password').fill('admin123');
      await page.getByRole('button', { name: 'Sign In' }).click();

      // The server must NOT redirect off-host: it ignores/validates `next`.
      await expect(page).toHaveURL(/^https?:\/\/127\.0\.0\.1:8000\//);
      await expect(page).not.toHaveURL(/evil\.com/);
    });
  });

  test.describe('static', () => {
    test('FE-SEC-07 — main.js reads a nonexistent csrf-token meta (orphaned, harmless)', async () => {
      const templates = readTemplates();
      const refs = templates.filter((t) => t.includes('main.js'));
      expect(refs).toEqual([]); // no template loads main.js
      const baseHtml = readSource('templates/base.html');
      expect(baseHtml).not.toContain('meta name="csrf-token"');
    });

    test('FE-SEC-09 — booking_form/payment_form latent innerHTML sinks', async () => {
      const paymentHtml = readSource('templates/payment_form.html');
      const bookingHtml = readSource('templates/booking_form.html');
      // good pattern: customer/project/plot strings use |escapejs
      expect(paymentHtml).toContain('|escapejs');
      // latent sinks (fed only by server enum/numbers / hardcoded config today)
      expect(paymentHtml).toContain('planInfo.innerHTML');
      expect(paymentHtml).toContain('function handleDrop');
      expect(bookingHtml).toContain('templateInfo.innerHTML');
    });

    test('FE-SEC-10 — Every POST form carries csrf_token (regression)', async () => {
      const templates = readTemplates();
      const postForms = templates.filter((t) => /<form[^>]*method\s*=\s*["']post["']/i.test(t));
      expect(postForms.length).toBeGreaterThan(0);
      for (const t of postForms) {
        expect(t).toContain('csrf_token');
      }
    });

    test('FE-SEC-11 — Receipt WhatsApp share exfiltrates amount (informational)', async () => {
      const receiptHtml = readSource('templates/receipt_detail.html');
      expect(receiptHtml).toContain('wa.me/?text=');
      expect(receiptHtml).toContain('receipt.receipt_number');
      expect(receiptHtml).toContain('payment.amount');
    });
  });
});

// ============================================================================
// FE-A11Y — accessibility (WCAG 2.2)
// ============================================================================
test.describe('FE-A11Y', () => {
  test.describe('public', () => {
    test.use({ storageState: ANON });

    test('FE-A11Y-01 — Corporate lead form inputs have no <label>', async ({ page }) => {
      await page.goto('/');
      const controls = page.locator('#contact form input, #contact form select, #contact form textarea');
      const labels = page.locator('#contact form label');
      const controlCount = await controls.count();
      const labelCount = await labels.count();
      expect(controlCount).toBeGreaterThan(0);
      // CORRECT behaviour: every form control has a for-associated <label>.
      // RED: the corporate form renders placeholder-only inputs (zero labels).
      expect(labelCount).toBe(controlCount);
    });

    test('FE-A11Y-06 — Corporate mobile menu: no Escape-to-close / focus management', async ({ page }) => {
      await page.setViewportSize({ width: 390, height: 844 });
      await page.goto('/');
      const hamburger = page.locator('#hamburger');
      await hamburger.click();
      await expect(hamburger).toHaveAttribute('aria-expanded', 'true'); // opens (positive)
      await page.keyboard.press('Escape');
      // CORRECT behaviour: Escape closes the menu.
      await expect(hamburger).toHaveAttribute('aria-expanded', 'false'); // RED
    });
  });

  test.describe('staff', () => {
    test.use({ storageState: SS.admin });

    test('FE-A11Y-02 — base_form.html select and file labels have no `for`', async ({ page }) => {
      await page.goto('/properties/plot/create/');
      const selects = page.locator('form select');
      await expect(selects.first()).toBeVisible();
      // CORRECT behaviour: every select has a for-associated label.
      const allLabeled = await page.evaluate(() => {
        const sels = Array.from(document.querySelectorAll('form select'));
        return sels.every((s) => s.id && document.querySelector(`label[for="${s.id}"]`));
      });
      expect(allLabeled).toBe(true); // RED: base_form select branch renders <label> without `for`
    });

    test('FE-A11Y-03 — Confirm dialogs lack role=dialog / aria-modal / focus trap / Escape', async ({ page }) => {
      await page.goto('/dashboard/');
      await page.evaluate(() => {
        (window as any).showConfirm('Delete this item?', () => {});
      });
      const modal = page.locator('.modal-overlay .modal');
      await expect(modal).toBeVisible();
      // CORRECT behaviour: dialog semantics + focus management.
      await expect(modal).toHaveAttribute('role', 'dialog'); // RED
      await expect(modal).toHaveAttribute('aria-modal', 'true'); // RED
      await page.keyboard.press('Escape');
      await expect(page.locator('.modal-overlay')).toHaveCount(0); // RED: no Escape handler
    });

    test('FE-A11Y-04 — Sortable <th> not keyboard-focusable, no aria-sort', async ({ page }) => {
      await page.goto('/reports/financial/');
      const th = page.locator('table.sortable thead th').first();
      await expect(th).toBeVisible();
      // CORRECT behaviour: sortable header is keyboard-focusable + announces sort state.
      expect(await th.getAttribute('tabindex')).not.toBeNull(); // RED
      expect(await th.getAttribute('aria-sort')).not.toBeNull(); // RED
    });

    test('FE-A11Y-05 — User-menu trigger and theme buttons lack state ARIA', async ({ page }) => {
      await page.goto('/profile/');
      const trigger = page.locator('.user-menu-trigger');
      await expect(trigger).toBeVisible();
      // CORRECT behaviour: the trigger exposes its expanded state.
      await expect(trigger).toHaveAttribute('aria-expanded', 'false'); // RED

      const themeOption = page.locator('.theme-option').first();
      await expect(themeOption).toBeVisible();
      // CORRECT behaviour: the selected theme is conveyed to assistive tech.
      expect(await themeOption.getAttribute('aria-pressed')).not.toBeNull(); // RED
    });

    test('FE-A11Y-07 — Inline onclick icon buttons expose accessible names (spot-check)', async ({ page }) => {
      await page.goto('/dashboard/');
      // hamburger exposes a name via aria-label
      await expect(page.locator('.menu-toggle')).toHaveAttribute('aria-label', 'Toggle menu');
      // notification bell (admin has can_audit) exposes a name via title
      await expect(page.locator('a[title="Notifications"]')).toHaveAttribute('title', 'Notifications');
    });
  });
});
