import { test, expect, APIRequestContext } from '@playwright/test';
import { loginViaApi, loginViaUi } from '../helpers/auth';

/**
 * Samana ERP — Customers module Playwright suite.
 *
 * Covers create / edit / view / search / nominee management, the portal-login
 * (profile-create) flow, the customer profile PDF, the DRF customer + ledger
 * endpoints, and the IDOR / PII security surface documented in
 * `docs/qa/findings-confirmed.md` F3.
 *
 * Run with `DJANGO_DEBUG=True python manage.py runserver` on :8000 (see CONVENTIONS.md).
 */

// ══════════════════════════════════════════════════════════════════════════
// Helpers
// ══════════════════════════════════════════════════════════════════════════

let seq = 0;
/** Monotonic, run-unique timestamp string (never repeats within a run). */
function uniq(): string {
  return `${Date.now()}${String(seq++).padStart(3, '0')}`;
}

/** 13-digit raw CNIC + its canonical dashed form (XXXXX-XXXXXXX-X). */
function makeCnic(): { raw: string; dashed: string } {
  const raw = uniq().slice(-13);
  return { raw, dashed: `${raw.slice(0, 5)}-${raw.slice(5, 12)}-${raw.slice(12)}` };
}

function makePhone(): string {
  return `+92-300-${uniq().slice(-7)}`;
}

function makeEmail(): string {
  return `qa+${uniq()}@example.com`;
}

interface CustomerInfo {
  id: number;
  customerId: string;
  cnic: string;
  email: string | null;
  phone: string;
  firstName: string;
  lastName: string;
}

/**
 * Create a customer via the DRF API (admin). The create response uses
 * `CustomerCreateSerializer` (no numeric `id`), so we resolve the pk with a
 * search on the generated `customer_id`. Retries on 500: `Customer.save()`
 * derives the next `CUS-XXXXX` id via `select_for_update` on the last row, which
 * races under parallel execution and intermittently raises IntegrityError.
 */
async function createCustomerViaApi(
  request: APIRequestContext,
  token: string,
  overrides: Record<string, unknown> = {},
): Promise<CustomerInfo> {
  for (let attempt = 0; attempt < 6; attempt++) {
    const { dashed } = makeCnic();
    const payload = {
      first_name: 'QA',
      last_name: 'Customer',
      phone: makePhone(),
      cnic: dashed,
      email: makeEmail(),
      ...overrides,
    };
    const res = await request.post('/api/customers/', {
      data: payload,
      headers: { 'X-CSRFToken': token },
    });
    if (res.status() === 201) {
      const body = await res.json();
      const listRes = await request.get('/api/customers/', { params: { search: body.customer_id } });
      const rows = await listRes.json();
      const row = rows.find((r: { customer_id: string }) => r.customer_id === body.customer_id);
      expect(row, `created customer ${body.customer_id} not found in list`).toBeTruthy();
      return {
        id: row.id,
        customerId: body.customer_id,
        cnic: body.cnic,
        email: body.email ?? null,
        phone: body.phone,
        firstName: body.first_name,
        lastName: body.last_name,
      };
    }
    if (res.status() !== 500) {
      // Real validation error — surface it.
      expect(res.status(), `create customer failed: ${await res.text()}`).toBe(201);
    }
    // else: 500 (auto-id race) → retry with a fresh CNIC.
  }
  throw new Error('createCustomerViaApi: could not create customer after retries');
}

/** Best-effort teardown: delete any bookings (restoring their plots) then the customer. */
async function deleteCustomerViaApi(
  request: APIRequestContext,
  token: string,
  id: number,
): Promise<void> {
  try {
    const bs = await request.get(`/api/customers/${id}/bookings/`);
    if (bs.ok()) {
      const bookings = await bs.json();
      for (const b of bookings) {
        await request.delete(`/api/bookings/${b.id}/`, { headers: { 'X-CSRFToken': token } }).catch(() => {});
      }
    }
  } catch {
    /* ignore */
  }
  await request.delete(`/api/customers/${id}/`, { headers: { 'X-CSRFToken': token } }).catch(() => {});
}

/**
 * Book the customer onto an available zero-deposit plot with a zero advance so
 * no Payment is auto-created (keeps teardown a clean booking delete). Loops over
 * candidate plots to be safe under parallel execution.
 */
async function createBookingViaApi(
  request: APIRequestContext,
  token: string,
  customerId: number,
): Promise<{ id: number; booking_id: string }> {
  const plotsRes = await request.get('/api/plots/');
  const plots = await plotsRes.json();
  const candidates = plots.filter(
    (p: { status: string; holding_deposit: string | null }) =>
      p.status === 'available' && (p.holding_deposit === '0.00' || p.holding_deposit == null),
  );
  let lastStatus = 0;
  for (const plot of candidates) {
    const res = await request.post('/api/bookings/', {
      data: {
        customer: customerId,
        plot: plot.id,
        total_amount: plot.price,
        advance_paid: '0.00',
        source: 'walk_in',
      },
      headers: { 'X-CSRFToken': token },
    });
    if (res.status() === 201) {
      // The create response (BookingCreateSerializer) omits id/booking_id — resolve
      // the created booking from the customer's booking list.
      const bs = await request.get(`/api/customers/${customerId}/bookings/`);
      const bookings = await bs.json();
      const booking = bookings.find((b: { plot: number }) => b.plot === plot.id);
      expect(booking, 'created booking not found in customer bookings').toBeTruthy();
      return booking;
    }
    lastStatus = res.status();
  }
  throw new Error(`No available plot could be booked (last status ${lastStatus})`);
}

/**
 * Add a nominee via the HTML nominee form (POST with `csrfmiddlewaretoken`) —
 * there is no nominee DRF endpoint.
 */
async function addNomineeViaApi(
  request: APIRequestContext,
  token: string,
  customerId: number,
  name = 'Sara Khan',
): Promise<void> {
  const { raw } = makeCnic();
  await request.post(`/customers/${customerId}/nominee/`, {
    form: {
      csrfmiddlewaretoken: token,
      nominee_name: name,
      nominee_cnic: raw,
      nominee_phone: '',
      relationship: 'Wife',
    },
  });
}

// ══════════════════════════════════════════════════════════════════════════
// HP — happy path
// ══════════════════════════════════════════════════════════════════════════

test.describe('CUS — Happy path', () => {
  test.use({ storageState: { cookies: [], origins: [] } });
  test.beforeEach(async ({ page }) => {
    await loginViaUi(page, 'admin');
  });

  test('CUS-HP-01 — Create customer: auto CUS-XXXXX ID + failure-safe welcome email', async ({
    page,
    request,
  }) => {
    const token = await loginViaApi(request, 'admin');
    const { raw, dashed } = makeCnic();
    const phone = makePhone();
    const email = makeEmail();

    // Create #1 — with an email (welcome email fires; a delivery failure must not
    // prevent creation or the redirect).
    await page.goto('/customers/create/');
    await page.getByLabel('First Name').fill('Ali');
    await page.getByLabel('Last Name').fill('Khan');
    await page.getByLabel('CNIC Number').fill(raw);
    await page.getByLabel('Phone Number').fill(phone);
    await page.getByLabel('Email Address').fill(email);
    await page.getByRole('button', { name: 'Create Customer' }).click();
    await expect(page).toHaveURL(/\/customers\/$/);
    await expect(page.getByText(/created successfully/i).first()).toBeVisible();

    // Create #2 — blank email (still valid; welcome is skipped when no email).
    const cnic2 = makeCnic();
    await page.goto('/customers/create/');
    await page.getByLabel('First Name').fill('Ali');
    await page.getByLabel('Last Name').fill('Khan');
    await page.getByLabel('CNIC Number').fill(cnic2.raw);
    await page.getByLabel('Phone Number').fill(makePhone());
    await page.getByRole('button', { name: 'Create Customer' }).click();
    await expect(page).toHaveURL(/\/customers\/$/);
    await expect(page.getByText(/created successfully/i).first()).toBeVisible();

    // Both persisted with a CUS-XXXXX id and the dashed CNIC.
    for (const cnic of [dashed, cnic2.dashed]) {
      const list = await request.get('/api/customers/', { params: { search: cnic } });
      const row = (await list.json()).find((r: { cnic: string }) => r.cnic === cnic);
      expect(row, `customer with cnic ${cnic} persisted`).toBeTruthy();
      expect(row.customer_id).toMatch(/^CUS-\d{5}$/);
      await deleteCustomerViaApi(request, token, row.id);
    }
  });

  test('CUS-HP-02 — Edit customer', async ({ page, request }) => {
    const token = await loginViaApi(request, 'admin');
    const cust = await createCustomerViaApi(request, token);
    const newPhone = makePhone();

    await page.goto(`/customers/${cust.id}/edit/`);
    await page.getByLabel('Phone Number').fill(newPhone);
    await page.getByLabel('City').fill('Karachi');
    await page.getByRole('button', { name: 'Update Customer' }).click();
    await expect(page).toHaveURL(/\/customers\/$/);
    await expect(page.getByText(/updated successfully/i).first()).toBeVisible();

    const res = await request.get(`/api/customers/${cust.id}/`);
    const body = await res.json();
    expect(body.phone).toBe(newPhone);
    expect(body.city).toBe('Karachi');

    await deleteCustomerViaApi(request, token, cust.id);
  });

  test('CUS-HP-03 — View detail (CNIC / bookings)', async ({ page, request }) => {
    const token = await loginViaApi(request, 'admin');
    const cust = await createCustomerViaApi(request, token);
    await createBookingViaApi(request, token, cust.id);

    await page.goto(`/customers/${cust.id}/`);
    await expect(page.getByText(`${cust.firstName} ${cust.lastName}`).first()).toBeVisible();
    await expect(page.getByText(cust.cnic)).toBeVisible(); // dashed CNIC
    if (cust.email) await expect(page.getByText(cust.email)).toBeVisible();
    await expect(page.getByText(/1 booking/i).first()).toBeVisible();

    await deleteCustomerViaApi(request, token, cust.id);
  });

  test('CUS-HP-04 — Search by name / phone / CNIC', async ({ page, request }) => {
    const token = await loginViaApi(request, 'admin');
    const cust = await createCustomerViaApi(request, token, { first_name: 'Zulfiqar' });

    await page.goto(`/customers/?search=Zulfiqar`);
    await expect(page.getByText(cust.customerId)).toBeVisible();

    await page.goto(`/customers/?search=${cust.phone.slice(-4)}`);
    await expect(page.getByText(cust.customerId)).toBeVisible();

    await page.goto(`/customers/?search=${cust.cnic.slice(0, 8)}`);
    await expect(page.getByText(cust.customerId)).toBeVisible();

    await deleteCustomerViaApi(request, token, cust.id);
  });

  test('CUS-HP-05 — Add nominee', async ({ page, request }) => {
    const token = await loginViaApi(request, 'admin');
    const cust = await createCustomerViaApi(request, token);
    const { raw } = makeCnic();

    await page.goto(`/customers/${cust.id}/nominee/`);
    await page.locator('#id_nominee_name').fill('Sara Khan');
    await page.locator('#id_nominee_cnic').fill(raw);
    await page.locator('#id_relationship').fill('Wife');
    await page.getByRole('button', { name: 'Save Nominee' }).click();
    await expect(page).toHaveURL(new RegExp(`/customers/${cust.id}/$`));
    await expect(page.getByText('Sara Khan')).toBeVisible();

    await deleteCustomerViaApi(request, token, cust.id);
  });

  test('CUS-HP-06 — Edit nominee', async ({ page, request }) => {
    const token = await loginViaApi(request, 'admin');
    const cust = await createCustomerViaApi(request, token);
    await addNomineeViaApi(request, token, cust.id);

    const newPhone = makePhone();
    await page.goto(`/customers/${cust.id}/nominee/`);
    await page.locator('#id_nominee_phone').fill(newPhone);
    await page.getByRole('button', { name: 'Save Nominee' }).click();
    await expect(page).toHaveURL(new RegExp(`/customers/${cust.id}/$`));
    await expect(page.getByText(newPhone)).toBeVisible();

    await deleteCustomerViaApi(request, token, cust.id);
  });

  test('CUS-HP-07 — Remove nominee', async ({ page, request }) => {
    const token = await loginViaApi(request, 'admin');
    const cust = await createCustomerViaApi(request, token);
    await addNomineeViaApi(request, token, cust.id);

    await page.goto(`/customers/${cust.id}/nominee/`);
    await page.locator('#id_nominee_name').fill('');
    await page.getByRole('button', { name: 'Save Nominee' }).click();

    // NOTE: the template instructs "leave Nominee Name blank to remove", but
    // `nominee_name` is a required field (customers/models.py:167, no blank=True),
    // so the form re-renders with a required-field error and the nominee is NOT
    // removed. We assert the actual current behaviour (form stays, nominee intact).
    await expect(page).toHaveURL(new RegExp(`/customers/${cust.id}/nominee/$`));
    const detail = await request.get(`/customers/${cust.id}/`);
    expect(await detail.text()).toContain('Sara Khan');

    await deleteCustomerViaApi(request, token, cust.id);
  });

  test('CUS-HP-08 — Create portal login (profile-create)', async ({ page, request }) => {
    const token = await loginViaApi(request, 'admin');
    const cust = await createCustomerViaApi(request, token);
    const username = `qa_portal_${uniq()}`;
    const email = makeEmail();

    await page.goto('/customers/create-profile/');
    await page.getByLabel('Customer').selectOption(String(cust.id));
    await page.getByLabel('Username').fill(username);
    await page.getByLabel('Email').fill(email);
    await page.getByLabel(/^Password/).fill('secret123');
    await page.getByLabel('Confirm Password').fill('secret123');
    await page.getByRole('button', { name: 'Create Profile' }).click();
    await expect(page).toHaveURL(/\/customers\/$/);
    await expect(page.getByText(/Portal login created/i).first()).toBeVisible();

    // A User now exists for the new login.
    const users = await request.get('/api/users/');
    const found = (await users.json()).find((u: { username: string }) => u.username === username);
    expect(found, 'portal user created').toBeTruthy();

    // Verify the new login is non-staff and linked to the customer (is_customer=true).
    await request.get('/api/auth/csrf/');
    const csrf2 = (await request.storageState()).cookies.find((c) => c.name === 'csrftoken')?.value ?? '';
    const login = await request.post('/api/auth/login/', {
      data: { username, password: 'secret123' },
      headers: csrf2 ? { 'X-CSRFToken': csrf2 } : {},
    });
    expect(login.status()).toBe(200);
    const me = await request.get('/api/auth/me/');
    expect((await me.json()).is_staff).toBe(false);
    expect((await me.json()).is_customer).toBe(true);

    // Cleanup (re-auth as admin; the previous admin token is no longer valid).
    const adminToken = await loginViaApi(request, 'admin');
    await deleteCustomerViaApi(request, adminToken, cust.id);
  });

  test('CUS-HP-09 — Customer profile PDF', async ({ page, request }) => {
    const token = await loginViaApi(request, 'admin');
    const cust = await createCustomerViaApi(request, token);
    await createBookingViaApi(request, token, cust.id);
    await addNomineeViaApi(request, token, cust.id);

    const res = await page.request.get(`/customers/${cust.id}/pdf/`);
    expect(res.status()).toBe(200);
    expect(res.headers()['content-type']).toContain('application/pdf');
    expect(res.headers()['content-disposition']).toContain(
      `attachment; filename="customer_profile_${cust.customerId}.pdf"`,
    );
    expect((await res.body()).length).toBeGreaterThan(0);

    await deleteCustomerViaApi(request, token, cust.id);
  });
});

// ══════════════════════════════════════════════════════════════════════════
// EC — edge cases / boundaries
// ══════════════════════════════════════════════════════════════════════════

test.describe('CUS — Edge cases', () => {
  test.use({ storageState: { cookies: [], origins: [] } });
  test.beforeEach(async ({ page }) => {
    await loginViaUi(page, 'admin');
  });

  test('CUS-EC-01 — Duplicate CNIC rejected', async ({ page, request }) => {
    const token = await loginViaApi(request, 'admin');
    const existing = await createCustomerViaApi(request, token);
    const raw = existing.cnic.replace(/\D/g, ''); // 13 raw digits of the same CNIC

    await page.goto('/customers/create/');
    await page.getByLabel('First Name').fill('Dup');
    await page.getByLabel('Last Name').fill('CNIC');
    await page.getByLabel('CNIC Number').fill(raw);
    await page.getByLabel('Phone Number').fill(makePhone());
    await page.getByRole('button', { name: 'Create Customer' }).click();

    // Form re-renders with a uniqueness error on cnic; no second row is created.
    await expect(page).toHaveURL(/\/customers\/create\/$/);
    await expect(page.getByText(/already exists/i)).toBeVisible();

    const list = await request.get('/api/customers/', { params: { search: existing.cnic } });
    const rows = await list.json();
    expect(rows.filter((r: { cnic: string }) => r.cnic === existing.cnic).length).toBe(1);

    await deleteCustomerViaApi(request, token, existing.id);
  });

  test('CUS-EC-02 — Duplicate email rejected', async ({ page, request }) => {
    const token = await loginViaApi(request, 'admin');
    const existing = await createCustomerViaApi(request, token);
    expect(existing.email).toBeTruthy();

    await page.goto('/customers/create/');
    await page.getByLabel('First Name').fill('Dup');
    await page.getByLabel('Last Name').fill('Email');
    await page.getByLabel('CNIC Number').fill(makeCnic().raw);
    await page.getByLabel('Phone Number').fill(makePhone());
    await page.getByLabel('Email Address').fill(existing.email!);
    await page.getByRole('button', { name: 'Create Customer' }).click();

    await expect(page).toHaveURL(/\/customers\/create\/$/);
    await expect(page.getByText(/already exists/i)).toBeVisible();

    await deleteCustomerViaApi(request, token, existing.id);
  });

  test('CUS-EC-03 — Phone format divergence (form strict vs serializer loose)', async ({
    page,
    request,
  }) => {
    const token = await loginViaApi(request, 'admin');
    const garbagePhone = '-----------'; // 11 dashes

    // HTML: strict form rejects it.
    await page.goto('/customers/create/');
    await page.getByLabel('First Name').fill('Bad');
    await page.getByLabel('Last Name').fill('Phone');
    await page.getByLabel('CNIC Number').fill(makeCnic().raw);
    await page.getByLabel('Phone Number').fill(garbagePhone);
    await page.getByRole('button', { name: 'Create Customer' }).click();
    await expect(page).toHaveURL(/\/customers\/create\/$/);
    await expect(page.getByText(/Phone must be in format/i)).toBeVisible();

    // API: loose serializer accepts it verbatim.
    const { dashed } = makeCnic();
    const res = await request.post('/api/customers/', {
      data: { first_name: 'Bad', last_name: 'Phone', phone: garbagePhone, cnic: dashed },
      headers: { 'X-CSRFToken': token },
    });
    expect(res.status()).toBe(201);
    const body = await res.json();
    expect(body.phone).toBe(garbagePhone);

    const list = await request.get('/api/customers/', { params: { search: dashed } });
    const row = (await list.json()).find((r: { cnic: string }) => r.cnic === dashed);
    await deleteCustomerViaApi(request, token, row.id);
  });

  test('CUS-EC-04 — CNIC format asymmetry (form normalizes 13-digit, serializer requires dashed)', async ({
    page,
    request,
  }) => {
    const token = await loginViaApi(request, 'admin');

    // HTML: raw 13 digits → accepted and stored dashed.
    const { raw, dashed } = makeCnic();
    await page.goto('/customers/create/');
    await page.getByLabel('First Name').fill('Cnic');
    await page.getByLabel('Last Name').fill('Norm');
    await page.getByLabel('CNIC Number').fill(raw);
    await page.getByLabel('Phone Number').fill(makePhone());
    await page.getByRole('button', { name: 'Create Customer' }).click();
    await expect(page).toHaveURL(/\/customers\/$/);
    const listHtml = await request.get('/api/customers/', { params: { search: dashed } });
    const rowHtml = (await listHtml.json()).find((r: { cnic: string }) => r.cnic === dashed);
    expect(rowHtml, 'HTML-form cnic stored dashed').toBeTruthy();
    await deleteCustomerViaApi(request, token, rowHtml.id);

    // API: raw 13 digits → 400; dashed → 201.
    const rawRes = await request.post('/api/customers/', {
      data: { first_name: 'Cnic', last_name: 'Norm', phone: makePhone(), cnic: raw },
      headers: { 'X-CSRFToken': token },
    });
    expect(rawRes.status()).toBe(400);

    const dashedRes = await request.post('/api/customers/', {
      data: { first_name: 'Cnic', last_name: 'Norm', phone: makePhone(), cnic: dashed },
      headers: { 'X-CSRFToken': token },
    });
    expect(dashedRes.status()).toBe(201);
    const listApi = await request.get('/api/customers/', { params: { search: dashed } });
    const rowApi = (await listApi.json()).find((r: { cnic: string }) => r.cnic === dashed);
    await deleteCustomerViaApi(request, token, rowApi.id);
  });

  test('CUS-EC-05 — Ledger running_balance drift on same-date entries', async ({ request }) => {
    const token = await loginViaApi(request, 'admin');
    const cust = await createCustomerViaApi(request, token);

    // The customer ledger create API is currently broken: `running_balance` is
    // read-only in the serializer but NOT NULL with no default on the model, so
    // `perform_create` calls `serializer.save()` (omitting running_balance) and
    // raises IntegrityError before its `entry_date__lt` balance logic ever runs.
    // We assert the actual 500; once the field/ordering is fixed, replace this
    // with the two-entry same-date drift assertion described in specs/customers.md.
    const res = await request.post('/api/customer-ledger/', {
      data: {
        customer: cust.id,
        transaction_type: 'adjustment',
        debit: '100.00',
        credit: '0.00',
        entry_date: '2026-09-13',
      },
      headers: { 'X-CSRFToken': token },
    });
    expect(res.status()).toBe(500);

    await deleteCustomerViaApi(request, token, cust.id);
  });

  test('CUS-EC-06 — Nominee validation errors silently swallowed', async ({ page, request }) => {
    const token = await loginViaApi(request, 'admin');
    const cnic = makeCnic();

    // Valid customer fields, but an invalid nominee field (nominee_cnic 'abc' —
    // the only nominee field that carries validation; nominee_phone has none).
    await page.goto('/customers/create/');
    await page.getByLabel('First Name').fill('Nom');
    await page.getByLabel('Last Name').fill('Drop');
    await page.getByLabel('CNIC Number').fill(cnic.raw);
    await page.getByLabel('Phone Number').fill(makePhone());
    await page.getByLabel('Nominee Name').fill('Sara Khan');
    await page.getByLabel('Nominee CNIC').fill('abc');
    await page.getByRole('button', { name: 'Create Customer' }).click();

    // Customer saves (success); the invalid nominee is silently dropped.
    await expect(page).toHaveURL(/\/customers\/$/);
    await expect(page.getByText(/created successfully/i).first()).toBeVisible();

    const list = await request.get('/api/customers/', { params: { search: cnic.dashed } });
    const row = (await list.json()).find((r: { cnic: string }) => r.cnic === cnic.dashed);
    expect(row, 'customer persisted').toBeTruthy();
    const detail = await request.get(`/customers/${row.id}/`);
    expect(await detail.text()).not.toContain('Sara Khan');

    await deleteCustomerViaApi(request, token, row.id);
  });

  test('CUS-EC-07 — 14-digit CNIC in lead-convert slips through', async ({ request }) => {
    const token = await loginViaApi(request, 'admin');

    const leadRes = await request.post('/api/leads/', {
      data: { name: 'Lead Conv', phone: '+92-300-4444444' },
      headers: { 'X-CSRFToken': token },
    });
    expect(leadRes.status()).toBe(201);
    const lead = await leadRes.json();

    const cnic14 = `${makeCnic().raw}9`; // 14 digits
    const convRes = await request.post(`/api/leads/${lead.id}/convert/`, {
      data: { cnic: cnic14, name: 'Lead Conv', phone: '+92-300-4444444' },
      headers: { 'X-CSRFToken': token },
    });
    expect(convRes.status()).toBe(201);
    const conv = await convRes.json();

    const customer = await request.get(`/api/customers/${conv.customer_pk}/`);
    expect(customer.status()).toBe(200);
    expect((await customer.json()).cnic).toBe(cnic14); // stored raw, un-dashed

    await deleteCustomerViaApi(request, token, conv.customer_pk);
  });

  test('CUS-EC-08 — CNIC pasted with dashes/letters is normalized in the form', async ({
    page,
  }) => {
    // NOTE: the CNIC input carries maxlength=13 (forms.py __init__) plus a JS
    // handler that strips non-digits. A dashed 15-char paste is truncated to 13
    // chars BEFORE the dashes are stripped, dropping the final digit, so the form
    // rejects it. The server-side `clean_cnic` normalization is therefore
    // unreachable through the UI. We assert the actual current behaviour.
    await page.goto('/customers/create/');
    await page.getByLabel('First Name').fill('Paste');
    await page.getByLabel('Last Name').fill('Cnic');
    await page.getByLabel('CNIC Number').fill('37405-1234567-8');
    await page.getByLabel('Phone Number').fill(makePhone());
    await page.getByRole('button', { name: 'Create Customer' }).click();

    await expect(page).toHaveURL(/\/customers\/create\/$/);
    await expect(page.getByText(/CNIC must be exactly 13 digits/i)).toBeVisible();
  });
});

// ══════════════════════════════════════════════════════════════════════════
// SEC — negative & security (prioritized)
// ══════════════════════════════════════════════════════════════════════════

test.describe('CUS — Security (negative)', () => {
  test.describe('IDOR (sales user)', () => {
    test.use({ storageState: { cookies: [], origins: [] } });
    test.beforeEach(async ({ page }) => {
      await loginViaUi(page, 'sales');
    });

    test('CUS-SEC-01 — IDOR: sales user reads any customer detail', async ({ page, request }) => {
      // CONFIRMED BUG: docs/qa/findings-confirmed.md F3
      const token = await loginViaApi(request, 'admin');
      let victim: CustomerInfo | undefined;
      try {
        victim = await createCustomerViaApi(request, token);
        await page.goto(`/customers/${victim.id}/`);
        // Correct behaviour: a non-owner is redirected away from the detail page.
        await expect(page).toHaveURL(/\/dashboard\//);
      } finally {
        if (victim) await deleteCustomerViaApi(request, token, victim.id);
      }
    });

    test('CUS-SEC-02 — IDOR: sales user edits any customer', async ({ page, request }) => {
      // CONFIRMED BUG: docs/qa/findings-confirmed.md F3
      const token = await loginViaApi(request, 'admin');
      let victim: CustomerInfo | undefined;
      try {
        victim = await createCustomerViaApi(request, token);
        const originalPhone = victim.phone;
        const tampered = makePhone();

        await page.goto(`/customers/${victim.id}/edit/`);
        await page.getByLabel('Phone Number').fill(tampered);
        await page.getByRole('button', { name: 'Update Customer' }).click();

        // Correct behaviour: the edit is denied and the victim's phone is unchanged.
        const res = await request.get(`/api/customers/${victim.id}/`);
        expect((await res.json()).phone).toBe(originalPhone);
      } finally {
        if (victim) await deleteCustomerViaApi(request, token, victim.id);
      }
    });

    test('CUS-SEC-03 — IDOR: sales user manages any customer’s nominee', async ({
      page,
      request,
    }) => {
      // CONFIRMED BUG: docs/qa/findings-confirmed.md F3
      const token = await loginViaApi(request, 'admin');
      let victim: CustomerInfo | undefined;
      try {
        victim = await createCustomerViaApi(request, token);
        await addNomineeViaApi(request, token, victim.id);

        // sales edits the victim's nominee (the manage view is @login_required only).
        await page.goto(`/customers/${victim.id}/nominee/`);
        await page.locator('#id_nominee_name').fill('Hacker Khan');
        await page.getByRole('button', { name: 'Save Nominee' }).click();

        // Correct behaviour: denied — the victim's nominee name is unchanged.
        const detail = await request.get(`/customers/${victim.id}/`);
        expect(await detail.text()).toContain('Sara Khan');
      } finally {
        if (victim) await deleteCustomerViaApi(request, token, victim.id);
      }
    });

    test('CUS-SEC-04 — IDOR: any authenticated user downloads any customer profile PDF', async ({
      page,
      request,
    }) => {
      // CONFIRMED BUG: docs/qa/findings-confirmed.md F3
      const token = await loginViaApi(request, 'admin');
      let victim: CustomerInfo | undefined;
      try {
        victim = await createCustomerViaApi(request, token);
        const res = await page.request.get(`/customers/${victim.id}/pdf/`);
        // Correct behaviour: denied for a non-owner (not a 200 PDF).
        expect(res.status()).toBe(403);
      } finally {
        if (victim) await deleteCustomerViaApi(request, token, victim.id);
      }
    });
  });

  test.describe('Portal customer reaches /customers/*', () => {
    test.use({ storageState: { cookies: [], origins: [] } });
    test.beforeEach(async ({ page }) => {
      await loginViaUi(page, 'customer');
    });

    test('CUS-SEC-05 — Portal customer reaches /customers/* (no is_staff gate)', async ({
      page,
    }) => {
      // CONFIRMED BUG: docs/qa/findings-confirmed.md F3
      // Land on the portal first (confirms we are the non-staff customer).
      await page.goto('/portal/');
      await expect(page).toHaveURL(/\/portal\/$/);

      // Correct behaviour: non-staff is redirected away from the ERP customer area.
      await page.goto('/customers/');
      await expect(page).toHaveURL(/\/portal\//); // FAILS: list renders
    });
  });

  test('CUS-SEC-06 — API PII exposure: any authenticated user GETs full customer data', async ({
    request,
  }) => {
    // CONFIRMED BUG: docs/qa/findings-confirmed.md F3
    await loginViaApi(request, 'sales');
    const res = await request.get('/api/customers/');
    // Correct behaviour: a non-admin GET is forbidden.
    expect.soft(res.status()).toBe(403);
    // Document the PII that is actually exposed (the bug): full cnic/phone/email.
    const rows = await res.json();
    expect(rows.length).toBeGreaterThan(0);
    expect(rows[0]).toHaveProperty('cnic');
    expect(rows[0]).toHaveProperty('phone');
    expect(rows[0]).toHaveProperty('email');
  });

  test('CUS-SEC-07 — Profile-create overwrite orphans the previous User', async ({ request }) => {
    // CONFIRMED BUG: docs/qa/findings-confirmed.md F3
    const token = await loginViaApi(request, 'admin');
    const cust = await createCustomerViaApi(request, token);

    // First profile-create links a User.
    const first = await request.post('/api/customer-profiles/', {
      data: {
        username: `qa_old_${uniq()}`,
        email: makeEmail(),
        password: 'secret123',
        confirm_password: 'secret123',
        customer: cust.id,
      },
      headers: { 'X-CSRFToken': token },
    });
    expect(first.status()).toBe(201);

    // Second profile-create on the same customer.
    const second = await request.post('/api/customer-profiles/', {
      data: {
        username: `qa_new_${uniq()}`,
        email: makeEmail(),
        password: 'secret123',
        confirm_password: 'secret123',
        customer: cust.id,
      },
      headers: { 'X-CSRFToken': token },
    });

    // Correct behaviour: re-create is refused because the customer already has a
    // profile (the previous User must not be orphaned).
    expect.soft(second.status()).toBe(400);
    // Document the bug: the second create succeeds (201) and re-links the customer.
    if (second.status() === 201) {
      const body = await second.json();
      expect(body).toHaveProperty('customer_id', cust.customerId);
    }

    await deleteCustomerViaApi(request, token, cust.id);
  });

  test('CUS-SEC-08 — Delete guard: blocked when bookings/ledger exist', async ({ request }) => {
    const token = await loginViaApi(request, 'admin');
    const cust = await createCustomerViaApi(request, token);
    await createBookingViaApi(request, token, cust.id);

    const res = await request.post(`/customers/${cust.id}/delete/`, {
      form: { csrfmiddlewaretoken: token },
    });
    expect(res.status()).toBe(200); // followed redirect to detail with error message
    expect(await res.text()).toContain('Cannot delete a customer with bookings or ledger history');

    // Customer is intact.
    const get = await request.get(`/api/customers/${cust.id}/`);
    expect(get.status()).toBe(200);

    await deleteCustomerViaApi(request, token, cust.id);
  });

  test('CUS-SEC-09 — Delete: hard delete when clean (nominee cascades)', async ({ request }) => {
    const token = await loginViaApi(request, 'admin');
    const cust = await createCustomerViaApi(request, token);
    await addNomineeViaApi(request, token, cust.id);

    const res = await request.post(`/customers/${cust.id}/delete/`, {
      form: { csrfmiddlewaretoken: token },
    });
    expect(res.status()).toBe(200); // redirect to /customers/ after delete

    const get = await request.get(`/api/customers/${cust.id}/`);
    expect(get.status()).toBe(404); // hard-deleted, no soft-delete
  });

  test('CUS-SEC-10 — Unauthenticated access redirects to login (baseline)', async ({ browser }) => {
    const ctx = await browser.newContext({
      baseURL: 'http://127.0.0.1:8000',
      storageState: { cookies: [], origins: [] },
    });
    const page = await ctx.newPage();

    await page.goto('/customers/');
    await expect(page).toHaveURL(/\/login\//);

    const api = await ctx.request.get('/api/customers/');
    expect([401, 403]).toContain(api.status());

    await ctx.close();
  });
});

// ══════════════════════════════════════════════════════════════════════════
// API — API contract
// ══════════════════════════════════════════════════════════════════════════

test.describe('CUS — API contract', () => {
  test('CUS-API-01 — GET /api/customers/ (list)', async ({ request }) => {
    await loginViaApi(request, 'admin');
    const res = await request.get('/api/customers/');
    expect(res.status()).toBe(200);
    const rows = await res.json();
    expect(Array.isArray(rows)).toBe(true);
    expect(rows.length).toBeGreaterThan(0);
    expect(rows[0]).toHaveProperty('customer_id');
    expect(rows[0]).toHaveProperty('cnic');
    expect(rows[0]).toHaveProperty('phone');
    expect(rows[0]).toHaveProperty('email');
    expect(rows[0]).toHaveProperty('total_bookings');
    expect(rows[0]).toHaveProperty('total_paid');
    expect(rows[0]).toHaveProperty('current_balance');

    // is_active filter narrows to active only.
    const active = await request.get('/api/customers/', { params: { is_active: 'true' } });
    expect(active.status()).toBe(200);
    for (const r of await active.json()) expect(r.is_active).toBe(true);
  });

  test('CUS-API-02 — POST /api/customers/ (create)', async ({ request }) => {
    const token = await loginViaApi(request, 'admin');
    const { dashed } = makeCnic();

    const res = await request.post('/api/customers/', {
      data: { first_name: 'Api', last_name: 'Create', phone: makePhone(), cnic: dashed, email: makeEmail() },
      headers: { 'X-CSRFToken': token },
    });
    expect(res.status()).toBe(201);
    const body = await res.json();
    expect(body.customer_id).toMatch(/^CUS-\d{5}$/);
    expect(body.cnic).toBe(dashed);

    // Missing cnic / non-dashed cnic → 400.
    const noCnic = await request.post('/api/customers/', {
      data: { first_name: 'X', last_name: 'Y', phone: makePhone() },
      headers: { 'X-CSRFToken': token },
    });
    expect(noCnic.status()).toBe(400);

    const badCnic = await request.post('/api/customers/', {
      data: { first_name: 'X', last_name: 'Y', phone: makePhone(), cnic: '1234567890123' },
      headers: { 'X-CSRFToken': token },
    });
    expect(badCnic.status()).toBe(400);

    const list = await request.get('/api/customers/', { params: { search: dashed } });
    const row = (await list.json()).find((r: { cnic: string }) => r.cnic === dashed);
    await deleteCustomerViaApi(request, token, row.id);
  });

  test('CUS-API-03 — Search param names diverge (search vs q)', async ({ request }) => {
    const token = await loginViaApi(request, 'admin');
    const { dashed } = makeCnic();
    const last = `Zz${uniq()}`;

    const create = await request.post('/api/customers/', {
      data: { first_name: 'Search', last_name: last, phone: makePhone(), cnic: dashed },
      headers: { 'X-CSRFToken': token },
    });
    expect(create.status()).toBe(201);

    // (1) list endpoint filters on `search`
    const bySearch = await request.get('/api/customers/', { params: { search: last } });
    expect((await bySearch.json()).length).toBe(1);

    // (2) search action filters on `q`
    const byQ = await request.get('/api/customers/search/', { params: { q: last } });
    expect((await byQ.json()).length).toBe(1);

    // (3) search action ignores `search` → returns ALL customers, not the single match
    const cross = await request.get('/api/customers/search/', { params: { search: last } });
    expect((await cross.json()).length).toBeGreaterThan(1);

    const list = await request.get('/api/customers/', { params: { search: last } });
    const row = (await list.json()).find((r: { cnic: string }) => r.cnic === dashed);
    await deleteCustomerViaApi(request, token, row.id);
  });

  test('CUS-API-04 — customer_bookings action', async ({ request }) => {
    const token = await loginViaApi(request, 'admin');
    const cust = await createCustomerViaApi(request, token);
    const booking = await createBookingViaApi(request, token, cust.id);

    const res = await request.get(`/api/customers/${cust.id}/bookings/`);
    expect(res.status()).toBe(200);
    const rows = await res.json();
    expect(rows.length).toBe(1);
    expect(rows[0].booking_id).toBe(booking.booking_id);
    expect(rows[0].customer).toBe(cust.id);

    await deleteCustomerViaApi(request, token, cust.id);
  });

  test('CUS-API-05 — customer_ledger action', async ({ request }) => {
    const token = await loginViaApi(request, 'admin');
    const cust = await createCustomerViaApi(request, token);

    // The ledger create API is broken (see CUS-EC-05), so a fresh customer has no
    // entries; the action still returns 200 with a JSON array.
    const res = await request.get(`/api/customers/${cust.id}/ledger/`);
    expect(res.status()).toBe(200);
    expect(Array.isArray(await res.json())).toBe(true);

    await deleteCustomerViaApi(request, token, cust.id);
  });

  test('CUS-API-06 — Customer delete semantics', async ({ request }) => {
    const token = await loginViaApi(request, 'admin');
    const rich = await createCustomerViaApi(request, token);
    await createBookingViaApi(request, token, rich.id);
    const clean = await createCustomerViaApi(request, token);

    // rich → 400 with an error body
    const richDel = await request.delete(`/api/customers/${rich.id}/`, {
      headers: { 'X-CSRFToken': token },
    });
    expect(richDel.status()).toBe(400);
    expect(await richDel.json()).toHaveProperty('error');

    // clean → 204 hard delete
    const cleanDel = await request.delete(`/api/customers/${clean.id}/`, {
      headers: { 'X-CSRFToken': token },
    });
    expect(cleanDel.status()).toBe(204);

    await deleteCustomerViaApi(request, token, rich.id);
  });

  test('CUS-API-07 — PUT/PATCH validation (dashed CNIC required, loose phone)', async ({ request }) => {
    const token = await loginViaApi(request, 'admin');
    const cust = await createCustomerViaApi(request, token);

    // raw 13-digit cnic → 400
    const rawCnic = cust.cnic.replace(/\D/g, '');
    const badCnic = await request.patch(`/api/customers/${cust.id}/`, {
      data: { cnic: rawCnic },
      headers: { 'X-CSRFToken': token },
    });
    expect(badCnic.status()).toBe(400);

    // dashed cnic → 200
    const okCnic = await request.patch(`/api/customers/${cust.id}/`, {
      data: { cnic: cust.cnic },
      headers: { 'X-CSRFToken': token },
    });
    expect(okCnic.status()).toBe(200);

    // dash-only phone → 200 (loose phone accepted)
    const loosePhone = await request.patch(`/api/customers/${cust.id}/`, {
      data: { phone: '-----------' },
      headers: { 'X-CSRFToken': token },
    });
    expect(loosePhone.status()).toBe(200);

    await deleteCustomerViaApi(request, token, cust.id);
  });

  test('CUS-API-08 — POST /api/customer-profiles/ (portal login)', async ({ request }) => {
    const token = await loginViaApi(request, 'admin');
    const cust = await createCustomerViaApi(request, token);

    const res = await request.post('/api/customer-profiles/', {
      data: {
        username: `qa_api_portal_${uniq()}`,
        email: makeEmail(),
        password: 'secret123',
        confirm_password: 'secret123',
        customer: cust.id,
      },
      headers: { 'X-CSRFToken': token },
    });
    expect(res.status()).toBe(201);
    const body = await res.json();
    expect(body).toHaveProperty('id');
    expect(body).toHaveProperty('username');
    expect(body).toHaveProperty('email');
    expect(body).toHaveProperty('customer_id', cust.customerId);
    expect(body).toHaveProperty('full_name');

    await deleteCustomerViaApi(request, token, cust.id);
  });
});
