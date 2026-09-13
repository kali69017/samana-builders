/**
 * Samana ERP — finance module BROWSER suite.
 *
 * Drives the finance UI (`page` + storageState) for offices, office expenses,
 * project costs, budgets, investments and the ledger, and asserts the financial
 * ledger side-effects against the DRF read endpoints with exact Decimal amounts.
 *
 * Roles: `admin` (superuser) for management-gated flows (approve/pay/delete);
 * `accounts` (finance, below management) for the approval-bypass RED test.
 *
 * CONFIRMED BUGS — written RED on purpose (assert the SECURE behaviour, which
 * currently fails):
 *   - FIN-EC-05  approval bypass via the `status` field (docs/qa/findings-confirmed.md F3)
 *   - FIN-SEC-02 OfficeViewSet DELETE has no dependency guard
 *
 * Dev server must run on http://127.0.0.1:8000 with DJANGO_DEBUG=True.
 */
import { test, expect, Page } from '@playwright/test';
import { loginViaApi } from '../helpers/auth';


// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

const qa = (prefix: string) => `${prefix}-${Date.now()}-${Math.floor(Math.random() * 1e6)}`;
const today = () => new Date().toISOString().slice(0, 10);

async function csrf(page: Page): Promise<string> {
  const cookies = await page.context().cookies();
  return cookies.find((c) => c.name === 'csrftoken')?.value ?? '';
}

// ── cleanup registry (drained in afterAll as admin) ──
const projectIds: number[] = [];
const officeIds: number[] = [];
const categoryIds: number[] = [];
const officeExpenseIds: number[] = [];
const projectCostIds: number[] = [];
const budgetIds: number[] = [];
const investmentIds: number[] = [];
const transactionIds: number[] = [];
const ledgerRefs: Array<{ type: string; id: number }> = [];

// ── fixtures (created via the authenticated API as quick setup) ──
async function createOffice(page: Page, name: string, officeType = 'head_office'): Promise<{ id: number; name: string }> {
  const res = await page.request.post('/api/offices/', {
    data: { name, office_type: officeType, address: 'QA address', is_active: true },
    headers: { 'X-CSRFToken': await csrf(page) },
  });
  expect(res.status(), await res.text()).toBe(201);
  const id = (await res.json()).id as number;
  officeIds.push(id);
  return { id, name };
}

async function createCategory(page: Page, name: string, categoryType = 'rent'): Promise<{ id: number; name: string }> {
  const res = await page.request.post('/api/expense-categories/', {
    data: { name, category_type: categoryType, is_active: true },
    headers: { 'X-CSRFToken': await csrf(page) },
  });
  expect(res.status(), await res.text()).toBe(201);
  const id = (await res.json()).id as number;
  categoryIds.push(id);
  return { id, name };
}

async function createProject(page: Page, name: string): Promise<{ id: number; name: string }> {
  const res = await page.request.post('/api/projects/', {
    data: { name, location: 'QA Location', status: 'booking_open' },
    headers: { 'X-CSRFToken': await csrf(page) },
  });
  expect(res.status(), await res.text()).toBe(201);
  const id = (await res.json()).id as number;
  projectIds.push(id);
  return { id, name };
}

async function createCost(
  page: Page,
  o: { project: number; amount: string; date: string; status?: string; costCategory?: string },
): Promise<number> {
  const res = await page.request.post('/api/project-costs/', {
    data: {
      project: o.project,
      cost_category: o.costCategory ?? 'material',
      amount: o.amount,
      cost_date: o.date,
      status: o.status ?? 'paid',
    },
    headers: { 'X-CSRFToken': await csrf(page) },
  });
  expect(res.status(), await res.text()).toBe(201);
  const id = (await res.json()).id as number;
  projectCostIds.push(id);
  ledgerRefs.push({ type: 'ProjectCost', id });
  return id;
}

// ── ledger reads (exact Decimal strings) ──
async function ledgerRowsFor(page: Page, refType: string, refId: number): Promise<any[]> {
  const rows = (await (await page.request.get('/api/account-transactions/')).json()) as any[];
  return rows.filter((r) => r.reference_type === refType && r.reference_id === refId);
}

async function firstOfficeExpense(page: Page, officeId: number): Promise<any> {
  const rows = (await (await page.request.get(`/api/office-expenses/?office=${officeId}`)).json()) as any[];
  return rows[0];
}

// ── UI flows (selects in base_form.html have unassociated labels → use name=) ──
async function uiCreateOffice(page: Page, name: string, officeType: 'head_office' | 'branch', address: string): Promise<void> {
  await page.goto('/finance/offices/create/');
  await page.getByLabel('Name').fill(name);
  await page.locator('select[name="office_type"]').selectOption(officeType);
  await page.getByLabel('Address').fill(address);
  await page.getByRole('button', { name: 'Create' }).click();
  await expect(page).toHaveURL(/\/finance\/offices\/$/);
}

async function uiCreateOfficeExpense(
  page: Page,
  o: { office: string; category: string; amount: string; date: string; status: string },
): Promise<void> {
  await page.goto('/finance/office-expenses/create/');
  // Office options render as "Name (Head Office)" (Office.__str__), so match the full label.
  await page.locator('select[name="office"]').selectOption({ label: `${o.office} (Head Office)` });
  await page.locator('select[name="category"]').selectOption({ label: o.category });
  await page.getByLabel('Amount').fill(o.amount);
  await page.getByLabel('Expense date').fill(o.date);
  await page.locator('select[name="status"]').selectOption(o.status);
  await page.getByRole('button', { name: 'Create' }).click();
  await expect(page).toHaveURL(/\/finance\/office-expenses\/$/);
}

async function uiCreateProjectCost(
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
  await expect(page).toHaveURL(/\/finance\/project-costs\/$/);
}

// ─────────────────────────────────────────────────────────────────────────────
// Cleanup (drained once after the whole file, as admin)
// ─────────────────────────────────────────────────────────────────────────────

test.afterAll(async ({ request }) => {
  await loginViaApi(request, 'admin');
  const state = await request.storageState();
  const token = state.cookies.find((c) => c.name === 'csrftoken')?.value ?? '';
  const header = { 'X-CSRFToken': token };

  // 1. Ledger rows: any matching reference, plus ad-hoc rows by id.
  const rows = (await (await request.get('/api/account-transactions/')).json()) as any[];
  for (const row of rows) {
    const matched =
      ledgerRefs.some((ref) => ref.type === row.reference_type && ref.id === row.reference_id) ||
      transactionIds.includes(row.id);
    if (matched) {
      try {
        await request.delete(`/api/account-transactions/${row.id}/`, { headers: header });
      } catch {
        /* best-effort */
      }
    }
  }

  // 2. Budgets + investments.
  for (const id of budgetIds) {
    try { await request.delete(`/api/project-budgets/${id}/`, { headers: header }); } catch { /* noop */ }
  }
  for (const id of investmentIds) {
    try { await request.delete(`/api/project-investments/${id}/`, { headers: header }); } catch { /* noop */ }
  }

  // 3. Expenses + costs.
  for (const id of officeExpenseIds) {
    try { await request.delete(`/api/office-expenses/${id}/`, { headers: header }); } catch { /* noop */ }
  }
  for (const id of projectCostIds) {
    try { await request.delete(`/api/project-costs/${id}/`, { headers: header }); } catch { /* noop */ }
  }

  // 4. Offices, categories, projects.
  for (const id of officeIds) {
    try { await request.delete(`/api/offices/${id}/`, { headers: header }); } catch { /* noop */ }
  }
  for (const id of categoryIds) {
    try { await request.delete(`/api/expense-categories/${id}/`, { headers: header }); } catch { /* noop */ }
  }
  for (const id of projectIds) {
    try { await request.delete(`/api/projects/${id}/`, { headers: header }); } catch { /* noop */ }
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// FIN-HP — happy paths (admin UI + API verification)
// ─────────────────────────────────────────────────────────────────────────────

test.describe('FIN — browser flows (admin)', () => {

  // storageState sessions can go stale mid-run; re-authenticate via the API so
  // page.request carries a fresh sessionid + csrftoken for every test.
  test.beforeEach(async ({ page }) => {
    await loginViaApi(page.request, 'admin');
  });

  test('FIN-HP-01 — create office', async ({ page }) => {
    const name = qa('QA-HO');
    await uiCreateOffice(page, name, 'head_office', 'QA Head Office address');

    await page.goto('/finance/offices/');
    await expect(page.getByText(name)).toBeVisible();

    const list = await (await page.request.get('/api/offices/')).json();
    const office = list.find((o: any) => o.name === name);
    expect(office).toBeTruthy();
    expect(office.office_type).toBe('head_office');
  });

  test('FIN-HP-02 — create office expense with status "paid" posts exactly one ledger row', async ({ page }) => {
    const office = await createOffice(page, qa('QA-HO'));
    const category = await createCategory(page, qa('QA-Rent'));

    await uiCreateOfficeExpense(page, {
      office: office.name,
      category: category.name,
      amount: '25000.00',
      date: today(),
      status: 'paid',
    });

    const exp = await firstOfficeExpense(page, office.id);
    expect(exp.status).toBe('paid');
    officeExpenseIds.push(exp.id);
    ledgerRefs.push({ type: 'OfficeExpense', id: exp.id });

    const rows = await ledgerRowsFor(page, 'OfficeExpense', exp.id);
    expect(rows).toHaveLength(1);
    expect(rows[0].amount).toBe('25000.00');
    expect(rows[0].direction).toBe('out');
    expect(rows[0].transaction_type).toBe('office_expense');
    expect(rows[0].category).toBe(category.name);
    expect(rows[0].date).toBe(today());
  });

  test('FIN-HP-03 — approve then pay office expense posts ledger exactly once', async ({ page }) => {
    const office = await createOffice(page, qa('QA-HO'));
    const category = await createCategory(page, qa('QA-Rent'));

    await uiCreateOfficeExpense(page, {
      office: office.name,
      category: category.name,
      amount: '30000.00',
      date: today(),
      status: 'pending',
    });
    const exp = await firstOfficeExpense(page, office.id);
    officeExpenseIds.push(exp.id);
    ledgerRefs.push({ type: 'OfficeExpense', id: exp.id });

    // Approve (no ledger yet).
    await page.goto('/finance/office-expenses/');
    await page.getByRole('row', { name: office.name }).getByRole('button', { name: 'Approve' }).click();
    await expect
      .poll(async () => (await (await page.request.get(`/api/office-expenses/${exp.id}/`)).json()).status)
      .toBe('approved');
    expect(await ledgerRowsFor(page, 'OfficeExpense', exp.id)).toHaveLength(0);

    // Pay (accept the confirm) → exactly one ledger row.
    await page.goto('/finance/office-expenses/');
    page.once('dialog', (d) => d.accept());
    await page.getByRole('row', { name: office.name }).getByRole('button', { name: 'Pay' }).click();
    await expect
      .poll(async () => (await (await page.request.get(`/api/office-expenses/${exp.id}/`)).json()).status)
      .toBe('paid');

    const rows = await ledgerRowsFor(page, 'OfficeExpense', exp.id);
    expect(rows).toHaveLength(1);
    expect(rows[0].amount).toBe('30000.00');
  });

  test('FIN-HP-04 — create project cost (default "paid") posts ledger immediately', async ({ page }) => {
    const project = await createProject(page, qa('QA-Proj'));

    await uiCreateProjectCost(page, { project: project.name, amount: '40000.00', date: today() });

    const costs = (await (await page.request.get(`/api/project-costs/?project=${project.id}`)).json()) as any[];
    const cost = costs[0];
    expect(cost.status).toBe('paid');
    projectCostIds.push(cost.id);
    ledgerRefs.push({ type: 'ProjectCost', id: cost.id });

    const rows = await ledgerRowsFor(page, 'ProjectCost', cost.id);
    expect(rows).toHaveLength(1);
    expect(rows[0].amount).toBe('40000.00');
    expect(rows[0].direction).toBe('out');
    expect(rows[0].transaction_type).toBe('project_cost');
  });

  test('FIN-HP-05 — project budget: remaining = total − paid costs', async ({ page }) => {
    const project = await createProject(page, qa('QA-Proj'));
    await createCost(page, { project: project.id, amount: '40000.00', date: today(), status: 'paid' });

    await page.goto(`/finance/projects/${project.id}/budget/`);
    await page.getByLabel('Total budget').fill('100000.00');
    await page.getByRole('button', { name: 'Create' }).click();
    await expect(page).toHaveURL(/\/finance\/projects\/$/);

    const budgets = (await (await page.request.get('/api/project-budgets/')).json()) as any[];
    const budget = budgets.find((b: any) => b.project === project.id);
    expect(budget).toBeTruthy();
    expect(budget.total_budget).toBe('100000.00');
    // total_actual / remaining_budget are computed ReadOnlyFields → bare numbers.
    expect(budget.total_actual).toBe(40000);
    expect(budget.remaining_budget).toBe(60000);
    budgetIds.push(budget.id);
  });

  test('FIN-HP-06 — project investment recorded and shown', async ({ page }) => {
    const project = await createProject(page, qa('QA-Proj'));

    await page.goto(`/finance/projects/${project.id}/investment/`);
    await page.getByLabel('Total investment').fill('1500000.00');
    await page.getByLabel('Notes').fill('QA investment note');
    await page.getByRole('button', { name: 'Create' }).click();
    await expect(page).toHaveURL(/\/finance\/projects\/$/);

    const investments = (await (await page.request.get('/api/project-investments/')).json()) as any[];
    const inv = investments.find((i: any) => i.project === project.id);
    expect(inv).toBeTruthy();
    expect(inv.total_investment).toBe('1500000.00');
    investmentIds.push(inv.id);

    await page.goto('/finance/projects/');
    // Tables with >5 rows auto-collapse to the first 5 (static/js/erp.js);
    // the freshly created project sorts past that cut-off, so expand first.
    await page.getByRole('button', { name: 'View More' }).click();
    await expect(page.getByText(project.name)).toBeVisible();
  });

  test('FIN-HP-07 — ledger list: totals and filters', async ({ page }) => {
    const office = await createOffice(page, qa('QA-HO'));
    const category = await createCategory(page, qa('QA-Rent'));
    const inCategory = qa('QA-IN');

    await uiCreateOfficeExpense(page, {
      office: office.name,
      category: category.name,
      amount: '25000.00',
      date: today(),
      status: 'paid',
    });
    const exp = await firstOfficeExpense(page, office.id);
    officeExpenseIds.push(exp.id);
    ledgerRefs.push({ type: 'OfficeExpense', id: exp.id });

    // Ad-hoc money-in row so the ledger has both directions.
    const inRes = await page.request.post('/api/account-transactions/', {
      data: { date: today(), amount: '1000.00', direction: 'in', transaction_type: 'income', category: inCategory, reference_type: '' },
      headers: { 'X-CSRFToken': await csrf(page) },
    });
    expect(inRes.status(), await inRes.text()).toBe(201);
    transactionIds.push((await inRes.json()).id);

    await page.goto('/finance/ledger/');
    await expect(page.getByRole('heading', { name: 'Financial Ledger' })).toBeVisible();
    await expect(page.getByText(category.name)).toBeVisible();
    await expect(page.getByText(inCategory)).toBeVisible();

    await page.goto('/finance/ledger/?type=office_expense');
    await expect(page.getByText(category.name)).toBeVisible();
    await expect(page.getByText(inCategory)).toHaveCount(0);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// FIN-EC — edge cases
// ─────────────────────────────────────────────────────────────────────────────

test.describe('FIN — edge cases (browser)', () => {

  test.beforeEach(async ({ page }) => {
    await loginViaApi(page.request, 'admin');
  });

  test('FIN-EC-11 — zero / negative amount rejected', async ({ page }) => {
    const office = await createOffice(page, qa('QA-HO'));
    const category = await createCategory(page, qa('QA-Rent'));

    for (const amount of ['0', '-1']) {
      await page.goto('/finance/office-expenses/create/');
      await page.locator('select[name="office"]').selectOption({ label: `${office.name} (Head Office)` });
      await page.locator('select[name="category"]').selectOption({ label: category.name });
      await page.getByLabel('Amount').fill(amount);
      await page.getByLabel('Expense date').fill(today());
      await page.getByRole('button', { name: 'Create' }).click();

      // clean_amount raises, form re-renders, no row persisted.
      await expect(page).toHaveURL(/\/finance\/office-expenses\/create\/$/);
      await expect(page.getByText('Amount must be greater than 0')).toBeVisible();
    }

    const rows = await (await page.request.get(`/api/office-expenses/?office=${office.id}`)).json();
    expect(rows).toHaveLength(0);
  });

  test('FIN-API-04 — ledger idempotency: repeated pay keeps exactly one row', async ({ page }) => {
    const office = await createOffice(page, qa('QA-HO'));
    const category = await createCategory(page, qa('QA-Rent'));

    await uiCreateOfficeExpense(page, {
      office: office.name,
      category: category.name,
      amount: '27000.00',
      date: today(),
      status: 'paid', // posts one ledger row on create
    });
    const exp = await firstOfficeExpense(page, office.id);
    officeExpenseIds.push(exp.id);
    ledgerRefs.push({ type: 'OfficeExpense', id: exp.id });

    expect(await ledgerRowsFor(page, 'OfficeExpense', exp.id)).toHaveLength(1);

    // Re-pay twice: update_or_create must never duplicate the ledger row.
    const header = { 'X-CSRFToken': await csrf(page) };
    await page.request.post(`/api/office-expenses/${exp.id}/pay/`, { headers: header });
    await page.request.post(`/api/office-expenses/${exp.id}/pay/`, { headers: header });

    const rows = await ledgerRowsFor(page, 'OfficeExpense', exp.id);
    expect(rows).toHaveLength(1);
    expect(rows[0].amount).toBe('27000.00');
  });

  test('FIN-SEC-02 — office delete guard (RED)', async ({ page }) => {
    const office = await createOffice(page, qa('QA-HO'));
    const category = await createCategory(page, qa('QA-Rent'));

    // A paid expense gives the office both an expense and a ledger transaction,
    // so the HTML delete view would (correctly) refuse.
    await uiCreateOfficeExpense(page, {
      office: office.name,
      category: category.name,
      amount: '25000.00',
      date: today(),
      status: 'paid',
    });
    const exp = await firstOfficeExpense(page, office.id);
    officeExpenseIds.push(exp.id);
    ledgerRefs.push({ type: 'OfficeExpense', id: exp.id });

    // The ViewSet has no dependency guard, so DELETE cascades the office and its
    // expense away instead of being refused.
    const del = await page.request.delete(`/api/offices/${office.id}/`, {
      headers: { 'X-CSRFToken': await csrf(page) },
    });

    // CONFIRMED BUG: OfficeViewSet DELETE has no dependency guard — an office
    // that still owns expenses/ledger rows must NOT be deletable (400/403).
    expect([400, 403], `DELETE office with expenses should be refused, got ${del.status()}`).toContain(
      del.status(),
    );
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// FIN-EC — approval bypass (accounts, RED)
// ─────────────────────────────────────────────────────────────────────────────

test.describe('FIN — approval bypass (accounts, RED)', () => {

  test.beforeEach(async ({ page }) => {
    await loginViaApi(page.request, 'accounts');
  });

  test('FIN-EC-05 — approval bypass via status field (RED)', async ({ page }) => {
    const office = await createOffice(page, qa('QA-HO'));
    const category = await createCategory(page, qa('QA-Rent'));

    await uiCreateOfficeExpense(page, {
      office: office.name,
      category: category.name,
      amount: '100000.00',
      date: today(),
      status: 'paid',
    });
    const exp = await firstOfficeExpense(page, office.id);
    expect(exp.status).toBe('paid');
    officeExpenseIds.push(exp.id);
    ledgerRefs.push({ type: 'OfficeExpense', id: exp.id });

    // CONFIRMED BUG: docs/qa/findings-confirmed.md F3 — a below-management
    // finance user can post money out of the ledger by setting status=paid on
    // create, with no approve/pay gate. Correct behaviour: no ledger row.
    expect(await ledgerRowsFor(page, 'OfficeExpense', exp.id)).toHaveLength(0);
  });
});
