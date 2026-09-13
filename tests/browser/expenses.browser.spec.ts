/**
 * Samana ERP — expenses module BROWSER suite.
 *
 * Drives the web-only expenses module through the rendered UI (`page` + admin
 * storageState). There is no DRF ViewSet for `Expense`, so every expense is
 * created/edited/approved/rejected/paid/deleted through the Django forms, and
 * the financial ledger side-effects are asserted against the finance DRF read
 * endpoint (`/api/account-transactions/`).
 *
 * CONFIRMED BUGS — written RED on purpose (assert the SECURE behaviour, which
 * currently fails):
 *   - EXP-EC-01          GET-mutation (docs/qa/findings-confirmed.md F4)
 *   - EXP-SEC-04/05      stored XSS via the receipt FileField (F4)
 *   - EXP-SEC-06         unauthenticated /media/ serving
 *
 * Dev server must run on http://127.0.0.1:8000 with DJANGO_DEBUG=True.
 */
import { test, expect, Page } from '@playwright/test';
import { loginViaApi } from '../helpers/auth';

const BASE_URL = 'http://127.0.0.1:8000';

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

/** Unique, timestamped fixture token (safe for regex / list matching). */
const qa = (id: string) => `${id}-${Date.now()}-${Math.floor(Math.random() * 1e6)}`;

const today = () => new Date().toISOString().slice(0, 10);

/** Read the csrftoken cookie from the page context (valid post-login token). */
async function csrf(page: Page): Promise<string> {
  const cookies = await page.context().cookies();
  return cookies.find((c) => c.name === 'csrftoken')?.value ?? '';
}

// Tracked for afterAll cleanup (projects cascade their expenses).
const createdProjectIds: number[] = [];
const createdExpenseIds: number[] = [];

async function createProject(page: Page, opts: { name?: string; status?: string } = {}): Promise<{ id: number; name: string }> {
  const name = opts.name ?? qa('QA-Exp');
  const res = await page.request.post('/api/projects/', {
    data: {
      name,
      description: 'QA expenses browser fixture',
      location: 'QA',
      total_plots: 0,
      status: opts.status ?? 'booking_open',
    },
    headers: { 'X-CSRFToken': await csrf(page) },
  });
  expect(res.status(), `create project ${name}`).toBe(201);
  const body = await res.json();
  createdProjectIds.push(body.id);
  return { id: body.id, name };
}

/** Locate an expense's pk on the list page by its unique description. */
async function findExpensePk(page: Page, description: string): Promise<number> {
  const html = await (await page.request.get('/expenses/')).text();
  const esc = description.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const m = html.match(new RegExp(`<tr[\\s\\S]*?${esc}[\\s\\S]*?href="/expenses/(\\d+)/"`));
  if (!m) throw new Error(`Expense "${description}" not found on /expenses/`);
  return Number(m[1]);
}

/** Read an expense's status from its detail page HTML. */
async function getStatus(page: Page, pk: number): Promise<string> {
  const html = await (await page.request.get(`/expenses/${pk}/`)).text();
  if (html.includes('>Pending Approval</span>')) return 'pending';
  if (html.includes('>Approved</span>')) return 'approved';
  if (html.includes('>Paid</span>')) return 'paid';
  if (html.includes('>Rejected</span>')) return 'rejected';
  return 'unknown';
}

/** Ledger rows for an expense (reference_type='Expense', reference_id=pk). */
async function ledgerFor(page: Page, pk: number): Promise<any[]> {
  const rows = (await (await page.request.get('/api/account-transactions/')).json()) as any[];
  return rows.filter((r) => r.reference_type === 'Expense' && r.reference_id === pk);
}

/**
 * Drive the create form in the browser. Returns the new expense pk (located on
 * the list page by its unique description).
 */
async function uiCreateExpense(
  page: Page,
  opts: { projectName: string; description: string; amount: string },
): Promise<number> {
  await page.goto('/expenses/create/');
  await page.getByLabel(/Project/).selectOption({ label: opts.projectName });
  await page.getByLabel(/Expense Type/).selectOption({ label: 'Internal' });
  await page.getByLabel(/Amount/).fill(opts.amount);
  await page.getByLabel(/Expense Date/).fill(today());
  await page.getByLabel(/Description/).fill(opts.description);
  await page.getByLabel(/Paid To/).fill('ACME');
  await page.getByRole('button', { name: 'Add Expense' }).click();
  await expect(page).toHaveURL(/\/expenses\/$/);
  return findExpensePk(page, opts.description);
}

/** Create a project + a pending expense via the UI, returning both ids. */
async function newPendingExpense(
  page: Page,
  id: string,
  amount = '500.00',
): Promise<{ pid: number; eid: number; description: string }> {
  const project = await createProject(page);
  const description = qa(id);
  const eid = await uiCreateExpense(page, {
    projectName: project.name,
    description,
    amount,
  });
  createdExpenseIds.push(eid);
  return { pid: project.id, eid, description };
}

// ─────────────────────────────────────────────────────────────────────────────
// Cleanup
// ─────────────────────────────────────────────────────────────────────────────

test.afterAll(async ({ request }) => {
  await loginViaApi(request, 'admin');
  const state = await request.storageState();
  const token = state.cookies.find((c) => c.name === 'csrftoken')?.value ?? '';
  const header = { 'X-CSRFToken': token };

  // Delete ledger rows orphaned by approved/paid/deleted expenses.
  const rows = (await (await request.get('/api/account-transactions/')).json()) as any[];
  for (const row of rows) {
    if (row.reference_type === 'Expense' && createdExpenseIds.includes(row.reference_id)) {
      try {
        await request.delete(`/api/account-transactions/${row.id}/`, { headers: header });
      } catch {
        /* best-effort */
      }
    }
  }

  // Delete created projects (cascades any remaining expenses).
  for (const id of createdProjectIds) {
    try {
      await request.delete(`/api/projects/${id}/`, { headers: header });
    } catch {
      /* already gone */
    }
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// Happy-path flows (UI driven)
// ─────────────────────────────────────────────────────────────────────────────

test.describe('EXP — browser flows', () => {
  test.beforeEach(async ({ page }) => { await loginViaApi(page.request, 'admin'); });

  test('EXP-HP-01 — create expense lands as pending (no ledger)', async ({ page }) => {
    const { eid } = await newPendingExpense(page, 'EXP-HP-01', '5000.00');

    expect(await getStatus(page, eid)).toBe('pending');
    expect(await ledgerFor(page, eid)).toHaveLength(0);
  });

  test('EXP-HP-02 — approve posts the ledger exactly once', async ({ page }) => {
    const { eid } = await newPendingExpense(page, 'EXP-HP-02', '5001.50');

    await page.goto(`/expenses/${eid}/`);
    await page.getByRole('button', { name: '✓ Approve' }).click();
    await expect(page).toHaveURL(/\/expenses\/$/);

    expect(await getStatus(page, eid)).toBe('approved');
    const ledger = await ledgerFor(page, eid);
    expect(ledger).toHaveLength(1);
    expect(ledger[0].amount).toBe('5001.50');
    expect(ledger[0].direction).toBe('out');
    expect(ledger[0].transaction_type).toBe('project_cost');
  });

  test('EXP-HP-04 — reject writes no ledger row', async ({ page }) => {
    const { eid } = await newPendingExpense(page, 'EXP-HP-04', '5003.00');

    await page.goto(`/expenses/${eid}/`);
    await page.getByRole('button', { name: '✗ Reject' }).click();
    await expect(page).toHaveURL(/\/expenses\/$/);

    expect(await getStatus(page, eid)).toBe('rejected');
    expect(await ledgerFor(page, eid)).toHaveLength(0);
  });

  test('EXP-HP-03 — mark-paid keeps the ledger at one row', async ({ page }) => {
    const { eid } = await newPendingExpense(page, 'EXP-HP-03', '5002.00');

    await page.goto(`/expenses/${eid}/`);
    await page.getByRole('button', { name: '✓ Approve' }).click();
    await expect(page).toHaveURL(/\/expenses\/$/);
    expect(await ledgerFor(page, eid)).toHaveLength(1);

    await page.goto(`/expenses/${eid}/`);
    await page.getByRole('button', { name: 'Mark Paid' }).click();
    await expect(page).toHaveURL(/\/expenses\/$/);

    expect(await getStatus(page, eid)).toBe('paid');
    const ledger = await ledgerFor(page, eid);
    expect(ledger).toHaveLength(1);
    expect(ledger[0].amount).toBe('5002.00');
  });

  test('EXP-HP-05 — edit a pending expense', async ({ page }) => {
    const { eid } = await newPendingExpense(page, 'EXP-HP-05', '5000.00');
    const newDescription = qa('EXP-HP-05-edited');

    await page.goto(`/expenses/${eid}/edit/`);
    await page.getByLabel(/Amount/).fill('7500.00');
    await page.getByLabel(/Description/).fill(newDescription);
    await page.getByRole('button', { name: 'Save Changes' }).click();
    await expect(page).toHaveURL(/\/expenses\/$/);

    expect(await getStatus(page, eid)).toBe('pending');
    expect(await ledgerFor(page, eid)).toHaveLength(0);
    const html = await (await page.request.get(`/expenses/${eid}/`)).text();
    expect(html).toContain('Rs. 7500');
  });

  test('EXP-HP-08 — delete an expense (confirm page)', async ({ page }) => {
    const { eid, description } = await newPendingExpense(page, 'EXP-HP-08', '5010.00');

    await page.goto(`/expenses/${eid}/delete/`);
    await expect(page.getByRole('heading', { name: 'Delete Expense' })).toBeVisible();
    await page.getByRole('button', { name: /Yes, Delete/ }).click();
    await expect(page).toHaveURL(/\/expenses\/$/);

    await expect(page.getByText(description)).toHaveCount(0);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Edge cases
// ─────────────────────────────────────────────────────────────────────────────

test.describe('EXP — edge cases (browser)', () => {
  test.beforeEach(async ({ page }) => { await loginViaApi(page.request, 'admin'); });

  test('EXP-EC-06 — zero / negative amount rejected', async ({ page }) => {
    const project = await createProject(page);

    for (const amount of ['0', '-1500']) {
      const description = qa('EXP-EC-06');
      await page.goto('/expenses/create/');
      await page.getByLabel(/Project/).selectOption({ label: project.name });
      await page.getByLabel(/Expense Type/).selectOption({ label: 'Internal' });
      await page.getByLabel(/Amount/).fill(amount);
      await page.getByLabel(/Expense Date/).fill(today());
      await page.getByLabel(/Description/).fill(description);
      await page.getByRole('button', { name: 'Add Expense' }).click();

      // Re-rendered (no redirect) with the raw DB-constraint non-field error.
      await expect(page).toHaveURL(/\/expenses\/create\/$/);
      await expect(page.getByText(/expense_amount_positive/)).toBeVisible();

      const listHtml = await (await page.request.get('/expenses/')).text();
      expect(listHtml).not.toContain(description);
    }
  });

  test('EXP-EC-07 — edit is locked on an approved expense', async ({ page }) => {
    const { eid } = await newPendingExpense(page, 'EXP-EC-07', '5000.00');

    await page.goto(`/expenses/${eid}/`);
    await page.getByRole('button', { name: '✓ Approve' }).click();
    await expect(page).toHaveURL(/\/expenses\/$/);

    await page.goto(`/expenses/${eid}/edit/`);
    await expect(page).toHaveURL(new RegExp(`/expenses/${eid}/$`));
    await expect(page.getByText('An approved/paid expense can no longer be edited.')).toBeVisible();
    expect(await getStatus(page, eid)).toBe('approved');
  });

  test('EXP-EC-01 — approve/reject/mark-paid mutate on GET (RED)', async ({ page }) => {
    // Documented defect (F4): the three views have no request.method guard, so a
    // plain browser GET performs the mutation. Asserting the SECURE behaviour —
    // GET must NOT change status — which fails today.

    const a = await newPendingExpense(page, 'EXP-EC-01', '6001.00');
    const b = await newPendingExpense(page, 'EXP-EC-01', '6002.00');
    const c = await newPendingExpense(page, 'EXP-EC-01', '6003.00');

    await page.goto(`/expenses/${a.eid}/approve/`);
    await page.goto(`/expenses/${b.eid}/reject/`);
    await page.goto(`/expenses/${c.eid}/mark-paid/`);

    // CONFIRMED BUG: docs/qa/findings-confirmed.md F4 — GET mutates status.
    expect(await getStatus(page, a.eid)).toBe('pending');
    // CONFIRMED BUG: docs/qa/findings-confirmed.md F4
    expect(await getStatus(page, b.eid)).toBe('pending');
    // CONFIRMED BUG: docs/qa/findings-confirmed.md F4
    expect(await getStatus(page, c.eid)).toBe('pending');
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Security (RED on purpose)
// ─────────────────────────────────────────────────────────────────────────────

test.describe('EXP — security (browser, RED)', () => {
  test.beforeEach(async ({ page }) => { await loginViaApi(page.request, 'admin'); });

  test('EXP-SEC-04 — SVG receipt upload is rejected (RED)', async ({ page }) => {
    const project = await createProject(page);
    await page.goto('/expenses/create/');
    await page.getByLabel(/Project/).selectOption({ label: project.name });
    await page.getByLabel(/Amount/).fill('500.00');
    await page.getByLabel(/Expense Date/).fill(today());
    await page.getByLabel(/Description/).fill(qa('EXP-SEC-04'));
    await page.getByLabel(/Receipt/).setInputFiles({
      name: `poc-${Date.now()}.svg`,
      mimeType: 'image/svg+xml',
      buffer: Buffer.from(
        `<svg xmlns="http://www.w3.org/2000/svg" onload="alert(document.domain)"><script>fetch('/expenses/')</script></svg>`,
      ),
    });
    await page.getByRole('button', { name: 'Add Expense' }).click();

    // CONFIRMED BUG: FileField accepts arbitrary content types — the SVG should
    // be rejected and the form re-rendered.
    await expect(page).toHaveURL(/\/expenses\/create\/$/);
  });

  test('EXP-SEC-05 — HTML receipt upload is rejected (RED)', async ({ page }) => {
    const project = await createProject(page);
    await page.goto('/expenses/create/');
    await page.getByLabel(/Project/).selectOption({ label: project.name });
    await page.getByLabel(/Amount/).fill('500.00');
    await page.getByLabel(/Expense Date/).fill(today());
    await page.getByLabel(/Description/).fill(qa('EXP-SEC-05'));
    await page.getByLabel(/Receipt/).setInputFiles({
      name: `poc-${Date.now()}.html`,
      mimeType: 'text/html',
      buffer: Buffer.from('<script>alert(document.domain)</script>'),
    });
    await page.getByRole('button', { name: 'Add Expense' }).click();

    // CONFIRMED BUG: FileField accepts arbitrary content types — the HTML should
    // be rejected and the form re-rendered.
    await expect(page).toHaveURL(/\/expenses\/create\/$/);
  });

  test('EXP-SEC-06 — unauthenticated /media/ serving (RED)', async ({ page, playwright }) => {
    const project = await createProject(page);
    const description = qa('EXP-SEC-06');

    await page.goto('/expenses/create/');
    await page.getByLabel(/Project/).selectOption({ label: project.name });
    await page.getByLabel(/Amount/).fill('500.00');
    await page.getByLabel(/Expense Date/).fill(today());
    await page.getByLabel(/Description/).fill(description);
    await page.getByLabel(/Receipt/).setInputFiles({
      name: `invoice-${Date.now()}.png`,
      mimeType: 'image/png',
      buffer: Buffer.from('invoice'),
    });
    await page.getByRole('button', { name: 'Add Expense' }).click();
    await expect(page).toHaveURL(/\/expenses\/$/);

    const eid = await findExpensePk(page, description);
    const detailHtml = await (await page.request.get(`/expenses/${eid}/`)).text();
    const m = detailHtml.match(/href="(\/media\/[^"]+)"/);
    expect(m).toBeTruthy();

    const anon = await playwright.request.newContext({ baseURL: BASE_URL });
    const res = await anon.get(m![1], { maxRedirects: 0 });
    await anon.dispose();

    // CONFIRMED BUG: media is served with no authentication — the invoice must
    // be gated behind login (302/403).
    expect(res.status()).toBeGreaterThanOrEqual(300);
  });
});
