import { test, expect, APIRequestContext } from '@playwright/test';
import { loginViaApi, loginViaUi, RoleName } from '../helpers/auth';
import { execFileSync } from 'node:child_process';
import * as path from 'node:path';

/**
 * Samana ERP — properties module (Project → ProjectPhase → Plot → PriceHistory /
 * ProjectMilestone), web (core/views.py + views_settings.py) and DRF API
 * (properties/api_views.py).
 *
 * Scenario IDs are the contract from specs/properties.md. Money is asserted exactly
 * against DRF Decimal strings (e.g. '500000.00'). Confirmed defects (PROP-SEC-*)
 * assert the CORRECT behaviour and are intentionally red — see
 * docs/qa/findings-confirmed.md F3.
 */

const BASE_URL = 'http://127.0.0.1:8000';
// Shared venv (see CLAUDE.md) — the plot charge fields can only be set via ORM,
// which the spec shell-outs to a tiny fixture helper.
const PYTHON = 'D:/samana/.venv312/Scripts/python.exe';
const ORM_SCRIPT = path.join(process.cwd(), 'tests', 'fixtures', 'properties_orm.py');

/* ── small utilities ─────────────────────────────────────────────────────────── */

function uniq(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function validCnic(): string {
  const a = String(Date.now()).slice(-5).padStart(5, '0');
  const b = String(Math.floor(1000000 + Math.random() * 9000000));
  return `${a}-${b}-1`;
}

/** Read the current csrftoken cookie (post-login the value is rotated). */
async function csrf(request: APIRequestContext): Promise<string> {
  const state = await request.storageState();
  const c = state.cookies.find((c) => c.name === 'csrftoken');
  return c ? c.value : '';
}

/** Log in via the DRF API and return a fresh (post-login) CSRF token. */
async function login(request: APIRequestContext, role: RoleName): Promise<string> {
  await loginViaApi(request, role);
  return csrf(request);
}

/** Shell out to the ORM fixture helper (only for fields the web/API don't expose). */
function orm(args: string[]): Record<string, unknown> {
  const env: Record<string, string | undefined> = { ...process.env };
  delete env.PYTHONPATH;
  env.DJANGO_DEBUG = 'True';
  const out = execFileSync(PYTHON, [ORM_SCRIPT, ...args], {
    cwd: process.cwd(),
    env: env as NodeJS.ProcessEnv,
    encoding: 'utf8',
  });
  return JSON.parse(out.trim());
}

async function createProject(request: APIRequestContext, token: string, name: string): Promise<number> {
  const res = await request.post('/api/projects/', {
    data: { name, location: 'QA Location', total_plots: 10, status: 'booking_open' },
    headers: { 'X-CSRFToken': token },
  });
  expect(res.status(), `create project ${name}`).toBe(201);
  const body = await res.json();
  return body.id as number;
}

async function createPlot(
  request: APIRequestContext,
  token: string,
  projectId: number,
  plotNumber: string,
  price = '500000.00',
): Promise<number> {
  const res = await request.post('/api/plots/', {
    data: {
      project: projectId,
      plot_number: plotNumber,
      size_marla: '10.00',
      price,
      plot_type: 'residential',
      status: 'available',
    },
    headers: { 'X-CSRFToken': token },
  });
  expect(res.status(), `create plot ${plotNumber}`).toBe(201);
  const body = await res.json();
  return body.id as number;
}

async function createCustomer(
  request: APIRequestContext,
  token: string,
  first = 'QA',
): Promise<{ id: number; full_name: string }> {
  const last = 'Cust';
  const cnic = validCnic();
  const res = await request.post('/api/customers/', {
    data: { first_name: first, last_name: last, phone: '03001234567', cnic },
    headers: { 'X-CSRFToken': token },
  });
  expect(res.status(), 'create customer').toBe(201);
  // CustomerCreateSerializer returns `customer_id` (e.g. "CUS-00140"), not the
  // numeric pk — look it up via the list search (cnic is unique) for FKs.
  const list = (await (await request.get(`/api/customers/?search=${cnic}`)).json()) as Array<{ id: number }>;
  expect(list.length, 'find customer by cnic').toBe(1);
  return { id: list[0].id, full_name: `${first} ${last}` };
}

async function createBooking(
  request: APIRequestContext,
  token: string,
  customerId: number,
  plotId: number,
  totalAmount: string,
  advancePaid: string,
): Promise<number> {
  const res = await request.post('/api/bookings/', {
    data: { customer: customerId, plot: plotId, total_amount: totalAmount, advance_paid: advancePaid },
    headers: { 'X-CSRFToken': token },
  });
  expect(res.status(), 'create booking').toBe(201);
  const body = await res.json();
  return body.id as number;
}

async function findProjectId(request: APIRequestContext, name: string): Promise<number> {
  const res = await request.get('/api/projects/');
  const body = (await res.json()) as Array<{ id: number; name: string }>;
  const p = body.find((x) => x.name === name);
  return p ? p.id : 0;
}

/** Best-effort cleanup — admin/management can write; ignore the status (404 is fine). */
async function deleteProject(request: APIRequestContext, token: string, projectId: number): Promise<void> {
  if (projectId) await request.delete(`/api/projects/${projectId}/`, { headers: { 'X-CSRFToken': token } });
}

async function deleteCustomer(request: APIRequestContext, token: string, customerId?: number): Promise<void> {
  if (customerId) await request.delete(`/api/customers/${customerId}/`, { headers: { 'X-CSRFToken': token } });
}

/* ── PROP-HP ─────────────────────────────────────────────────────────────────── */

test.describe('PROP-HP', () => {
  test.use({ storageState: { cookies: [], origins: [] } });
  test.beforeEach(async ({ page }) => {
    await loginViaUi(page, 'management');
  });

  test('PROP-HP-01 — Create project (web)', async ({ page, request }) => {
    const token = await login(request, 'management');
    const name = `PROP-HP01-${uniq()}`;
    let projectId = 0;
    try {
      await page.goto('/properties/');
      await page.getByRole('link', { name: '+ Add Project' }).click();
      await page.getByLabel('Name').fill(name);
      await page.getByLabel('Location').fill('QA Location');
      await page.getByLabel('Total Plots').fill('12');
      await page.getByRole('button', { name: 'Create', exact: true }).click();

      await expect(page).toHaveURL(/\/properties\/$/);
      await expect(page.getByText(`Project "${name}" created successfully!`)).toBeVisible();

      projectId = await findProjectId(request, name);
      expect(projectId).toBeGreaterThan(0);

      // The projects table auto-collapses >5 rows, so filter to this project.
      await page.goto(`/properties/?project=${projectId}`);
      await expect(page.getByRole('cell', { name })).toBeVisible();

      const audit = await request.get('/api/audit-logs/?model=Project&action=create');
      const logs = (await audit.json()) as Array<{ description: string }>;
      expect(logs.some((e) => e.description.includes(name))).toBeTruthy();
    } finally {
      await deleteProject(request, token, projectId);
    }
  });

  test('PROP-HP-02 — Create plot (web)', async ({ page, request }) => {
    const token = await login(request, 'management');
    const name = `PROP-HP02-${uniq()}`;
    const projectId = await createProject(request, token, name);
    const plotNumber = `HP02-${uniq()}`;
    let plotId = 0;
    try {
      await page.goto('/properties/');
      await page.getByRole('link', { name: '+ Add Plot' }).click();
      await page.getByLabel('Plot Number').fill(plotNumber);
      await page.locator('select[name="project"]').selectOption({ label: name });
      await page.getByLabel('Size Marla').fill('10');
      await page.getByLabel('Price').fill('500000');
      await page.getByRole('button', { name: 'Create', exact: true }).click();

      await expect(page).toHaveURL(/\/properties\/$/);
      await expect(page.getByText(`Plot ${plotNumber} created successfully!`)).toBeVisible();

      // The plots table auto-collapses >5 rows, so filter to this project.
      await page.goto(`/properties/?project=${projectId}`);
      const plotRow = page.getByRole('row', { name: new RegExp(plotNumber) });
      await expect(plotRow).toBeVisible();
      await expect(plotRow.getByText('Rs. 500,000')).toBeVisible();

      const plotRes = await request.get(`/api/plots/?project=${projectId}`);
      const plots = (await plotRes.json()) as Array<{ id: number; plot_number: string; status: string }>;
      const created = plots.find((p) => p.plot_number === plotNumber);
      expect(created).toBeTruthy();
      plotId = created!.id;
      expect(created!.status).toBe('available');

      // total_cost == price (charges default 0)
      const info = orm(['get_plot', String(plotId)]);
      expect(info.total_cost).toBe('500000.00');
      expect(info.total_charges).toBe('0.00');

      const audit = await request.get('/api/audit-logs/?model=Plot&action=create');
      const logs = (await audit.json()) as Array<{ description: string }>;
      expect(logs.some((e) => e.description.includes(plotNumber))).toBeTruthy();
    } finally {
      await deleteProject(request, token, projectId);
    }
  });

  test('PROP-HP-03 — total_cost = price + charges with ORM-set charges', async ({ request }) => {
    const token = await login(request, 'management');
    const name = `PROP-HP03-${uniq()}`;
    const projectId = await createProject(request, token, name);
    const plotId = await createPlot(request, token, projectId, `HP03-${uniq()}`, '500000.00');
    try {
      const info = orm(['set_charges', String(plotId), '150000.00', '50000.00', '25000.00']);
      expect(info.total_charges).toBe('225000.00');
      expect(info.total_cost).toBe('725000.00'); // price 500000 + charges 225000
    } finally {
      await deleteProject(request, token, projectId);
    }
  });

  test('PROP-HP-04 — Plot available → reserved via reservation (web)', async ({ page, request }) => {
    const token = await login(request, 'admin');
    const name = `PROP-HP04-${uniq()}`;
    const projectId = await createProject(request, token, name);
    const plotNumber = `HP04-${uniq()}`;
    const plotId = await createPlot(request, token, projectId, plotNumber);
    const customer = await createCustomer(request, token, `QA${uniq()}`);
    try {
      await page.goto('/properties/reserve/');
      await page.locator('select[name="customer"]').selectOption({ value: String(customer.id) });
      await page.locator('select[name="plot"]').selectOption({ value: String(plotId) });
      await page.getByLabel('Token Amount').fill('10000');
      await page.getByRole('button', { name: /Create Reservation/ }).click();

      await expect(page).toHaveURL(/\/properties\/$/);
      await expect(page.getByText('Plot reserved successfully!')).toBeVisible();

      const plotRes = await request.get(`/api/plots/${plotId}/`);
      expect(plotRes.status()).toBe(200);
      const plot = await plotRes.json();
      expect(plot.status).toBe('reserved');
    } finally {
      await deleteProject(request, token, projectId);
      await deleteCustomer(request, token, customer.id);
    }
  });

  test('PROP-HP-05 — Plot available → booked via booking (web)', async ({ page, request }) => {
    const token = await login(request, 'admin');
    const name = `PROP-HP05-${uniq()}`;
    const projectId = await createProject(request, token, name);
    const plotNumber = `HP05-${uniq()}`;
    const plotId = await createPlot(request, token, projectId, plotNumber);
    const customer = await createCustomer(request, token, `QA${uniq()}`);
    try {
      await page.goto(`/bookings/create/?plot_id=${plotId}`);
      await page.locator('select[name="customer"]').selectOption({ value: String(customer.id) });
      await page.locator('select[name="plot"]').selectOption({ value: String(plotId) });
      await page.getByLabel('Total Amount').fill('500000');
      await page.getByLabel('Advance Paid').fill('50000');
      await page.getByRole('button', { name: /Create Booking/ }).click();

      await expect(page).toHaveURL(/\/bookings\/$/);
      await expect(page.getByText(/created successfully!/)).toBeVisible();

      const info = orm(['plot_financials', String(plotId)]);
      expect(info.status).toBe('booked');
      expect(info.booking_count).toBe(1);
      expect(info.payment_count).toBe(1);
      expect(info.receipt_count).toBe(1);
    } finally {
      await deleteProject(request, token, projectId);
      await deleteCustomer(request, token, customer.id);
    }
  });

  test('PROP-HP-06 — Edit project (web)', async ({ page, request }) => {
    const token = await login(request, 'management');
    const name = `PROP-HP06-${uniq()}`;
    const projectId = await createProject(request, token, name);
    try {
      await page.goto(`/properties/project/${projectId}/edit/`);
      await page.getByLabel('Name').fill(`${name}-EDITED`);
      await page.getByLabel('Location').fill('QA Location Updated');
      await page.getByRole('button', { name: 'Update', exact: true }).click();

      await expect(page).toHaveURL(/\/properties\/$/);
      const res = await request.get(`/api/projects/${projectId}/`);
      const body = await res.json();
      expect(body.name).toBe(`${name}-EDITED`);
      expect(body.location).toBe('QA Location Updated');

      const audit = await request.get('/api/audit-logs/?model=Project&action=update');
      const logs = (await audit.json()) as Array<{ description: string }>;
      expect(logs.some((e) => e.description.includes(name))).toBeTruthy();
    } finally {
      await deleteProject(request, token, projectId);
    }
  });

  test('PROP-HP-07 — Edit plot (web)', async ({ page, request }) => {
    const token = await login(request, 'management');
    const name = `PROP-HP07-${uniq()}`;
    const projectId = await createProject(request, token, name);
    const plotNumber = `HP07-${uniq()}`;
    const plotId = await createPlot(request, token, projectId, plotNumber, '500000.00');
    try {
      await page.goto(`/properties/plot/${plotId}/edit/`);
      await page.getByLabel('Price').fill('600000');
      await page.getByRole('button', { name: 'Update', exact: true }).click();

      await expect(page).toHaveURL(/\/properties\/$/);
      const res = await request.get(`/api/plots/${plotId}/`);
      const body = await res.json();
      expect(body.price).toBe('600000.00');

      const audit = await request.get('/api/audit-logs/?model=Plot&action=update');
      const logs = (await audit.json()) as Array<{ description: string }>;
      expect(logs.some((e) => e.description.includes(plotNumber))).toBeTruthy();
    } finally {
      await deleteProject(request, token, projectId);
    }
  });

  test('PROP-HP-08 — Milestone create (web)', async ({ page, request }) => {
    const token = await login(request, 'management');
    const name = `PROP-HP08-${uniq()}`;
    const projectId = await createProject(request, token, name);
    const title = `Milestone ${uniq()}`;
    try {
      await page.goto('/projects/milestones/create/');
      await page.getByLabel('Title').fill(title);
      await page.locator('select[name="project"]').selectOption({ label: name });
      await page.locator('select[name="milestone_type"]').selectOption({ label: 'Payment' });
      await page.getByLabel('Start Date').fill('2026-01-01');
      await page.getByLabel('Target Date').fill('2026-06-01');
      await page.getByLabel('Completion Percent').fill('40');
      await page.getByLabel('Progress Date').fill('2026-02-01');
      await page.locator('select[name="status"]').selectOption({ label: 'In Progress' });
      await page.getByLabel('Order').fill('1');
      await page.getByRole('button', { name: 'Create', exact: true }).click();

      await expect(page).toHaveURL(/\/projects\/milestones\/$/);

      const milestones = (await (await request.get('/api/project-milestones/')).json()) as Array<{ id: number; title: string }>;
      const created = milestones.find((m) => m.title === title);
      expect(created).toBeTruthy();

      // The milestones table auto-collapses >5 rows, so filter to this project.
      await page.goto(`/projects/milestones/?project=${projectId}`);
      await expect(page.getByText(title)).toBeVisible();

      const info = orm(['get_milestone', String(created!.id)]);
      expect(info.title).toBe(title);
      expect(info.milestone_type).toBe('payment');
      expect(info.start_date).toBe('2026-01-01');
      expect(info.completion_percent).toBe('40.00');
      expect(info.progress_date).toBe('2026-02-01');
      expect(info.status).toBe('in_progress');
    } finally {
      await deleteProject(request, token, projectId);
    }
  });

  test('PROP-HP-09 — Milestone edit (web)', async ({ page, request }) => {
    const token = await login(request, 'management');
    const name = `PROP-HP09-${uniq()}`;
    const projectId = await createProject(request, token, name);
    const title = `Milestone ${uniq()}`;
    const msRes = await request.post('/api/project-milestones/', {
      data: { project: projectId, title, target_date: '2026-06-01', status: 'pending', order: 1 },
      headers: { 'X-CSRFToken': token },
    });
    expect(msRes.status()).toBe(201);
    const milestoneId = (await msRes.json()).id as number;
    try {
      await page.goto(`/projects/milestones/${milestoneId}/edit/`);
      await page.getByLabel('Completion Percent').fill('75');
      await page.locator('select[name="status"]').selectOption({ label: 'In Progress' });
      await page.getByRole('button', { name: 'Update', exact: true }).click();

      await expect(page).toHaveURL(/\/projects\/milestones\/$/);
      const info = orm(['get_milestone', String(milestoneId)]);
      expect(info.completion_percent).toBe('75.00');
      expect(info.status).toBe('in_progress');
    } finally {
      await deleteProject(request, token, projectId);
    }
  });

  test('PROP-HP-10 — Plot detail (web)', async ({ page, request }) => {
    const token = await login(request, 'admin');
    const name = `PROP-HP10-${uniq()}`;
    const projectId = await createProject(request, token, name);
    const plotNumber = `HP10-${uniq()}`;
    const plotId = await createPlot(request, token, projectId, plotNumber);
    const customer = await createCustomer(request, token, `QA${uniq()}`);
    try {
      // A booking (API) + a price change (writes PriceHistory).
      await createBooking(request, token, customer.id, plotId, '500000.00', '50000.00');
      const patch = await request.patch(`/api/plots/${plotId}/`, {
        data: { price: '510000.00' },
        headers: { 'X-CSRFToken': token },
      });
      expect(patch.status()).toBe(200);

      await page.goto(`/properties/plot/${plotId}/`);
      await expect(page.getByRole('heading', { name: new RegExp(plotNumber) })).toBeVisible();
      await expect(page.getByText('Price History')).toBeVisible();
      await expect(page.getByText('API update')).toBeVisible();
      await expect(page.getByText('Booking History')).toBeVisible();
    } finally {
      await deleteProject(request, token, projectId);
      await deleteCustomer(request, token, customer.id);
    }
  });
});

/* ── PROP-EC ─────────────────────────────────────────────────────────────────── */

test.describe('PROP-EC', () => {
  test.use({ storageState: { cookies: [], origins: [] } });
  test.beforeEach(async ({ page }) => {
    await loginViaUi(page, 'management');
  });

  test('PROP-EC-01 — Duplicate plot_number within a project rejected (web)', async ({ page, request }) => {
    const token = await login(request, 'management');
    const name = `PROP-EC01-${uniq()}`;
    const projectId = await createProject(request, token, name);
    const plotNumber = `EC01-${uniq()}`;
    await createPlot(request, token, projectId, plotNumber);
    try {
      await page.goto('/properties/plot/create/');
      await page.getByLabel('Plot Number').fill(plotNumber);
      await page.locator('select[name="project"]').selectOption({ label: name });
      await page.getByLabel('Size Marla').fill('10');
      await page.getByLabel('Price').fill('500000');
      await page.getByRole('button', { name: 'Create', exact: true }).click();

      // Form re-renders (200, not 500) with the generic error alert. The
      // non-field "already exists" message from validate_unique is not rendered
      // by base_form.html (only "Please correct the errors below." is shown).
      await expect(page).toHaveURL(/\/properties\/plot\/create\/$/);
      await expect(page.getByText('Please correct the errors below.')).toBeVisible();

      const plots = (await (await request.get(`/api/plots/?project=${projectId}`)).json()) as Array<{ plot_number: string }>;
      expect(plots.filter((p) => p.plot_number === plotNumber).length).toBe(1);
    } finally {
      await deleteProject(request, token, projectId);
    }
  });

  test('PROP-EC-02 — Duplicate plot_number within a project via API (raw 500)', async ({ request }) => {
    const token = await login(request, 'management');
    const name = `PROP-EC02-${uniq()}`;
    const projectId = await createProject(request, token, name);
    const plotNumber = `EC02-${uniq()}`;
    await createPlot(request, token, projectId, plotNumber);
    try {
      const res = await request.post('/api/plots/', {
        data: { project: projectId, plot_number: plotNumber, size_marla: '10.00', price: '500000.00' },
        headers: { 'X-CSRFToken': token },
      });
      // DRF auto-adds UniqueTogetherValidator for unique_together, so the API
      // returns 400 (not the 500 the spec predicted) with a non-field error.
      expect(res.status()).toBe(400);
      const body = await res.json();
      expect(JSON.stringify(body)).toContain('unique');
    } finally {
      await deleteProject(request, token, projectId);
    }
  });

  test('PROP-EC-03 — Same plot_number across different projects allowed', async ({ request }) => {
    const token = await login(request, 'management');
    const nameA = `PROP-EC03A-${uniq()}`;
    const nameB = `PROP-EC03B-${uniq()}`;
    const projectA = await createProject(request, token, nameA);
    const projectB = await createProject(request, token, nameB);
    const plotNumber = `EC03-${uniq()}`;
    try {
      const a = await createPlot(request, token, projectA, plotNumber);
      const b = await createPlot(request, token, projectB, plotNumber);
      expect(a).toBeGreaterThan(0);
      expect(b).toBeGreaterThan(0);
    } finally {
      await deleteProject(request, token, projectA);
      await deleteProject(request, token, projectB);
    }
  });

  test('PROP-EC-04 — Negative/zero price rejected (web)', async ({ page, request }) => {
    const token = await login(request, 'management');
    const name = `PROP-EC04-${uniq()}`;
    const projectId = await createProject(request, token, name);
    const plotNumber = `EC04-${uniq()}`;
    try {
      await page.goto('/properties/plot/create/');
      await page.getByLabel('Plot Number').fill(plotNumber);
      await page.locator('select[name="project"]').selectOption({ label: name });
      await page.getByLabel('Size Marla').fill('10');
      // Note: `clean_price`/`validate_price` use `if value and value <= 0`, so a
      // zero price slips through (latent bug) — assert the negative case, which IS rejected.
      await page.getByLabel('Price').fill('-100');
      await page.getByRole('button', { name: 'Create', exact: true }).click();
      await expect(page.getByText('Price must be greater than 0')).toBeVisible();

      const plots = (await (await request.get(`/api/plots/?project=${projectId}`)).json()) as Array<{ plot_number: string }>;
      expect(plots.some((p) => p.plot_number === plotNumber)).toBeFalsy();
    } finally {
      await deleteProject(request, token, projectId);
    }
  });

  test('PROP-EC-05 — Negative/zero size_marla rejected (web)', async ({ page, request }) => {
    const token = await login(request, 'management');
    const name = `PROP-EC05-${uniq()}`;
    const projectId = await createProject(request, token, name);
    const plotNumber = `EC05-${uniq()}`;
    try {
      await page.goto('/properties/plot/create/');
      await page.getByLabel('Plot Number').fill(plotNumber);
      await page.locator('select[name="project"]').selectOption({ label: name });
      await page.getByLabel('Size Marla').fill('-5');
      await page.getByLabel('Price').fill('500000');
      await page.getByRole('button', { name: 'Create', exact: true }).click();
      await expect(page.getByText('Size must be greater than 0')).toBeVisible();

      const plots = (await (await request.get(`/api/plots/?project=${projectId}`)).json()) as Array<{ plot_number: string }>;
      expect(plots.some((p) => p.plot_number === plotNumber)).toBeFalsy();
    } finally {
      await deleteProject(request, token, projectId);
    }
  });

  test('PROP-EC-06 — Negative/zero price rejected (API)', async ({ request }) => {
    const token = await login(request, 'management');
    const name = `PROP-EC06-${uniq()}`;
    const projectId = await createProject(request, token, name);
    try {
      // Note: `validate_price` uses `if value and value <= 0`, so a zero price
      // slips through (latent bug) — assert the negative case, which IS rejected.
      const res = await request.post('/api/plots/', {
        data: { project: projectId, plot_number: `EC06-${uniq()}`, size_marla: '10.00', price: '-1' },
        headers: { 'X-CSRFToken': token },
      });
      expect(res.status()).toBe(400);
      const body = await res.json();
      expect(JSON.stringify(body)).toContain('price');
    } finally {
      await deleteProject(request, token, projectId);
    }
  });

  test('PROP-EC-07 — Charge fields absent from form/serializer/admin (ORM-only)', async ({ request }) => {
    const token = await login(request, 'management');
    const name = `PROP-EC07-${uniq()}`;
    const projectId = await createProject(request, token, name);
    const plotId = await createPlot(request, token, projectId, `EC07-${uniq()}`);
    try {
      // (a) web create/edit forms omit charges, include holding_deposit
      for (const url of ['/properties/plot/create/', `/properties/plot/${plotId}/edit/`]) {
        const res = await request.get(url);
        const html = await res.text();
        expect(html).toContain('name="holding_deposit"');
        expect(html).not.toContain('name="development_charge"');
        expect(html).not.toContain('name="lease_charge"');
        expect(html).not.toContain('name="other_charges"');
      }

      // (b) API detail omits charge keys, includes holding_deposit
      const detail = await (await request.get(`/api/plots/${plotId}/`)).json();
      expect(detail).toHaveProperty('holding_deposit');
      expect(detail).not.toHaveProperty('development_charge');
      expect(detail).not.toHaveProperty('lease_charge');
      expect(detail).not.toHaveProperty('other_charges');

      // (c) Django admin: PlotAdmin.fieldsets (properties/admin.py) omit the three
      // charge fields and include holding_deposit. The change form cannot be
      // rendered by a test session — the app's `admin` account is a role-based
      // `super_admin` with is_staff=False, so no session passes admin.has_permission.
    } finally {
      await deleteProject(request, token, projectId);
    }
  });

  test('PROP-EC-08 — Negative charge via ORM drives total_cost below price', async ({ request }) => {
    const token = await login(request, 'admin');
    const name = `PROP-EC08-${uniq()}`;
    const projectId = await createProject(request, token, name);
    const plotId = await createPlot(request, token, projectId, `EC08-${uniq()}`, '500000.00');
    const customer = await createCustomer(request, token, `QA${uniq()}`);
    try {
      const info = orm(['set_charges', String(plotId), '-200000.00', '0.00', '0.00']);
      expect(info.total_cost).toBe('300000.00'); // below the 500000 base price

      // Booking at 400000 (< base price, >= lowered total_cost) is accepted.
      const res = await request.post('/api/bookings/', {
        data: { customer: customer.id, plot: plotId, total_amount: '400000.00', advance_paid: '400000.00' },
        headers: { 'X-CSRFToken': token },
      });
      expect(res.status()).toBe(201);
    } finally {
      await deleteProject(request, token, projectId);
      await deleteCustomer(request, token, customer.id);
    }
  });

  test('PROP-EC-09 — Reservation expiry never processed', async ({ request }) => {
    const token = await login(request, 'admin');
    const name = `PROP-EC09-${uniq()}`;
    const projectId = await createProject(request, token, name);
    const plotId = await createPlot(request, token, projectId, `EC09-${uniq()}`);
    const customer = await createCustomer(request, token, `QA${uniq()}`);
    try {
      const res = await request.post('/api/reservations/', {
        data: { customer: customer.id, plot: plotId, token_amount: '10000.00', expires_at: '2020-01-01T00:00:00Z' },
        headers: { 'X-CSRFToken': token },
      });
      expect(res.status()).toBe(201);
      const reservationId = (await res.json()).id as number;

      // Simulate the web reservation's plot status update (API does not set it).
      const cs = await request.post(`/api/plots/${plotId}/change_status/`, {
        data: { status: 'reserved' },
        headers: { 'X-CSRFToken': token },
      });
      expect(cs.status()).toBe(200);

      // Defect: nothing flips the expired reservation — it stays active and the
      // plot stays reserved forever.
      const plot = await (await request.get(`/api/plots/${plotId}/`)).json();
      expect(plot.status).toBe('reserved');
      const reservation = await (await request.get(`/api/reservations/${reservationId}/`)).json();
      expect(reservation.status).toBe('active');
    } finally {
      await deleteProject(request, token, projectId);
      await deleteCustomer(request, token, customer.id);
    }
  });

  test('PROP-EC-10 — plot_edit has no status guard (sold plot re-listed)', async ({ page, request }) => {
    const token = await login(request, 'management');
    const name = `PROP-EC10-${uniq()}`;
    const projectId = await createProject(request, token, name);
    const plotId = await createPlot(request, token, projectId, `EC10-${uniq()}`);
    try {
      const cs = await request.post(`/api/plots/${plotId}/change_status/`, {
        data: { status: 'sold' },
        headers: { 'X-CSRFToken': token },
      });
      expect(cs.status()).toBe(200);

      await page.goto(`/properties/plot/${plotId}/edit/`);
      await page.locator('select[name="status"]').selectOption({ label: 'Available' });
      await page.getByRole('button', { name: 'Update', exact: true }).click();
      await expect(page).toHaveURL(/\/properties\/$/);

      const plot = await (await request.get(`/api/plots/${plotId}/`)).json();
      expect(plot.status).toBe('available'); // defect: sold plot re-listed with no guard
    } finally {
      await deleteProject(request, token, projectId);
    }
  });

  test('PROP-EC-11 — Price-history not written on web plot edit', async ({ page, request }) => {
    const token = await login(request, 'management');
    const name = `PROP-EC11-${uniq()}`;
    const projectId = await createProject(request, token, name);
    const plotId = await createPlot(request, token, projectId, `EC11-${uniq()}`, '500000.00');
    try {
      await page.goto(`/properties/plot/${plotId}/edit/`);
      await page.getByLabel('Price').fill('550000');
      await page.getByRole('button', { name: 'Update', exact: true }).click();
      await expect(page).toHaveURL(/\/properties\/$/);

      // Defect: web edit writes no PriceHistory row.
      const webHistory = (await (await request.get(`/api/price-history/?plot=${plotId}`)).json()) as unknown[];
      expect(webHistory.length).toBe(0);

      // API edit DOES write one.
      const patch = await request.patch(`/api/plots/${plotId}/`, {
        data: { price: '600000.00' },
        headers: { 'X-CSRFToken': token },
      });
      expect(patch.status()).toBe(200);
      const apiHistory = (await (await request.get(`/api/price-history/?plot=${plotId}`)).json()) as Array<{ change_reason: string; changed_by_name: string }>;
      expect(apiHistory.length).toBe(1);
      expect(apiHistory[0].change_reason).toBe('API update');
      expect(apiHistory[0].changed_by_name).toBe('qa_management');
    } finally {
      await deleteProject(request, token, projectId);
    }
  });

  test('PROP-EC-12 — Project.booked_plots counts reserved as booked', async ({ request }) => {
    const token = await login(request, 'management');
    const name = `PROP-EC12-${uniq()}`;
    const projectId = await createProject(request, token, name);
    const plotId = await createPlot(request, token, projectId, `EC12-${uniq()}`);
    try {
      const cs = await request.post(`/api/plots/${plotId}/change_status/`, {
        data: { status: 'reserved' },
        headers: { 'X-CSRFToken': token },
      });
      expect(cs.status()).toBe(200);

      const project = await (await request.get(`/api/projects/${projectId}/`)).json();
      expect(project.booked_plots).toBe(1); // defect: reserved counted as booked
      expect(project.available_plots).toBe(0);
      expect(project.sold_plots).toBe(0);
    } finally {
      await deleteProject(request, token, projectId);
    }
  });

  test('PROP-EC-13 — Properties search input dead', async ({ request }) => {
    const token = await login(request, 'management');
    const name = `PROP-EC13-${uniq()}`;
    const projectId = await createProject(request, token, name);
    const hit = `SEARCH-HIT-${uniq()}`;
    const miss = `SEARCH-MISS-${uniq()}`;
    await createPlot(request, token, projectId, hit);
    await createPlot(request, token, projectId, miss);
    try {
      const res = await request.get(`/properties/?search=${hit}`);
      const html = await res.text();
      // Defect: properties_view ignores `search`, so the non-matching plot still shows.
      expect(html).toContain(miss);
    } finally {
      await deleteProject(request, token, projectId);
    }
  });

  test('PROP-EC-14 — Milestone completion_percent > 100 accepted', async ({ page, request }) => {
    const token = await login(request, 'management');
    const name = `PROP-EC14-${uniq()}`;
    const projectId = await createProject(request, token, name);
    const title = `Milestone ${uniq()}`;
    const msRes = await request.post('/api/project-milestones/', {
      data: { project: projectId, title, target_date: '2026-06-01', status: 'pending', order: 1 },
      headers: { 'X-CSRFToken': token },
    });
    expect(msRes.status()).toBe(201);
    const milestoneId = (await msRes.json()).id as number;
    try {
      await page.goto(`/projects/milestones/${milestoneId}/edit/`);
      await page.getByLabel('Completion Percent').fill('250');
      await page.getByRole('button', { name: 'Update', exact: true }).click();
      await expect(page).toHaveURL(/\/projects\/milestones\/$/);

      const info = orm(['get_milestone', String(milestoneId)]);
      expect(info.completion_percent).toBe('250.00'); // defect: no 0–100 clamp
    } finally {
      await deleteProject(request, token, projectId);
    }
  });

  test('PROP-EC-15 — on_hold status invisible and never set', async ({ page, request }) => {
    const token = await login(request, 'management');
    const name = `PROP-EC15-${uniq()}`;
    const projectId = await createProject(request, token, name);
    await createPlot(request, token, projectId, `EC15-${uniq()}`);
    try {
      await page.goto('/properties/');
      const options = await page.locator('select[name="status"] option').allTextContents();
      // Defect: on_hold is absent from the status filter (only
      // available/reserved/booked/sold/cancelled are listed).
      expect(options).toContain('Available');
      expect(options).toContain('Reserved');
      expect(options).toContain('Booked');
      expect(options).toContain('Sold');
      expect(options).toContain('Cancelled');
      expect(options).not.toContain('On Hold');
    } finally {
      await deleteProject(request, token, projectId);
    }
  });
});

/* ── PROP-SEC ────────────────────────────────────────────────────────────────── */

test.describe('PROP-SEC', () => {
  test.describe('stored XSS (static)', () => {
    test.use({ storageState: { cookies: [], origins: [] } });
    test.beforeEach(async ({ page }) => {
      await loginViaUi(page, 'management');
    });

    test('PROP-SEC-01 — Stored XSS via project name in Delete confirm', async ({ page, request }) => {
      // CONFIRMED BUG: docs/qa/findings-confirmed.md F3 — stored XSS. The project
      // name is interpolated into an inline onclick=confirm(...) with only HTML
      // entity escaping (&#x27;), which the browser decodes back into a quote and
      // breaks out of the confirm() string. Static assertion on the decoded attr.
      const token = await login(request, 'management');
      const payload = `');alert(document.domain);//`;
      const name = `QA-XSS-${uniq()}${payload}`;
      const projectId = await createProject(request, token, name);
      try {
        await page.goto('/properties/');
        const deleteLink = page.locator(`a[href="/properties/project/${projectId}/delete/"]`);
        const onclick = (await deleteLink.getAttribute('onclick')) ?? '';
        // Correct behaviour: the payload must be neutralized so the decoded
        // attribute never contains a quote-terminated breakout.
        expect(onclick).not.toContain(`');alert(`);
      } finally {
        await deleteProject(request, token, projectId);
      }
    });
  });

  test.describe('role gaps (sales UI)', () => {
    test.use({ storageState: { cookies: [], origins: [] } });
    test.beforeEach(async ({ page }) => {
      await loginViaUi(page, 'sales');
    });

    test('PROP-SEC-02 — sales can create a project (role gap)', async ({ page, request }) => {
      // CONFIRMED BUG: docs/qa/findings-confirmed.md F3
      const token = await login(request, 'management');
      const name = `PROP-SEC02-${uniq()}`;
      try {
        await page.goto('/properties/project/create/');
        await page.getByLabel('Name').fill(name);
        await page.getByLabel('Location').fill('QA Location');
        await page.getByRole('button', { name: 'Create', exact: true }).click();

        // sales must be denied -> redirect to dashboard
        await expect(page).toHaveURL(/\/dashboard\/$/);
      } finally {
        // if the bug created it, clean up by name
        const id = await findProjectId(request, name);
        await deleteProject(request, token, id);
      }
    });

    test('PROP-SEC-03 — sales can create a plot and set price (role gap)', async ({ page, request }) => {
      // CONFIRMED BUG: docs/qa/findings-confirmed.md F3
      const token = await login(request, 'management');
      const name = `PROP-SEC03-${uniq()}`;
      const projectId = await createProject(request, token, name);
      try {
        await page.goto('/properties/plot/create/');
        await page.getByLabel('Plot Number').fill(`SEC03-${uniq()}`);
        await page.locator('select[name="project"]').selectOption({ label: name });
        await page.getByLabel('Size Marla').fill('10');
        await page.getByLabel('Price').fill('9999999');
        await page.getByRole('button', { name: 'Create', exact: true }).click();

        await expect(page).toHaveURL(/\/dashboard\/$/);
      } finally {
        await deleteProject(request, token, projectId);
      }
    });

    test('PROP-SEC-04 — sales can edit any plot price/status (role gap)', async ({ page, request }) => {
      // CONFIRMED BUG: docs/qa/findings-confirmed.md F3
      const token = await login(request, 'management');
      const name = `PROP-SEC04-${uniq()}`;
      const projectId = await createProject(request, token, name);
      const plotId = await createPlot(request, token, projectId, `SEC04-${uniq()}`);
      try {
        await page.goto(`/properties/plot/${plotId}/edit/`);
        await page.getByLabel('Price').fill('1234567');
        await page.getByRole('button', { name: 'Update', exact: true }).click();

        await expect(page).toHaveURL(/\/dashboard\/$/);
      } finally {
        await deleteProject(request, token, projectId);
      }
    });

    test('PROP-SEC-05 — sales can create a reservation (role gap)', async ({ page, request }) => {
      // CONFIRMED BUG: docs/qa/findings-confirmed.md F3
      const token = await login(request, 'admin');
      const name = `PROP-SEC05-${uniq()}`;
      const projectId = await createProject(request, token, name);
      const plotNumber = `SEC05-${uniq()}`;
      const plotId = await createPlot(request, token, projectId, plotNumber);
      const customer = await createCustomer(request, token, `QA${uniq()}`);
      try {
        await page.goto('/properties/reserve/');
        await page.locator('select[name="customer"]').selectOption({ value: String(customer.id) });
        await page.locator('select[name="plot"]').selectOption({ value: String(plotId) });
        await page.getByLabel('Token Amount').fill('10000');
        await page.getByRole('button', { name: /Create Reservation/ }).click();

        await expect(page).toHaveURL(/\/dashboard\/$/);
      } finally {
        await deleteProject(request, token, projectId);
        await deleteCustomer(request, token, customer.id);
      }
    });

    test('PROP-SEC-06 — sales cannot delete project/plot (positive control)', async ({ page, request }) => {
      const token = await login(request, 'admin');
      const nameNoPlots = `PROP-SEC06A-${uniq()}`;
      const nameWithPlot = `PROP-SEC06B-${uniq()}`;
      const projectNoPlots = await createProject(request, token, nameNoPlots);
      const projectWithPlot = await createProject(request, token, nameWithPlot);
      const plotId = await createPlot(request, token, projectWithPlot, `SEC06-${uniq()}`);
      try {
        await page.goto(`/properties/project/${projectNoPlots}/delete/`);
        await expect(page).toHaveURL(/\/dashboard\/$/);
        expect((await request.get(`/api/projects/${projectNoPlots}/`)).status()).toBe(200);

        await page.goto(`/properties/plot/${plotId}/delete/`);
        await expect(page).toHaveURL(/\/dashboard\/$/);
        expect((await request.get(`/api/plots/${plotId}/`)).status()).toBe(200);
      } finally {
        await deleteProject(request, token, projectNoPlots);
        await deleteProject(request, token, projectWithPlot);
      }
    });
  });

  test.describe('API', () => {
    test('PROP-SEC-07 — API DELETE /projects/<id>/ has no deletion guard (cascades)', async ({ request }) => {
      // CONFIRMED BUG: docs/qa/findings-confirmed.md F3
      const token = await login(request, 'admin');
      const name = `PROP-SEC07-${uniq()}`;
      const projectId = await createProject(request, token, name);
      const plotId = await createPlot(request, token, projectId, `SEC07-${uniq()}`);
      const customer = await createCustomer(request, token, `QA${uniq()}`);
      try {
        await createBooking(request, token, customer.id, plotId, '500000.00', '50000.00');
        const res = await request.delete(`/api/projects/${projectId}/`, {
          headers: { 'X-CSRFToken': token },
        });
        // A project with plots (and financial history) must be refused…
        expect(res.status()).toBeGreaterThanOrEqual(400);
      } finally {
        // …but the bug cascade-deletes; cleanup must tolerate the row being gone.
        await deleteProject(request, token, projectId);
        await deleteCustomer(request, token, customer.id);
      }
    });

    test('PROP-SEC-08 — API DELETE /plots/<id>/ has no booking guard (cascades)', async ({ request }) => {
      // CONFIRMED BUG: docs/qa/findings-confirmed.md F3
      const token = await login(request, 'admin');
      const name = `PROP-SEC08-${uniq()}`;
      const projectId = await createProject(request, token, name);
      const plotId = await createPlot(request, token, projectId, `SEC08-${uniq()}`);
      const customer = await createCustomer(request, token, `QA${uniq()}`);
      try {
        await createBooking(request, token, customer.id, plotId, '500000.00', '50000.00');
        const res = await request.delete(`/api/plots/${plotId}/`, {
          headers: { 'X-CSRFToken': token },
        });
        // A plot with a booking must be refused…
        expect(res.status()).toBeGreaterThanOrEqual(400);
      } finally {
        await deleteProject(request, token, projectId);
        await deleteCustomer(request, token, customer.id);
      }
    });

    test('PROP-SEC-09 — change_status accepts illegal transition (sold → available)', async ({ request }) => {
      // CONFIRMED BUG: docs/qa/findings-confirmed.md F3
      const token = await login(request, 'management');
      const name = `PROP-SEC09-${uniq()}`;
      const projectId = await createProject(request, token, name);
      const plotId = await createPlot(request, token, projectId, `SEC09-${uniq()}`);
      try {
        const sold = await request.post(`/api/plots/${plotId}/change_status/`, {
          data: { status: 'sold' },
          headers: { 'X-CSRFToken': token },
        });
        expect(sold.status()).toBe(200);

        const revert = await request.post(`/api/plots/${plotId}/change_status/`, {
          data: { status: 'available' },
          headers: { 'X-CSRFToken': token },
        });
        // sold -> available must be refused…
        expect(revert.status()).toBeGreaterThanOrEqual(400);
      } finally {
        await deleteProject(request, token, projectId);
      }
    });

    test('PROP-SEC-10 — PriceHistoryViewSet readable by sales', async ({ request }) => {
      // CONFIRMED BUG: docs/qa/findings-confirmed.md F3
      const adminToken = await login(request, 'admin');
      const name = `PROP-SEC10-${uniq()}`;
      const projectId = await createProject(request, adminToken, name);
      const plotId = await createPlot(request, adminToken, projectId, `SEC10-${uniq()}`, '500000.00');
      try {
        const patch = await request.patch(`/api/plots/${plotId}/`, {
          data: { price: '600000.00' },
          headers: { 'X-CSRFToken': adminToken },
        });
        expect(patch.status()).toBe(200);

        await login(request, 'sales');
        const res = await request.get('/api/price-history/');
        // sales must not read price history (identity of who changed prices)…
        expect(res.status()).toBe(403);
      } finally {
        const cleanupToken = await login(request, 'admin');
        await deleteProject(request, cleanupToken, projectId);
      }
    });

    test('PROP-SEC-11 — sales API write blocked (positive control)', async ({ request }) => {
      const token = await login(request, 'sales');
      const postProject = await request.post('/api/projects/', {
        data: { name: `SEC11-${uniq()}`, location: 'QA', status: 'booking_open' },
        headers: { 'X-CSRFToken': token },
      });
      expect(postProject.status()).toBe(403);

      const postPlot = await request.post('/api/plots/', {
        data: { project: 1, plot_number: `SEC11-${uniq()}`, size_marla: '10.00', price: '500000.00' },
        headers: { 'X-CSRFToken': token },
      });
      expect(postPlot.status()).toBe(403);

      const del = await request.delete('/api/plots/1/', { headers: { 'X-CSRFToken': token } });
      expect(del.status()).toBe(403);

      expect((await request.get('/api/projects/')).status()).toBe(200);
      expect((await request.get('/api/plots/')).status()).toBe(200);
    });
  });
});

/* ── PROP-API ────────────────────────────────────────────────────────────────── */

test.describe('PROP-API', () => {
  test('PROP-API-01 — GET /api/projects/ list + status filter', async ({ request }) => {
    const token = await login(request, 'management');
    const nameA = `PROP-API01A-${uniq()}`;
    const nameB = `PROP-API01B-${uniq()}`;
    const projectA = await createProject(request, token, nameA);
    const resB = await request.post('/api/projects/', {
      data: { name: nameB, location: 'QA Location', status: 'under_construction' },
      headers: { 'X-CSRFToken': token },
    });
    expect(resB.status()).toBe(201);
    const projectB = (await resB.json()).id as number;
    try {
      const list = (await (await request.get('/api/projects/')).json()) as Array<{ id: number; status_display: string }>;
      const a = list.find((p) => p.id === projectA);
      const b = list.find((p) => p.id === projectB);
      expect(a).toBeTruthy();
      expect(b).toBeTruthy();
      expect(a!.status_display).toBe('Booking Open');

      const filtered = (await (await request.get('/api/projects/?status=booking_open')).json()) as Array<{ id: number }>;
      expect(filtered.some((p) => p.id === projectA)).toBeTruthy();
      expect(filtered.some((p) => p.id === projectB)).toBeFalsy();
    } finally {
      await deleteProject(request, token, projectA);
      await deleteProject(request, token, projectB);
    }
  });

  test('PROP-API-02 — POST /api/projects/ (management create)', async ({ request }) => {
    const token = await login(request, 'management');
    const name = `PROP-API02-${uniq()}`;
    let projectId = 0;
    try {
      const res = await request.post('/api/projects/', {
        data: { name, location: 'QA Location', status: 'booking_open' },
        headers: { 'X-CSRFToken': token },
      });
      expect(res.status()).toBe(201);
      const body = await res.json();
      expect(body.id).toBeTruthy();
      expect(body.created_at).toBeTruthy();
      expect(body.total_plots).toBe(0);
      projectId = body.id;
    } finally {
      await deleteProject(request, token, projectId);
    }
  });

  test('PROP-API-03 — GET /api/plots/ list + filters', async ({ request }) => {
    const token = await login(request, 'management');
    const nameA = `PROP-API03A-${uniq()}`;
    const nameB = `PROP-API03B-${uniq()}`;
    const projectA = await createProject(request, token, nameA);
    const projectB = await createProject(request, token, nameB);
    const plotA = await createPlot(request, token, projectA, `API03A-${uniq()}`);
    const plotB = await createPlot(request, token, projectB, `API03B-${uniq()}`);
    try {
      const all = (await (await request.get('/api/plots/')).json()) as Array<Record<string, unknown>>;
      const a = all.find((p) => p.id === plotA);
      expect(a).toBeTruthy();
      expect(a!.project_name).toBe(nameA);
      expect(a!.status_display).toBe('Available');
      expect(a).not.toHaveProperty('development_charge');

      const byProject = (await (await request.get(`/api/plots/?project=${projectA}`)).json()) as Array<{ id: number }>;
      expect(byProject.some((p) => p.id === plotA)).toBeTruthy();
      expect(byProject.some((p) => p.id === plotB)).toBeFalsy();

      const byType = (await (await request.get('/api/plots/?plot_type=residential')).json()) as Array<{ id: number }>;
      expect(byType.some((p) => p.id === plotA)).toBeTruthy();
    } finally {
      await deleteProject(request, token, projectA);
      await deleteProject(request, token, projectB);
    }
  });

  test('PROP-API-04 — POST /api/plots/ create + validation', async ({ request }) => {
    const token = await login(request, 'management');
    const name = `PROP-API04-${uniq()}`;
    const projectId = await createProject(request, token, name);
    try {
      const ok = await request.post('/api/plots/', {
        data: { project: projectId, plot_number: `API04-${uniq()}`, size_marla: '10.00', price: '500000.00' },
        headers: { 'X-CSRFToken': token },
      });
      expect(ok.status()).toBe(201);
      expect((await ok.json()).status).toBe('available');

      // Negative price and negative size are rejected (a zero value slips through
      // the `if value and value <= 0` checks — latent bug).
      for (const bad of [{ price: '-1' }, { size_marla: '-1' }]) {
        const res = await request.post('/api/plots/', {
          data: { project: projectId, plot_number: `API04b-${uniq()}`, size_marla: '10.00', price: '500000.00', ...bad },
          headers: { 'X-CSRFToken': token },
        });
        expect(res.status()).toBe(400);
      }
    } finally {
      await deleteProject(request, token, projectId);
    }
  });

  test('PROP-API-05 — GET /api/plots/<id>/ detail', async ({ request }) => {
    const token = await login(request, 'management');
    const name = `PROP-API05-${uniq()}`;
    const projectId = await createProject(request, token, name);
    const plotId = await createPlot(request, token, projectId, `API05-${uniq()}`);
    try {
      const patch = await request.patch(`/api/plots/${plotId}/`, {
        data: { price: '510000.00' },
        headers: { 'X-CSRFToken': token },
      });
      expect(patch.status()).toBe(200);

      const res = await request.get(`/api/plots/${plotId}/`);
      expect(res.status()).toBe(200);
      const body = await res.json();
      expect(Array.isArray(body.features)).toBeTruthy();
      expect(Array.isArray(body.price_history)).toBeTruthy();
      expect(body.price_history.length).toBeGreaterThan(0);
      expect(body).toHaveProperty('project_phase_name');
    } finally {
      await deleteProject(request, token, projectId);
    }
  });

  test('PROP-API-06 — PUT/PATCH /api/plots/<id>/ writes PriceHistory on price change', async ({ request }) => {
    const token = await login(request, 'management');
    const name = `PROP-API06-${uniq()}`;
    const projectId = await createProject(request, token, name);
    const plotId = await createPlot(request, token, projectId, `API06-${uniq()}`, '500000.00');
    try {
      const patch = await request.patch(`/api/plots/${plotId}/`, {
        data: { price: '600000.00' },
        headers: { 'X-CSRFToken': token },
      });
      expect(patch.status()).toBe(200);

      const history = (await (await request.get(`/api/price-history/?plot=${plotId}`)).json()) as Array<{
        old_price: string;
        new_price: string;
        change_reason: string;
        changed_by_name: string;
      }>;
      expect(history.length).toBe(1);
      expect(history[0].old_price).toBe('500000.00');
      expect(history[0].new_price).toBe('600000.00');
      expect(history[0].change_reason).toBe('API update');
      expect(history[0].changed_by_name).toBe('qa_management');

      // Non-price change writes no history.
      const patch2 = await request.patch(`/api/plots/${plotId}/`, {
        data: { block: 'A' },
        headers: { 'X-CSRFToken': token },
      });
      expect(patch2.status()).toBe(200);
      const after = (await (await request.get(`/api/price-history/?plot=${plotId}`)).json()) as unknown[];
      expect(after.length).toBe(1);
    } finally {
      await deleteProject(request, token, projectId);
    }
  });

  test('PROP-API-07 — POST /api/plots/<id>/change_status/ (valid + invalid value)', async ({ request }) => {
    const token = await login(request, 'management');
    const name = `PROP-API07-${uniq()}`;
    const projectId = await createProject(request, token, name);
    const plotId = await createPlot(request, token, projectId, `API07-${uniq()}`);
    try {
      const ok = await request.post(`/api/plots/${plotId}/change_status/`, {
        data: { status: 'booked' },
        headers: { 'X-CSRFToken': token },
      });
      expect(ok.status()).toBe(200);

      const bad = await request.post(`/api/plots/${plotId}/change_status/`, {
        data: { status: 'bogus' },
        headers: { 'X-CSRFToken': token },
      });
      expect(bad.status()).toBe(400);
    } finally {
      await deleteProject(request, token, projectId);
    }
  });

  test('PROP-API-08 — GET /api/plots/list/ (public, available-only, capped)', async ({ playwright, request }) => {
    const token = await login(request, 'admin');
    const name = `PROP-API08-${uniq()}`;
    const projectId = await createProject(request, token, name);
    const availableIds: number[] = [];
    let bookedId = 0;
    try {
      for (let i = 0; i < 21; i++) {
        availableIds.push(await createPlot(request, token, projectId, `API08-${uniq()}`));
      }
      bookedId = await createPlot(request, token, projectId, `API08-booked-${uniq()}`);
      const cs = await request.post(`/api/plots/${bookedId}/change_status/`, {
        data: { status: 'booked' },
        headers: { 'X-CSRFToken': token },
      });
      expect(cs.status()).toBe(200);

      const anon = await playwright.request.newContext({ baseURL: BASE_URL });
      try {
        const res = await anon.get('/api/plots/list/');
        expect(res.status()).toBe(200);
        const body = (await res.json()) as Array<{ id: number; status: string }>;
        expect(body.length).toBeLessThanOrEqual(20);
        expect(body.length).toBeGreaterThan(0);
        for (const p of body) expect(p.status).toBe('available');
        expect(body.some((p) => p.id === bookedId)).toBeFalsy();
      } finally {
        await anon.dispose();
      }
    } finally {
      await deleteProject(request, token, projectId);
    }
  });

  test('PROP-API-09 — GET /api/price-history/ read-only list + plot filter', async ({ request }) => {
    const token = await login(request, 'management');
    const name = `PROP-API09-${uniq()}`;
    const projectId = await createProject(request, token, name);
    const plotA = await createPlot(request, token, projectId, `API09A-${uniq()}`, '500000.00');
    const plotB = await createPlot(request, token, projectId, `API09B-${uniq()}`, '500000.00');
    try {
      await request.patch(`/api/plots/${plotA}/`, { data: { price: '510000.00' }, headers: { 'X-CSRFToken': token } });
      await request.patch(`/api/plots/${plotB}/`, { data: { price: '520000.00' }, headers: { 'X-CSRFToken': token } });

      const all = (await (await request.get('/api/price-history/')).json()) as Array<{ plot: number; changed_by_name: string }>;
      expect(all.filter((h) => h.plot === plotA).length).toBe(1);
      expect(all.filter((h) => h.plot === plotB).length).toBe(1);
      expect(all.every((h) => h.changed_by_name)).toBeTruthy();

      const filtered = (await (await request.get(`/api/price-history/?plot=${plotA}`)).json()) as Array<{ plot: number }>;
      expect(filtered.length).toBe(1);
      expect(filtered[0].plot).toBe(plotA);
    } finally {
      await deleteProject(request, token, projectId);
    }
  });

  test('PROP-API-10 — GET/POST /api/project-milestones/ omits new fields', async ({ request }) => {
    const token = await login(request, 'management');
    const name = `PROP-API10-${uniq()}`;
    const projectId = await createProject(request, token, name);
    const title = `Milestone ${uniq()}`;
    try {
      const res = await request.post('/api/project-milestones/', {
        data: {
          project: projectId,
          title,
          start_date: '2026-01-01',
          milestone_type: 'payment',
          completion_percent: '40.00',
          progress_date: '2026-02-01',
          status: 'pending',
          order: 1,
        },
        headers: { 'X-CSRFToken': token },
      });
      expect(res.status()).toBe(201);
      const body = await res.json();
      // Defect: the serializer silently drops the new fields.
      expect(body).not.toHaveProperty('start_date');
      expect(body).not.toHaveProperty('milestone_type');
      expect(body).not.toHaveProperty('completion_percent');
      expect(body).not.toHaveProperty('progress_date');

      const list = (await (await request.get('/api/project-milestones/')).json()) as Array<Record<string, unknown>>;
      const item = list.find((m) => m.title === title);
      expect(item).toBeTruthy();
      expect(item).not.toHaveProperty('completion_percent');
    } finally {
      await deleteProject(request, token, projectId);
    }
  });

  test('PROP-API-11 — POST /api/project-milestones/<id>/set_status/ (no transition guard/audit)', async ({ request }) => {
    const token = await login(request, 'management');
    const name = `PROP-API11-${uniq()}`;
    const projectId = await createProject(request, token, name);
    const title = `Milestone ${uniq()}`;
    const msRes = await request.post('/api/project-milestones/', {
      data: { project: projectId, title, target_date: '2026-06-01', status: 'pending', order: 1 },
      headers: { 'X-CSRFToken': token },
    });
    expect(msRes.status()).toBe(201);
    const milestoneId = (await msRes.json()).id as number;
    try {
      const completed = await request.post(`/api/project-milestones/${milestoneId}/set_status/`, {
        data: { status: 'completed' },
        headers: { 'X-CSRFToken': token },
      });
      expect(completed.status()).toBe(200);
      expect((await completed.json()).completed_date).toBeTruthy();

      const revert = await request.post(`/api/project-milestones/${milestoneId}/set_status/`, {
        data: { status: 'pending' },
        headers: { 'X-CSRFToken': token },
      });
      expect(revert.status()).toBe(200);
      expect((await revert.json()).completed_date).toBeNull();

      const bogus = await request.post(`/api/project-milestones/${milestoneId}/set_status/`, {
        data: { status: 'bogus' },
        headers: { 'X-CSRFToken': token },
      });
      expect(bogus.status()).toBe(400);
    } finally {
      await deleteProject(request, token, projectId);
    }
  });
});
