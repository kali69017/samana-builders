import { test, expect, APIRequestContext } from '@playwright/test';
import { loginViaApi, type RoleName } from '../helpers/auth';

/**
 * Samana ERP — browser-driven dashboard + navigation suite.
 *
 * Drives the real dashboard, its sidebar role gating, the quick-action buttons
 * and the settings/report pages through `page`. A separate `request` context is
 * used only to verify the revenue figure against the API (Σ advance_paid).
 *
 * Role storageStates are produced by the `setup` project (tests/.auth/*.json).
 * Read-only: no records are created or mutated.
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

/** Σ advance_paid across all bookings — the single source of truth for revenue. */
async function sumAdvancePaid(request: APIRequestContext): Promise<number> {
  await loginViaApi(request, 'admin');
  const bookings = unwrapList(await (await request.get('/api/bookings/')).json());
  return bookings.reduce((s, b) => s + Number(b.advance_paid), 0);
}

// ── DASH-HP (happy path) ──────────────────────────────────────────────────────

test.describe('DASH-HP', () => {
  test.describe('admin', () => {
    test.beforeEach(async ({ page }) => { await loginViaApi(page.request, 'admin'); });

    test('DASH-HP-01 — Dashboard revenue equals Σ advance_paid', async ({ page, request }) => {
      const advanceSum = await sumAdvancePaid(request);

      await page.goto('/dashboard/');
      // Stat row 1 is visible for every role.
      await expect(page.getByText('Total Customers')).toBeVisible();
      await expect(page.getByText('Active Projects')).toBeVisible();

      const revenueCard = page.locator('.stat-card', { hasText: 'Total Revenue' });
      await expect(revenueCard).toBeVisible();
      const raw = (await revenueCard.locator('[data-target]').getAttribute('data-target')) ?? '';
      const shown = Number(raw.replace(/[^\d.-]/g, ''));

      // Headline is Σ advance_paid (single source of truth), never the payment total.
      expect(shown).toBe(Math.round(advanceSum));
    });

    test('DASH-HP-02 — Quick-action buttons navigate to their create pages', async ({ page }) => {
      const quickActions: { name: string; url: RegExp }[] = [
        { name: 'New Customer', url: /customers\/create/ },
        { name: 'New Booking', url: /bookings\/create/ },
        { name: 'Record Payment', url: /payments\/create/ },
        { name: 'Add Plot', url: /properties\/plot\/create/ },
      ];
      for (const action of quickActions) {
        await page.goto('/dashboard/');
        // `.first()` tolerates the empty-state duplicate ("+ New Booking" /
        // "+ Record Payment") — both point at the same create page.
        await page.getByRole('link', { name: action.name }).first().click();
        await expect(page).toHaveURL(action.url);
      }
    });

    test('DASH-HP-03 — Recent bookings and payments lists render', async ({ page }) => {
      await page.goto('/dashboard/');
      await expect(page.getByRole('heading', { name: 'Recent Bookings' })).toBeVisible();
      await expect(page.getByRole('heading', { name: 'Recent Payments' })).toBeVisible();
    });
  });

  test.describe('management', () => {
    test.beforeEach(async ({ page }) => { await loginViaApi(page.request, 'management'); });

    test('DASH-HP-04 — Audit logs list renders', async ({ page }) => {
      await page.goto('/audit-logs/');
      await expect(page.getByRole('heading', { name: 'Audit Logs' })).toBeVisible();
      await expect(page.getByText('IP Address')).toBeVisible();
      await expect(page.getByRole('button', { name: 'Filter' })).toBeVisible();
    });

    test('DASH-HP-05 — Milestones list renders', async ({ page }) => {
      await page.goto('/projects/milestones/');
      await expect(page.getByRole('heading', { name: 'Project Milestones' })).toBeVisible();
      await expect(page.getByRole('heading', { name: 'Milestones', exact: true })).toBeVisible();
      await expect(page.getByRole('link', { name: 'Add Milestone' }).first()).toBeVisible();
    });
  });

  test.describe('accounts', () => {
    test.beforeEach(async ({ page }) => { await loginViaApi(page.request, 'accounts'); });

    test('DASH-HP-06 — Sales report renders with a print button', async ({ page }) => {
      await page.goto('/reports/sales/');
      await expect(page.getByRole('heading', { name: 'Sales & Commission Report' })).toBeVisible();
      await expect(page.getByText('Total Sales Value')).toBeVisible();
      await expect(page.getByRole('heading', { name: 'Agent Commissions' })).toBeVisible();
      await expect(page.getByRole('button', { name: 'Print Report' })).toBeVisible();
    });

    test('DASH-HP-07 — Receivables aging renders', async ({ page }) => {
      await page.goto('/reports/receivables/');
      await expect(page.getByRole('heading', { name: 'Receivables Aging' })).toBeVisible();
      await expect(page.getByText('Total Receivables')).toBeVisible();
      await expect(page.getByText('Overdue (30+ days)')).toBeVisible();
      await expect(page.getByRole('heading', { name: 'Outstanding by Aging Bucket' })).toBeVisible();
    });
  });

  test.describe('admin settings', () => {
    test.beforeEach(async ({ page }) => { await loginViaApi(page.request, 'admin'); });

    test('DASH-HP-08 — Company settings form renders', async ({ page }) => {
      await page.goto('/settings/company/');
      await expect(page.getByRole('heading', { name: 'Company Settings' })).toBeVisible();
      await expect(page.locator('input[name="company_name"]')).toBeVisible();
      await expect(page.getByRole('button', { name: 'Save Settings' })).toBeVisible();
    });
  });
});

// ── DASH-SEC (role gating) ────────────────────────────────────────────────────

// Sidebar nav expectations per role, derived from core/context_processors.py
// (erp_context) + templates/includes/sidebar.html. `visible` asserts presence,
// `hidden` asserts the link is not rendered at all.
const NAV_MATRIX: Record<string, { visible: string[]; hidden: string[] }> = {
  admin: {
    visible: [
      'Dashboard', 'Customers', 'Properties', 'Bookings', 'Payments', 'Expenses',
      'Leads', 'Agents', 'Receivables', 'Sales Report', 'Milestones', 'Ledger',
      'HR Overview', 'Departments', 'Manage Users', 'Notifications', 'DB Backup',
      'Company Settings', 'Preferences',
    ],
    hidden: [],
  },
  management: {
    visible: [
      'Dashboard', 'Payments', 'Expenses', 'Leads', 'Receivables', 'Sales Report',
      'Milestones', 'HR Overview', 'Departments', 'Manage Users', 'Notifications', 'Preferences',
    ],
    hidden: ['DB Backup', 'Company Settings'],
  },
  accounts: {
    visible: [
      'Dashboard', 'Payments', 'Expenses', 'Leads', 'Receivables', 'Sales Report',
      'Milestones', 'HR Overview', 'Payroll', 'Preferences',
    ],
    hidden: [
      'Manage Users', 'Notifications', 'DB Backup', 'Company Settings',
      'Departments', 'Designations', 'Salary Components',
    ],
  },
  sales: {
    visible: ['Dashboard', 'Customers', 'Properties', 'Bookings', 'Leads', 'Agents', 'Milestones', 'Preferences'],
    hidden: [
      'Payments', 'Expenses', 'Receivables', 'Sales Report', 'HR Overview',
      'Manage Users', 'Notifications', 'DB Backup', 'Company Settings',
    ],
  },
  hr: {
    visible: [
      'Dashboard', 'Customers', 'Properties', 'Bookings', 'Agents', 'Milestones',
      'HR Overview', 'Departments', 'Payroll', 'Preferences',
    ],
    hidden: [
      'Payments', 'Expenses', 'Leads', 'Receivables', 'Sales Report',
      'Manage Users', 'Notifications', 'DB Backup', 'Company Settings',
    ],
  },
};

for (const [role, matrix] of Object.entries(NAV_MATRIX)) {
  test.describe(`DASH-SEC-01 sidebar gating — ${role}`, () => {
    test(`sees/hides the correct nav items`, async ({ page }) => {
      await loginViaApi(page.request, role as RoleName);
      await page.goto('/dashboard/');
      const nav = page.getByRole('navigation');
      for (const item of matrix.visible) {
        await expect(nav.getByRole('link', { name: item, exact: true })).toBeVisible();
      }
      for (const item of matrix.hidden) {
        await expect(nav.getByRole('link', { name: item, exact: true })).toHaveCount(0);
      }
    });
  });
}

test.describe('DASH-SEC-02 sales dashboard', () => {
  test.beforeEach(async ({ page }) => { await loginViaApi(page.request, 'sales'); });

  test('sales dashboard hides finance widgets (revenue, payments)', async ({ page }) => {
    await page.goto('/dashboard/');
    // Bookings list renders, but every can_view_payments-gated block is absent.
    await expect(page.getByRole('heading', { name: 'Recent Bookings' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Recent Payments' })).toHaveCount(0);
    await expect(page.getByText('Total Revenue')).toHaveCount(0);
    await expect(page.getByText('This Month')).toHaveCount(0);
  });
});
