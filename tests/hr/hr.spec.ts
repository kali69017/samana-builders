import { test, expect, APIRequestContext } from '@playwright/test';
import { loginViaApi } from '../helpers/auth';

/**
 * Samana ERP — HR module test suite.
 *
 * Contract source: `specs/hr.md` (scenario IDs are the test names).
 * Confirmed bugs: `docs/qa/findings-confirmed.md` (F3 systemic API read-open, F8 HR
 * read-open + LeaveSerializer.status writable).
 *
 * API/security scenarios use `request` + `loginViaApi`; payroll/attendance/leave UI flows
 * use `page` (hr storageState) or a fresh browser context for the self-service staff user.
 *
 * Note on cleanup: `cleanup()` re-logs as `admin` (superuser) and deletes the objects the
 * test created (payroll run → slips/payments cascade; employee → salaries/leaves/attendance
 * cascade; ledger rows are matched by reference_id before the run is deleted). Confirmed-bug
 * tests assert the *correct* behaviour, so they fail (RED) before reaching cleanup — those
 * fixtures leak into the shared dev DB by design.
 */

const uniq = (p = '') => `${p}${Date.now()}${Math.floor(Math.random() * 1e6)}`;

// ── helpers ─────────────────────────────────────────────────────────────────

async function loginCustom(request: APIRequestContext, username: string, password: string): Promise<string> {
  await request.get('/api/auth/csrf/');
  let token = '';
  try {
    const st = await request.storageState();
    token = st.cookies.find((c) => c.name === 'csrftoken')?.value ?? '';
  } catch {
    token = '';
  }
  const res = await request.post('/api/auth/login/', {
    data: { username, password },
    headers: token ? { 'X-CSRFToken': token } : {},
  });
  if (res.status() !== 200) throw new Error(`login ${username} failed: ${res.status()} ${await res.text()}`);
  return token;
}

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
  const slipIds = slips.filter((s) => s.run === runId).map((s) => s.id);
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

// ── Happy Path ──────────────────────────────────────────────────────────────

test.describe('HR — Happy Path (HP)', () => {
  test.use({ storageState: 'tests/.auth/hr.json' });

  test('HR-HP-01 — Create employee: EMP-xxxxx auto-ID and monthly_gross from salary components', async ({ request, page }) => {
    const adminToken = await loginViaApi(request, 'admin');
    const s = uniq();
    const md = await createMasterData(request, adminToken, s);

    await page.goto('/hr/employees/create/');
    await page.getByLabel('First name').fill('QA');
    await page.getByLabel('Last name').fill(`Emp${s}`);
    // Selects in base_form.html render a bare <label> with no `for`, so a role/label
    // locator cannot target them — name= attribute is the only reliable handle.
    await page.locator('select[name="department"]').selectOption(String(md.deptId));
    await page.locator('select[name="designation"]').selectOption(String(md.desigId));
    await page.getByLabel('Joining date').fill('2026-01-01');
    await page.getByLabel('Cnic').fill('3740502357224');
    await page.getByRole('button', { name: 'Create' }).click();
    await expect(page).toHaveURL(/\/hr\/employees\/\d+\/$/);

    // Canonical dashed CNIC is stored/displayed.
    await expect(page.getByText('37405-0235722-4').first()).toBeVisible();

    const empPk = Number(page.url().split('/').filter(Boolean).pop());

    // Add the earning component via the UI.
    await page.goto(`/hr/employees/${empPk}/salary/add/`);
    await page.locator('select[name="component"]').selectOption(String(md.basicId));
    await page.getByLabel('Amount').fill('50000');
    await page.getByRole('button', { name: 'Create' }).click();
    await expect(page).toHaveURL(new RegExp(`/hr/employees/${empPk}/$`));

    // monthly_gross = sum of earning components only.
    await expect(page.getByText('Rs. 50000').first()).toBeVisible();

    // Confirm auto-ID format + canonical CNIC + salary amount via the API.
    const emps = (await (await request.get(`/api/employees/?search=Emp${s}`)).json()) as any[];
    const emp = emps.find((e) => e.id === empPk);
    expect(emp.employee_id).toMatch(/^EMP-\d{5}$/);
    expect(emp.cnic).toBe('37405-0235722-4');
    expect(emp.salaries[0].amount).toBe('50000.00');

    await cleanup(request, {
      employeeIds: [empPk],
      componentIds: [md.basicId, md.taxId, md.allowanceId],
      departmentIds: [md.deptId],
      designationIds: [md.desigId],
    });
  });

  test('HR-HP-02 — Payroll run generate → process → pay posts the ledger exactly once', async ({ request, page }) => {
    const adminToken = await loginViaApi(request, 'admin');
    const s = uniq();
    const md = await createMasterData(request, adminToken, s);
    const a = await createEmployee(request, adminToken, { first: 'QA', last: `Pay${s}`, department: md.deptId, designation: md.desigId });
    await addSalary(request, adminToken, a.id, md.basicId, 50000);

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

    // Assert the slip is paid, exactly one payment, exactly one ledger row.
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

  test('HR-HP-03 — Salary slip recalculation recomputes gross/net from items', async ({ request }) => {
    const token = await loginViaApi(request, 'hr');
    const s = uniq();
    const md = await createMasterData(request, token, s);
    const a = await createEmployee(request, token, { first: 'QA', last: `Recalc${s}`, department: md.deptId, designation: md.desigId });
    await addSalary(request, token, a.id, md.basicId, 50000);
    await addSalary(request, token, a.id, md.taxId, 5000);

    const { month, year } = freshPeriod();
    const run = (await (await request.post('/api/payroll-runs/', { headers: { 'X-CSRFToken': token }, data: { month, year } })).json()) as any;
    await request.post(`/api/payroll-runs/${run.id}/generate/`, { headers: { 'X-CSRFToken': token } });

    const slips = (await (await request.get('/api/salary-slips/')).json()) as any[];
    const slip = slips.find((x) => x.run === run.id && x.employee === a.id);
    expect(slip.gross).toBe('50000.00');
    expect(slip.total_deductions).toBe('5000.00');
    expect(slip.net).toBe('45000.00');

    // Add earning item "Allowance" 10000 via the server view.
    await request.post(`/hr/slips/${slip.id}/add-item/`, {
      headers: { 'X-CSRFToken': token },
      form: { component: String(md.allowanceId), amount: '10000' },
    });

    const after = (await (await request.get(`/api/salary-slips/${slip.id}/`)).json()) as any;
    expect(after.gross).toBe('60000.00');
    expect(after.total_earnings).toBe('60000.00');
    expect(after.total_deductions).toBe('5000.00');
    expect(after.net).toBe('55000.00');

    await cleanup(request, {
      runIds: [run.id],
      employeeIds: [a.id],
      componentIds: [md.basicId, md.taxId, md.allowanceId],
      departmentIds: [md.deptId],
      designationIds: [md.desigId],
    });
  });

  test('HR-HP-04 — Bulk attendance mark updates, never duplicates, per employee+date', async ({ request, page }) => {
    const adminToken = await loginViaApi(request, 'admin');
    const s = uniq();
    const md = await createMasterData(request, adminToken, s);
    const a = await createEmployee(request, adminToken, { first: 'QA', last: `AttA${s}`, department: md.deptId, designation: md.desigId, status: 'active' });
    const d = await createEmployee(request, adminToken, { first: 'QA', last: `AttD${s}`, department: md.deptId, designation: md.desigId, status: 'on_leave' });

    const attDate = '2020-01-15'; // far-past date to avoid touching today's real data

    // Step 1: A absent, D left at default (server coerces on_leave → leave).
    await page.goto('/hr/attendance/create/');
    await page.getByLabel('Attendance Date').fill(attDate);
    // Per-row selects carry only a name="status_<pk>" attribute — no label/testid.
    await page.locator(`select[name="status_${a.id}"]`).selectOption('absent');
    await page.getByRole('button', { name: 'Mark Attendance' }).click();
    await expect(page).toHaveURL(/\/hr\/attendance\/$/);

    // Step 2: re-mark the same date with A present.
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

    await cleanup(request, {
      employeeIds: [a.id, d.id],
      componentIds: [md.basicId, md.taxId, md.allowanceId],
      departmentIds: [md.deptId],
      designationIds: [md.desigId],
    });
  });

  test('HR-HP-05 — Leave apply then approve (with approved_by stamp)', async ({ request, browser }) => {
    const adminToken = await loginViaApi(request, 'admin');
    const s = uniq();
    const md = await createMasterData(request, adminToken, s);
    const f = await createEmployee(request, adminToken, { first: 'QA', last: `LeaveF${s}`, department: md.deptId, designation: md.desigId });

    // Create a staff login linked to F (EmployeeProfileForm.save()).
    const hrToken = await loginViaApi(request, 'hr');
    const staffUsername = `staff${s}`;
    const staffPassword = 'admin123';
    await request.post('/hr/employee-profile/', {
      headers: { 'X-CSRFToken': hrToken },
      form: {
        employee: String(f.id),
        username: staffUsername,
        email: `${staffUsername}@example.com`,
        password: staffPassword,
        confirm_password: staffPassword,
      },
    });

    // F applies via the self-service UI.
    const fctx = await browser.newContext({ baseURL: 'http://127.0.0.1:8000' });
    const fpage = await fctx.newPage();
    await fpage.goto('/login/');
    await fpage.getByRole('textbox', { name: 'Username' }).fill(staffUsername);
    await fpage.getByRole('textbox', { name: 'Password' }).fill(staffPassword);
    await fpage.getByRole('button', { name: 'Sign In' }).click();
    await expect(fpage).toHaveURL('/hr/my-leave/');

    await fpage.goto('/hr/my-leave/apply/');
    await fpage.getByLabel('Days').fill('3');
    await fpage.getByLabel('Leave Type').selectOption('annual');
    await fpage.getByLabel('Start date').fill('2026-02-01');
    await fpage.getByLabel('End date').fill('2026-02-03');
    await fpage.getByLabel('Reason').fill('Annual leave QA');
    await fpage.getByRole('button', { name: 'Create' }).click();
    await expect(fpage).toHaveURL('/hr/my-leave/');
    await fctx.close();

    // hr approves; the leave is bound to F and approved_by is stamped.
    const hrUserId = (await (await request.get('/api/auth/me/')).json()).id;
    const leaves = (await (await request.get('/api/leaves/')).json()) as any[];
    const leave = leaves.find((l) => l.employee === f.id && l.status === 'pending');
    expect(leave).toBeTruthy();
    const approved = (await (await request.post(`/api/leaves/${leave.id}/approve/`, { headers: { 'X-CSRFToken': hrToken } })).json()) as any;
    expect(approved.status).toBe('approved');
    expect(approved.approved_by).toBe(hrUserId);

    await cleanup(request, {
      employeeIds: [f.id],
      componentIds: [md.basicId, md.taxId, md.allowanceId],
      departmentIds: [md.deptId],
      designationIds: [md.desigId],
    });
  });

  test('HR-HP-06 — Employee self-service portal hides admin nav and scopes data to self', async ({ request, browser }) => {
    const adminToken = await loginViaApi(request, 'admin');
    const s = uniq();
    const md = await createMasterData(request, adminToken, s);
    const f = await createEmployee(request, adminToken, { first: 'QA', last: `SelfF${s}`, department: md.deptId, designation: md.desigId });
    const other = await createEmployee(request, adminToken, { first: 'QA', last: `SelfOther${s}`, department: md.deptId, designation: md.desigId });

    const hrToken = await loginViaApi(request, 'hr');
    await request.post('/api/leaves/', {
      headers: { 'X-CSRFToken': hrToken },
      data: { employee: other.id, leave_type: 'annual', start_date: '2026-03-01', end_date: '2026-03-02', days: 2, reason: 'other employee leave' },
    });

    const staffUsername = `staff${s}`;
    const staffPassword = 'admin123';
    await request.post('/hr/employee-profile/', {
      headers: { 'X-CSRFToken': hrToken },
      form: {
        employee: String(f.id),
        username: staffUsername,
        email: `${staffUsername}@example.com`,
        password: staffPassword,
        confirm_password: staffPassword,
      },
    });

    const fctx = await browser.newContext({ baseURL: 'http://127.0.0.1:8000' });
    const fpage = await fctx.newPage();
    await fpage.goto('/login/');
    await fpage.getByRole('textbox', { name: 'Username' }).fill(staffUsername);
    await fpage.getByRole('textbox', { name: 'Password' }).fill(staffPassword);
    await fpage.getByRole('button', { name: 'Sign In' }).click();
    await expect(fpage).toHaveURL('/hr/my-leave/');

    // Admin/HR nav is hidden for an employee; only "My Leave" is shown.
    await expect(fpage.getByRole('link', { name: 'Employees' })).toHaveCount(0);
    await expect(fpage.getByRole('link', { name: 'Payroll' })).toHaveCount(0);
    await expect(fpage.getByRole('link', { name: 'Departments' })).toHaveCount(0);
    await expect(fpage.getByRole('link', { name: 'My Leave' })).toBeVisible();

    // My Leave lists only F's own (empty) requests — never another employee's.
    await expect(fpage.getByText(other.full_name)).toHaveCount(0);
    await expect(fpage.getByText('No Leave Requests')).toBeVisible();
    await fctx.close();

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
  test('HR-EC-01 — Zero- or negative-net slip breaks the whole pay run (rollback → 500)', async ({ request }) => {
    const token = await loginViaApi(request, 'hr');
    const s = uniq();
    const md = await createMasterData(request, token, s);
    const a = await createEmployee(request, token, { first: 'QA', last: `Ec1A${s}`, department: md.deptId, designation: md.desigId });
    await addSalary(request, token, a.id, md.basicId, 50000);
    const b = await createEmployee(request, token, { first: 'QA', last: `Ec1B${s}`, department: md.deptId, designation: md.desigId }); // no components → net 0

    const { month, year } = freshPeriod();
    const run = (await (await request.post('/api/payroll-runs/', { headers: { 'X-CSRFToken': token }, data: { month, year } })).json()) as any;
    await request.post(`/api/payroll-runs/${run.id}/generate/`, { headers: { 'X-CSRFToken': token } });
    await request.post(`/api/payroll-runs/${run.id}/process/`, { headers: { 'X-CSRFToken': token } });

    const payRes = await request.post(`/api/payroll-runs/${run.id}/pay/`, { headers: { 'X-CSRFToken': token } });
    // CORRECT: the zero/negative-net slip is skipped and does not block the others.
    expect(payRes.status()).toBe(200);

    // CORRECT: A's valid payment exists and is not rolled back.
    const payments = (await (await request.get('/api/salary-payments/')).json()) as any[];
    const aPayment = payments.find((p) => p.employee_name === a.full_name);
    expect(aPayment).toBeTruthy();
    expect(aPayment.amount).toBe('50000.00');

    await cleanup(request, {
      runIds: [run.id],
      employeeIds: [a.id, b.id],
      componentIds: [md.basicId, md.taxId, md.allowanceId],
      departmentIds: [md.deptId],
      designationIds: [md.desigId],
    });
  });

  test('HR-EC-02 — Duplicate payroll month via API returns 500', async ({ request }) => {
    const token = await loginViaApi(request, 'hr');
    const { month, year } = freshPeriod();
    const first = await request.post('/api/payroll-runs/', { headers: { 'X-CSRFToken': token }, data: { month, year } });
    expect(first.status()).toBe(201);
    const runId = (await first.json()).id;

    const dup = await request.post('/api/payroll-runs/', { headers: { 'X-CSRFToken': token }, data: { month, year } });
    // CORRECT: uniqueness validation error (400), not a 500.
    expect(dup.status()).toBe(400);

    await cleanup(request, { runIds: [runId] });
  });

  test('HR-EC-03 — Leave over-allowance is accepted (no balance enforcement)', async ({ request }) => {
    const token = await loginViaApi(request, 'hr');
    const s = uniq();
    const md = await createMasterData(request, token, s);
    const f = await createEmployee(request, token, { first: 'QA', last: `Ec3${s}`, department: md.deptId, designation: md.desigId });

    const leave = (await (await request.post('/api/leaves/', {
      headers: { 'X-CSRFToken': token },
      data: { employee: f.id, leave_type: 'annual', start_date: '2026-01-01', end_date: '2026-01-25', days: 25, reason: 'over allowance' },
    })).json()) as any;
    await request.post(`/api/leaves/${leave.id}/approve/`, { headers: { 'X-CSRFToken': token } });

    const approved = (await (await request.get(`/api/leaves/${leave.id}/`)).json()) as any;
    // CORRECT: annual allowance is 18; a 25-day request must be blocked or clamped.
    expect(approved.days).toBeLessThanOrEqual(18);

    await cleanup(request, {
      employeeIds: [f.id],
      componentIds: [md.basicId, md.taxId, md.allowanceId],
      departmentIds: [md.deptId],
      designationIds: [md.desigId],
    });
  });

  test('HR-EC-04 — Slip-item edit on a processed/paid slip (no status guard)', async ({ request }) => {
    const token = await loginViaApi(request, 'hr');
    const s = uniq();
    const md = await createMasterData(request, token, s);
    const a = await createEmployee(request, token, { first: 'QA', last: `Ec4${s}`, department: md.deptId, designation: md.desigId });
    await addSalary(request, token, a.id, md.basicId, 50000);

    const { month, year } = freshPeriod();
    const run = (await (await request.post('/api/payroll-runs/', { headers: { 'X-CSRFToken': token }, data: { month, year } })).json()) as any;
    await request.post(`/api/payroll-runs/${run.id}/generate/`, { headers: { 'X-CSRFToken': token } });
    await request.post(`/api/payroll-runs/${run.id}/process/`, { headers: { 'X-CSRFToken': token } });
    await request.post(`/api/payroll-runs/${run.id}/pay/`, { headers: { 'X-CSRFToken': token } });

    const slip = (await (await request.get('/api/salary-slips/')).json()).find((x) => x.run === run.id && x.employee === a.id);
    expect(slip.status).toBe('paid');
    const netBefore = slip.net; // '50000.00'

    // Tamper: add an item to a paid slip.
    await request.post(`/hr/slips/${slip.id}/add-item/`, {
      headers: { 'X-CSRFToken': token },
      form: { component: String(md.allowanceId), amount: '99999' },
    });

    const after = (await (await request.get(`/api/salary-slips/${slip.id}/`)).json()) as any;
    // CORRECT: a paid slip is locked; net must not change.
    expect(after.net).toBe(netBefore);

    await cleanup(request, {
      runIds: [run.id],
      employeeIds: [a.id],
      componentIds: [md.basicId, md.taxId, md.allowanceId],
      departmentIds: [md.deptId],
      designationIds: [md.desigId],
    });
  });

  test('HR-EC-05 — Non-numeric slip-item amount → uncaught 500', async ({ request }) => {
    const token = await loginViaApi(request, 'hr');
    const s = uniq();
    const md = await createMasterData(request, token, s);
    const a = await createEmployee(request, token, { first: 'QA', last: `Ec5${s}`, department: md.deptId, designation: md.desigId });
    await addSalary(request, token, a.id, md.basicId, 50000);

    const { month, year } = freshPeriod();
    const run = (await (await request.post('/api/payroll-runs/', { headers: { 'X-CSRFToken': token }, data: { month, year } })).json()) as any;
    await request.post(`/api/payroll-runs/${run.id}/generate/`, { headers: { 'X-CSRFToken': token } });
    const slip = (await (await request.get('/api/salary-slips/')).json()).find((x) => x.run === run.id && x.employee === a.id);

    const res = await request.post(`/hr/slips/${slip.id}/add-item/`, {
      headers: { 'X-CSRFToken': token },
      form: { component: String(md.allowanceId), amount: 'abc' },
    });
    // CORRECT: a friendly "invalid amount" error (2xx/3xx), never a 500.
    expect(res.status()).not.toBe(500);

    await cleanup(request, {
      runIds: [run.id],
      employeeIds: [a.id],
      componentIds: [md.basicId, md.taxId, md.allowanceId],
      departmentIds: [md.deptId],
      designationIds: [md.desigId],
    });
  });

  test('HR-EC-06 — Pay on a non-processed (draft) run marks it paid with 0 payments', async ({ request }) => {
    const token = await loginViaApi(request, 'hr');
    const s = uniq();
    const md = await createMasterData(request, token, s);
    const a = await createEmployee(request, token, { first: 'QA', last: `Ec6${s}`, department: md.deptId, designation: md.desigId });
    await addSalary(request, token, a.id, md.basicId, 50000);

    const { month, year } = freshPeriod();
    const run = (await (await request.post('/api/payroll-runs/', { headers: { 'X-CSRFToken': token }, data: { month, year } })).json()) as any;
    await request.post(`/api/payroll-runs/${run.id}/generate/`, { headers: { 'X-CSRFToken': token } });

    // Pay before processing (crafted POST).
    await request.post(`/hr/payroll/${run.id}/pay/`, { headers: { 'X-CSRFToken': token }, form: {} });

    const after = (await (await request.get(`/api/payroll-runs/${run.id}/`)).json()) as any;
    // CORRECT: pay must be rejected while the run is draft; status stays draft.
    expect(after.status).toBe('draft');

    await cleanup(request, {
      runIds: [run.id],
      employeeIds: [a.id],
      componentIds: [md.basicId, md.taxId, md.allowanceId],
      departmentIds: [md.deptId],
      designationIds: [md.desigId],
    });
  });

  test('HR-EC-07 — CNIC duplicate guard bypassed via API (raw vs canonical dashed)', async ({ request }) => {
    const token = await loginViaApi(request, 'hr');
    const s = uniq();
    const md = await createMasterData(request, token, s);
    const g = await createEmployee(request, token, { first: 'QA', last: `Ec7${s}`, department: md.deptId, designation: md.desigId, cnic: '37405-0235722-4' });

    const dup = await request.post('/api/employees/', {
      headers: { 'X-CSRFToken': token },
      data: { first_name: 'QA', last_name: `Ec7dup${s}`, department: md.deptId, designation: md.desigId, joining_date: '2026-01-01', cnic: '3740502357224' },
    });
    const dupId = dup.status() === 201 ? (await dup.json()).id : null;
    // CORRECT: duplicate CNIC (raw form) must be rejected with 400.
    expect(dup.status()).toBe(400);

    await cleanup(request, {
      employeeIds: [g.id, dupId].filter((x) => x != null),
      componentIds: [md.basicId, md.taxId, md.allowanceId],
      departmentIds: [md.deptId],
      designationIds: [md.desigId],
    });
  });

  test('HR-EC-08 — Attendance duplicate POST via API → 500', async ({ request }) => {
    const token = await loginViaApi(request, 'hr');
    const s = uniq();
    const md = await createMasterData(request, token, s);
    const a = await createEmployee(request, token, { first: 'QA', last: `Ec8${s}`, department: md.deptId, designation: md.desigId });
    const attDate = '2026-05-10';

    const first = await request.post('/api/attendance/', { headers: { 'X-CSRFToken': token }, data: { employee: a.id, date: attDate, status: 'present' } });
    expect(first.status()).toBe(201);
    const firstId = (await first.json()).id;

    const dup = await request.post('/api/attendance/', { headers: { 'X-CSRFToken': token }, data: { employee: a.id, date: attDate, status: 'absent' } });
    // CORRECT: duplicate (employee, date) is updated or rejected (200/400), never 500.
    expect([200, 400]).toContain(dup.status());

    await cleanup(request, {
      employeeIds: [a.id],
      attendanceIds: [firstId],
      componentIds: [md.basicId, md.taxId, md.allowanceId],
      departmentIds: [md.deptId],
      designationIds: [md.desigId],
    });
  });

  test('HR-EC-09 — Bulk attendance with an invalid date silently marks today', async ({ request }) => {
    const token = await loginViaApi(request, 'hr');
    const s = uniq();
    const md = await createMasterData(request, token, s);
    const a = await createEmployee(request, token, { first: 'QA', last: `Ec9${s}`, department: md.deptId, designation: md.desigId });

    // NOTE: the buggy view marks every active/on_leave employee for *today*.
    await request.post('/hr/attendance/create/', {
      headers: { 'X-CSRFToken': token },
      form: { date: 'not-a-date', [`status_${a.id}`]: 'absent' },
    });

    // CORRECT: an invalid date is a field error — no attendance row for A is created.
    const recs = (await (await request.get(`/api/attendance/?employee=${a.id}`)).json()) as any[];
    expect(recs).toHaveLength(0);

    await cleanup(request, {
      employeeIds: [a.id],
      componentIds: [md.basicId, md.taxId, md.allowanceId],
      departmentIds: [md.deptId],
      designationIds: [md.desigId],
    });
  });

  test('HR-EC-10 — Leave form/model accepts an invalid date range or days=0', async ({ request }) => {
    const token = await loginViaApi(request, 'hr');
    const s = uniq();
    const md = await createMasterData(request, token, s);
    const f = await createEmployee(request, token, { first: 'QA', last: `Ec10${s}`, department: md.deptId, designation: md.desigId });

    await request.post('/hr/leaves/create/', {
      headers: { 'X-CSRFToken': token },
      form: { employee: String(f.id), leave_type: 'annual', start_date: '2026-01-10', end_date: '2026-01-05', days: '0', reason: '' },
    });

    // CORRECT: end < start and days=0 must be rejected — no leave persisted for F.
    const leaves = (await (await request.get('/api/leaves/')).json()) as any[];
    expect(leaves.filter((l) => l.employee === f.id)).toHaveLength(0);

    await cleanup(request, {
      employeeIds: [f.id],
      componentIds: [md.basicId, md.taxId, md.allowanceId],
      departmentIds: [md.deptId],
      designationIds: [md.desigId],
    });
  });
});

// ── Security ────────────────────────────────────────────────────────────────

test.describe('HR — Security (SEC)', () => {
  test('HR-SEC-01 — HR API read-open: any authenticated user reads the full employee directory (CRITICAL)', async ({ request }) => {
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

    // Low-privilege authenticated user (role `sales`).
    await loginViaApi(request, 'sales');

    // CONFIRMED BUG: docs/qa/findings-confirmed.md F3/F8 — reads are open to ANY authenticated user.
    const endpoints = [
      '/api/employees/',
      '/api/salary-slips/',
      '/api/salary-payments/',
      '/api/payroll-runs/',
      '/api/attendance/',
      '/api/leaves/',
      '/api/employee-salaries/',
    ];
    for (const url of endpoints) {
      const res = await request.get(url);
      expect.soft(res.status(), `${url} must deny low-privilege reads`).toBe(403);
    }

    await cleanup(request, {
      employeeIds: [emp.id],
      componentIds: [md.basicId, md.taxId, md.allowanceId],
      departmentIds: [md.deptId],
      designationIds: [md.desigId],
    });
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

    // CONFIRMED BUG: docs/qa/findings-confirmed.md F8 — status is writable; a direct PATCH self-approves.
    const patchRes = await request.patch(`/api/leaves/${leave.id}/`, {
      headers: { 'X-CSRFToken': token },
      data: { status: 'approved' },
    });
    expect(patchRes.status()).toBe(200);
    const patched = (await patchRes.json()) as any;
    // CORRECT: status is read-only; only the approve action may set it (and stamp approved_by).
    expect(patched.status).toBe('pending');

    await cleanup(request, {
      employeeIds: [emp.id],
      componentIds: [md.basicId, md.taxId, md.allowanceId],
      departmentIds: [md.deptId],
      designationIds: [md.desigId],
    });
  });

  test('HR-SEC-03 — Employee deletion leaves a dangling ledger reference_id (no guard)', async ({ request }) => {
    const token = await loginViaApi(request, 'hr');
    const s = uniq();
    const md = await createMasterData(request, token, s);
    const a = await createEmployee(request, token, { first: 'QA', last: `Sec3${s}`, department: md.deptId, designation: md.desigId });
    await addSalary(request, token, a.id, md.basicId, 50000);

    const { month, year } = freshPeriod();
    const run = (await (await request.post('/api/payroll-runs/', { headers: { 'X-CSRFToken': token }, data: { month, year } })).json()) as any;
    await request.post(`/api/payroll-runs/${run.id}/generate/`, { headers: { 'X-CSRFToken': token } });
    await request.post(`/api/payroll-runs/${run.id}/process/`, { headers: { 'X-CSRFToken': token } });
    await request.post(`/api/payroll-runs/${run.id}/pay/`, { headers: { 'X-CSRFToken': token } });

    // Attempt to delete the employee (server view).
    await request.post(`/hr/employees/${a.id}/delete/`, { headers: { 'X-CSRFToken': token }, form: {} });

    // CORRECT: deletion is blocked (like projects-with-plots); the employee still exists.
    const stillThere = await request.get(`/api/employees/${a.id}/`);
    expect(stillThere.status()).toBe(200);

    await cleanup(request, {
      runIds: [run.id],
      employeeIds: [a.id],
      componentIds: [md.basicId, md.taxId, md.allowanceId],
      departmentIds: [md.deptId],
      designationIds: [md.desigId],
    });
  });

  test('HR-SEC-04 — Leave approval has no pending/ownership guard (re-approve/reject any leave by pk)', async ({ request }) => {
    const token = await loginViaApi(request, 'hr');
    const s = uniq();
    const md = await createMasterData(request, token, s);
    const emp = await createEmployee(request, token, { first: 'QA', last: `Sec4${s}`, department: md.deptId, designation: md.desigId });

    const leave = (await (await request.post('/api/leaves/', {
      headers: { 'X-CSRFToken': token },
      data: { employee: emp.id, leave_type: 'annual', start_date: '2026-03-01', end_date: '2026-03-02', days: 2 },
    })).json()) as any;
    await request.post(`/api/leaves/${leave.id}/approve/`, { headers: { 'X-CSRFToken': token } });

    // Try to reject an already-approved leave (correct: only pending leaves may transition).
    await request.post(`/api/leaves/${leave.id}/reject/`, { headers: { 'X-CSRFToken': token } });

    const after = (await (await request.get(`/api/leaves/${leave.id}/`)).json()) as any;
    // CORRECT: transition only from pending — the approved leave stays approved.
    expect(after.status).toBe('approved');

    await cleanup(request, {
      employeeIds: [emp.id],
      componentIds: [md.basicId, md.taxId, md.allowanceId],
      departmentIds: [md.deptId],
      designationIds: [md.desigId],
    });
  });

  test('HR-SEC-05 — My Leave cannot be scoped to another employee (negative confirmation)', async ({ request }) => {
    const adminToken = await loginViaApi(request, 'admin');
    const s = uniq();
    const md = await createMasterData(request, adminToken, s);
    const f = await createEmployee(request, adminToken, { first: 'QA', last: `Sec5F${s}`, department: md.deptId, designation: md.desigId });
    const a = await createEmployee(request, adminToken, { first: 'QA', last: `Sec5A${s}`, department: md.deptId, designation: md.desigId });

    const hrToken = await loginViaApi(request, 'hr');
    const staffUsername = `staff${s}`;
    const staffPassword = 'admin123';
    await request.post('/hr/employee-profile/', {
      headers: { 'X-CSRFToken': hrToken },
      form: {
        employee: String(f.id),
        username: staffUsername,
        email: `${staffUsername}@example.com`,
        password: staffPassword,
        confirm_password: staffPassword,
      },
    });

    // F applies via self-service, tampering employee=A — the view must ignore it.
    const fToken = await loginCustom(request, staffUsername, staffPassword);
    await request.post('/hr/my-leave/apply/', {
      headers: { 'X-CSRFToken': fToken },
      form: { employee: String(a.id), days: '2', leave_type: 'annual', start_date: '2026-04-01', end_date: '2026-04-02', reason: 'self' },
    });

    // CORRECT: the leave is always bound to F, never A.
    await loginViaApi(request, 'admin');
    const leaves = (await (await request.get('/api/leaves/')).json()) as any[];
    expect(leaves.filter((l) => l.employee === f.id)).toHaveLength(1);
    expect(leaves.filter((l) => l.employee === a.id)).toHaveLength(0);

    await cleanup(request, {
      employeeIds: [f.id, a.id],
      componentIds: [md.basicId, md.taxId, md.allowanceId],
      departmentIds: [md.deptId],
      designationIds: [md.desigId],
    });
  });
});

// ── API Contract ────────────────────────────────────────────────────────────

test.describe('HR — API Contract (API)', () => {
  test('HR-API-01 — GET/POST /api/employees/', async ({ request }) => {
    const token = await loginViaApi(request, 'hr');
    const s = uniq();
    const md = await createMasterData(request, token, s);

    expect((await request.get('/api/employees/')).status()).toBe(200);

    const postRes = await request.post('/api/employees/', {
      headers: { 'X-CSRFToken': token },
      data: { first_name: 'QA', last_name: `Api1${s}`, department: md.deptId, designation: md.desigId, joining_date: '2026-01-01' },
    });
    expect(postRes.status()).toBe(201);
    const emp = (await postRes.json()) as any;
    expect(emp.employee_id).toMatch(/^EMP-\d{5}$/);
    expect(emp.salaries).toEqual([]);
    expect(emp.full_name).toBe(`QA Api1${s}`);

    await cleanup(request, {
      employeeIds: [emp.id],
      componentIds: [md.basicId, md.taxId, md.allowanceId],
      departmentIds: [md.deptId],
      designationIds: [md.desigId],
    });
  });

  test('HR-API-02 — GET/POST /api/leaves/ (status writable)', async ({ request }) => {
    const token = await loginViaApi(request, 'hr');
    const s = uniq();
    const md = await createMasterData(request, token, s);
    const emp = await createEmployee(request, token, { first: 'QA', last: `Api2${s}`, department: md.deptId, designation: md.desigId });

    expect((await request.get('/api/leaves/')).status()).toBe(200);

    const ok = await request.post('/api/leaves/', {
      headers: { 'X-CSRFToken': token },
      data: { employee: emp.id, leave_type: 'annual', start_date: '2026-02-01', end_date: '2026-02-03', days: 3 },
    });
    expect(ok.status()).toBe(201);

    // Contract: end >= start and days > 0 are enforced.
    const badRange = await request.post('/api/leaves/', {
      headers: { 'X-CSRFToken': token },
      data: { employee: emp.id, leave_type: 'annual', start_date: '2026-02-10', end_date: '2026-02-05', days: 2 },
    });
    expect(badRange.status()).toBe(400);

    const zeroDays = await request.post('/api/leaves/', {
      headers: { 'X-CSRFToken': token },
      data: { employee: emp.id, leave_type: 'annual', start_date: '2026-02-01', end_date: '2026-02-03', days: 0 },
    });
    expect(zeroDays.status()).toBe(400);

    // NOTE: `status` is writable (a leave can be created directly in `approved` state
    // with approved_by=null) — covered by HR-SEC-02.

    await cleanup(request, {
      employeeIds: [emp.id],
      componentIds: [md.basicId, md.taxId, md.allowanceId],
      departmentIds: [md.deptId],
      designationIds: [md.desigId],
    });
  });

  test('HR-API-03 — GET/POST /api/payroll-runs/', async ({ request }) => {
    const token = await loginViaApi(request, 'hr');
    expect((await request.get('/api/payroll-runs/')).status()).toBe(200);

    const { month, year } = freshPeriod();
    const first = await request.post('/api/payroll-runs/', { headers: { 'X-CSRFToken': token }, data: { month, year, notes: 'QA' } });
    expect(first.status()).toBe(201);
    const run = (await first.json()) as any;
    expect(run.status).toBe('draft');
    expect(run.period_label).toBe(`${String(month).padStart(2, '0')}/${year}`);
    const runId = run.id;

    const dup = await request.post('/api/payroll-runs/', { headers: { 'X-CSRFToken': token }, data: { month, year } });
    // CORRECT: duplicate month/year must be rejected with 400 (see HR-EC-02).
    expect(dup.status()).toBe(400);

    await cleanup(request, { runIds: [runId] });
  });

  test('HR-API-04 — GET/POST /api/salary-slips/', async ({ request }) => {
    const token = await loginViaApi(request, 'hr');
    const s = uniq();
    const md = await createMasterData(request, token, s);
    const a = await createEmployee(request, token, { first: 'QA', last: `Api4${s}`, department: md.deptId, designation: md.desigId });
    await addSalary(request, token, a.id, md.basicId, 50000);

    const { month, year } = freshPeriod();
    const run = (await (await request.post('/api/payroll-runs/', { headers: { 'X-CSRFToken': token }, data: { month, year } })).json()) as any;
    await request.post(`/api/payroll-runs/${run.id}/generate/`, { headers: { 'X-CSRFToken': token } });

    const slips = (await (await request.get('/api/salary-slips/')).json()) as any[];
    const slip = slips.find((x) => x.run === run.id && x.employee === a.id);
    expect(slip.gross).toBe('50000.00');
    expect(slip.net).toBe('50000.00');
    expect(Array.isArray(slip.items)).toBe(true);
    expect(slip.items.length).toBeGreaterThan(0);

    // A new employee created after generate → POST a slip for (newEmp, run).
    // gross/net are read-only, so the posted values are ignored.
    const b = await createEmployee(request, token, { first: 'QA', last: `Api4b${s}`, department: md.deptId, designation: md.desigId });
    const posted = await request.post('/api/salary-slips/', {
      headers: { 'X-CSRFToken': token },
      data: { employee: b.id, run: run.id, gross: '99999.00', net: '99999.00' },
    });
    expect(posted.status()).toBe(201);
    const postedSlip = (await posted.json()) as any;
    expect(postedSlip.gross).toBe('0.00');
    expect(postedSlip.net).toBe('0.00');

    await cleanup(request, {
      runIds: [run.id],
      employeeIds: [a.id, b.id],
      componentIds: [md.basicId, md.taxId, md.allowanceId],
      departmentIds: [md.deptId],
      designationIds: [md.desigId],
    });
  });

  test('HR-API-05 — GET/POST /api/salary-payments/', async ({ request }) => {
    const token = await loginViaApi(request, 'hr');
    const s = uniq();
    const md = await createMasterData(request, token, s);
    const a = await createEmployee(request, token, { first: 'QA', last: `Api5${s}`, department: md.deptId, designation: md.desigId });
    await addSalary(request, token, a.id, md.basicId, 50000);

    const { month, year } = freshPeriod();
    const run = (await (await request.post('/api/payroll-runs/', { headers: { 'X-CSRFToken': token }, data: { month, year } })).json()) as any;
    await request.post(`/api/payroll-runs/${run.id}/generate/`, { headers: { 'X-CSRFToken': token } });
    const slip = (await (await request.get('/api/salary-slips/')).json()).find((x) => x.run === run.id && x.employee === a.id);

    expect((await request.get('/api/salary-payments/')).status()).toBe(200);

    const pay = await request.post('/api/salary-payments/', {
      headers: { 'X-CSRFToken': token },
      data: { slip: slip.id, amount: '50000.00', payment_date: '2026-01-15', method: 'bank_transfer' },
    });
    expect(pay.status()).toBe(201);
    const payment = (await pay.json()) as any;
    expect(payment.amount).toBe('50000.00');

    // perform_create posts exactly one ledger row.
    const txs = (await (await request.get('/api/account-transactions/?transaction_type=payroll')).json()) as any[];
    const matches = txs.filter((t) => t.reference_type === 'SalaryPayment' && t.reference_id === payment.id);
    expect(matches).toHaveLength(1);

    await cleanup(request, {
      runIds: [run.id],
      employeeIds: [a.id],
      componentIds: [md.basicId, md.taxId, md.allowanceId],
      departmentIds: [md.deptId],
      designationIds: [md.desigId],
    });
  });

  test('HR-API-06 — GET/POST /api/attendance/', async ({ request }) => {
    const token = await loginViaApi(request, 'hr');
    const s = uniq();
    const md = await createMasterData(request, token, s);
    const a = await createEmployee(request, token, { first: 'QA', last: `Api6${s}`, department: md.deptId, designation: md.desigId });
    const attDate = '2026-05-05';

    expect((await request.get('/api/attendance/')).status()).toBe(200);

    const first = await request.post('/api/attendance/', { headers: { 'X-CSRFToken': token }, data: { employee: a.id, date: attDate, status: 'present' } });
    expect(first.status()).toBe(201);
    const firstId = (await first.json()).id;

    const filtered = (await (await request.get(`/api/attendance/?employee=${a.id}&date=${attDate}`)).json()) as any[];
    expect(filtered).toHaveLength(1);

    const dup = await request.post('/api/attendance/', { headers: { 'X-CSRFToken': token }, data: { employee: a.id, date: attDate, status: 'absent' } });
    // CORRECT: duplicate must update or 400, never 500 (see HR-EC-08).
    expect([200, 400]).toContain(dup.status());

    await cleanup(request, {
      employeeIds: [a.id],
      attendanceIds: [firstId],
      componentIds: [md.basicId, md.taxId, md.allowanceId],
      departmentIds: [md.deptId],
      designationIds: [md.desigId],
    });
  });

  test('HR-API-07 — approve / pay actions', async ({ request }) => {
    const token = await loginViaApi(request, 'hr');
    const s = uniq();
    const md = await createMasterData(request, token, s);
    const a = await createEmployee(request, token, { first: 'QA', last: `Api7${s}`, department: md.deptId, designation: md.desigId });
    await addSalary(request, token, a.id, md.basicId, 50000);

    const hrUserId = (await (await request.get('/api/auth/me/')).json()).id;

    // approve action stamps approved_by.
    const leave = (await (await request.post('/api/leaves/', {
      headers: { 'X-CSRFToken': token },
      data: { employee: a.id, leave_type: 'annual', start_date: '2026-04-01', end_date: '2026-04-02', days: 2 },
    })).json()) as any;
    const approved = (await (await request.post(`/api/leaves/${leave.id}/approve/`, { headers: { 'X-CSRFToken': token } })).json()) as any;
    expect(approved.status).toBe('approved');
    expect(approved.approved_by).toBe(hrUserId);

    // pay action posts one ledger row per new payment.
    const { month, year } = freshPeriod();
    const run = (await (await request.post('/api/payroll-runs/', { headers: { 'X-CSRFToken': token }, data: { month, year } })).json()) as any;
    await request.post(`/api/payroll-runs/${run.id}/generate/`, { headers: { 'X-CSRFToken': token } });
    await request.post(`/api/payroll-runs/${run.id}/process/`, { headers: { 'X-CSRFToken': token } });
    const payRes = await request.post(`/api/payroll-runs/${run.id}/pay/`, { headers: { 'X-CSRFToken': token } });
    expect(payRes.status()).toBe(200);
    const payBody = (await payRes.json()) as any;
    expect(payBody.paid).toBeGreaterThanOrEqual(1);

    const payments = (await (await request.get('/api/salary-payments/')).json()) as any[];
    const aPayment = payments.find((p) => p.employee_name === a.full_name);
    const txs = (await (await request.get('/api/account-transactions/?transaction_type=payroll')).json()) as any[];
    const matches = txs.filter((t) => t.reference_type === 'SalaryPayment' && t.reference_id === aPayment.id);
    expect(matches).toHaveLength(1);

    await cleanup(request, {
      runIds: [run.id],
      employeeIds: [a.id],
      componentIds: [md.basicId, md.taxId, md.allowanceId],
      departmentIds: [md.deptId],
      designationIds: [md.desigId],
    });
  });
});
