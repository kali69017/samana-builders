import { test, expect, APIRequestContext } from '@playwright/test';
import { loginViaApi } from '../helpers/auth';

/**
 * Samana ERP — Leads (CRM) browser suite.
 *
 * Drives the real rendered UI (Django templates via `core/views_crm.py`) with
 * `page` + role-specific `storageState`: admin (super_admin) for the happy path
 * and edge cases, sales for the role-access surface. Cross-checks lead state,
 * converted customers and notes against the DRF `/api/leads/`, `/api/customers/`
 * and `/api/lead-notes/` contracts.
 *
 * Field labels / button names / headers are taken verbatim from
 * `templates/leads.html`, `lead_form.html` (via `base_form.html`),
 * `lead_detail.html` and `lead_convert.html`.
 *
 * Run with `DJANGO_DEBUG=True python manage.py runserver` on :8000 (CONVENTIONS.md).
 */

// ══════════════════════════════════════════════════════════════════════════
// Helpers
// ══════════════════════════════════════════════════════════════════════════

let seq = 0;
/** Monotonic, run-unique timestamp string (never repeats within a run). */
function uniq(): string {
  return `${Date.now()}${String(seq++).padStart(3, '0')}`;
}

function makePhone(): string {
  return `+92-300-${uniq().slice(-7)}`;
}

function makeEmail(): string {
  return `qa+${uniq()}@example.com`;
}

/** 13-digit raw CNIC + its canonical dashed form (XXXXX-XXXXXXX-X). */
function makeCnic(): { raw: string; dashed: string } {
  const raw = uniq().slice(-13);
  return { raw, dashed: `${raw.slice(0, 5)}-${raw.slice(5, 12)}-${raw.slice(12)}` };
}

/** Leads created during this worker's run (deleted in afterAll). */
const createdLeads: number[] = [];
/** Customers created via lead conversion during this worker's run (deleted in afterAll). */
const createdCustomers: number[] = [];

/** Create a lead via the DRF API (admin) and register it for cleanup. */
async function createLeadViaApi(
  request: APIRequestContext,
  token: string,
  overrides: Record<string, unknown> = {},
): Promise<{ id: number; name: string; email: string; phone: string; status: string }> {
  const payload = { name: `QA Lead ${uniq()}`, phone: makePhone(), email: makeEmail(), ...overrides };
  const res = await request.post('/api/leads/', {
    data: payload,
    headers: { 'X-CSRFToken': token },
  });
  expect(res.status(), `create lead failed: ${await res.text()}`).toBe(201);
  const body = await res.json();
  createdLeads.push(body.id);
  return { id: body.id, name: body.name, email: body.email, phone: body.phone, status: body.status };
}

/** Resolve a lead pk by its unique email (used after UI creates). */
async function leadIdByEmail(request: APIRequestContext, email: string): Promise<number> {
  const rows = await (await request.get('/api/leads/')).json();
  const row = rows.find((r: { email: string }) => r.email === email);
  expect(row, `lead with email ${email} not found`).toBeTruthy();
  createdLeads.push(row.id);
  return row.id;
}

// ══════════════════════════════════════════════════════════════════════════
// HP — happy path
// ══════════════════════════════════════════════════════════════════════════

test.describe('LEAD — Happy path', () => {
  test.beforeEach(async ({ page }) => { await loginViaApi(page.request, 'admin'); });

  test('LEAD-HP-01 — Create lead (name + email + phone)', async ({ page, request }) => {
    const token = await loginViaApi(request, 'admin');
    const name = `QA Lead ${uniq()}`;
    const email = makeEmail();
    const phone = makePhone();

    await page.goto('/leads/create/');
    await page.getByLabel('Name').fill(name);
    await page.getByLabel('Email').fill(email);
    await page.getByLabel('Phone').fill(phone);
    await page.getByRole('button', { name: 'Create' }).click();

    await expect(page).toHaveURL(/\/leads\/$/);
    await expect(page.getByText(/Lead created successfully!/i).first()).toBeVisible();

    // Persisted with the entered contact fields and default status 'new'.
    const id = await leadIdByEmail(request, email);
    const body = await (await request.get(`/api/leads/${id}/`)).json();
    expect(body.name).toBe(name);
    expect(body.email).toBe(email);
    expect(body.phone).toBe(phone);
    expect(body.status).toBe('new');
  });

  test('LEAD-HP-02 — Create lead with phone only (at least one contact field)', async ({
    page,
    request,
  }) => {
    const token = await loginViaApi(request, 'admin');
    const phone = makePhone();

    await page.goto('/leads/create/');
    await page.getByLabel('Phone').fill(phone);
    await page.getByRole('button', { name: 'Create' }).click();

    await expect(page).toHaveURL(/\/leads\/$/);
    await expect(page.getByText(/Lead created successfully!/i).first()).toBeVisible();

    // The lead persists with an empty name/email and the phone as its identity.
    const rows = await (await request.get('/api/leads/')).json();
    const row = rows.find((r: { phone: string }) => r.phone === phone);
    expect(row, `lead with phone ${phone} not found`).toBeTruthy();
    expect(row.name).toBe('');
    expect(row.email).toBe('');
    createdLeads.push(row.id);
  });

  test('LEAD-HP-03 — Edit lead', async ({ page, request }) => {
    const token = await loginViaApi(request, 'admin');
    const lead = await createLeadViaApi(request, token);
    const newName = `QA Lead Edit ${uniq()}`;
    const newPhone = makePhone();

    await page.goto(`/leads/${lead.id}/edit/`);
    await page.getByLabel('Name').fill(newName);
    await page.getByLabel('Phone').fill(newPhone);
    await page.getByRole('button', { name: 'Update' }).click();

    await expect(page).toHaveURL(new RegExp(`/leads/${lead.id}/$`));
    await expect(page.getByText(/Lead updated successfully!/i).first()).toBeVisible();

    const body = await (await request.get(`/api/leads/${lead.id}/`)).json();
    expect(body.name).toBe(newName);
    expect(body.phone).toBe(newPhone);
  });

  test('LEAD-HP-04 — Status transitions via quick status update', async ({ page, request }) => {
    const token = await loginViaApi(request, 'admin');
    const lead = await createLeadViaApi(request, token);

    await page.goto(`/leads/${lead.id}/`);
    await expect(page.getByText('New').first()).toBeVisible(); // initial badge

    // new → contacted → qualified → lost (the "converted" status is exercised in
    // LEAD-HP-06 via the convert-to-customer flow).
    const walk: Array<{ value: string; badge: string }> = [
      { value: 'contacted', badge: 'Contacted' },
      { value: 'qualified', badge: 'Qualified' },
      { value: 'lost', badge: 'Lost' },
    ];
    for (const step of walk) {
      await page.locator('select[name="status"]').selectOption(step.value);
      await page.getByRole('button', { name: 'Update Status' }).click();
      await expect(page).toHaveURL(new RegExp(`/leads/${lead.id}/$`));
      await expect(page.getByText(step.badge).first()).toBeVisible();
    }

    // Contacted must also have flipped the is_contacted flag.
    const body = await (await request.get(`/api/leads/${lead.id}/`)).json();
    expect(body.status).toBe('lost');
    expect(body.is_contacted).toBe(true);
  });

  test('LEAD-HP-05 — Detail: add a note to the timeline', async ({ page, request }) => {
    const token = await loginViaApi(request, 'admin');
    const lead = await createLeadViaApi(request, token);
    const note = `QA note ${uniq()}`;

    await page.goto(`/leads/${lead.id}/`);
    await page.getByPlaceholder('Add a note...').fill(note);
    await page.getByRole('button', { name: 'Add Note' }).click();

    await expect(page).toHaveURL(new RegExp(`/leads/${lead.id}/$`));
    await expect(page.getByText(note)).toBeVisible();

    // The note is persisted and attributed to the current user.
    const notes = await (await request.get('/api/lead-notes/')).json();
    const found = notes.find((n: { note: string; lead: number }) => n.note === note && n.lead === lead.id);
    expect(found, `note for lead ${lead.id} persisted`).toBeTruthy();
    expect(found.created_by_name).toBe('admin');
  });

  test('LEAD-HP-06 — Convert lead to customer (creates Customer)', async ({ page, request }) => {
    const token = await loginViaApi(request, 'admin');
    const lead = await createLeadViaApi(request, token, { name: 'QA Convert' });
    const { dashed } = makeCnic();

    await page.goto(`/leads/${lead.id}/convert/`);
    await page.locator('input[name="first_name"]').fill('QA');
    await page.locator('input[name="last_name"]').fill('Converted');
    await page.locator('input[name="cnic"]').fill(dashed);
    await page.locator('input[name="city"]').fill('Lahore');
    await page.getByRole('button', { name: 'Convert to Customer' }).click();

    // Redirected to the newly created customer's detail page.
    await expect(page).toHaveURL(/\/customers\/\d+\/$/);
    await expect(page.getByText(/Lead converted to customer CUS-\d{5}!/).first()).toBeVisible();
    const customerPk = Number(page.url().match(/\/customers\/(\d+)\/$/)?.[1]);
    if (customerPk) createdCustomers.push(customerPk);

    // The lead is now converted and linked to the customer.
    const leadBody = await (await request.get(`/api/leads/${lead.id}/`)).json();
    expect(leadBody.status).toBe('converted');
    expect(leadBody.converted_customer).toBe(customerPk);

    const custBody = await (await request.get(`/api/customers/${customerPk}/`)).json();
    expect(custBody.first_name).toBe('QA');
    expect(custBody.last_name).toBe('Converted');
    expect(custBody.cnic).toBe(dashed);
  });

  test('LEAD-HP-07 — Filter by status & source', async ({ page, request }) => {
    const token = await loginViaApi(request, 'admin');
    const lead = await createLeadViaApi(request, token, { source: 'referral' });

    await page.goto('/leads/');
    await expect(page.getByText(lead.name)).toBeVisible();

    // Filter by status = new → still present.
    await page.locator('select[name="status"]').selectOption('new');
    await page.getByRole('button', { name: 'Filter' }).click();
    await expect(page).toHaveURL(/status=new/);
    await expect(page.getByText(lead.name)).toBeVisible();

    // Filter by status = lost → absent (empty result).
    await page.locator('select[name="status"]').selectOption('lost');
    await page.getByRole('button', { name: 'Filter' }).click();
    await expect(page.getByText(lead.name)).toHaveCount(0);

    // Filter by source = referral → present; source = agent → absent.
    await page.goto('/leads/');
    await page.locator('select[name="source"]').selectOption('referral');
    await page.getByRole('button', { name: 'Filter' }).click();
    await expect(page.getByText(lead.name)).toBeVisible();

    await page.locator('select[name="source"]').selectOption('agent');
    await page.getByRole('button', { name: 'Filter' }).click();
    await expect(page.getByText(lead.name)).toHaveCount(0);
  });

  test('LEAD-HP-08 — Search by name / email / phone', async ({ page, request }) => {
    const token = await loginViaApi(request, 'admin');
    const lead = await createLeadViaApi(request, token);

    for (const term of [lead.name, lead.email, lead.phone.slice(-4)]) {
      await page.goto('/leads/');
      await page.getByPlaceholder('Search name, email, phone...').fill(term);
      await page.getByRole('button', { name: 'Filter' }).click();
      await expect(page.getByText(lead.name)).toBeVisible();
    }

    // Non-matching search → empty state.
    await page.goto('/leads/');
    await page.getByPlaceholder('Search name, email, phone...').fill(`no-such-${uniq()}`);
    await page.getByRole('button', { name: 'Filter' }).click();
    await expect(page.getByText(/No Leads Found/i)).toBeVisible();
  });

  test('LEAD-HP-09 — Delete lead', async ({ page, request }) => {
    const token = await loginViaApi(request, 'admin');
    const lead = await createLeadViaApi(request, token);

    await page.goto(`/leads/${lead.id}/delete/`);
    await expect(page.getByText('Confirm Deletion')).toBeVisible();
    await page.getByRole('button', { name: /Yes, Delete/ }).click();

    await expect(page).toHaveURL(/\/leads\/$/);
    await expect(page.getByText(/Lead deleted successfully!/i).first()).toBeVisible();

    // Hard-deleted.
    const res = await request.get(`/api/leads/${lead.id}/`);
    expect(res.status()).toBe(404);
  });
});

// ══════════════════════════════════════════════════════════════════════════
// EC — edge cases / boundaries
// ══════════════════════════════════════════════════════════════════════════

test.describe('LEAD — Edge cases', () => {
  test.beforeEach(async ({ page }) => { await loginViaApi(page.request, 'admin'); });

  test('LEAD-EC-01 — Empty contact fields rejected', async ({ page }) => {
    await page.goto('/leads/create/');
    // Leave name/email/phone all blank and submit.
    await page.getByRole('button', { name: 'Create' }).click();

    // Form re-renders with a validation error (the "at least one of name/email/
    // phone" rule is a non-field error in LeadForm.clean, surfaced by the
    // base_form "Please correct the errors below" alert).
    await expect(page).toHaveURL(/\/leads\/create\/$/);
    await expect(page.getByText('Please correct the errors below.')).toBeVisible();
  });

  test('LEAD-EC-02 — Invalid status rejected (status unchanged)', async ({ request }) => {
    const token = await loginViaApi(request, 'admin');
    const lead = await createLeadViaApi(request, token);

    // The quick-status view guards against a status outside LEAD_STATUS_CHOICES.
    await request.post(`/leads/${lead.id}/status/`, {
      form: { csrfmiddlewaretoken: token, status: 'bogus', next: '' },
    });

    const body = await (await request.get(`/api/leads/${lead.id}/`)).json();
    expect(body.status).toBe('new'); // untouched
  });

  test('LEAD-EC-03 — Convert already-converted rejected', async ({ page, request }) => {
    const token = await loginViaApi(request, 'admin');
    const lead = await createLeadViaApi(request, token);

    // Convert once via API to establish a converted lead.
    const conv = await request.post(`/api/leads/${lead.id}/convert/`, {
      data: { cnic: makeCnic().dashed, phone: lead.phone },
      headers: { 'X-CSRFToken': token },
    });
    expect(conv.status()).toBe(201);
    const customerPk = (await conv.json()).customer_pk as number;
    createdCustomers.push(customerPk);

    // UI: the convert page for an already-converted lead redirects to the
    // customer detail (guard at core/views_crm.py lead_convert_view).
    await page.goto(`/leads/${lead.id}/convert/`);
    await expect(page).toHaveURL(new RegExp(`/customers/${customerPk}/$`));
    await expect(page.getByText(/already converted/i).first()).toBeVisible();

    // API: a second convert is rejected.
    const again = await request.post(`/api/leads/${lead.id}/convert/`, {
      data: { cnic: makeCnic().dashed, phone: lead.phone },
      headers: { 'X-CSRFToken': token },
    });
    expect(again.status()).toBe(400);
    expect(await again.json()).toHaveProperty('error');
  });

  test('LEAD-EC-04 — Open redirect via next is blocked', async ({ request }) => {
    // CONFIRMED BUG: core/views_crm.py lead_status_update_view redirects to
    // `request.POST.get('next') or 'leads'` with no same-origin validation, so an
    // attacker-controlled `next` can bounce a logged-in staff member off-site.
    const token = await loginViaApi(request, 'admin');
    const lead = await createLeadViaApi(request, token);

    const res = await request.post(`/leads/${lead.id}/status/`, {
      form: {
        csrfmiddlewaretoken: token,
        status: 'new',
        next: 'https://evil.example.com/phish',
      },
      maxRedirects: 0,
    });
    expect(res.status()).toBe(302);
    const location = res.headers()['location'] ?? '';
    // Correct behaviour: `next` is constrained to same-origin app paths.
    expect(location).not.toContain('evil.example.com'); // FAILS — open redirect
  });
});

// ══════════════════════════════════════════════════════════════════════════
// SEC — role access (sales user)
// ══════════════════════════════════════════════════════════════════════════

test.describe('LEAD — Role access (sales)', () => {
  test.beforeEach(async ({ page }) => { await loginViaApi(page.request, 'sales'); });

  test('LEAD-SEC-01 — Sales creates a lead (allowed)', async ({ page, request }) => {
    const token = await loginViaApi(request, 'admin'); // admin for verification/cleanup only
    const phone = makePhone();
    const name = `QA Sales Lead ${uniq()}`;

    await page.goto('/leads/create/');
    await page.getByLabel('Name').fill(name);
    await page.getByLabel('Phone').fill(phone);
    await page.getByRole('button', { name: 'Create' }).click();

    await expect(page).toHaveURL(/\/leads\/$/);
    await expect(page.getByText(/Lead created successfully!/i).first()).toBeVisible();

    const rows = await (await request.get('/api/leads/')).json();
    const row = rows.find((r: { phone: string }) => r.phone === phone);
    expect(row, `sales-created lead ${phone} persisted`).toBeTruthy();
    createdLeads.push(row.id);
  });

  test('LEAD-SEC-02 — Sales cannot delete a lead (redirected)', async ({ page, request }) => {
    const token = await loginViaApi(request, 'admin');
    const lead = await createLeadViaApi(request, token);

    // lead_delete_view is @management_or_above; sales is not in that group.
    await page.goto(`/leads/${lead.id}/delete/`);
    await expect(page).toHaveURL(/\/dashboard\//);

    // The lead is intact.
    const res = await request.get(`/api/leads/${lead.id}/`);
    expect(res.status()).toBe(200);
  });
});

// ══════════════════════════════════════════════════════════════════════════
// Cleanup — afterAll deletes every lead / customer this worker created.
// ══════════════════════════════════════════════════════════════════════════

test.afterAll(async ({ playwright }) => {
  const request = await playwright.request.newContext({ baseURL: 'http://127.0.0.1:8000' });
  try {
    const token = await loginViaApi(request, 'admin');
    for (const id of createdLeads) {
      await request.delete(`/api/leads/${id}/`, { headers: { 'X-CSRFToken': token } }).catch(() => {});
    }
    for (const id of createdCustomers) {
      await request.delete(`/api/customers/${id}/`, { headers: { 'X-CSRFToken': token } }).catch(() => {});
    }
  } finally {
    await request.dispose();
  }
});
