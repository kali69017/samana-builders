import { test, expect, APIRequestContext } from '@playwright/test';
import { loginViaApi, RoleName } from '../helpers/auth';
import { execFileSync } from 'node:child_process';
import * as path from 'node:path';

/**
 * Samana ERP — properties module, BROWSER suite.
 *
 * Drives the server-rendered UI with `page` + per-role storageState
 * (tests/.auth/admin.json, tests/.auth/sales.json), and verifies the resulting
 * server state via the DRF API (plot status, price) and the ORM fixture helper
 * (`total_cost`, which the API serializers deliberately omit — see PROP-EC-07).
 *
 * Money is asserted EXACTLY: DRF returns Decimal strings like "500000.00"; the
 * UI renders "Rs. 500,000" via the `money` filter. Confirmed defects are written
 * RED on purpose (assert the CORRECT behaviour) — see docs/qa/findings-confirmed.md
 * F3 and specs/properties.md PROP-EC-09/-10.
 */

// Shared venv (see CLAUDE.md) — the plot charge fields / total_cost can only be
// read via the ORM, so verification shells out to the fixture helper.
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

async function createProject(
  request: APIRequestContext,
  token: string,
  name: string,
  status = 'booking_open',
): Promise<number> {
  const res = await request.post('/api/projects/', {
    data: { name, location: 'QA Location', total_plots: 10, status },
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
  plotType = 'residential',
): Promise<number> {
  const res = await request.post('/api/plots/', {
    data: {
      project: projectId,
      plot_number: plotNumber,
      size_marla: '10.00',
      price,
      plot_type: plotType,
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

async function setPlotStatus(
  request: APIRequestContext,
  token: string,
  plotId: number,
  status: string,
): Promise<void> {
  const res = await request.post(`/api/plots/${plotId}/change_status/`, {
    data: { status },
    headers: { 'X-CSRFToken': token },
  });
  expect(res.status(), `set plot ${plotId} -> ${status}`).toBe(200);
}

async function findProjectId(request: APIRequestContext, name: string): Promise<number> {
  const res = await request.get('/api/projects/');
  const body = (await res.json()) as Array<{ id: number; name: string }>;
  const p = body.find((x) => x.name === name);
  return p ? p.id : 0;
}

/** Best-effort cleanup — admin can write; ignore the status (404 is fine). */
async function deleteProject(request: APIRequestContext, token: string, projectId: number): Promise<void> {
  if (projectId) await request.delete(`/api/projects/${projectId}/`, { headers: { 'X-CSRFToken': token } });
}

async function deleteCustomer(request: APIRequestContext, token: string, customerId?: number): Promise<void> {
  if (customerId) await request.delete(`/api/customers/${customerId}/`, { headers: { 'X-CSRFToken': token } });
}

/* ── Forms (admin) ──────────────────────────────────────────────────────────── */

test.describe('Properties — Forms (admin)', () => {
  test.beforeEach(async ({ page }) => { await loginViaApi(page.request, 'admin'); });

  test('PROP-HP-01 — Create project (browser)', async ({ page, request }) => {
    const token = await login(request, 'admin');
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
      const project = await (await request.get(`/api/projects/${projectId}/`)).json();
      expect(project.name).toBe(name);
    } finally {
      await deleteProject(request, token, projectId);
    }
  });

  test('PROP-HP-06 — Edit project (browser)', async ({ page, request }) => {
    const token = await login(request, 'admin');
    const name = `PROP-HP06-${uniq()}`;
    const projectId = await createProject(request, token, name);
    try {
      await page.goto(`/properties/project/${projectId}/edit/`);
      await page.getByLabel('Name').fill(`${name}-EDITED`);
      await page.getByLabel('Location').fill('QA Location Updated');
      await page.getByRole('button', { name: 'Update', exact: true }).click();

      await expect(page).toHaveURL(/\/properties\/$/);
      const body = await (await request.get(`/api/projects/${projectId}/`)).json();
      expect(body.name).toBe(`${name}-EDITED`);
      expect(body.location).toBe('QA Location Updated');
    } finally {
      await deleteProject(request, token, projectId);
    }
  });

  test('Project delete — blocked when project has plots (guard)', async ({ page, request }) => {
    const token = await login(request, 'admin');
    const name = `PROP-DEL-GUARD-${uniq()}`;
    const projectId = await createProject(request, token, name);
    await createPlot(request, token, projectId, `DEL-GUARD-${uniq()}`);
    try {
      await page.goto(`/properties/project/${projectId}/delete/`);

      // The guard redirects back to /properties/ with an error — the project is intact.
      await expect(page).toHaveURL(/\/properties\/$/);
      await expect(page.getByText(/Cannot delete project/)).toBeVisible();
      expect((await request.get(`/api/projects/${projectId}/`)).status()).toBe(200);
    } finally {
      await deleteProject(request, token, projectId);
    }
  });

  test('Project delete — succeeds when empty', async ({ page, request }) => {
    const token = await login(request, 'admin');
    const name = `PROP-DEL-OK-${uniq()}`;
    const projectId = await createProject(request, token, name);
    try {
      await page.goto(`/properties/project/${projectId}/delete/`);

      await expect(page.getByText('Confirm Deletion')).toBeVisible();
      await page.getByRole('button', { name: /Yes, Delete/ }).click();

      await expect(page).toHaveURL(/\/properties\/$/);
      await expect(page.getByText(`Project "${name}" deleted successfully!`)).toBeVisible();
      expect((await request.get(`/api/projects/${projectId}/`)).status()).toBe(404);
    } finally {
      await deleteProject(request, token, projectId);
    }
  });

  test('PROP-HP-02 — Create plot (browser) + money exact', async ({ page, request }) => {
    const token = await login(request, 'admin');
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

      const created = (await (await request.get(`/api/plots/?project=${projectId}`)).json()) as Array<{
        id: number;
        plot_number: string;
        status: string;
        price: string;
      }>;
      const p = created.find((x) => x.plot_number === plotNumber);
      expect(p).toBeTruthy();
      plotId = p!.id;
      expect(p!.status).toBe('available');
      expect(p!.price).toBe('500000.00');

      // total_cost == price (charges default 0) — read via ORM (API omits it).
      const info = orm(['get_plot', String(plotId)]);
      expect(info.total_cost).toBe('500000.00');
      expect(info.total_charges).toBe('0.00');
    } finally {
      await deleteProject(request, token, projectId);
    }
  });

  test('PROP-HP-07 — Edit plot (browser)', async ({ page, request }) => {
    const token = await login(request, 'admin');
    const name = `PROP-HP07-${uniq()}`;
    const projectId = await createProject(request, token, name);
    const plotId = await createPlot(request, token, projectId, `HP07-${uniq()}`, '500000.00');
    try {
      await page.goto(`/properties/plot/${plotId}/edit/`);
      await page.getByLabel('Price').fill('600000');
      await page.getByRole('button', { name: 'Update', exact: true }).click();

      await expect(page).toHaveURL(/\/properties\/$/);
      const body = await (await request.get(`/api/plots/${plotId}/`)).json();
      expect(body.price).toBe('600000.00');
    } finally {
      await deleteProject(request, token, projectId);
    }
  });

  test('Plot delete — succeeds when unbooked', async ({ page, request }) => {
    const token = await login(request, 'admin');
    const name = `PROP-PLOTDEL-${uniq()}`;
    const projectId = await createProject(request, token, name);
    const plotId = await createPlot(request, token, projectId, `PLOTDEL-${uniq()}`);
    try {
      await page.goto(`/properties/plot/${plotId}/delete/`);

      await expect(page.getByText('Confirm Deletion')).toBeVisible();
      await page.getByRole('button', { name: /Yes, Delete/ }).click();

      await expect(page).toHaveURL(/\/properties\/$/);
      await expect(page.getByText('Plot deleted successfully!')).toBeVisible();
      expect((await request.get(`/api/plots/${plotId}/`)).status()).toBe(404);
    } finally {
      await deleteProject(request, token, projectId);
    }
  });

  test('PROP-HP-08 — Milestone create (browser) + progress bar', async ({ page, request }) => {
    const token = await login(request, 'admin');
    const name = `PROP-HP08-${uniq()}`;
    const projectId = await createProject(request, token, name);
    const title = `Milestone ${uniq()}`;
    let milestoneId = 0;
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
      await expect(page.getByText('Milestone created successfully!')).toBeVisible();

      const milestones = (await (await request.get('/api/project-milestones/')).json()) as Array<{ id: number; title: string }>;
      const created = milestones.find((m) => m.title === title);
      expect(created).toBeTruthy();
      milestoneId = created!.id;

      // Progress bar reflects completion_percent (filter to this project first).
      await page.goto(`/projects/milestones/?project=${projectId}`);
      const row = page.getByRole('row', { name: new RegExp(title) });
      await expect(row).toBeVisible();
      await expect(row.getByText('40%')).toBeVisible();

      const info = orm(['get_milestone', String(milestoneId)]);
      expect(info.title).toBe(title);
      expect(info.milestone_type).toBe('payment');
      expect(info.start_date).toBe('2026-01-01');
      expect(info.completion_percent).toBe('40.00');
      expect(info.status).toBe('in_progress');
    } finally {
      await deleteProject(request, token, projectId);
    }
  });

  test('PROP-HP-09 — Milestone edit (browser)', async ({ page, request }) => {
    const token = await login(request, 'admin');
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

  test('PROP-HP-04 — Reservation (browser): available → reserved', async ({ page, request }) => {
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

      const plot = await (await request.get(`/api/plots/${plotId}/`)).json();
      expect(plot.status).toBe('reserved');

      // Badge reflects the transition.
      await page.goto(`/properties/?project=${projectId}`);
      await expect(page.getByRole('row', { name: new RegExp(plotNumber) }).getByText('Reserved')).toBeVisible();
    } finally {
      await deleteProject(request, token, projectId);
      await deleteCustomer(request, token, customer.id);
    }
  });
});

/* ── Interactive (admin) ────────────────────────────────────────────────────── */

test.describe('Properties — Interactive (admin)', () => {
  test.beforeEach(async ({ page }) => { await loginViaApi(page.request, 'admin'); });

  test('Plot filter — by status', async ({ page, request }) => {
    const token = await login(request, 'admin');
    const name = `PROP-FILT-${uniq()}`;
    const projectId = await createProject(request, token, name);
    const availableNumber = `FILT-AVAIL-${uniq()}`;
    const bookedNumber = `FILT-BOOKED-${uniq()}`;
    await createPlot(request, token, projectId, availableNumber);
    const bookedId = await createPlot(request, token, projectId, bookedNumber);
    await setPlotStatus(request, token, bookedId, 'booked');
    try {
      // Scope the status filter to this project: the plots table auto-collapses
      // after 5 rows, and there are many seeded booked plots globally.
      await page.goto(`/properties/?project=${projectId}&status=booked`);
      await expect(page.getByRole('row', { name: new RegExp(bookedNumber) })).toBeVisible();
      await expect(page.getByRole('row', { name: new RegExp(availableNumber) })).toHaveCount(0);

      await page.goto(`/properties/?project=${projectId}&status=available`);
      await expect(page.getByRole('row', { name: new RegExp(availableNumber) })).toBeVisible();
      await expect(page.getByRole('row', { name: new RegExp(bookedNumber) })).toHaveCount(0);
    } finally {
      await deleteProject(request, token, projectId);
    }
  });

  test('Plot list — project filter + type column', async ({ page, request }) => {
    const token = await login(request, 'admin');
    const nameA = `PROP-TYPE-A-${uniq()}`;
    const nameB = `PROP-TYPE-B-${uniq()}`;
    const projectA = await createProject(request, token, nameA);
    const projectB = await createProject(request, token, nameB);
    const residential = `TYPE-RES-${uniq()}`;
    const commercial = `TYPE-COM-${uniq()}`;
    await createPlot(request, token, projectA, residential, '500000.00', 'residential');
    await createPlot(request, token, projectA, commercial, '900000.00', 'commercial');
    const otherProjectPlot = `TYPE-OTHER-${uniq()}`;
    await createPlot(request, token, projectB, otherProjectPlot);
    try {
      await page.goto(`/properties/?project=${projectA}`);
      const resRow = page.getByRole('row', { name: new RegExp(residential) });
      const comRow = page.getByRole('row', { name: new RegExp(commercial) });
      await expect(resRow).toBeVisible();
      await expect(comRow).toBeVisible();
      await expect(resRow.getByText('Residential')).toBeVisible();
      await expect(comRow.getByText('Commercial')).toBeVisible();
      // The other project's plot is filtered out.
      await expect(page.getByRole('row', { name: new RegExp(otherProjectPlot) })).toHaveCount(0);
    } finally {
      await deleteProject(request, token, projectA);
      await deleteProject(request, token, projectB);
    }
  });

  test('Project cards & status counts', async ({ page, request }) => {
    const token = await login(request, 'admin');
    const name = `PROP-COUNTS-${uniq()}`;
    const projectId = await createProject(request, token, name);
    await createPlot(request, token, projectId, `COUNTS-${uniq()}`);
    try {
      await page.goto(`/properties/?project=${projectId}`);

      // Project table row shows the status badge and the computed Available count.
      // Scope to #projectsTable: the plot row's "Project" column also contains the
      // project name, so an unscoped row query matches both tables.
      const row = page.locator('#projectsTable').getByRole('row', { name: new RegExp(name) });
      await expect(row).toBeVisible();
      await expect(row.getByText('Booking Open')).toBeVisible();

      // Stat cards (Projects / Total Plots / Available Plots) reflect the filter.
      // CSS is used only because the numeric value has no role/name of its own.
      await expect(page.locator('.stat-card', { hasText: 'Projects' }).locator('.stat-value')).toHaveText('1');
      await expect(page.locator('.stat-card', { hasText: 'Total Plots' }).locator('.stat-value')).toHaveText('1');
      await expect(page.locator('.stat-card', { hasText: 'Available Plots' }).locator('.stat-value')).toHaveText('1');
    } finally {
      await deleteProject(request, token, projectId);
    }
  });

  test('PROP-HP-05 — Plot status transition: available → booked (browser)', async ({ page, request }) => {
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

      const plot = await (await request.get(`/api/plots/${plotId}/`)).json();
      expect(plot.status).toBe('booked');

      // Badge reflects the transition.
      await page.goto(`/properties/?project=${projectId}`);
      await expect(page.getByRole('row', { name: new RegExp(plotNumber) }).getByText('Booked')).toBeVisible();
    } finally {
      await deleteProject(request, token, projectId);
      await deleteCustomer(request, token, customer.id);
    }
  });
});

/* ── Edge cases (admin) ─────────────────────────────────────────────────────── */

test.describe('Properties — Edge cases (admin)', () => {
  test.beforeEach(async ({ page }) => { await loginViaApi(page.request, 'admin'); });

  test('PROP-EC-01 — Duplicate plot_number within a project rejected (browser)', async ({ page, request }) => {
    const token = await login(request, 'admin');
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

      // Form re-renders (200, not 500) with the generic error alert.
      await expect(page).toHaveURL(/\/properties\/plot\/create\/$/);
      await expect(page.getByText('Please correct the errors below.')).toBeVisible();

      const plots = (await (await request.get(`/api/plots/?project=${projectId}`)).json()) as Array<{ plot_number: string }>;
      expect(plots.filter((p) => p.plot_number === plotNumber).length).toBe(1);
    } finally {
      await deleteProject(request, token, projectId);
    }
  });

  test('PROP-EC-04 — Negative price rejected (browser)', async ({ page, request }) => {
    const token = await login(request, 'admin');
    const name = `PROP-EC04-${uniq()}`;
    const projectId = await createProject(request, token, name);
    const plotNumber = `EC04-${uniq()}`;
    try {
      await page.goto('/properties/plot/create/');
      await page.getByLabel('Plot Number').fill(plotNumber);
      await page.locator('select[name="project"]').selectOption({ label: name });
      await page.getByLabel('Size Marla').fill('10');
      // Note: `clean_price` uses `if price and price <= 0`, so a ZERO price slips
      // through (latent bug) — assert the negative case, which IS rejected.
      await page.getByLabel('Price').fill('-100');
      await page.getByRole('button', { name: 'Create', exact: true }).click();

      await expect(page.getByText('Price must be greater than 0')).toBeVisible();

      const plots = (await (await request.get(`/api/plots/?project=${projectId}`)).json()) as Array<{ plot_number: string }>;
      expect(plots.some((p) => p.plot_number === plotNumber)).toBeFalsy();
    } finally {
      await deleteProject(request, token, projectId);
    }
  });

  test('Empty required fields rejected (browser)', async ({ page }) => {
    await page.goto('/properties/plot/create/');
    await page.getByRole('button', { name: 'Create', exact: true }).click();

    // The form re-renders (stays on create) with the generic error alert and
    // the required inputs still present — nothing was persisted.
    await expect(page).toHaveURL(/\/properties\/plot\/create\/$/);
    await expect(page.getByText('Please correct the errors below.')).toBeVisible();
    await expect(page.getByLabel('Plot Number')).toBeVisible();
  });

  test('PROP-EC-10 — Plot edit on a booked plot re-lists it (RED)', async ({ page, request }) => {
    // CONFIRMED BUG: plot_edit_view has no status guard (specs/properties.md
    // PROP-EC-10). Editing a booked plot's status to Available succeeds and
    // re-lists it, while the booking still references it.
    const token = await login(request, 'admin');
    const name = `PROP-EC10-${uniq()}`;
    const projectId = await createProject(request, token, name);
    const plotId = await createPlot(request, token, projectId, `EC10-${uniq()}`);
    const customer = await createCustomer(request, token, `QA${uniq()}`);
    await createBooking(request, token, customer.id, plotId, '500000.00', '50000.00');
    try {
      await page.goto(`/properties/plot/${plotId}/edit/`);
      await page.locator('select[name="status"]').selectOption({ label: 'Available' });
      await page.getByRole('button', { name: 'Update', exact: true }).click();
      await expect(page).toHaveURL(/\/properties\/$/);

      // CORRECT behaviour: a booked plot must stay booked (edit denied or
      // ignored). The app re-lists it as available -> this assertion is RED.
      const plot = await (await request.get(`/api/plots/${plotId}/`)).json();
      expect(plot.status).toBe('booked');
    } finally {
      await deleteProject(request, token, projectId);
      await deleteCustomer(request, token, customer.id);
    }
  });

  test('PROP-EC-09 — Reservation expiry never processed (RED)', async ({ page, request }) => {
    // CONFIRMED BUG: no cron/command flips an expired reservation; the plot
    // stays reserved forever (specs/properties.md PROP-EC-09).
    const token = await login(request, 'admin');
    const name = `PROP-EC09-${uniq()}`;
    const projectId = await createProject(request, token, name);
    const plotId = await createPlot(request, token, projectId, `EC09-${uniq()}`);
    const customer = await createCustomer(request, token, `QA${uniq()}`);
    try {
      await page.goto('/properties/reserve/');
      await page.locator('select[name="customer"]').selectOption({ value: String(customer.id) });
      await page.locator('select[name="plot"]').selectOption({ value: String(plotId) });
      await page.getByLabel('Token Amount').fill('10000');
      // datetime-local input (required); name attr is the unambiguous handle.
      await page.locator('input[name="expires_at"]').fill('2020-01-01T00:00');
      await page.getByRole('button', { name: /Create Reservation/ }).click();
      await expect(page).toHaveURL(/\/properties\/$/);

      // CORRECT behaviour: an already-expired reservation must release the plot
      // back to available. The app never processes it -> this assertion is RED.
      const plot = await (await request.get(`/api/plots/${plotId}/`)).json();
      expect(plot.status).toBe('available');
    } finally {
      await deleteProject(request, token, projectId);
      await deleteCustomer(request, token, customer.id);
    }
  });
});

/* ── Security (sales role gaps + stored XSS) ────────────────────────────────── */

test.describe('Properties — Security', () => {
  test.describe('role gaps (sales UI)', () => {
    test.beforeEach(async ({ page }) => { await loginViaApi(page.request, 'sales'); });

    test('PROP-SEC-02 — sales can create a project (RED)', async ({ page, request }) => {
      // CONFIRMED BUG: docs/qa/findings-confirmed.md F3 — project_create_view is
      // @login_required only, so a sales user can create projects.
      const token = await login(request, 'admin');
      const name = `PROP-SEC02-${uniq()}`;
      try {
        await page.goto('/properties/project/create/');
        await page.getByLabel('Name').fill(name);
        await page.getByLabel('Location').fill('QA Location');
        await page.getByLabel('Total Plots').fill('5');
        await page.getByRole('button', { name: 'Create', exact: true }).click();

        // CORRECT behaviour: sales must be denied -> redirect to dashboard.
        await expect(page).toHaveURL(/\/dashboard\/$/);
      } finally {
        const id = await findProjectId(request, name);
        await deleteProject(request, token, id);
      }
    });

    test('PROP-SEC-03 — sales can create a plot and set price (RED)', async ({ page, request }) => {
      // CONFIRMED BUG: docs/qa/findings-confirmed.md F3 — plot_create_view is
      // @login_required only.
      const token = await login(request, 'admin');
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

    test('PROP-SEC-04 — sales can edit any plot price/status (RED)', async ({ page, request }) => {
      // CONFIRMED BUG: docs/qa/findings-confirmed.md F3 — plot_edit_view is
      // @login_required only (no role or ownership guard).
      const token = await login(request, 'admin');
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

    test('PROP-SEC-05 — sales can create a reservation (RED)', async ({ page, request }) => {
      // CONFIRMED BUG: docs/qa/findings-confirmed.md F3 — reservation_create_view
      // is @login_required only.
      const token = await login(request, 'admin');
      const name = `PROP-SEC05-${uniq()}`;
      const projectId = await createProject(request, token, name);
      const plotId = await createPlot(request, token, projectId, `SEC05-${uniq()}`);
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
  });

  test.describe('stored XSS (static)', () => {
    test.beforeEach(async ({ page }) => { await loginViaApi(page.request, 'admin'); });

    test('PROP-SEC-01 — Stored XSS via project name in Delete confirm (RED)', async ({ page, request }) => {
      // CONFIRMED BUG: docs/qa/findings-confirmed.md F3 — stored XSS. The project
      // name is interpolated into an inline onclick=confirm(...) with only HTML
      // entity escaping (&#x27;), which the browser decodes back into a quote and
      // breaks out of the confirm() string. Static assertion on the decoded attr.
      const token = await login(request, 'admin');
      const payload = `');alert(document.domain);//`;
      const name = `QA-XSS-${uniq()}${payload}`;
      const projectId = await createProject(request, token, name);
      try {
        await page.goto('/properties/');
        const deleteLink = page.locator(`a[href="/properties/project/${projectId}/delete/"]`);
        const onclick = (await deleteLink.getAttribute('onclick')) ?? '';
        // CORRECT behaviour: the payload must be neutralized so the decoded
        // attribute never contains a quote-terminated breakout.
        expect(onclick).not.toContain(`');alert(`);
      } finally {
        await deleteProject(request, token, projectId);
      }
    });
  });
});
