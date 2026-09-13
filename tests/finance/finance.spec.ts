import { test, expect, APIRequestContext, Page } from '@playwright/test';
import { loginViaApi, ROLES } from '../helpers/auth';

/**
 * Finance module E2E (specs/finance.md, 34 scenarios: FIN-HP-*, FIN-EC-*,
 * FIN-SEC-*, FIN-API-*).
 *
 * Split of tools:
 *  - `request` + `loginViaApi` for API/ledger data-plane checks.
 *  - `page` for the office / expense / cost / budget UI flows.
 *
 * Confirmed bugs (docs/qa/findings-confirmed.md F3 — the finance read-open) are
 * written RED on purpose: they assert the CORRECT behaviour and fail today.
 * The edge-case "observed bug" scenarios (FIN-EC-*) assert the CURRENT (buggy)
 * behaviour so they PASS, each tagged with a `KNOWN BUG` comment.
 */

type Role = keyof typeof ROLES;

interface Ctx {
  request: APIRequestContext;
  token: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

/** Unique timestamped fixture name. */
function qa(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 1_000_000)}`;
}

/** YYYY-MM-DD for `expense_date` / `cost_date`. */
function today(): string {
  return new Date().toISOString().slice(0, 10);
}

const csrf = (token: string) => ({ 'X-CSRFToken': token });

/**
 * Log in via API and return a FRESH CSRF token. `loginViaApi` returns the token
 * read BEFORE login, but Django rotates the CSRF token during `auth_login`, so
 * we re-read the cookie to obtain the token that matches the logged-in session.
 */
async function apiLogin(request: APIRequestContext, role: Role): Promise<string> {
  await loginViaApi(request, role);
  const state = await request.storageState();
  const cookie = state.cookies.find((c) => c.name === 'csrftoken');
  return cookie ? cookie.value : '';
}

// — fixtures (create via API, admin or finance role) —

async function createOffice(ctx: Ctx, name: string, officeType = 'head_office'): Promise<number> {
  const res = await ctx.request.post('/api/offices/', {
    data: { name, office_type: officeType, address: 'QA address', is_active: true },
    headers: csrf(ctx.token),
  });
  expect(res.status(), await res.text()).toBe(201);
  return (await res.json()).id as number;
}

async function createCategory(ctx: Ctx, name: string, categoryType = 'rent'): Promise<number> {
  const res = await ctx.request.post('/api/expense-categories/', {
    data: { name, category_type: categoryType, is_active: true },
    headers: csrf(ctx.token),
  });
  expect(res.status(), await res.text()).toBe(201);
  return (await res.json()).id as number;
}

async function createProject(ctx: Ctx, name: string): Promise<number> {
  const res = await ctx.request.post('/api/projects/', {
    data: { name, location: 'QA Location', status: 'booking_open' },
    headers: csrf(ctx.token),
  });
  expect(res.status(), await res.text()).toBe(201);
  return (await res.json()).id as number;
}

async function createExpense(
  ctx: Ctx,
  o: { office: number; category: number; amount: string; date: string; status: string },
): Promise<number> {
  const res = await ctx.request.post('/api/office-expenses/', {
    data: {
      office: o.office,
      category: o.category,
      amount: o.amount,
      expense_date: o.date,
      status: o.status,
    },
    headers: csrf(ctx.token),
  });
  expect(res.status(), await res.text()).toBe(201);
  return (await res.json()).id as number;
}

async function createCost(
  ctx: Ctx,
  o: { project: number; amount: string; date: string; status: string; costCategory?: string },
): Promise<number> {
  const res = await ctx.request.post('/api/project-costs/', {
    data: {
      project: o.project,
      cost_category: o.costCategory ?? 'material',
      amount: o.amount,
      cost_date: o.date,
      status: o.status,
    },
    headers: csrf(ctx.token),
  });
  expect(res.status(), await res.text()).toBe(201);
  return (await res.json()).id as number;
}

// — ledger reads —

async function listTransactions(request: APIRequestContext, transactionType: string): Promise<any[]> {
  const res = await request.get(`/api/account-transactions/?transaction_type=${transactionType}`);
  expect(res.status()).toBe(200);
  return await res.json();
}

async function ledgerRowsFor(
  request: APIRequestContext,
  transactionType: string,
  referenceType: string,
  referenceId: number,
): Promise<any[]> {
  const rows = await listTransactions(request, transactionType);
  return rows.filter((r) => r.reference_type === referenceType && r.reference_id === referenceId);
}

// — cleanup registry (drained in afterEach as admin) —

let cleanups: Array<(ctx: Ctx) => Promise<void>> = [];

function regObject(path: string): void {
  cleanups.push(async (ctx) => {
    await ctx.request.delete(path, { headers: csrf(ctx.token) });
  });
}

function regLedger(transactionType: string, referenceType: string, referenceId: number): void {
  cleanups.push(async (ctx) => {
    const rows = await ledgerRowsFor(ctx.request, transactionType, referenceType, referenceId);
    for (const row of rows) {
      await ctx.request.delete(`/api/account-transactions/${row.id}/`, {
        headers: csrf(ctx.token),
      });
    }
  });
}

test.beforeEach(() => {
  cleanups = [];
});

test.afterEach(async ({ request }) => {
  if (cleanups.length === 0) return;
  let token: string;
  try {
    token = await apiLogin(request, 'admin');
  } catch {
    return;
  }
  const ctx: Ctx = { request, token };
  for (const fn of [...cleanups].reverse()) {
    try {
      await fn(ctx);
    } catch {
      /* cleanup is best-effort */
    }
  }
});

// — UI flows (role/label locators; selects have unassociated labels, so use name=) —

async function uiCreateOffice(
  page: Page,
  name: string,
  officeType: 'head_office' | 'branch',
  address: string,
): Promise<void> {
  await page.goto('/finance/offices/create/');
  await page.getByLabel('Name').fill(name);
  await page.locator('select[name="office_type"]').selectOption(officeType);
  await page.getByLabel('Address').fill(address);
  await page.getByRole('button', { name: 'Create' }).click();
  await expect(page).toHaveURL(/\/finance\/offices\//);
}

async function uiCreateExpense(
  page: Page,
  o: { office: string; category: string; amount: string; date: string; status: string; paidTo?: string },
): Promise<void> {
  await page.goto('/finance/office-expenses/create/');
  await page.locator('select[name="office"]').selectOption({ label: o.office });
  await page.locator('select[name="category"]').selectOption({ label: o.category });
  await page.getByLabel('Amount').fill(o.amount);
  await page.getByLabel('Expense date').fill(o.date);
  if (o.paidTo) await page.getByLabel('Paid to').fill(o.paidTo);
  await page.locator('select[name="status"]').selectOption(o.status);
  await page.getByRole('button', { name: 'Create' }).click();
  await expect(page).toHaveURL(/\/finance\/office-expenses\//);
}

async function uiCreateCost(
  page: Page,
  o: { project: string; amount: string; date: string; costCategory?: string; status?: string },
): Promise<void> {
  await page.goto('/finance/project-costs/create/');
  await page.locator('select[name="project"]').selectOption({ label: o.project });
  if (o.costCategory) await page.locator('select[name="cost_category"]').selectOption(o.costCategory);
  await page.getByLabel('Amount').fill(o.amount);
  await page.getByLabel('Cost date').fill(o.date);
  if (o.status) await page.locator('select[name="status"]').selectOption(o.status);
  await page.getByRole('button', { name: 'Create' }).click();
  await expect(page).toHaveURL(/\/finance\/project-costs\//);
}

async function uiEditExpense(
  page: Page,
  expenseId: number,
  updates: { amount?: string; date?: string; status?: string },
): Promise<void> {
  await page.goto(`/finance/office-expenses/${expenseId}/edit/`);
  if (updates.amount !== undefined) await page.getByLabel('Amount').fill(updates.amount);
  if (updates.date !== undefined) await page.getByLabel('Expense date').fill(updates.date);
  if (updates.status !== undefined) await page.locator('select[name="status"]').selectOption(updates.status);
  await page.getByRole('button', { name: 'Update' }).click();
  await expect(page).toHaveURL(/\/finance\/office-expenses\//);
}

async function uiEditCost(
  page: Page,
  costId: number,
  updates: { amount?: string; date?: string },
): Promise<void> {
  await page.goto(`/finance/project-costs/${costId}/edit/`);
  if (updates.amount !== undefined) await page.getByLabel('Amount').fill(updates.amount);
  if (updates.date !== undefined) await page.getByLabel('Cost date').fill(updates.date);
  await page.getByRole('button', { name: 'Update' }).click();
  await expect(page).toHaveURL(/\/finance\/project-costs\//);
}

// ─────────────────────────────────────────────────────────────────────────────
// FIN-HP — happy paths (admin UI + API verification)
// ─────────────────────────────────────────────────────────────────────────────
test.describe('FIN-HP — happy paths', () => {
  test('FIN-HP-01 — Create office', async ({ page, request }) => {
    const token = await apiLogin(request, 'admin');
    const name = qa('QA-HO');
    await uiCreateOffice(page, name, 'head_office', 'QA Head Office address');

    // Office row persisted, listed on the offices page.
    await page.goto('/finance/offices/');
    await expect(page.getByText(name)).toBeVisible();

    // Verify via API and register cleanup.
    const list = await request.get('/api/offices/');
    const body = await list.json();
    const office = body.find((o: any) => o.name === name);
    expect(office, 'office should be persisted').toBeTruthy();
    expect(office.office_type).toBe('head_office');
    regObject(`/api/offices/${office.id}/`);
  });

  test('FIN-HP-02 — Create office expense with status "paid" posts exactly one ledger row', async ({
    page,
    request,
  }) => {
    const token = await apiLogin(request, 'admin');
    const ctx: Ctx = { request, token };
    const officeName = qa('QA-HO');
    const categoryName = qa('QA-Rent');
    const officeId = await createOffice(ctx, officeName);
    const categoryId = await createCategory(ctx, categoryName);
    regObject(`/api/offices/${officeId}/`);
    regObject(`/api/expense-categories/${categoryId}/`);

    await uiCreateExpense(page, {
      office: officeName,
      category: categoryName,
      amount: '25000.00',
      date: today(),
      status: 'paid',
    });

    const exps = await request.get(`/api/office-expenses/?office=${officeId}`);
    const expBody = await exps.json();
    const exp = expBody[0];
    expect(exp.status).toBe('paid');
    regObject(`/api/office-expenses/${exp.id}/`);
    regLedger('office_expense', 'OfficeExpense', exp.id);

    const rows = await ledgerRowsFor(request, 'office_expense', 'OfficeExpense', exp.id);
    expect(rows.length).toBe(1);
    expect(rows[0].amount).toBe('25000.00');
    expect(rows[0].direction).toBe('out');
    expect(rows[0].transaction_type).toBe('office_expense');
    expect(rows[0].category).toBe(categoryName);
    expect(rows[0].date).toBe(today());
  });

  test('FIN-HP-03 — Approve then Pay office expense posts ledger exactly once (idempotent)', async ({
    page,
    request,
  }) => {
    const token = await apiLogin(request, 'admin');
    const ctx: Ctx = { request, token };
    const officeName = qa('QA-HO');
    const categoryName = qa('QA-Rent');
    const officeId = await createOffice(ctx, officeName);
    const categoryId = await createCategory(ctx, categoryName);
    const expenseId = await createExpense(ctx, {
      office: officeId,
      category: categoryId,
      amount: '25000.00',
      date: today(),
      status: 'pending',
    });
    regObject(`/api/offices/${officeId}/`);
    regObject(`/api/expense-categories/${categoryId}/`);
    regObject(`/api/office-expenses/${expenseId}/`);
    regLedger('office_expense', 'OfficeExpense', expenseId);

    // Approve: status approved, no ledger row yet.
    await page.goto('/finance/office-expenses/');
    await page.getByRole('row', { name: officeName }).getByRole('button', { name: 'Approve' }).click();
    // The approve redirects back to the same list URL, so poll the API state
    // instead of asserting on the (unchanged) URL.
    await expect
      .poll(async () => (await (await request.get(`/api/office-expenses/${expenseId}/`)).json()).status)
      .toBe('approved');
    expect(await ledgerRowsFor(request, 'office_expense', 'OfficeExpense', expenseId)).toHaveLength(0);

    // Pay (accept the JS confirm on the form).
    await page.goto('/finance/office-expenses/');
    page.once('dialog', (d) => d.accept());
    await page.getByRole('row', { name: officeName }).getByRole('button', { name: 'Pay' }).click();
    await expect
      .poll(async () => (await (await request.get(`/api/office-expenses/${expenseId}/`)).json()).status)
      .toBe('paid');

    expect(await ledgerRowsFor(request, 'office_expense', 'OfficeExpense', expenseId)).toHaveLength(1);

    // Double pay via API — still exactly one row (idempotent).
    await request.post(`/api/office-expenses/${expenseId}/pay/`, { headers: csrf(token) });
    expect(await ledgerRowsFor(request, 'office_expense', 'OfficeExpense', expenseId)).toHaveLength(1);
  });

  test('FIN-HP-04 — Create project cost (default "paid") posts ledger immediately', async ({
    page,
    request,
  }) => {
    const token = await apiLogin(request, 'admin');
    const ctx: Ctx = { request, token };
    const projectName = qa('QA-Proj');
    const projectId = await createProject(ctx, projectName);
    regObject(`/api/projects/${projectId}/`);

    await uiCreateCost(page, { project: projectName, amount: '40000.00', date: today() });

    const costs = await request.get(`/api/project-costs/?project=${projectId}`);
    const costBody = await costs.json();
    const cost = costBody[0];
    expect(cost.status).toBe('paid');
    regObject(`/api/project-costs/${cost.id}/`);
    regLedger('project_cost', 'ProjectCost', cost.id);

    const rows = await ledgerRowsFor(request, 'project_cost', 'ProjectCost', cost.id);
    expect(rows.length).toBe(1);
    expect(rows[0].amount).toBe('40000.00');
    expect(rows[0].direction).toBe('out');
    expect(rows[0].transaction_type).toBe('project_cost');
  });

  test('FIN-HP-05 — Project budget: remaining = total − paid costs', async ({ page, request }) => {
    const token = await apiLogin(request, 'admin');
    const ctx: Ctx = { request, token };
    const projectName = qa('QA-Proj');
    const projectId = await createProject(ctx, projectName);
    const costId = await createCost(ctx, {
      project: projectId,
      amount: '40000.00',
      date: today(),
      status: 'paid',
    });
    regObject(`/api/projects/${projectId}/`);
    regObject(`/api/project-costs/${costId}/`);
    regLedger('project_cost', 'ProjectCost', costId);

    // Set budget via UI.
    await page.goto(`/finance/projects/${projectId}/budget/`);
    await page.getByLabel('Total budget').fill('100000.00');
    await page.getByRole('button', { name: 'Create' }).click();
    await expect(page).toHaveURL(/\/finance\/projects\//);

    // Verify remaining via API (exact Decimal string).
    const budgets = await request.get('/api/project-budgets/');
    const budgetBody = await budgets.json();
    const budget = budgetBody.find((b: any) => b.project === projectId);
    expect(budget).toBeTruthy();
    expect(budget.total_budget).toBe('100000.00');
    expect(budget.total_actual).toBe('40000.00');
    expect(budget.remaining_budget).toBe('60000.00');
    regObject(`/api/project-budgets/${budget.id}/`);
  });

  test('FIN-HP-06 — Project investment recorded and shown', async ({ page, request }) => {
    const token = await apiLogin(request, 'admin');
    const ctx: Ctx = { request, token };
    const projectName = qa('QA-Proj');
    const projectId = await createProject(ctx, projectName);
    regObject(`/api/projects/${projectId}/`);

    await page.goto(`/finance/projects/${projectId}/investment/`);
    await page.getByLabel('Total investment').fill('1500000.00');
    await page.getByLabel('Notes').fill('QA investment note');
    await page.getByRole('button', { name: 'Create' }).click();
    await expect(page).toHaveURL(/\/finance\/projects\//);

    const investments = await request.get('/api/project-investments/');
    const invBody = await investments.json();
    const inv = invBody.find((i: any) => i.project === projectId);
    expect(inv).toBeTruthy();
    expect(inv.total_investment).toBe('1500000.00');
    regObject(`/api/project-investments/${inv.id}/`);

    // Project finance view renders the row without crashing.
    await page.goto('/finance/projects/');
    await expect(page.getByText(projectName)).toBeVisible();
  });

  test('FIN-HP-07 — Ledger list: totals and filters', async ({ page, request }) => {
    const token = await apiLogin(request, 'admin');
    const ctx: Ctx = { request, token };
    const officeName = qa('QA-HO');
    const officeCategory = qa('QA-Rent');
    const inCategory = qa('QA-IN');
    const officeId = await createOffice(ctx, officeName);
    const categoryId = await createCategory(ctx, officeCategory);
    const expenseId = await createExpense(ctx, {
      office: officeId,
      category: categoryId,
      amount: '25000.00',
      date: today(),
      status: 'paid',
    });
    regObject(`/api/offices/${officeId}/`);
    regObject(`/api/expense-categories/${categoryId}/`);
    regObject(`/api/office-expenses/${expenseId}/`);
    regLedger('office_expense', 'OfficeExpense', expenseId);

    // Ad-hoc money-in row (no reference) so the ledger has both directions.
    const inRes = await request.post('/api/account-transactions/', {
      data: {
        date: today(),
        amount: '1000.00',
        direction: 'in',
        transaction_type: 'income',
        category: inCategory,
      },
      headers: csrf(token),
    });
    expect(inRes.status(), await inRes.text()).toBe(201);
    const inRow = await inRes.json();
    regObject(`/api/account-transactions/${inRow.id}/`);

    await page.goto('/finance/ledger/');
    await expect(page.getByRole('heading', { name: 'Financial Ledger' })).toBeVisible();
    await expect(page.getByText(officeCategory)).toBeVisible();
    await expect(page.getByText(inCategory)).toBeVisible();

    await page.goto('/finance/ledger/?type=office_expense');
    await expect(page.getByText(officeCategory)).toBeVisible();
    await expect(page.getByText(inCategory)).toHaveCount(0);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// FIN-EC — edge cases (admin UI / API)
// ─────────────────────────────────────────────────────────────────────────────
test.describe('FIN-EC — edge cases (admin)', () => {
  test('FIN-EC-01 — Status demotion orphans the ledger (paid → draft leaves the row)', async ({
    page,
    request,
  }) => {
    const token = await apiLogin(request, 'admin');
    const ctx: Ctx = { request, token };
    const officeName = qa('QA-HO');
    const categoryName = qa('QA-Rent');
    const officeId = await createOffice(ctx, officeName);
    const categoryId = await createCategory(ctx, categoryName);
    const expenseId = await createExpense(ctx, {
      office: officeId,
      category: categoryId,
      amount: '25000.00',
      date: today(),
      status: 'paid',
    });
    regObject(`/api/offices/${officeId}/`);
    regObject(`/api/expense-categories/${categoryId}/`);
    regObject(`/api/office-expenses/${expenseId}/`);
    regLedger('office_expense', 'OfficeExpense', expenseId);

    expect(await ledgerRowsFor(request, 'office_expense', 'OfficeExpense', expenseId)).toHaveLength(1);

    await uiEditExpense(page, expenseId, { status: 'draft' });

    const exp = await (await request.get(`/api/office-expenses/${expenseId}/`)).json();
    expect(exp.status).toBe('draft');
    // KNOWN BUG (finance_analysis §5): demoting a paid expense does NOT void its
    // ledger row — money stays booked out while the object is no longer paid.
    expect(await ledgerRowsFor(request, 'office_expense', 'OfficeExpense', expenseId)).toHaveLength(1);
  });

  test('FIN-EC-02 — Delete paid ProjectCost leaves orphaned AccountTransaction', async ({ request }) => {
    const token = await apiLogin(request, 'admin');
    const ctx: Ctx = { request, token };
    const projectId = await createProject(ctx, qa('QA-Proj'));
    const costId = await createCost(ctx, {
      project: projectId,
      amount: '40000.00',
      date: today(),
      status: 'paid',
    });
    regObject(`/api/projects/${projectId}/`);
    regObject(`/api/project-costs/${costId}/`);
    regLedger('project_cost', 'ProjectCost', costId);

    expect(await ledgerRowsFor(request, 'project_cost', 'ProjectCost', costId)).toHaveLength(1);

    // Delete via the HTML view (management_or_above) — admin is superuser.
    const del = await request.post(`/finance/project-costs/${costId}/delete/`, {
      headers: csrf(token),
    });
    expect(del.status()).toBe(200);

    // KNOWN BUG (finance_analysis §5): the cost is gone, but the ledger row
    // survives (reference_id is a plain int, no FK cascade) — phantom spend.
    const costs = await request.get(`/api/project-costs/?project=${projectId}`);
    expect((await costs.json()).filter((c: any) => c.id === costId)).toHaveLength(0);
    expect(await ledgerRowsFor(request, 'project_cost', 'ProjectCost', costId)).toHaveLength(1);
  });

  test('FIN-EC-03 — Editing a paid office expense re-dates/re-amounts the historical ledger row', async ({
    page,
    request,
  }) => {
    const token = await apiLogin(request, 'admin');
    const ctx: Ctx = { request, token };
    const officeName = qa('QA-HO');
    const categoryName = qa('QA-Rent');
    const officeId = await createOffice(ctx, officeName);
    const categoryId = await createCategory(ctx, categoryName);
    const expenseId = await createExpense(ctx, {
      office: officeId,
      category: categoryId,
      amount: '25000.00',
      date: today(),
      status: 'paid',
    });
    regObject(`/api/offices/${officeId}/`);
    regObject(`/api/expense-categories/${categoryId}/`);
    regObject(`/api/office-expenses/${expenseId}/`);
    regLedger('office_expense', 'OfficeExpense', expenseId);

    await uiEditExpense(page, expenseId, { amount: '50000.00', date: '2020-01-01' });

    // KNOWN BUG (finance_analysis §5): update_or_create silently rewrites the
    // historical ledger row's amount/date — no immutability for paid records.
    const rows = await ledgerRowsFor(request, 'office_expense', 'OfficeExpense', expenseId);
    expect(rows.length).toBe(1);
    expect(rows[0].amount).toBe('50000.00');
    expect(rows[0].date).toBe('2020-01-01');
  });

  test('FIN-EC-04 — Editing a paid project cost re-dates/re-amounts the historical ledger row', async ({
    page,
    request,
  }) => {
    const token = await apiLogin(request, 'admin');
    const ctx: Ctx = { request, token };
    const projectId = await createProject(ctx, qa('QA-Proj'));
    const costId = await createCost(ctx, {
      project: projectId,
      amount: '40000.00',
      date: today(),
      status: 'paid',
    });
    regObject(`/api/projects/${projectId}/`);
    regObject(`/api/project-costs/${costId}/`);
    regLedger('project_cost', 'ProjectCost', costId);

    await uiEditCost(page, costId, { amount: '90000.00', date: '2020-01-01' });

    // KNOWN BUG (finance_analysis §5): historical project-cost ledger row rewritten.
    const rows = await ledgerRowsFor(request, 'project_cost', 'ProjectCost', costId);
    expect(rows.length).toBe(1);
    expect(rows[0].amount).toBe('90000.00');
    expect(rows[0].date).toBe('2020-01-01');
  });

  test('FIN-EC-07 — Negative total_budget → IntegrityError / HTTP 500 (no form/serializer validation)', async ({
    request,
  }) => {
    const token = await apiLogin(request, 'admin');
    const ctx: Ctx = { request, token };
    const projectId = await createProject(ctx, qa('QA-Proj'));
    regObject(`/api/projects/${projectId}/`);

    // HTML form path.
    const html = await request.post(`/finance/projects/${projectId}/budget/`, {
      data: {
        total_budget: '-1',
        material_budget: '0',
        labor_budget: '0',
        contractor_budget: '0',
        transportation_budget: '0',
        other_budget: '0',
      },
      headers: csrf(token),
    });
    // KNOWN BUG (finance_analysis §5): no form clean() → model constraint raises → 500.
    expect(html.status()).toBe(500);

    // API path (fresh project, no budget yet).
    const project2Id = await createProject(ctx, qa('QA-Proj'));
    regObject(`/api/projects/${project2Id}/`);
    const api = await request.post('/api/project-budgets/', {
      data: { project: project2Id, total_budget: '-1' },
      headers: csrf(token),
    });
    expect(api.status()).toBe(500);

    // Clean up any budget row the HTML get_or_create left behind.
    const budgets = await request.get('/api/project-budgets/');
    for (const b of await budgets.json()) {
      if (b.project === projectId) regObject(`/api/project-budgets/${b.id}/`);
    }
  });

  test('FIN-EC-08 — Negative total_investment → IntegrityError / HTTP 500 (no form/serializer validation)', async ({
    request,
  }) => {
    const token = await apiLogin(request, 'admin');
    const ctx: Ctx = { request, token };
    const projectId = await createProject(ctx, qa('QA-Proj'));
    regObject(`/api/projects/${projectId}/`);

    const html = await request.post(`/finance/projects/${projectId}/investment/`, {
      data: { total_investment: '-1', notes: '' },
      headers: csrf(token),
    });
    // KNOWN BUG (finance_analysis §5): model-only gte=0 constraint → 500.
    expect(html.status()).toBe(500);

    const project2Id = await createProject(ctx, qa('QA-Proj'));
    regObject(`/api/projects/${project2Id}/`);
    const api = await request.post('/api/project-investments/', {
      data: { project: project2Id, total_investment: '-1' },
      headers: csrf(token),
    });
    expect(api.status()).toBe(500);

    const investments = await request.get('/api/project-investments/');
    for (const i of await investments.json()) {
      if (i.project === projectId) regObject(`/api/project-investments/${i.id}/`);
    }
  });

  test('FIN-EC-09 — Budget remaining goes negative (no guard)', async ({ request }) => {
    const token = await apiLogin(request, 'admin');
    const ctx: Ctx = { request, token };
    const projectId = await createProject(ctx, qa('QA-Proj'));
    regObject(`/api/projects/${projectId}/`);

    const budgetRes = await request.post('/api/project-budgets/', {
      data: { project: projectId, total_budget: '100000.00' },
      headers: csrf(token),
    });
    expect(budgetRes.status()).toBe(201);
    const budgetId = (await budgetRes.json()).id;
    regObject(`/api/project-budgets/${budgetId}/`);

    const costId = await createCost(ctx, {
      project: projectId,
      amount: '150000.00',
      date: today(),
      status: 'paid',
    });
    regObject(`/api/project-costs/${costId}/`);
    regLedger('project_cost', 'ProjectCost', costId);

    const budgets = await request.get('/api/project-budgets/');
    const budget = (await budgets.json()).find((b: any) => b.project === projectId);
    expect(budget.remaining_budget).toBe('-50000.00');
  });

  test('FIN-EC-10 — Office delete guard exists only in the HTML view', async ({ request }) => {
    const token = await apiLogin(request, 'admin');
    const ctx: Ctx = { request, token };
    const oaName = qa('QA-HO');
    const obName = qa('QA-BR');
    const oaId = await createOffice(ctx, oaName);
    const obId = await createOffice(ctx, obName, 'branch');
    const categoryId = await createCategory(ctx, qa('QA-Rent'));
    const expenseId = await createExpense(ctx, {
      office: oaId,
      category: categoryId,
      amount: '25000.00',
      date: today(),
      status: 'paid',
    });
    regObject(`/api/offices/${oaId}/`);
    regObject(`/api/offices/${obId}/`);
    regObject(`/api/expense-categories/${categoryId}/`);
    regObject(`/api/office-expenses/${expenseId}/`);
    regLedger('office_expense', 'OfficeExpense', expenseId);

    // OA (with dependents) must be refused.
    await request.post(`/finance/offices/${oaId}/delete/`, { headers: csrf(token) });
    const oaStill = await request.get(`/api/offices/${oaId}/`);
    expect(oaStill.status()).toBe(200);

    // OB (no dependents) must be deleted.
    await request.post(`/finance/offices/${obId}/delete/`, { headers: csrf(token) });
    const obGone = await request.get(`/api/offices/${obId}/`);
    expect(obGone.status()).toBe(404);
  });

  test('FIN-EC-11 — Zero amount rejected at all layers (defense-in-depth)', async ({ request }) => {
    const token = await apiLogin(request, 'admin');
    const ctx: Ctx = { request, token };
    const officeId = await createOffice(ctx, qa('QA-HO'));
    const categoryId = await createCategory(ctx, qa('QA-Rent'));
    regObject(`/api/offices/${officeId}/`);
    regObject(`/api/expense-categories/${categoryId}/`);

    // API expense amount=0 → 400.
    const exp = await request.post('/api/office-expenses/', {
      data: { office: officeId, category: categoryId, amount: '0', expense_date: today(), status: 'pending' },
      headers: csrf(token),
    });
    expect(exp.status()).toBe(400);

    // API transaction amount=0 → 400.
    const tx = await request.post('/api/account-transactions/', {
      data: { date: today(), amount: '0', direction: 'in', transaction_type: 'income' },
      headers: csrf(token),
    });
    expect(tx.status()).toBe(400);

    // HTML expense amount=0 → re-render (200) and no row persisted.
    const html = await request.post('/finance/office-expenses/create/', {
      data: {
        office: String(officeId),
        category: String(categoryId),
        amount: '0',
        expense_date: today(),
        payment_method: 'bank_transfer',
        status: 'pending',
      },
      headers: csrf(token),
    });
    expect(html.status()).toBe(200);
    const exps = await request.get(`/api/office-expenses/?office=${officeId}`);
    expect(await exps.json()).toHaveLength(0);
  });

  test('FIN-EC-12 — Deleted category leaves expense.category=None and stale ledger category string', async ({
    request,
  }) => {
    const token = await apiLogin(request, 'admin');
    const ctx: Ctx = { request, token };
    const officeId = await createOffice(ctx, qa('QA-HO'));
    const categoryName = qa('QA-Rent');
    const categoryId = await createCategory(ctx, categoryName);
    const expenseId = await createExpense(ctx, {
      office: officeId,
      category: categoryId,
      amount: '25000.00',
      date: today(),
      status: 'paid',
    });
    regObject(`/api/offices/${officeId}/`);
    regObject(`/api/expense-categories/${categoryId}/`);
    regObject(`/api/office-expenses/${expenseId}/`);
    regLedger('office_expense', 'OfficeExpense', expenseId);

    // Delete the category (management_or_above).
    await request.post(`/finance/expense-categories/${categoryId}/delete/`, { headers: csrf(token) });

    // Expense.category is SET_NULL.
    const exp = await (await request.get(`/api/office-expenses/${expenseId}/`)).json();
    expect(exp.category).toBeNull();
    expect(exp.category_name).toBeNull();

    // KNOWN BUG / accepted: the ledger's denormalized category string is stale.
    const rows = await ledgerRowsFor(request, 'office_expense', 'OfficeExpense', expenseId);
    expect(rows.length).toBe(1);
    expect(rows[0].category).toBe(categoryName);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// FIN-EC — approval bypass (accounts UI)
// ─────────────────────────────────────────────────────────────────────────────
test.describe('FIN-EC — approval bypass (accounts)', () => {
  test.use({ storageState: 'tests/.auth/accounts.json' });

  test('FIN-EC-05 — Approval bypass: accounts user creates an already-paid office expense', async ({
    page,
    request,
  }) => {
    const token = await apiLogin(request, 'admin');
    const ctx: Ctx = { request, token };
    const officeName = qa('QA-HO');
    const categoryName = qa('QA-Rent');
    const officeId = await createOffice(ctx, officeName);
    const categoryId = await createCategory(ctx, categoryName);
    regObject(`/api/offices/${officeId}/`);
    regObject(`/api/expense-categories/${categoryId}/`);

    await uiCreateExpense(page, {
      office: officeName,
      category: categoryName,
      amount: '100000.00',
      date: today(),
      status: 'paid',
    });

    const exps = await request.get(`/api/office-expenses/?office=${officeId}`);
    const exp = (await exps.json())[0];
    expect(exp.status).toBe('paid');
    regObject(`/api/office-expenses/${exp.id}/`);
    regLedger('office_expense', 'OfficeExpense', exp.id);

    // KNOWN BUG (finance_analysis §5): a below-management finance user can post
    // money out of the ledger by setting status=paid on create — no approve gate.
    const rows = await ledgerRowsFor(request, 'office_expense', 'OfficeExpense', exp.id);
    expect(rows.length).toBe(1);
    expect(rows[0].amount).toBe('100000.00');
  });

  test('FIN-EC-06 — Approval bypass: project cost defaults to paid and posts to ledger', async ({
    page,
    request,
  }) => {
    const token = await apiLogin(request, 'admin');
    const ctx: Ctx = { request, token };
    const projectName = qa('QA-Proj');
    const projectId = await createProject(ctx, projectName);
    regObject(`/api/projects/${projectId}/`);

    await uiCreateCost(page, { project: projectName, amount: '200000.00', date: today() });

    const costs = await request.get(`/api/project-costs/?project=${projectId}`);
    const cost = (await costs.json())[0];
    expect(cost.status).toBe('paid');
    regObject(`/api/project-costs/${cost.id}/`);
    regLedger('project_cost', 'ProjectCost', cost.id);

    // KNOWN BUG (finance_analysis §5): ProjectCost defaults to paid and posts to
    // the ledger immediately — no approval path exists at all.
    const rows = await ledgerRowsFor(request, 'project_cost', 'ProjectCost', cost.id);
    expect(rows.length).toBe(1);
    expect(rows[0].amount).toBe('200000.00');
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// FIN-SEC — negative & security (API)
// ─────────────────────────────────────────────────────────────────────────────
test.describe('FIN-SEC — negative & security (API)', () => {
  test('FIN-SEC-01 — Any authenticated staff can GET the finance API (leaks amounts)', async ({
    playwright,
  }) => {
    // The correct behaviour is 403 for non-finance roles; today IsFinanceOrAbove
    // returns True for all SAFE_METHODS, so these return 200.
    for (const role of ['customer', 'sales', 'hr'] as Role[]) {
      const ctx = await playwright.request.newContext({ baseURL: 'http://127.0.0.1:8000' });
      await apiLogin(ctx, role);
      for (const path of ['/api/office-expenses/', '/api/account-transactions/']) {
        const res = await ctx.get(path);
        // CONFIRMED BUG: docs/qa/findings-confirmed.md F3
        expect(res.status(), `${role} GET ${path} should be 403`).toBe(403);
      }
      await ctx.dispose();
    }
  });

  test('FIN-SEC-02 — OfficeViewSet / admin DELETE has no guard (cascades expenses)', async ({
    request,
  }) => {
    // Fixtures as admin.
    const token = await apiLogin(request, 'admin');
    const ctx: Ctx = { request, token };
    const officeName = qa('QA-HO');
    const officeId = await createOffice(ctx, officeName);
    const categoryId = await createCategory(ctx, qa('QA-Rent'));
    const expenseId = await createExpense(ctx, {
      office: officeId,
      category: categoryId,
      amount: '25000.00',
      date: today(),
      status: 'paid',
    });
    regObject(`/api/offices/${officeId}/`);
    regObject(`/api/expense-categories/${categoryId}/`);
    regObject(`/api/office-expenses/${expenseId}/`);
    regLedger('office_expense', 'OfficeExpense', expenseId);

    // Switch to accounts (finance role, below management) and DELETE the office.
    const accountsToken = await apiLogin(request, 'accounts');
    const res = await request.delete(`/api/offices/${officeId}/`, {
      headers: csrf(accountsToken),
    });
    // CONFIRMED BUG: docs/qa/findings-confirmed.md F3 — OfficeViewSet is a plain
    // ModelViewSet with no destroy guard; correct behaviour is a refusal (400/403).
    expect([400, 403], `DELETE office with expenses should be refused, got ${res.status()}`).toContain(
      res.status(),
    );
  });

  test('FIN-SEC-03 — No status-transition guards on approve/pay (illegal draft→paid, paid→approved)', async ({
    request,
  }) => {
    const token = await apiLogin(request, 'admin');
    const ctx: Ctx = { request, token };
    const officeId = await createOffice(ctx, qa('QA-HO'));
    const categoryId = await createCategory(ctx, qa('QA-Rent'));
    const draftId = await createExpense(ctx, {
      office: officeId,
      category: categoryId,
      amount: '25000.00',
      date: today(),
      status: 'draft',
    });
    const paidId = await createExpense(ctx, {
      office: officeId,
      category: categoryId,
      amount: '30000.00',
      date: today(),
      status: 'paid',
    });
    regObject(`/api/offices/${officeId}/`);
    regObject(`/api/expense-categories/${categoryId}/`);
    regObject(`/api/office-expenses/${draftId}/`);
    regObject(`/api/office-expenses/${paidId}/`);
    regLedger('office_expense', 'OfficeExpense', draftId);
    regLedger('office_expense', 'OfficeExpense', paidId);

    // Pay may only follow approved — paying a draft must be refused.
    const payRes = await request.post(`/api/office-expenses/${draftId}/pay/`, {
      headers: csrf(token),
    });
    // CONFIRMED BUG: docs/qa/findings-confirmed.md F3 — no transition guard.
    expect(payRes.status(), `draft→paid should be refused, got ${payRes.status()}`).toBe(400);

    // Approve may only follow pending — approving a paid expense must be refused.
    const appRes = await request.post(`/api/office-expenses/${paidId}/approve/`, {
      headers: csrf(token),
    });
    // CONFIRMED BUG: docs/qa/findings-confirmed.md F3 — approve demotes a paid expense.
    expect(appRes.status(), `paid→approved should be refused, got ${appRes.status()}`).toBe(400);
  });

  test('FIN-SEC-04 — Ledger integrity gaps misstate financial reports', async ({ request }) => {
    const token = await apiLogin(request, 'admin');
    const ctx: Ctx = { request, token };
    const projectId = await createProject(ctx, qa('QA-Proj'));
    const costId = await createCost(ctx, {
      project: projectId,
      amount: '40000.00',
      date: today(),
      status: 'paid',
    });
    regObject(`/api/projects/${projectId}/`);
    regObject(`/api/project-costs/${costId}/`);
    regLedger('project_cost', 'ProjectCost', costId);

    // Reproduce an orphan: delete the paid cost via the HTML view.
    await request.post(`/finance/project-costs/${costId}/delete/`, { headers: csrf(token) });

    // KNOWN BUG (finance_analysis §5): the phantom `out` row still inflates total_out.
    const out = await request.get('/api/account-transactions/?direction=out&transaction_type=project_cost');
    const outRows = await out.json();
    const orphan = outRows.find((r: any) => r.reference_type === 'ProjectCost' && r.reference_id === costId);
    expect(orphan, 'orphaned ProjectCost ledger row should still exist').toBeTruthy();
  });

  test('FIN-SEC-05 — Non-finance staff write to finance API → 403 (control assertion)', async ({
    request,
  }) => {
    const token = await apiLogin(request, 'sales');

    const exp = await request.post('/api/office-expenses/', {
      data: { amount: '1.00', expense_date: today(), status: 'pending' },
      headers: csrf(token),
    });
    expect(exp.status()).toBe(403);

    const cost = await request.post('/api/project-costs/', {
      data: { amount: '1.00', cost_date: today(), status: 'paid' },
      headers: csrf(token),
    });
    expect(cost.status()).toBe(403);

    const del = await request.delete('/api/offices/1/', { headers: csrf(token) });
    expect(del.status()).toBe(403);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// FIN-SEC — HTML denial (sales UI)
// ─────────────────────────────────────────────────────────────────────────────
test.describe('FIN-SEC — HTML denial (sales)', () => {
  test.use({ storageState: 'tests/.auth/sales.json' });

  test('FIN-SEC-06 — Non-finance staff denied finance HTML pages (redirect to /dashboard/)', async ({
    page,
  }) => {
    for (const path of ['/finance/ledger/', '/finance/offices/', '/finance/project-costs/', '/finance/projects/']) {
      await page.goto(path);
      await expect(page, `${path} should redirect to /dashboard/`).toHaveURL(/\/dashboard\//);
    }
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// FIN-API — API contract
// ─────────────────────────────────────────────────────────────────────────────
test.describe('FIN-API — API contract', () => {
  test('FIN-API-01 — GET /api/office-expenses/ list + filters', async ({ request }) => {
    const token = await apiLogin(request, 'admin');
    const ctx: Ctx = { request, token };
    const officeName = qa('QA-HO');
    const categoryName = qa('QA-Rent');
    const officeId = await createOffice(ctx, officeName);
    const categoryId = await createCategory(ctx, categoryName);
    const pendingId = await createExpense(ctx, {
      office: officeId,
      category: categoryId,
      amount: '1000.00',
      date: today(),
      status: 'pending',
    });
    const paidId = await createExpense(ctx, {
      office: officeId,
      category: categoryId,
      amount: '2000.00',
      date: today(),
      status: 'paid',
    });
    regObject(`/api/offices/${officeId}/`);
    regObject(`/api/expense-categories/${categoryId}/`);
    regObject(`/api/office-expenses/${pendingId}/`);
    regObject(`/api/office-expenses/${paidId}/`);
    regLedger('office_expense', 'OfficeExpense', paidId);

    const all = await (await request.get('/api/office-expenses/')).json();
    const mine = all.filter((e: any) => e.office === officeId);
    expect(mine.length).toBeGreaterThanOrEqual(2);
    expect(mine[0].office_name).toBe(officeName);
    expect(mine[0].category_name).toBe(categoryName);
    expect(mine[0].status_display).toBeTruthy();
    expect(typeof mine[0].amount).toBe('string');

    const byOffice = await (await request.get(`/api/office-expenses/?office=${officeId}`)).json();
    expect(byOffice.every((e: any) => e.office === officeId)).toBe(true);

    const byStatus = await (await request.get('/api/office-expenses/?status=paid')).json();
    expect(byStatus.every((e: any) => e.status === 'paid')).toBe(true);
  });

  test('FIN-API-02 — POST /api/office-expenses/ (finance) + status=paid posts ledger', async ({
    request,
  }) => {
    const token = await apiLogin(request, 'admin');
    const ctx: Ctx = { request, token };
    const officeId = await createOffice(ctx, qa('QA-HO'));
    const categoryId = await createCategory(ctx, qa('QA-Rent'));
    regObject(`/api/offices/${officeId}/`);
    regObject(`/api/expense-categories/${categoryId}/`);

    const res = await request.post('/api/office-expenses/', {
      data: {
        office: officeId,
        category: categoryId,
        amount: '25000.00',
        expense_date: today(),
        status: 'paid',
      },
      headers: csrf(token),
    });
    expect(res.status(), await res.text()).toBe(201);
    const exp = await res.json();
    regObject(`/api/office-expenses/${exp.id}/`);
    regLedger('office_expense', 'OfficeExpense', exp.id);

    const rows = await ledgerRowsFor(request, 'office_expense', 'OfficeExpense', exp.id);
    expect(rows.length).toBe(1);
    expect(rows[0].amount).toBe('25000.00');
  });

  test('FIN-API-03 — POST /api/office-expenses/{id}/approve/', async ({ request }) => {
    const token = await apiLogin(request, 'admin');
    const ctx: Ctx = { request, token };
    const officeId = await createOffice(ctx, qa('QA-HO'));
    const categoryId = await createCategory(ctx, qa('QA-Rent'));
    const expenseId = await createExpense(ctx, {
      office: officeId,
      category: categoryId,
      amount: '25000.00',
      date: today(),
      status: 'pending',
    });
    regObject(`/api/offices/${officeId}/`);
    regObject(`/api/expense-categories/${categoryId}/`);
    regObject(`/api/office-expenses/${expenseId}/`);
    regLedger('office_expense', 'OfficeExpense', expenseId);

    const res = await request.post(`/api/office-expenses/${expenseId}/approve/`, {
      headers: csrf(token),
    });
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body.status).toBe('approved');

    // No ledger row is posted by approve alone.
    expect(await ledgerRowsFor(request, 'office_expense', 'OfficeExpense', expenseId)).toHaveLength(0);
  });

  test('FIN-API-04 — POST /api/office-expenses/{id}/pay/ (posts ledger, idempotent)', async ({
    request,
  }) => {
    const token = await apiLogin(request, 'admin');
    const ctx: Ctx = { request, token };
    const officeId = await createOffice(ctx, qa('QA-HO'));
    const categoryId = await createCategory(ctx, qa('QA-Rent'));
    const expenseId = await createExpense(ctx, {
      office: officeId,
      category: categoryId,
      amount: '25000.00',
      date: today(),
      status: 'approved',
    });
    regObject(`/api/offices/${officeId}/`);
    regObject(`/api/expense-categories/${categoryId}/`);
    regObject(`/api/office-expenses/${expenseId}/`);
    regLedger('office_expense', 'OfficeExpense', expenseId);

    const res = await request.post(`/api/office-expenses/${expenseId}/pay/`, {
      headers: csrf(token),
    });
    expect(res.status()).toBe(200);
    expect((await res.json()).status).toBe('paid');
    expect(await ledgerRowsFor(request, 'office_expense', 'OfficeExpense', expenseId)).toHaveLength(1);

    // Idempotent: a second pay still leaves exactly one row.
    await request.post(`/api/office-expenses/${expenseId}/pay/`, { headers: csrf(token) });
    expect(await ledgerRowsFor(request, 'office_expense', 'OfficeExpense', expenseId)).toHaveLength(1);
  });

  test('FIN-API-05 — GET/POST /api/project-costs/', async ({ request }) => {
    const token = await apiLogin(request, 'admin');
    const ctx: Ctx = { request, token };
    const projectId = await createProject(ctx, qa('QA-Proj'));
    regObject(`/api/projects/${projectId}/`);

    const res = await request.post('/api/project-costs/', {
      data: { project: projectId, cost_category: 'material', amount: '40000.00', cost_date: today(), status: 'paid' },
      headers: csrf(token),
    });
    expect(res.status(), await res.text()).toBe(201);
    const cost = await res.json();
    regObject(`/api/project-costs/${cost.id}/`);
    regLedger('project_cost', 'ProjectCost', cost.id);

    expect(await ledgerRowsFor(request, 'project_cost', 'ProjectCost', cost.id)).toHaveLength(1);

    const byProject = await (await request.get(`/api/project-costs/?project=${projectId}`)).json();
    expect(byProject.every((c: any) => c.project === projectId)).toBe(true);
    expect(byProject[0].project_name).toBeTruthy();
    expect(byProject[0].cost_category_display).toBeTruthy();

    const byCategory = await (await request.get('/api/project-costs/?category=material')).json();
    expect(byCategory.every((c: any) => c.cost_category === 'material')).toBe(true);
  });

  test('FIN-API-06 — GET/POST/DELETE /api/offices/', async ({ request }) => {
    const token = await apiLogin(request, 'admin');
    const ctx: Ctx = { request, token };
    const name = qa('QA-HO');

    const post = await request.post('/api/offices/', {
      data: { name, office_type: 'head_office' },
      headers: csrf(token),
    });
    expect(post.status(), await post.text()).toBe(201);
    const office = await post.json();
    regObject(`/api/offices/${office.id}/`);

    // Duplicate name → 400.
    const dup = await request.post('/api/offices/', {
      data: { name, office_type: 'branch' },
      headers: csrf(token),
    });
    expect(dup.status()).toBe(400);

    // GET list includes it.
    const all = await (await request.get('/api/offices/')).json();
    expect(all.some((o: any) => o.name === name)).toBe(true);

    // DELETE a dependent office (with an expense) — KNOWN BUG: 204 cascade.
    const categoryId = await createCategory(ctx, qa('QA-Rent'));
    regObject(`/api/expense-categories/${categoryId}/`);
    const expenseId = await createExpense(ctx, {
      office: office.id,
      category: categoryId,
      amount: '25000.00',
      date: today(),
      status: 'paid',
    });
    regObject(`/api/office-expenses/${expenseId}/`);
    regLedger('office_expense', 'OfficeExpense', expenseId);

    const del = await request.delete(`/api/offices/${office.id}/`, { headers: csrf(token) });
    // KNOWN BUG (finance_analysis §5 / F3): no dependency guard on the ViewSet.
    expect(del.status()).toBe(204);
  });

  test('FIN-API-07 — GET/POST /api/account-transactions/ (direction validation + filters)', async ({
    request,
  }) => {
    const token = await apiLogin(request, 'admin');
    const category = qa('QA-TX');

    const res = await request.post('/api/account-transactions/', {
      data: { date: today(), amount: '1000.00', direction: 'in', transaction_type: 'income', category },
      headers: csrf(token),
    });
    expect(res.status(), await res.text()).toBe(201);
    const tx = await res.json();
    regObject(`/api/account-transactions/${tx.id}/`);

    const byType = await (await request.get('/api/account-transactions/?transaction_type=income')).json();
    expect(byType.every((t: any) => t.transaction_type === 'income')).toBe(true);

    const byDirection = await (await request.get('/api/account-transactions/?direction=in')).json();
    expect(byDirection.every((t: any) => t.direction === 'in')).toBe(true);

    // Invalid direction → 400.
    const bad = await request.post('/api/account-transactions/', {
      data: { date: today(), amount: '1000.00', direction: 'sideways', transaction_type: 'income' },
      headers: csrf(token),
    });
    expect(bad.status()).toBe(400);

    // amount <= 0 → 400.
    const zero = await request.post('/api/account-transactions/', {
      data: { date: today(), amount: '0', direction: 'in', transaction_type: 'income' },
      headers: csrf(token),
    });
    expect(zero.status()).toBe(400);
  });

  test('FIN-API-08 — GET/POST /api/project-budgets/ (negative total_budget → 500)', async ({ request }) => {
    const token = await apiLogin(request, 'admin');
    const ctx: Ctx = { request, token };
    const p1 = await createProject(ctx, qa('QA-Proj'));
    const p2 = await createProject(ctx, qa('QA-Proj'));
    regObject(`/api/projects/${p1}/`);
    regObject(`/api/projects/${p2}/`);

    const get = await (await request.get('/api/project-budgets/')).json();
    if (get.length) {
      const sample = get[0];
      expect(sample).toHaveProperty('total_actual');
      expect(sample).toHaveProperty('remaining_budget');
    }

    const ok = await request.post('/api/project-budgets/', {
      data: { project: p1, total_budget: '100000.00' },
      headers: csrf(token),
    });
    expect(ok.status(), await ok.text()).toBe(201);
    regObject(`/api/project-budgets/${(await ok.json()).id}/`);

    // KNOWN BUG (finance_analysis §5): no validate_total_budget → IntegrityError → 500.
    const neg = await request.post('/api/project-budgets/', {
      data: { project: p2, total_budget: '-1' },
      headers: csrf(token),
    });
    expect(neg.status()).toBe(500);
  });

  test('FIN-API-09 — GET/POST /api/project-investments/ (negative → 500)', async ({ request }) => {
    const token = await apiLogin(request, 'admin');
    const ctx: Ctx = { request, token };
    const p1 = await createProject(ctx, qa('QA-Proj'));
    const p2 = await createProject(ctx, qa('QA-Proj'));
    regObject(`/api/projects/${p1}/`);
    regObject(`/api/projects/${p2}/`);

    const get = await request.get('/api/project-investments/');
    expect(get.status()).toBe(200);

    const ok = await request.post('/api/project-investments/', {
      data: { project: p1, total_investment: '1500000.00' },
      headers: csrf(token),
    });
    expect(ok.status(), await ok.text()).toBe(201);
    regObject(`/api/project-investments/${(await ok.json()).id}/`);

    // KNOWN BUG (finance_analysis §5): no validate_total_investment → 500.
    const neg = await request.post('/api/project-investments/', {
      data: { project: p2, total_investment: '-1' },
      headers: csrf(token),
    });
    expect(neg.status()).toBe(500);
  });
});
