/**
 * Samana ERP — expenses module Playwright suite.
 *
 * Covers the 32 scenarios from specs/expenses.md (EXP-HP-*, EXP-EC-*, EXP-SEC-*,
 * EXP-API-*). Expenses are a web-only module (no DRF ViewSet), so fixtures are
 * created by driving the Django forms via `page.request` / `request` POSTs (with
 * CSRF) and verified against the DRF finance read endpoints (account-transactions,
 * audit-logs) plus the rendered HTML.
 *
 * CONFIRMED BUGS — written RED on purpose (assert the SECURE behaviour, which
 * currently fails):
 *   - EXP-SEC-01/02/03  GET-mutation  (docs/qa/findings-confirmed.md F4)
 *   - EXP-SEC-04/05     stored XSS via receipt FileField
 *   - EXP-SEC-06        unauthenticated /media/ serving
 *
 * The dev server must be running on http://127.0.0.1:8000 with DJANGO_DEBUG=True.
 */
import { test, expect, Page, APIRequestContext } from '@playwright/test';

const ADMIN_SS = 'tests/.auth/admin.json';
const ACCOUNTS_SS = 'tests/.auth/accounts.json';
const SALES_SS = 'tests/.auth/sales.json';
const BASE_URL = 'http://127.0.0.1:8000';

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

/** Short, unique, timestamped description (<= 40 chars so the list page never truncates it). */
const desc = (id: string) => `${id} ${Date.now()}${Math.floor(Math.random() * 1e6)}`;

const today = () => new Date().toISOString().slice(0, 10);

/** Read the current csrftoken cookie from the page context (valid post-login token). */
async function csrf(page: Page): Promise<string> {
  const cookies = await page.context().cookies();
  return cookies.find((c) => c.name === 'csrftoken')?.value ?? '';
}

// Created projects are deleted in afterEach (cascades their expenses).
const createdProjectIds: number[] = [];

async function createProject(
  ctx: APIRequestContext,
  token: string,
  opts: { name?: string; status?: string } = {},
): Promise<{ id: number; name: string }> {
  const name = opts.name ?? `QA-Exp-${Date.now()}${Math.floor(Math.random() * 1e6)}`;
  const res = await ctx.post('/api/projects/', {
    data: {
      name,
      description: 'QA expenses fixture',
      location: 'QA',
      total_plots: 0,
      status: opts.status ?? 'booking_open',
    },
    headers: { 'X-CSRFToken': token },
  });
  expect(res.status(), 'create project').toBe(201);
  const body = await res.json();
  createdProjectIds.push(body.id);
  return { id: body.id, name };
}

type ExpenseOpts = {
  projectId: number;
  description: string;
  amount: string;
  expenseType?: string;
  paidTo?: string;
  expenseDate?: string;
  file?: { name: string; mimeType: string; buffer: Buffer };
};

/** Create an expense via the Django form (urlencoded or multipart), returning its pk. */
async function createExpense(
  ctx: APIRequestContext,
  token: string,
  opts: ExpenseOpts,
): Promise<number> {
  const fields: Record<string, string> = {
    project: String(opts.projectId),
    description: opts.description,
    amount: opts.amount,
    expense_type: opts.expenseType ?? 'internal',
    paid_to: opts.paidTo ?? 'ACME',
    expense_date: opts.expenseDate ?? today(),
    payment_reference: '',
  };
  const res = opts.file
    ? await ctx.post('/expenses/create/', {
        multipart: { ...fields, receipt_attachment: opts.file },
        headers: { 'X-CSRFToken': token },
        maxRedirects: 0,
      })
    : await ctx.post('/expenses/create/', {
        form: fields,
        headers: { 'X-CSRFToken': token },
        maxRedirects: 0,
      });
  expect(res.status(), `create expense ${opts.description}`).toBe(302);
  return findExpensePk(ctx, opts.description);
}

/** Locate an expense's pk on the list page by its unique description. */
async function findExpensePk(ctx: APIRequestContext, description: string): Promise<number> {
  const res = await ctx.get('/expenses/');
  const html = await res.text();
  const esc = description.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const m = html.match(new RegExp(`<tr[\\s\\S]*?${esc}[\\s\\S]*?href="/expenses/(\\d+)/"`));
  if (!m) throw new Error(`Expense "${description}" not found on /expenses/`);
  return Number(m[1]);
}

/** Create a project + a pending expense, returning both ids and the description. */
async function newPendingExpense(
  page: Page,
  token: string,
  id: string,
  overrides: Partial<ExpenseOpts> & { projectName?: string } = {},
): Promise<{ pid: number; eid: number; description: string }> {
  const description = desc(id);
  const { id: pid } = await createProject(page.request, token, overrides.projectName ? { name: overrides.projectName } : {});
  const eid = await createExpense(page.request, token, {
    projectId: pid,
    description,
    amount: overrides.amount ?? '500.00',
    expenseType: overrides.expenseType,
    paidTo: overrides.paidTo,
    expenseDate: overrides.expenseDate,
    file: overrides.file,
  });
  return { pid, eid, description };
}

/** Read an expense's status from its detail page HTML. */
async function getStatus(ctx: APIRequestContext, pk: number): Promise<string> {
  const html = await (await ctx.get(`/expenses/${pk}/`)).text();
  if (html.includes('>Pending Approval</span>')) return 'pending';
  if (html.includes('>Approved</span>')) return 'approved';
  if (html.includes('>Paid</span>')) return 'paid';
  if (html.includes('>Rejected</span>')) return 'rejected';
  return 'unknown';
}

/** Ledger rows for an expense (reference_type='Expense', reference_id=pk). */
async function ledgerFor(ctx: APIRequestContext, pk: number): Promise<any[]> {
  const rows = (await (await ctx.get('/api/account-transactions/')).json()) as any[];
  return rows.filter((r) => r.reference_type === 'Expense' && r.reference_id === pk);
}

/** AuditLog rows for a given model + object id. */
async function auditFor(ctx: APIRequestContext, modelName: string, objectId: number): Promise<any[]> {
  const rows = (await (await ctx.get(`/api/audit-logs/?model=${encodeURIComponent(modelName)}`)).json()) as any[];
  return rows.filter((r) => r.model_name === modelName && r.object_id === String(objectId));
}

const approve = (ctx: APIRequestContext, token: string, pk: number) =>
  ctx.post(`/expenses/${pk}/approve/`, { headers: { 'X-CSRFToken': token }, maxRedirects: 0 });
const reject = (ctx: APIRequestContext, token: string, pk: number) =>
  ctx.post(`/expenses/${pk}/reject/`, { headers: { 'X-CSRFToken': token }, maxRedirects: 0 });
const markPaid = (ctx: APIRequestContext, token: string, pk: number) =>
  ctx.post(`/expenses/${pk}/mark-paid/`, { headers: { 'X-CSRFToken': token }, maxRedirects: 0 });
const deleteExpense = (ctx: APIRequestContext, token: string, pk: number) =>
  ctx.post(`/expenses/${pk}/delete/`, { headers: { 'X-CSRFToken': token }, maxRedirects: 0 });

test.afterEach(async ({ page }) => {
  for (const id of createdProjectIds.splice(0)) {
    try {
      const t = (await page.context().cookies()).find((c) => c.name === 'csrftoken')?.value;
      await page.request.delete(`/api/projects/${id}/`, { headers: t ? { 'X-CSRFToken': t } : {} });
    } catch {
      /* already gone */
    }
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// HP — happy path
// ─────────────────────────────────────────────────────────────────────────────

test.describe('EXP — happy path (HP)', () => {
  test.use({ storageState: ADMIN_SS });

  test('EXP-HP-01 — Create expense lands as pending', async ({ page }) => {
    const token = await csrf(page);
    const { id: pid, name: pname } = await createProject(page.request, token);
    const description = desc('EXP-HP-01');

    await page.goto('/expenses/create/');
    await page.getByLabel(/Project/).selectOption({ label: pname });
    await page.getByLabel(/Expense Type/).selectOption({ label: 'Internal' });
    await page.getByLabel(/Amount/).fill('5000.00');
    await page.getByLabel(/Expense Date/).fill(today());
    await page.getByLabel(/Description/).fill(description);
    await page.getByLabel(/Paid To/).fill('ACME');
    await page.getByRole('button', { name: 'Add Expense' }).click();

    await expect(page).toHaveURL(/\/expenses\/$/);
    const eid = await findExpensePk(page.request, description);
    expect(await getStatus(page.request, eid)).toBe('pending');
    expect(await ledgerFor(page.request, eid)).toHaveLength(0);
    const logs = await auditFor(page.request, 'Expense', eid);
    expect(logs.some((l) => l.action === 'create')).toBe(true);
  });

  test('EXP-HP-02 — Approve a pending expense posts the ledger exactly once', async ({ page }) => {
    const token = await csrf(page);
    const { eid } = await newPendingExpense(page, token, 'EXP-HP-02', { amount: '5001.50' });

    const res = await approve(page.request, token, eid);
    expect(res.status()).toBe(302);
    expect(await getStatus(page.request, eid)).toBe('approved');

    const ledger = await ledgerFor(page.request, eid);
    expect(ledger).toHaveLength(1);
    expect(ledger[0].amount).toBe('5001.50');
    expect(ledger[0].direction).toBe('out');
    expect(ledger[0].transaction_type).toBe('project_cost');

    const logs = await auditFor(page.request, 'Expense', eid);
    expect(logs.some((l) => l.action === 'verify')).toBe(true);

    const html = await (await page.request.get(`/expenses/${eid}/`)).text();
    expect(html).toContain('Approved By</div><div class="detail-value">admin');
  });

  test('EXP-HP-03 — Mark-paid on an approved expense keeps ledger at one row', async ({ page }) => {
    const token = await csrf(page);
    const { eid } = await newPendingExpense(page, token, 'EXP-HP-03', { amount: '5002.00' });

    expect((await approve(page.request, token, eid)).status()).toBe(302);
    expect((await markPaid(page.request, token, eid)).status()).toBe(302);

    expect(await getStatus(page.request, eid)).toBe('paid');
    const ledger = await ledgerFor(page.request, eid);
    expect(ledger).toHaveLength(1);
    expect(ledger[0].amount).toBe('5002.00');
  });

  test('EXP-HP-04 — Reject a pending expense writes no ledger row', async ({ page }) => {
    const token = await csrf(page);
    const { eid } = await newPendingExpense(page, token, 'EXP-HP-04', { amount: '5003.00' });

    expect((await reject(page.request, token, eid)).status()).toBe(302);
    expect(await getStatus(page.request, eid)).toBe('rejected');
    expect(await ledgerFor(page.request, eid)).toHaveLength(0);
    const logs = await auditFor(page.request, 'Expense', eid);
    expect(logs.some((l) => l.action === 'reject')).toBe(true);
  });

  test('EXP-HP-05 — Edit a pending expense', async ({ page }) => {
    const token = await csrf(page);
    const { pid, eid } = await newPendingExpense(page, token, 'EXP-HP-05', { amount: '5000.00' });

    const res = await page.request.post(`/expenses/${eid}/edit/`, {
      form: {
        project: String(pid),
        description: `EXP-HP-05 ${Date.now()}`,
        amount: '7500.00',
        expense_type: 'internal',
        paid_to: 'NEW-VENDOR',
        expense_date: today(),
        payment_reference: '',
      },
      headers: { 'X-CSRFToken': token },
      maxRedirects: 0,
    });
    expect(res.status()).toBe(302);

    expect(await getStatus(page.request, eid)).toBe('pending');
    expect(await ledgerFor(page.request, eid)).toHaveLength(0);
    const html = await (await page.request.get(`/expenses/${eid}/`)).text();
    expect(html).toContain('Rs. 7500');
    const logs = await auditFor(page.request, 'Expense', eid);
    expect(logs.some((l) => l.action === 'update')).toBe(true);
  });

  test('EXP-HP-06 — Expenses dashboard aggregates correctly', async ({ page }) => {
    const token = await csrf(page);
    // Prefix with "000-" so the fixture sorts first alphabetically and appears in the
    // initially-visible rows of the client-paginated "Project-Wise Summary" table.
    const activeName = `000-HP06-ACT-${Date.now()}`;
    const inactiveName = `000-HP06-INA-${Date.now()}`;

    const active = await createProject(page.request, token, { name: activeName });
    await createProject(page.request, token, { name: inactiveName, status: 'inactive' });

    await createExpense(page.request, token, { projectId: active.id, description: desc('EXP-HP-06'), amount: '3000.00' });
    await createExpense(page.request, token, { projectId: active.id, description: desc('EXP-HP-06'), amount: '2000.00' });

    await page.goto('/expenses/');
    await expect(page.locator('canvas').first()).toBeVisible();

    const summaryTable = page.getByRole('table').filter({ hasText: 'Revenue' });
    const row = summaryTable.getByRole('row').filter({ hasText: activeName });
    await expect(row).toContainText('Rs. 5000'); // expenses = 3000 + 2000
    await expect(row).toContainText('Rs. 0'); // revenue (no bookings)

    // Inactive project is excluded from the per-project summary.
    await expect(summaryTable.getByRole('row').filter({ hasText: inactiveName })).toHaveCount(0);
  });

  test('EXP-HP-07 — Mark-paid on a pending expense is one-step approve + pay', async ({ page }) => {
    const token = await csrf(page);
    const { eid } = await newPendingExpense(page, token, 'EXP-HP-07', { amount: '5004.00' });

    expect((await markPaid(page.request, token, eid)).status()).toBe(302);

    expect(await getStatus(page.request, eid)).toBe('paid');
    const ledger = await ledgerFor(page.request, eid);
    expect(ledger).toHaveLength(1);

    // The one-step path stamps approved_by/approved_at.
    const html = await (await page.request.get(`/expenses/${eid}/`)).text();
    expect(html).toContain('Approved By</div><div class="detail-value">admin');
  });

  test('EXP-HP-08 — Detail page renders full record', async ({ page }) => {
    const token = await csrf(page);
    const description = desc('EXP-HP-08');
    const { id: pid } = await createProject(page.request, token);
    const eid = await createExpense(page.request, token, {
      projectId: pid,
      description,
      amount: '5005.00',
      paidTo: 'ACME',
      file: { name: `receipt-${Date.now()}.png`, mimeType: 'image/png', buffer: Buffer.from('fakepng') },
    });
    await approve(page.request, token, eid);

    await page.goto(`/expenses/${eid}/`);
    await expect(page.getByRole('heading', { name: 'Expense Detail' })).toBeVisible();
    await expect(page.getByText('Approved', { exact: true })).toBeVisible();
    await expect(page.getByText('Download 📎')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Mark Paid' })).toBeVisible();
    await expect(page.getByRole('button', { name: '✓ Approve' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: '✗ Reject' })).toHaveCount(0);

    const html = await (await page.request.get(`/expenses/${eid}/`)).text();
    expect(html).toContain('Approved By</div><div class="detail-value">admin');
    expect(html).toContain('Recorded By</div><div class="detail-value">admin');
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// EC — edge cases / boundary
// ─────────────────────────────────────────────────────────────────────────────

test.describe('EXP — edge cases (EC)', () => {
  test.use({ storageState: ADMIN_SS });

  test('EXP-EC-01 — approve/reject/mark-paid mutate on GET (no method check)', async ({ page }) => {
    // Documented defect (F4): the three views have no request.method guard, so a
    // plain GET performs the mutation. Asserting the ACTUAL (buggy) behaviour.
    const token = await csrf(page);

    const a = await newPendingExpense(page, token, 'EXP-EC-01');
    await page.request.get(`/expenses/${a.eid}/approve/`);
    expect(await getStatus(page.request, a.eid)).toBe('approved');
    expect(await ledgerFor(page.request, a.eid)).toHaveLength(1);

    const b = await newPendingExpense(page, token, 'EXP-EC-01');
    await page.request.get(`/expenses/${b.eid}/reject/`);
    expect(await getStatus(page.request, b.eid)).toBe('rejected');

    const c = await newPendingExpense(page, token, 'EXP-EC-01');
    await page.request.get(`/expenses/${c.eid}/mark-paid/`);
    expect(await getStatus(page.request, c.eid)).toBe('paid');
  });

  test('EXP-EC-02 — approved → rejected is legal but the ledger row is never reversed', async ({ page }) => {
    const token = await csrf(page);
    const { eid } = await newPendingExpense(page, token, 'EXP-EC-02', { amount: '5006.00' });

    await approve(page.request, token, eid);
    await reject(page.request, token, eid);

    expect(await getStatus(page.request, eid)).toBe('rejected');
    // Documented defect: the project_cost debit survives the rejection (orphan).
    expect(await ledgerFor(page.request, eid)).toHaveLength(1);
  });

  test('EXP-EC-03 — Delete a paid/approved expense (no status guard; ledger survives)', async ({ page }) => {
    const token = await csrf(page);
    const { eid, description } = await newPendingExpense(page, token, 'EXP-EC-03', { amount: '5007.00' });

    await approve(page.request, token, eid);
    expect((await deleteExpense(page.request, token, eid)).status()).toBe(302);

    // Expense gone, ledger row orphaned (reference_id has no FK).
    const listHtml = await (await page.request.get('/expenses/')).text();
    expect(listHtml).not.toContain(description);
    expect(await ledgerFor(page.request, eid)).toHaveLength(1);
  });

  test('EXP-EC-04 — No re-open path (rejected stays rejected)', async ({ page }) => {
    const token = await csrf(page);
    const { eid } = await newPendingExpense(page, token, 'EXP-EC-04');

    await reject(page.request, token, eid);
    expect(await getStatus(page.request, eid)).toBe('rejected');

    // Approve is blocked on a rejected expense.
    const approveRes = await approve(page.request, token, eid);
    expect(approveRes.headers()['location'] ?? '').toContain(`/expenses/${eid}/`);
    expect(await getStatus(page.request, eid)).toBe('rejected');

    // Mark-paid is blocked too.
    const payRes = await markPaid(page.request, token, eid);
    expect(payRes.headers()['location'] ?? '').toContain(`/expenses/${eid}/`);
    expect(await getStatus(page.request, eid)).toBe('rejected');
  });

  test('EXP-EC-05 — Double-approve re-stamps approved_at and writes a duplicate AuditLog', async ({ page }) => {
    const token = await csrf(page);
    const { eid } = await newPendingExpense(page, token, 'EXP-EC-05', { amount: '5008.00' });

    await approve(page.request, token, eid);
    await approve(page.request, token, eid);

    expect(await getStatus(page.request, eid)).toBe('approved');
    // Ledger stays single (idempotent), but two 'verify' audit entries are appended.
    expect(await ledgerFor(page.request, eid)).toHaveLength(1);
    const verifyLogs = (await auditFor(page.request, 'Expense', eid)).filter((l) => l.action === 'verify');
    expect(verifyLogs.length).toBeGreaterThanOrEqual(2);
  });

  test('EXP-EC-06 — Negative / zero amount rejected with a raw technical message', async ({ page }) => {
    const token = await csrf(page);
    const { id: pid } = await createProject(page.request, token);

    for (const amount of ['-1500', '0']) {
      const description = desc('EXP-EC-06');
      const res = await page.request.post('/expenses/create/', {
        form: {
          project: String(pid),
          description,
          amount,
          expense_type: 'internal',
          paid_to: 'ACME',
          expense_date: today(),
          payment_reference: '',
        },
        headers: { 'X-CSRFToken': token },
        maxRedirects: 0,
      });
      // Documented defect: the DB CheckConstraint surfaces as a raw non-field error.
      expect(res.status()).toBe(200);
      const body = await res.text();
      expect(body).toContain('expense_amount_positive');
      const listHtml = await (await page.request.get('/expenses/')).text();
      expect(listHtml).not.toContain(description);
    }
  });

  test('EXP-EC-07 — Locked edit is blocked server-side but the Edit button still renders', async ({ page }) => {
    const token = await csrf(page);
    const { eid } = await newPendingExpense(page, token, 'EXP-EC-07');

    await approve(page.request, token, eid);

    // The status guard blocks the edit (redirects back to detail, no form render).
    const res = await page.request.get(`/expenses/${eid}/edit/`, { maxRedirects: 0 });
    expect(res.status()).toBe(302);
    expect(res.headers()['location'] ?? '').toContain(`/expenses/${eid}/`);
    expect(await getStatus(page.request, eid)).toBe('approved');

    // Documented minor defect: the Edit button is still rendered for a locked record.
    await page.goto(`/expenses/${eid}/`);
    await expect(page.getByRole('link', { name: 'Edit' })).toBeVisible();
  });

  test('EXP-EC-08 — Rejected expense is editable but editing does not reset status', async ({ page }) => {
    const token = await csrf(page);
    const { pid, eid } = await newPendingExpense(page, token, 'EXP-EC-08', { amount: '5000.00' });

    await reject(page.request, token, eid);

    const res = await page.request.post(`/expenses/${eid}/edit/`, {
      form: {
        project: String(pid),
        description: `EXP-EC-08 ${Date.now()}`,
        amount: '9000.00',
        expense_type: 'internal',
        paid_to: 'EDITED-VENDOR',
        expense_date: today(),
        payment_reference: '',
      },
      headers: { 'X-CSRFToken': token },
      maxRedirects: 0,
    });
    expect(res.status()).toBe(302);
    expect(await getStatus(page.request, eid)).toBe('rejected');
    const html = await (await page.request.get(`/expenses/${eid}/`)).text();
    expect(html).toContain('Rs. 9000');
  });

  test('EXP-EC-09 — Illegal transitions are blocked (mark-paid on rejected; reject on paid)', async ({ page }) => {
    const token = await csrf(page);
    const rejected = await newPendingExpense(page, token, 'EXP-EC-09');
    await reject(page.request, token, rejected.eid);

    const paid = await newPendingExpense(page, token, 'EXP-EC-09');
    await markPaid(page.request, token, paid.eid);

    // mark-paid on rejected → blocked.
    const payRejected = await markPaid(page.request, token, rejected.eid);
    expect(payRejected.headers()['location'] ?? '').toContain(`/expenses/${rejected.eid}/`);
    expect(await getStatus(page.request, rejected.eid)).toBe('rejected');

    // reject on paid → blocked.
    const rejectPaid = await reject(page.request, token, paid.eid);
    expect(rejectPaid.headers()['location'] ?? '').toContain(`/expenses/${paid.eid}/`);
    expect(await getStatus(page.request, paid.eid)).toBe('paid');
  });

  test('EXP-EC-10 — Inactive project excluded from the form\'s project queryset', async ({ page }) => {
    const token = await csrf(page);
    const activeName = `QA-EC10-ACT-${Date.now()}`;
    const inactiveName = `QA-EC10-INA-${Date.now()}`;
    const active = await createProject(page.request, token, { name: activeName });
    const inactive = await createProject(page.request, token, { name: inactiveName, status: 'inactive' });

    const formHtml = await (await page.request.get('/expenses/create/')).text();
    expect(formHtml).toContain(activeName);
    expect(formHtml).not.toContain(inactiveName);

    // A direct POST with the inactive id is rejected as an invalid choice.
    const description = desc('EXP-EC-10');
    const res = await page.request.post('/expenses/create/', {
      form: {
        project: String(inactive.id),
        description,
        amount: '500.00',
        expense_type: 'internal',
        paid_to: 'ACME',
        expense_date: today(),
        payment_reference: '',
      },
      headers: { 'X-CSRFToken': token },
      maxRedirects: 0,
    });
    expect(res.status()).toBe(200);
    expect(await res.text()).toContain('Select a valid choice');
    const listHtml = await (await page.request.get('/expenses/')).text();
    expect(listHtml).not.toContain(description);
  });

  test('EXP-EC-11 — Oversized receipt upload is not handled gracefully', async ({ page }) => {
    const token = await csrf(page);
    const { id: pid } = await createProject(page.request, token);
    const description = desc('EXP-EC-11');
    const big = Buffer.alloc(3 * 1024 * 1024, 0x41); // ~3 MB

    const res = await page.request.post('/expenses/create/', {
      multipart: {
        project: String(pid),
        description,
        amount: '500.00',
        expense_type: 'internal',
        paid_to: 'ACME',
        expense_date: today(),
        receipt_attachment: { name: 'big.bin', mimeType: 'application/octet-stream', buffer: big },
      },
      headers: { 'X-CSRFToken': token },
      maxRedirects: 0,
    });

    // Documented defect: no friendly "file too large" message either way.
    const body = await res.text();
    expect(/too\s+large|file.{0,15}large/i.test(body)).toBe(false);
  });

  test('EXP-EC-12 — Concurrent double-submit of approve keeps the ledger single', async ({ page }) => {
    const token = await csrf(page);
    const { eid } = await newPendingExpense(page, token, 'EXP-EC-12', { amount: '5009.00' });

    await Promise.allSettled([approve(page.request, token, eid), approve(page.request, token, eid)]);

    // Invariant: exactly one ledger row, even if the losing request 500s.
    expect(await ledgerFor(page.request, eid)).toHaveLength(1);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// SEC — negative & security
// ─────────────────────────────────────────────────────────────────────────────

test.describe('EXP — security (SEC)', () => {
  test.use({ storageState: ADMIN_SS });

  test('EXP-SEC-01 — CSRF via GET on approve (HIGH)', async ({ page }) => {
    const token = await csrf(page);
    const { eid } = await newPendingExpense(page, token, 'EXP-SEC-01');

    await page.request.get(`/expenses/${eid}/approve/`); // plain GET, no CSRF

    // CONFIRMED BUG: docs/qa/findings-confirmed.md F4 — GET mutates.
    expect(await getStatus(page.request, eid)).toBe('pending');
  });

  test('EXP-SEC-02 — CSRF via GET on reject (HIGH)', async ({ page }) => {
    const token = await csrf(page);
    const { eid } = await newPendingExpense(page, token, 'EXP-SEC-02');

    await page.request.get(`/expenses/${eid}/reject/`);

    // CONFIRMED BUG: docs/qa/findings-confirmed.md F4 — GET mutates.
    expect(await getStatus(page.request, eid)).toBe('pending');
  });

  test('EXP-SEC-03 — CSRF via GET on mark-paid (HIGH)', async ({ page }) => {
    const token = await csrf(page);
    const { eid } = await newPendingExpense(page, token, 'EXP-SEC-03');

    await page.request.get(`/expenses/${eid}/mark-paid/`);

    // CONFIRMED BUG: docs/qa/findings-confirmed.md F4 — GET mutates.
    expect(await getStatus(page.request, eid)).toBe('pending');
  });

  test('EXP-SEC-04 — Stored XSS via SVG receipt upload (HIGH)', async ({ page }) => {
    const token = await csrf(page);
    const { id: pid } = await createProject(page.request, token);
    const description = desc('EXP-SEC-04');
    const svg = Buffer.from(
      `<svg xmlns="http://www.w3.org/2000/svg" onload="alert(document.domain)"><script>fetch('/expenses/')</script></svg>`,
    );

    const res = await page.request.post('/expenses/create/', {
      multipart: {
        project: String(pid),
        description,
        amount: '500.00',
        expense_type: 'internal',
        paid_to: 'ACME',
        expense_date: today(),
        receipt_attachment: { name: `poc-${Date.now()}.svg`, mimeType: 'image/svg+xml', buffer: svg },
      },
      headers: { 'X-CSRFToken': token },
      maxRedirects: 0,
    });

    // CONFIRMED BUG: FileField accepts arbitrary types — the SVG should be rejected.
    expect(res.status()).toBe(200);
  });

  test('EXP-SEC-05 — Stored XSS via HTML receipt upload', async ({ page }) => {
    const token = await csrf(page);
    const { id: pid } = await createProject(page.request, token);
    const description = desc('EXP-SEC-05');
    const html = Buffer.from(`<script>alert(document.domain)</script>`);

    const res = await page.request.post('/expenses/create/', {
      multipart: {
        project: String(pid),
        description,
        amount: '500.00',
        expense_type: 'internal',
        paid_to: 'ACME',
        expense_date: today(),
        receipt_attachment: { name: `poc-${Date.now()}.html`, mimeType: 'text/html', buffer: html },
      },
      headers: { 'X-CSRFToken': token },
      maxRedirects: 0,
    });

    // CONFIRMED BUG: FileField accepts arbitrary types — the HTML should be rejected.
    expect(res.status()).toBe(200);
  });

  test('EXP-SEC-06 — Unauthenticated media serving of vendor invoices', async ({ page, playwright }) => {
    const token = await csrf(page);
    const { id: pid } = await createProject(page.request, token);
    const eid = await createExpense(page.request, token, {
      projectId: pid,
      description: desc('EXP-SEC-06'),
      amount: '500.00',
      file: { name: `invoice-${Date.now()}.png`, mimeType: 'image/png', buffer: Buffer.from('invoice') },
    });

    const detailHtml = await (await page.request.get(`/expenses/${eid}/`)).text();
    const m = detailHtml.match(/href="(\/media\/[^"]+)"/);
    const mediaUrl = m?.[1];
    expect(mediaUrl).toBeTruthy();

    const anon = await playwright.request.newContext({ baseURL: BASE_URL });
    const res = await anon.get(mediaUrl!, { maxRedirects: 0 });
    await anon.dispose();

    // CONFIRMED BUG: media is served with no authentication.
    expect(res.status()).toBeGreaterThanOrEqual(300);
  });

  test('EXP-SEC-09 — Project CASCADE deletes expenses → orphaned ledger rows', async ({ page }) => {
    const token = await csrf(page);
    const name = `QA-SEC09-${Date.now()}`;
    const { id: pid } = await createProject(page.request, token, { name });
    const eid = await createExpense(page.request, token, {
      projectId: pid,
      description: desc('EXP-SEC-09'),
      amount: '5010.00',
    });
    await approve(page.request, token, eid);
    expect(await ledgerFor(page.request, eid)).toHaveLength(1);

    // Delete the (plot-less) project; expenses CASCADE, ledger rows orphan.
    const del = await page.request.delete(`/api/projects/${pid}/`, { headers: { 'X-CSRFToken': token } });
    expect(del.status()).toBe(204);

    // Documented defect: the ledger row survives the cascade (reference_id has no FK).
    expect(await ledgerFor(page.request, eid)).toHaveLength(1);
  });

  test('EXP-SEC-10 — XSS in text fields: negative control (auto-escaped)', async ({ page }) => {
    const token = await csrf(page);
    const { id: pid } = await createProject(page.request, token);
    const payload = '<script>alert(1)</script>';
    const description = `EXP-SEC-10 ${Date.now()}`;
    const eid = await createExpense(page.request, token, {
      projectId: pid,
      description,
      amount: '500.00',
      paidTo: payload,
    });

    const html = await (await page.request.get(`/expenses/${eid}/`)).text();
    expect(html).toContain('&lt;script&gt;alert(1)&lt;/script&gt;');
    expect(html).not.toContain('<script>alert(1)');
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// SEC-07 — IDOR / no maker-checker (two finance users)
// ─────────────────────────────────────────────────────────────────────────────

test.describe('EXP — IDOR / maker-checker (SEC-07)', () => {
  test('EXP-SEC-07 — any finance user can approve another user\'s expense', async ({ browser }) => {
    // Two pre-authenticated finance users via saved storageState. (Avoiding API
    // login here — Django's auth.login() rotates sessions, which would invalidate
    // the storageState sessions of tests running in parallel.)
    const ctxA = await browser.newContext({ storageState: ADMIN_SS, baseURL: BASE_URL });
    const pageA = await ctxA.newPage();
    const tokenA = await csrf(pageA);
    const pid = (await createProject(pageA.request, tokenA)).id;
    const eid = await createExpense(pageA.request, tokenA, {
      projectId: pid,
      description: desc('EXP-SEC-07'),
      amount: '5011.00',
    });

    // user B = accounts approves A's expense (no ownership / maker-checker guard).
    const ctxB = await browser.newContext({ storageState: ACCOUNTS_SS, baseURL: BASE_URL });
    const pageB = await ctxB.newPage();
    const tokenB = await csrf(pageB);
    const res = await pageB.request.post(`/expenses/${eid}/approve/`, { headers: { 'X-CSRFToken': tokenB }, maxRedirects: 0 });
    expect(res.status()).toBe(302);
    expect(await getStatus(pageB.request, eid)).toBe('approved');
    const html = await (await pageB.request.get(`/expenses/${eid}/`)).text();
    expect(html).toContain('Approved By</div><div class="detail-value">qa_accounts');

    await ctxA.close();
    await ctxB.close();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// SEC-08 — authorization denials (sales + anonymous)
// ─────────────────────────────────────────────────────────────────────────────

test.describe('EXP — authorization denials (SEC-08)', () => {
  test.use({ storageState: SALES_SS });

  test('EXP-SEC-08 — non-finance roles and anonymous are denied', async ({ page, browser }) => {
    // The login_required / finance_or_above decorators fire before get_object_or_404,
    // so a non-existent pk exercises the denial without needing a fixture.
    const pk = 999999999;
    const routes = [
      '/expenses/',
      '/expenses/create/',
      `/expenses/${pk}/`,
      `/expenses/${pk}/edit/`,
      `/expenses/${pk}/approve/`,
      `/expenses/${pk}/reject/`,
      `/expenses/${pk}/mark-paid/`,
      `/expenses/${pk}/delete/`,
    ];

    // sales → 302 to /dashboard/ (no mutation).
    for (const r of routes) {
      const res = await page.request.get(r, { maxRedirects: 0 });
      expect(res.status(), `sales ${r}`).toBe(302);
      expect(res.headers()['location'] ?? '', `sales ${r}`).toContain('/dashboard/');
    }

    // anonymous → 302 to /login/ (explicitly clear the inherited storageState).
    const anonCtx = await browser.newContext({ baseURL: BASE_URL, storageState: { cookies: [], origins: [] } });
    const anonPage = await anonCtx.newPage();
    for (const r of routes) {
      const res = await anonPage.request.get(r, { maxRedirects: 0 });
      expect(res.status(), `anon ${r}`).toBe(302);
      expect(res.headers()['location'] ?? '', `anon ${r}`).toContain('/login/');
    }
    await anonCtx.close();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// API — API contract (web-only module)
// ─────────────────────────────────────────────────────────────────────────────

test.describe('EXP — API contract (API)', () => {
  test.use({ storageState: ADMIN_SS });

  test('EXP-API-01 — No DRF endpoint for Expense', async ({ page }) => {
    for (const path of ['/api/expenses/', '/api/expense/', '/api/expenses/1/']) {
      const res = await page.request.get(path);
      expect(res.status(), path).toBe(404);
    }
  });

  test('EXP-API-02 — Document the URL route table and verb behavior', async ({ page }) => {
    const token = await csrf(page);
    const fixtures = await Promise.all([
      newPendingExpense(page, token, 'EXP-API-02'),
      newPendingExpense(page, token, 'EXP-API-02'),
      newPendingExpense(page, token, 'EXP-API-02'),
      newPendingExpense(page, token, 'EXP-API-02'),
    ]);

    // Route table (name, path, expected status). The three ⚠ routes mutate on GET
    // (documented defect F4 — see EXP-EC-01 / EXP-SEC-01..03).
    const table: Array<{ path: string; status: number }> = [
      { path: '/expenses/', status: 200 },                              // expenses (GET)
      { path: '/expenses/create/', status: 200 },                       // expense_create (GET)
      { path: `/expenses/${fixtures[3].eid}/edit/`, status: 200 },      // expense_edit (GET)
      { path: `/expenses/${fixtures[3].eid}/`, status: 200 },           // expense_detail (GET)
      { path: `/expenses/${fixtures[3].eid}/delete/`, status: 200 },    // expense_delete (GET → confirm)
      { path: `/expenses/${fixtures[0].eid}/approve/`, status: 302 },   // ⚠ mutates on GET
      { path: `/expenses/${fixtures[1].eid}/reject/`, status: 302 },    // ⚠ mutates on GET
      { path: `/expenses/${fixtures[2].eid}/mark-paid/`, status: 302 }, // ⚠ mutates on GET
    ];

    for (const { path, status } of table) {
      const res = await page.request.get(path, { maxRedirects: 0 });
      expect(res.status(), path).toBe(status);
    }
  });
});
