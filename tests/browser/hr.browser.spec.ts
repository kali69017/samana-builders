import { test, expect, APIRequestContext, Page, Browser } from '@playwright/test';
import { loginViaApi } from '../helpers/auth';

/**
 * Samana ERP — HR module, BROWSER-driven suite.
 *
 * Contract source: `specs/hr.md` (scenario IDs are the test names).
 * Confirmed bugs: `docs/qa/findings-confirmed.md` (F3 systemic API read-open, F8 HR
 * read-open + LeaveSerializer.status writable).
 *
 * Every HP/EC test drives the real UI with `page` (storageState `hr`) — forms are
 * filled, buttons clicked, redirects asserted — and then verifies money/ledger state
 * through the DRF API (`request`). The employee self-service flows use a fresh
 * `browser` context logged in as a per-test `staff` user (created via the
 * `/hr/employee-profile/` form).
 *
 * Selects are targeted by `name=` because `base_form.html` renders a bare <label>
 * with no `for` for `<select>`/`<input type=date>` fields, so no role/label locator
 * can reach them (the only reliable handle is the field `name`).
 *
 * Cleanup: `cleanup()` re-logs as `admin` and deletes this test's fixtures in
 * dependency order. Confirmed-bug (RED) tests assert the *correct* behaviour, so they
 * fail before reaching cleanup — those fixtures leak into the shared dev DB by design.
 */

const uniq = (p = '') => `${p}${Date.now()}${Math.floor(Math.random() * 1e6)}`;

// ── helpers ─────────────────────────────────────────────────────────────────

async function createMasterData(request: APIRequestContext, token: string, s: string) {
  const dept = await request.post('/api/departments/', { headers: { 'X-CSRFToken': token }, data: { name: `QA Dept ${s}` } });
  const desig = await request.post('/api/designations/', { headers: { 'X-CSRFToken': token }, data: { title: `QA Desig ${s}` } });
  const basic = await request.post('/api/salary-components/', { headers: { 'X-CSRFToken': token }, data: { name: `Basic Salary ${s}`, component_type: 'earning' } });
  const tax = await request.post('/api/salary-components/', { headers: { 'X-CSRFToken': token }, data: { name: `Income Tax ${s}`, component_type: 'deduction' } });
  const allowance = await request.post('/api/salary-components/', { headers: { 'X-CSRFToken': token }, data: { name: `Allowance ${s}`, component_type: 'earning' } });
  for (const r of [dept, desig, basic, tax, allowance]) {
    if (r.status() !== 201) throw new Error(`master data failed: ${r.status()} ${await r.text()}`);
  }
  return {
    deptId: (await dept.json()).id as number,
    desigId: (await desig.json()).id as number,
    basicId: (await basic.json()).id as number,
    taxId: (await tax.json()).id as number,
    allowanceId: (await allowance.json()).id as number,
  };
}

interface EmployeeOpts {
  first: string;
  last: string;
  department?: number | null;
  designation?: number | null;
  joining_date?: string;
  cnic?: string;
  phone?: string;
  email?: string;
  address?: string;
  status?: string;
}

async function createEmployee(request: APIRequestContext, token: string, opts: EmployeeOpts): Promise<any> {
  const res = await request.post('/api/employees/', {
    headers: { 'X-CSRFToken': token },
    data: {
      first_name: opts.first,
      last_name: opts.last,
      department: opts.department ?? null,
      designation: opts.designation ?? null,
      joining_date: opts.joining_date ?? '2026-01-01',
      cnic: opts.cnic ?? '',
      phone: opts.phone ?? '',
      email: opts.email ?? '',
      address: opts.address ?? '',
      status: opts.status ?? 'active',
    },
  });
  if (res.status() !== 201) throw new Error(`createEmployee failed: ${res.status()} ${await res.text()}`);
  return await res.json();
}

async function addSalary(request: APIRequestContext, token: string, employeeId: number, componentId: number, amount: number): Promise<any> {
  const res = await request.post('/api/employee-salaries/', {
    headers: { 'X-CSRFToken': token },
    data: { employee: employeeId, component: componentId, amount: String(amount) },
  });
  if (res.status() !== 201) throw new Error(`addSalary failed: ${res.status()} ${await res.text()}`);
  return await res.json();
}

/** Fresh globally-unique payroll period (PayrollRun is unique on month+year). */
const freshPeriod = () => ({ month: Math.floor(Math.random() * 12) + 1, year: 2300 + Math.floor(Math.random() * 700) });

async function del(request: APIRequestContext, token: string, url: string) {
  try {
    await request.delete(url, { headers: { 'X-CSRFToken': token } });
  } catch {
    /* ignore */
  }
}

async function getRunPaymentIds(request: APIRequestContext, runId: number): Promise<number[]> {
  const slips = (await (await request.get('/api/salary-slips/')).json()) as any[];
  const slipIds = slips.filter((x) => x.run === runId).map((x) => x.id);
  const payments = (await (await request.get('/api/salary-payments/')).json()) as any[];
  return payments.filter((p) => slipIds.includes(p.slip)).map((p) => p.id);
}

async function deleteLedgerForPayments(request: APIRequestContext, token: string, paymentIds: number[]) {
  if (!paymentIds.length) return;
  const rows = (await (await request.get('/api/account-transactions/?transaction_type=payroll')).json()) as any[];
  for (const row of rows) {
    if (row.reference_type === 'SalaryPayment' && paymentIds.includes(row.reference_id)) {
      await del(request, token, `/api/account-transactions/${row.id}/`);
    }
  }
}

interface CleanupOpts {
  runIds?: number[];
  employeeIds?: number[];
  leaveIds?: number[];
  attendanceIds?: number[];
  componentIds?: number[];
  departmentIds?: number[];
  designationIds?: number[];
}

/** Re-log as admin and delete this test's fixtures in dependency order. */
async function cleanup(request: APIRequestContext, opts: CleanupOpts) {
  const token = await loginViaApi(request, 'admin');
  for (const id of opts.runIds ?? []) {
    try {
      const paymentIds = await getRunPaymentIds(request, id);
      await deleteLedgerForPayments(request, token, paymentIds);
    } catch {
      /* ignore */
    }
  }
  for (const id of opts.leaveIds ?? []) await del(request, token, `/api/leaves/${id}/`);
  for (const id of opts.attendanceIds ?? []) await del(request, token, `/api/attendance/${id}/`);
  for (const id of opts.runIds ?? []) await del(request, token, `/api/payroll-runs/${id}/`);
  for (const id of opts.employeeIds ?? []) await del(request, token, `/api/employees/${id}/`);
  for (const id of opts.componentIds ?? []) await del(request, token, `/api/salary-components/${id}/`);
  for (const id of opts.departmentIds ?? []) await del(request, token, `/api/departments/${id}/`);
  for (const id of opts.designationIds ?? []) await del(request, token, `/api/designations/${id}/`);
}

/** Create an ERP login (role `staff`) linked to an existing employee. */
async function createStaffLogin(request: APIRequestContext, hrToken: string, employeeId: number, username: string, password: string) {
  await request.post('/hr/employee-profile/', {
    headers: { 'X-CSRFToken': hrToken },
    form: {
      employee: String(employeeId),
      username,
      email: `${username}@example.com`,
      password,
      confirm_password: password,
    },
  });
}

/** Log in as a staff employee through the rendered login form in a fresh context. */
async function loginStaffUi(browser: Browser, username: string, password: string): Promise<Page> {
  const ctx = await browser.newContext({ baseURL: 'http://127.0.0.1:8000' });
  const page = await ctx.newPage();
  await page.goto('/login/');
  await page.getByRole('textbox', { name: 'Username' }).fill(username);
  await page.getByRole('textbox', { name: 'Password' }).fill(password);
  await page.getByRole('button', { name: 'Sign In' }).click();
  await expect(page).toHaveURL('/hr/my-leave/');
  return page;
}

// ── Happy Path — Forms ──────────────────────────────────────────────────────

test.describe('HR — Happy Path — Forms (HP)', () => {
  test.beforeEach(async ({ page }) => { await loginViaApi(page.request, 'hr'); });

  test('HR-HP-01 — Create employee: EMP-xxxxx auto-ID and monthly_gross from salary components', async ({ request, page }) => {
    await loginViaApi(request, 'hr');
    const s = uniq();
    const deptName = `QA Dept ${s}`;
    const desigTitle = `QA Desig ${s}`;
    const basicName = `Basic Salary ${s}`;
    const taxName = `Income Tax ${s}`;

    // Department form (UI).
    await page.goto('/hr/departments/create/');
    await page.getByLabel('Name').fill(deptName);
    await page.getByRole('button', { name: 'Create' }).click();
    await expect(page).toHaveURL(/\/hr\/departments\/$/);
    // The departments table collapses rows past the 5th ("View More" toggle), so a
    // freshly-created department can land in a hidden row. Assert presence in the DOM.
    await expect(page.getByText(deptName)).toBeAttached();

    // Designation form (UI).
    await page.goto('/hr/designations/create/');
    await page.getByLabel('Title').fill(desigTitle);
    await page.getByRole('button', { name: 'Create' }).click();
    await expect(page).toHaveURL(/\/hr\/designations\/$/);

    // Salary component forms (UI): earning + deduction.
    await page.goto('/hr/salary-components/create/');
    await page.getByLabel('Name').fill(basicName);
    await page.locator('select[name="component_type"]').selectOption('earning');
    await page.getByRole('button', { name: 'Create' }).click();
    await expect(page).toHaveURL(/\/hr\/salary-components\/$/);

    await page.goto('/hr/salary-components/create/');
    await page.getByLabel('Name').fill(taxName);
    await page.locator('select[name="component_type"]').selectOption('deduction');
    await page.getByRole('button', { name: 'Create' }).click();
    await expect(page).toHaveURL(/\/hr\/salary-components\/$/);

    // Resolve the created records' ids via API for the selects below.
    const deptId = ((await (await request.get('/api/departments/')).json()) as any[]).find((d) => d.name === deptName).id as number;
    const desigId = ((await (await request.get('/api/designations/')).json()) as any[]).find((d) => d.title === desigTitle).id as number;
    const comps = (await (await request.get('/api/salary-components/')).json()) as any[];
    const basicId = comps.find((c) => c.name === basicName).id as number;
    const taxId = comps.find((c) => c.name === taxName).id as number;

    // Employee form (UI).
    const last = `Emp${s}`;
    await page.goto('/hr/employees/create/');
    await page.getByLabel('First name').fill('QA');
    await page.getByLabel('Last name').fill(last);
    await page.locator('select[name="department"]').selectOption(String(deptId));
    await page.locator('select[name="designation"]').selectOption(String(desigId));
    await page.getByLabel('Joining date').fill('2026-01-01');
    await page.getByLabel('Cnic').fill('3740502357224');
    await page.getByRole('button', { name: 'Create' }).click();
    await expect(page).toHaveURL(/\/hr\/employees\/\d+\/$/);
    const empPk = Number(page.url().split('/').filter(Boolean).pop());

    // Canonical dashed CNIC is stored/displayed.
    await expect(page.getByText('37405-0235722-4').first()).toBeVisible();

    // Add salary components via the salary form (UI): earning + deduction.
    await page.goto(`/hr/employees/${empPk}/salary/add/`);
    await page.locator('select[name="component"]').selectOption(String(basicId));
    await page.getByLabel('Amount').fill('50000');
    await page.getByRole('button', { name: 'Create' }).click();
    await expect(page).toHaveURL(new RegExp(`/hr/employees/${empPk}/$`));

    await page.goto(`/hr/employees/${empPk}/salary/add/`);
    await page.locator('select[name="component"]').selectOption(String(taxId));
    await page.getByLabel('Amount').fill('2000');
    await page.getByRole('button', { name: 'Create' }).click();
    await expect(page).toHaveURL(new RegExp(`/hr/employees/${empPk}/$`));

    // monthly_gross = sum of earning components only (50000, not 52000 or 48000).
    await expect(page.getByText('Rs. 50000').first()).toBeVisible();

    // Verify via API (exact money + auto EMP id + canonical CNIC).
    const emps = (await (await request.get(`/api/employees/?search=${last}`)).json()) as any[];
    const emp = emps.find((e) => e.id === empPk);
    expect(emp.employee_id).toMatch(/^EMP-\d{5}$/);
    expect(emp.cnic).toBe('37405-0235722-4');
    expect(emp.salaries.find((x: any) => x.component_name === basicName).amount).toBe('50000.00');
    expect(emp.salaries.find((x: any) => x.component_name === taxName).amount).toBe('2000.00');
    const gross = emp.salaries
      .filter((x: any) => x.component_type === 'earning')
      .reduce((acc: number, x: any) => acc + Number(x.amount), 0);
    expect(gross).toBe(50000);

    await cleanup(request, {
      employeeIds: [empPk],
      componentIds: [basicId, taxId],
      departmentIds: [deptId],
      designationIds: [desigId],
    });
  });
});

// ── Happy Path — Interactive ────────────────────────────────────────────────

test.describe('HR — Happy Path — Interactive (HP)', () => {
  test.beforeEach(async ({ page }) => { await loginViaApi(page.request, 'hr'); });

  test('HR-HP-02 — Payroll run generate → process → pay posts the ledger exactly once', async ({ request, page }) => {
    const token = await loginViaApi(request, 'hr');
    const s = uniq();
    const md = await createMasterData(request, token, s);
    const a = await createEmployee(request, token, { first: 'QA', last: `Pay${s}`, department: md.deptId, designation: md.desigId });
    await addSalary(request, token, a.id, md.basicId, 50000);

    const { month, year } = freshPeriod();

    await page.goto('/hr/payroll/create/');
    await page.locator('select[name="month"]').selectOption(String(month));
    await page.getByLabel('Year').fill(String(year));
    await page.getByRole('button', { name: 'Create' }).click();
    await expect(page).toHaveURL(/\/hr\/payroll\/\d+\/$/);
    const runId = Number(page.url().split('/').filter(Boolean).pop());

    await page.getByRole('button', { name: 'Generate Slips' }).click();
    await expect(page.getByRole('button', { name: 'Process & Approve' })).toBeVisible();

    await page.getByRole('button', { name: 'Process & Approve' }).click();
    await expect(page.getByRole('button', { name: 'Mark Paid' })).toBeVisible();

    page.once('dialog', (d) => d.accept());
    await page.getByRole('button', { name: 'Mark Paid' }).click();
    await expect(page).toHaveURL(/\/hr\/payroll\/\d+\/$/);

    // Slip paid, exactly one payment, exactly one ledger row.
    const slips = (await (await request.get('/api/salary-slips/')).json()) as any[];
    const aSlip = slips.find((x) => x.run === runId && x.employee === a.id);
    expect(aSlip.status).toBe('paid');

    const payments = (await (await request.get('/api/salary-payments/')).json()) as any[];
    const aPayment = payments.find((p) => p.slip === aSlip.id);
    expect(aPayment.amount).toBe('50000.00');

    const txs = (await (await request.get('/api/account-transactions/?transaction_type=payroll')).json()) as any[];
    const matches = txs.filter((t) => t.reference_type === 'SalaryPayment' && t.reference_id === aPayment.id);
    expect(matches).toHaveLength(1);
    expect(matches[0].amount).toBe('50000.00');
    expect(matches[0].direction).toBe('out');
    expect(matches[0].category).toBe('Salary');

    const run = (await (await request.get(`/api/payroll-runs/${runId}/`)).json()) as any;
    expect(run.status).toBe('paid');

    await cleanup(request, {
      runIds: [runId],
      employeeIds: [a.id],
      componentIds: [md.basicId, md.taxId, md.allowanceId],
      departmentIds: [md.deptId],
      designationIds: [md.desigId],
    });
  });

  test('HR-HP-03 — Salary slip recalculation recomputes gross/net from items', async ({ request, page }) => {
    const token = await loginViaApi(request, 'hr');
    const s = uniq();
    const md = await createMasterData(request, token, s);
    const a = await createEmployee(request, token, { first: 'QA', last: `Recalc${s}`, department: md.deptId, designation: md.desigId });
    await addSalary(request, token, a.id, md.basicId, 50000);
    await addSalary(request, token, a.id, md.taxId, 5000);

    const { month, year } = freshPeriod();

    await page.goto('/hr/payroll/create/');
    await page.locator('select[name="month"]').selectOption(String(month));
    await page.getByLabel('Year').fill(String(year));
    await page.getByRole('button', { name: 'Create' }).click();
    await expect(page).toHaveURL(/\/hr\/payroll\/\d+\/$/);
    const runId = Number(page.url().split('/').filter(Boolean).pop());

    await page.getByRole('button', { name: 'Generate Slips' }).click();
    await expect(page.getByRole('button', { name: 'Process & Approve' })).toBeVisible();

    // Open A's slip from the run detail table.
    await page.getByRole('row', { name: new RegExp(a.full_name) }).getByRole('link', { name: 'View' }).click();
    await expect(page).toHaveURL(/\/hr\/slips\/\d+\/$/);
    const slipId = Number(page.url().split('/').filter(Boolean).pop());

    // Add earning item "Allowance" 10000 via the slip add-item form (UI).
    await page.locator('select[name="component"]').selectOption(String(md.allowanceId));
    await page.getByPlaceholder('Amount').fill('10000');
    await page.getByRole('button', { name: 'Add / Update' }).click();
    await expect(page).toHaveURL(new RegExp(`/hr/slips/${slipId}/$`));

    // Recalc: gross=total_earnings=60000, deductions=5000, net=55000.
    const slip = (await (await request.get(`/api/salary-slips/${slipId}/`)).json()) as any;
    expect(slip.gross).toBe('60000.00');
    expect(slip.total_earnings).toBe('60000.00');
    expect(slip.total_deductions).toBe('5000.00');
    expect(slip.net).toBe('55000.00');

    await cleanup(request, {
      runIds: [runId],
      employeeIds: [a.id],
      componentIds: [md.basicId, md.taxId, md.allowanceId],
      departmentIds: [md.deptId],
      designationIds: [md.desigId],
    });
  });

  test('HR-HP-04 — Bulk attendance mark updates, never duplicates, per employee+date', async ({ request, page }) => {
    const token = await loginViaApi(request, 'hr');
    const s = uniq();
    const md = await createMasterData(request, token, s);
    const a = await createEmployee(request, token, { first: 'QA', last: `AttA${s}`, department: md.deptId, designation: md.desigId, status: 'active' });
    const d = await createEmployee(request, token, { first: 'QA', last: `AttD${s}`, department: md.deptId, designation: md.desigId, status: 'on_leave' });

    const attDate = '2020-01-15'; // far-past date to avoid touching today's real data

    // Step 1: A absent, D left at default (server coerces on_leave → leave).
    await page.goto('/hr/attendance/create/');
    await page.getByLabel('Attendance Date').fill(attDate);
    await page.locator(`select[name="status_${a.id}"]`).selectOption('absent');
    await page.getByRole('button', { name: 'Mark Attendance' }).click();
    await expect(page).toHaveURL(/\/hr\/attendance\/$/);

    // Step 2: re-mark the same date with A present (updates, no duplicate).
    await page.goto('/hr/attendance/create/');
    await page.getByLabel('Attendance Date').fill(attDate);
    await page.locator(`select[name="status_${a.id}"]`).selectOption('present');
    await page.getByRole('button', { name: 'Mark Attendance' }).click();
    await expect(page).toHaveURL(/\/hr\/attendance\/$/);

    const aRecs = (await (await request.get(`/api/attendance/?employee=${a.id}&date=${attDate}`)).json()) as any[];
    const dRecs = (await (await request.get(`/api/attendance/?employee=${d.id}&date=${attDate}`)).json()) as any[];
    expect(aRecs).toHaveLength(1);
    expect(aRecs[0].status).toBe('present');
    expect(dRecs).toHaveLength(1);
    expect(dRecs[0].status).toBe('leave');

    // Attendance list filter by date (UI).
    await page.goto('/hr/attendance/');
    await page.locator('input[name="date"]').fill(attDate);
    await page.getByRole('button', { name: 'View' }).click();
    await expect(page).toHaveURL(/date=2020-01-15/);
    await expect(page.getByText(a.full_name)).toBeVisible();
    await expect(page.getByText(d.full_name)).toBeVisible();

    await cleanup(request, {
      employeeIds: [a.id, d.id],
      componentIds: [md.basicId, md.taxId, md.allowanceId],
      departmentIds: [md.deptId],
      designationIds: [md.desigId],
    });
  });

  test('HR-HP-05 — Leave apply then approve (with approved_by stamp)', async ({ request, page, browser }) => {
    // Stay logged in as `hr` throughout: logging in as a different user (admin)
    // rotates the shared session and invalidates the storageState the `page` uses.
    const hrToken = await loginViaApi(request, 'hr');
    const s = uniq();
    const md = await createMasterData(request, hrToken, s);
    const f = await createEmployee(request, hrToken, { first: 'QA', last: `LeaveF${s}`, department: md.deptId, designation: md.desigId });

    // Create a staff login linked to F (EmployeeProfileForm.save()).
    const staffUsername = `staff${s}`;
    const staffPassword = 'admin123';
    await createStaffLogin(request, hrToken, f.id, staffUsername, staffPassword);

    // F applies via the self-service UI.
    const fpage = await loginStaffUi(browser, staffUsername, staffPassword);
    await fpage.goto('/hr/my-leave/apply/');
    await fpage.getByLabel('Days').fill('3');
    await fpage.getByLabel('Leave Type').selectOption('annual');
    await fpage.getByLabel('Start date').fill('2026-02-01');
    await fpage.getByLabel('End date').fill('2026-02-03');
    await fpage.getByLabel('Reason').fill('Annual leave QA');
    await fpage.getByRole('button', { name: 'Create' }).click();
    await expect(fpage).toHaveURL('/hr/my-leave/');
    await fpage.context().close();

    // hr approves via the leaves list UI.
    await page.goto('/hr/leaves/');
    await page.getByRole('row', { name: new RegExp(f.full_name) }).getByRole('button', { name: 'Approve' }).click();
    await expect(page).toHaveURL(/\/hr\/leaves\/$/);

    // The leave is bound to F and approved_by is stamped with the hr user.
    const hrUserId = (await (await request.get('/api/auth/me/')).json()).id;
    const leaves = (await (await request.get('/api/leaves/')).json()) as any[];
    const leave = leaves.find((l) => l.employee === f.id);
    expect(leave.status).toBe('approved');
    expect(leave.approved_by).toBe(hrUserId);

    await cleanup(request, {
      employeeIds: [f.id],
      componentIds: [md.basicId, md.taxId, md.allowanceId],
      departmentIds: [md.deptId],
      designationIds: [md.desigId],
    });
  });

  test('HR-HP-06 — Employee self-service portal hides admin nav and scopes data to self', async ({ request, browser }) => {
    // Stay logged in as `hr` throughout so the shared storage-state session is not
    // rotated by a different-user login (which would de-authenticate later tests).
    const hrToken = await loginViaApi(request, 'hr');
    const s = uniq();
    const md = await createMasterData(request, hrToken, s);
    const f = await createEmployee(request, hrToken, { first: 'QA', last: `SelfF${s}`, department: md.deptId, designation: md.desigId });
    const other = await createEmployee(request, hrToken, { first: 'QA', last: `SelfOther${s}`, department: md.deptId, designation: md.desigId });

    // Give the unrelated employee a leave so we can confirm F never sees it.
    await request.post('/api/leaves/', {
      headers: { 'X-CSRFToken': hrToken },
      data: { employee: other.id, leave_type: 'annual', start_date: '2026-03-01', end_date: '2026-03-02', days: 2, reason: 'other employee leave' },
    });

    const staffUsername = `staff${s}`;
    const staffPassword = 'admin123';
    await createStaffLogin(request, hrToken, f.id, staffUsername, staffPassword);

    const fpage = await loginStaffUi(browser, staffUsername, staffPassword);

    // Admin/HR nav is hidden for an employee; only "My Leave" is shown.
    // `exact: true` so "Leave" does not substring-match the "My Leave" link.
    for (const name of ['Employees', 'Payroll', 'Departments', 'Designations', 'Salary Components', 'Attendance', 'HR Overview', 'Leave']) {
      await expect(fpage.getByRole('link', { name, exact: true })).toHaveCount(0);
    }
    await expect(fpage.getByRole('link', { name: 'My Leave', exact: true })).toBeVisible();

    // My Leave lists only F's own (empty) requests — never another employee's.
    await expect(fpage.getByText(other.full_name)).toHaveCount(0);
    await expect(fpage.getByText('No Leave Requests')).toBeVisible();
    await fpage.context().close();

    await cleanup(request, {
      employeeIds: [f.id, other.id],
      componentIds: [md.basicId, md.taxId, md.allowanceId],
      departmentIds: [md.deptId],
      designationIds: [md.desigId],
    });
  });
});

// ── Edge Cases ──────────────────────────────────────────────────────────────

test.describe('HR — Edge Cases (EC)', () => {
  test.beforeEach(async ({ page }) => { await loginViaApi(page.request, 'hr'); });

  test('HR-EC-01 — Zero- or negative-net slip breaks the whole pay run (rollback → 500)', async ({ request, page }) => {
    const token = await loginViaApi(request, 'hr');
    const s = uniq();
    const md = await createMasterData(request, token, s);
    const a = await createEmployee(request, token, { first: 'QA', last: `Ec1A${s}`, department: md.deptId, designation: md.desigId });
    await addSalary(request, token, a.id, md.basicId, 50000);
    const b = await createEmployee(request, token, { first: 'QA', last: `Ec1B${s}`, department: md.deptId, designation: md.desigId }); // no components → net 0
    const c = await createEmployee(request, token, { first: 'QA', last: `Ec1C${s}`, department: md.deptId, designation: md.desigId });
    await addSalary(request, token, c.id, md.basicId, 50000);
    await addSalary(request, token, c.id, md.taxId, 60000); // net −10000

    const { month, year } = freshPeriod();

    await page.goto('/hr/payroll/create/');
    await page.locator('select[name="month"]').selectOption(String(month));
    await page.getByLabel('Year').fill(String(year));
    await page.getByRole('button', { name: 'Create' }).click();
    await expect(page).toHaveURL(/\/hr\/payroll\/\d+\/$/);
    const runId = Number(page.url().split('/').filter(Boolean).pop());

    await page.getByRole('button', { name: 'Generate Slips' }).click();
    await expect(page.getByRole('button', { name: 'Process & Approve' })).toBeVisible();
    await page.getByRole('button', { name: 'Process & Approve' }).click();
    await expect(page.getByRole('button', { name: 'Mark Paid' })).toBeVisible();

    page.once('dialog', (d) => d.accept());
    const payResponse = page.waitForResponse((r) => r.url().includes(`/payroll/${runId}/pay/`), { timeout: 15000 }).catch(() => null);
    await page.getByRole('button', { name: 'Mark Paid' }).click();
    const resp = await payResponse;

    // CONFIRMED BUG: see specs/hr.md HR-EC-01 — a zero/negative-net slip writes a
    // non-positive ledger row, 500s, and rolls back the whole pay run.
    // CORRECT: the zero/negative-net slip is skipped and pay succeeds (HTTP 200).
    try {
      expect(resp?.status()).toBe(200);

      // CORRECT: A's valid payment is not rolled back.
      const payments = (await (await request.get('/api/salary-payments/')).json()) as any[];
      const aPayment = payments.find((p) => p.employee_name === a.full_name);
      expect(aPayment).toBeTruthy();
      expect(aPayment.amount).toBe('50000.00');
    } finally {
      await cleanup(request, {
        runIds: [runId],
        employeeIds: [a.id, b.id, c.id],
        componentIds: [md.basicId, md.taxId, md.allowanceId],
        departmentIds: [md.deptId],
        designationIds: [md.desigId],
      });
    }
  });

  test('HR-EC-02 — Duplicate payroll month via API returns 500', async ({ request, page }) => {
    const token = await loginViaApi(request, 'hr');
    const { month, year } = freshPeriod();

    // Create the run via the UI.
    await page.goto('/hr/payroll/create/');
    await page.locator('select[name="month"]').selectOption(String(month));
    await page.getByLabel('Year').fill(String(year));
    await page.getByRole('button', { name: 'Create' }).click();
    await expect(page).toHaveURL(/\/hr\/payroll\/\d+\/$/);
    const runId = Number(page.url().split('/').filter(Boolean).pop());

    // Duplicate (month, year) via API.
    const dup = await request.post('/api/payroll-runs/', { headers: { 'X-CSRFToken': token }, data: { month, year } });
    // CORRECT: uniqueness validation error (400), not a 500.
    expect(dup.status()).toBe(400);

    await cleanup(request, { runIds: [runId] });
  });

  test('HR-EC-03 — Leave over-allowance is accepted (no balance enforcement)', async ({ request, page }) => {
    const token = await loginViaApi(request, 'hr');
    const s = uniq();
    const md = await createMasterData(request, token, s);
    const f = await createEmployee(request, token, { first: 'QA', last: `Ec3${s}`, department: md.deptId, designation: md.desigId });

    // Apply a 25-day annual leave (annual allowance is 18) via the UI.
    await page.goto('/hr/leaves/create/');
    await page.locator('select[name="employee"]').selectOption(String(f.id));
    await page.locator('select[name="leave_type"]').selectOption('annual');
    await page.getByLabel('Start date').fill('2026-01-01');
    await page.getByLabel('End date').fill('2026-01-25');
    await page.getByLabel('Days').fill('25');
    await page.getByRole('button', { name: 'Create' }).click();
    await expect(page).toHaveURL(/\/hr\/leaves\/$/);

    // Approve it via the UI.
    await page.getByRole('row', { name: new RegExp(f.full_name) }).getByRole('button', { name: 'Approve' }).click();
    await expect(page).toHaveURL(/\/hr\/leaves\/$/);

    try {
      const leaves = (await (await request.get('/api/leaves/')).json()) as any[];
      const leave = leaves.find((l) => l.employee === f.id);
      // CONFIRMED BUG: specs/hr.md HR-EC-03 — no leave-balance enforcement.
      // CORRECT: annual allowance is 18; a 25-day request must be blocked or clamped.
      expect(leave.days).toBeLessThanOrEqual(18);
    } finally {
      await cleanup(request, {
        employeeIds: [f.id],
        componentIds: [md.basicId, md.taxId, md.allowanceId],
        departmentIds: [md.deptId],
        designationIds: [md.desigId],
      });
    }
  });

  test('HR-EC-04 — Slip-item edit on a processed/paid slip (no status guard)', async ({ request, page }) => {
    const token = await loginViaApi(request, 'hr');
    const s = uniq();
    const md = await createMasterData(request, token, s);
    const a = await createEmployee(request, token, { first: 'QA', last: `Ec4${s}`, department: md.deptId, designation: md.desigId });
    await addSalary(request, token, a.id, md.basicId, 50000);

    const { month, year } = freshPeriod();

    // Drive the run to paid via the UI.
    await page.goto('/hr/payroll/create/');
    await page.locator('select[name="month"]').selectOption(String(month));
    await page.getByLabel('Year').fill(String(year));
    await page.getByRole('button', { name: 'Create' }).click();
    await expect(page).toHaveURL(/\/hr\/payroll\/\d+\/$/);
    const runId = Number(page.url().split('/').filter(Boolean).pop());

    await page.getByRole('button', { name: 'Generate Slips' }).click();
    await expect(page.getByRole('button', { name: 'Process & Approve' })).toBeVisible();
    await page.getByRole('button', { name: 'Process & Approve' }).click();
    await expect(page.getByRole('button', { name: 'Mark Paid' })).toBeVisible();
    page.once('dialog', (d) => d.accept());
    await page.getByRole('button', { name: 'Mark Paid' }).click();
    await expect(page).toHaveURL(/\/hr\/payroll\/\d+\/$/);

    try {
      const slip = (await (await request.get('/api/salary-slips/')).json()).find((x) => x.run === runId && x.employee === a.id);
      expect(slip.status).toBe('paid');
      const netBefore = slip.net;

      // Tamper: add an item to the paid slip (the view has no status guard).
      await request.post(`/hr/slips/${slip.id}/add-item/`, {
        headers: { 'X-CSRFToken': token },
        form: { component: String(md.allowanceId), amount: '99999' },
      });

      const after = (await (await request.get(`/api/salary-slips/${slip.id}/`)).json()) as any;
      // CONFIRMED BUG: specs/hr.md HR-EC-04 — add-item view has no status guard.
      // CORRECT: a paid slip is locked; net must not change.
      expect(after.net).toBe(netBefore);
    } finally {
      await cleanup(request, {
        runIds: [runId],
        employeeIds: [a.id],
        componentIds: [md.basicId, md.taxId, md.allowanceId],
        departmentIds: [md.deptId],
        designationIds: [md.desigId],
      });
    }
  });

  test('HR-EC-05 — Non-numeric slip-item amount → uncaught 500', async ({ request, page }) => {
    const token = await loginViaApi(request, 'hr');
    const s = uniq();
    const md = await createMasterData(request, token, s);
    const a = await createEmployee(request, token, { first: 'QA', last: `Ec5${s}`, department: md.deptId, designation: md.desigId });
    await addSalary(request, token, a.id, md.basicId, 50000);

    const { month, year } = freshPeriod();

    // Drive run create + generate via the UI to produce a draft slip.
    await page.goto('/hr/payroll/create/');
    await page.locator('select[name="month"]').selectOption(String(month));
    await page.getByLabel('Year').fill(String(year));
    await page.getByRole('button', { name: 'Create' }).click();
    await expect(page).toHaveURL(/\/hr\/payroll\/\d+\/$/);
    const runId = Number(page.url().split('/').filter(Boolean).pop());

    await page.getByRole('button', { name: 'Generate Slips' }).click();
    await expect(page.getByRole('button', { name: 'Process & Approve' })).toBeVisible();

    try {
      const slip = (await (await request.get('/api/salary-slips/')).json()).find((x) => x.run === runId && x.employee === a.id);

      // Crafted POST with a non-numeric amount.
      const res = await request.post(`/hr/slips/${slip.id}/add-item/`, {
        headers: { 'X-CSRFToken': token },
        form: { component: String(md.allowanceId), amount: 'abc' },
      });
      // CONFIRMED BUG: specs/hr.md HR-EC-05 — Decimal('abc') raises InvalidOperation (uncaught 500).
      // CORRECT: a friendly "invalid amount" error (2xx/3xx), never a 500.
      expect(res.status()).not.toBe(500);
    } finally {
      await cleanup(request, {
        runIds: [runId],
        employeeIds: [a.id],
        componentIds: [md.basicId, md.taxId, md.allowanceId],
        departmentIds: [md.deptId],
        designationIds: [md.desigId],
      });
    }
  });

  test('HR-EC-06 — Pay on a non-processed (draft) run marks it paid with 0 payments', async ({ request, page }) => {
    const token = await loginViaApi(request, 'hr');
    const s = uniq();
    const md = await createMasterData(request, token, s);
    const a = await createEmployee(request, token, { first: 'QA', last: `Ec6${s}`, department: md.deptId, designation: md.desigId });
    await addSalary(request, token, a.id, md.basicId, 50000);

    const { month, year } = freshPeriod();

    // Drive run create + generate via the UI (still draft).
    await page.goto('/hr/payroll/create/');
    await page.locator('select[name="month"]').selectOption(String(month));
    await page.getByLabel('Year').fill(String(year));
    await page.getByRole('button', { name: 'Create' }).click();
    await expect(page).toHaveURL(/\/hr\/payroll\/\d+\/$/);
    const runId = Number(page.url().split('/').filter(Boolean).pop());

    await page.getByRole('button', { name: 'Generate Slips' }).click();
    await expect(page.getByRole('button', { name: 'Process & Approve' })).toBeVisible();

    // Pay before processing (crafted POST).
    await request.post(`/hr/payroll/${runId}/pay/`, { headers: { 'X-CSRFToken': token }, form: {} });

    try {
      const after = (await (await request.get(`/api/payroll-runs/${runId}/`)).json()) as any;
      // CONFIRMED BUG: specs/hr.md HR-EC-06 — pay view has no draft-status guard.
      // CORRECT: pay must be rejected while the run is draft; status stays draft.
      expect(after.status).toBe('draft');
    } finally {
      await cleanup(request, {
        runIds: [runId],
        employeeIds: [a.id],
        componentIds: [md.basicId, md.taxId, md.allowanceId],
        departmentIds: [md.deptId],
        designationIds: [md.desigId],
      });
    }
  });
});

// ── Security ────────────────────────────────────────────────────────────────

test.describe('HR — Security (SEC)', () => {
  test('HR-SEC-01 — HR API read-open: any authenticated user reads the full employee directory (CRITICAL)', async ({ request, browser }) => {
    const adminToken = await loginViaApi(request, 'admin');
    const s = uniq();
    const md = await createMasterData(request, adminToken, s);
    const emp = await createEmployee(request, adminToken, {
      first: 'QA',
      last: `Sec1${s}`,
      department: md.deptId,
      designation: md.desigId,
      cnic: '37405-0235722-4',
      phone: '+92-300-1234567',
      email: `sec1${s}@example.com`,
      address: 'QA Address',
    });
    await addSalary(request, adminToken, emp.id, md.basicId, 75000);

    // Low-privilege authenticated user: the portal customer (no HR/payroll role).
    await loginViaApi(request, 'customer');

    // Browser cross-check (correct behaviour): the server-rendered HR page denies
    // the customer — proving the UI and the API disagree on access.
    const cctx = await browser.newContext({ baseURL: 'http://127.0.0.1:8000' });
    const cpage = await cctx.newPage();
    await cpage.goto('/login/');
    await cpage.getByRole('textbox', { name: 'Username' }).fill('qa_customer');
    await cpage.getByRole('textbox', { name: 'Password' }).fill('admin123');
    await cpage.getByRole('button', { name: 'Sign In' }).click();
    await expect(cpage).toHaveURL(/portal\/?$/);
    await cpage.goto('/hr/employees/');
    await expect(cpage).not.toHaveURL(/\/hr\/employees\/$/);
    await cctx.close();

    // CONFIRMED BUG: docs/qa/findings-confirmed.md F3/F8 — HR reads are open to ANY
    // authenticated user (cnic, phone, salaries are returned).
    try {
      const res = await request.get('/api/employees/');
      expect(res.status()).toBe(403); // CORRECT: 403; actual: 200 with employee PII.
    } finally {
      await cleanup(request, {
        employeeIds: [emp.id],
        componentIds: [md.basicId, md.taxId, md.allowanceId],
        departmentIds: [md.deptId],
        designationIds: [md.desigId],
      });
    }
  });

  test('HR-SEC-02 — LeaveSerializer.status writable: self-approve bypassing the approve action (CRITICAL)', async ({ request }) => {
    const token = await loginViaApi(request, 'hr');
    const s = uniq();
    const md = await createMasterData(request, token, s);
    const emp = await createEmployee(request, token, { first: 'QA', last: `Sec2${s}`, department: md.deptId, designation: md.desigId });

    const leave = (await (await request.post('/api/leaves/', {
      headers: { 'X-CSRFToken': token },
      data: { employee: emp.id, leave_type: 'annual', start_date: '2026-02-01', end_date: '2026-02-03', days: 3 },
    })).json()) as any;

    // CONFIRMED BUG: docs/qa/findings-confirmed.md F8 — status is writable; a direct
    // PATCH self-approves without the approve action's approved_by stamp.
    const patchRes = await request.patch(`/api/leaves/${leave.id}/`, {
      headers: { 'X-CSRFToken': token },
      data: { status: 'approved' },
    });
    try {
      const patched = (await patchRes.json()) as any;
      // CORRECT: status is read-only; only the approve action may set it (and stamp approved_by).
      expect(patched.status).toBe('pending');
    } finally {
      await cleanup(request, {
        employeeIds: [emp.id],
        componentIds: [md.basicId, md.taxId, md.allowanceId],
        departmentIds: [md.deptId],
        designationIds: [md.desigId],
      });
    }
  });
});
