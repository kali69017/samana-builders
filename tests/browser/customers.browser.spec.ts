import { test, expect, APIRequestContext } from '@playwright/test';
import { loginViaApi } from '../helpers/auth';

/**
 * Samana ERP — Customers module, BROWSER-driven Playwright suite.
 *
 * Drives the real rendered UI (Django templates via `core/views.py`) with
 * `page` and role-specific `storageState`, and cross-checks money/IDs against
 * the DRF API with `request`. Complements `tests/customers/customers.spec.ts`
 * (API + mixed) — this file is pure browser navigation / fill / click.
 *
 * Roles: `admin` (super_admin) for the happy path + edge cases + delete flow,
 * `sales` and `customer` for the IDOR/PII security surface (RED on purpose —
 * see `docs/qa/findings-confirmed.md` F3).
 *
 * Field labels / button names / headers are taken verbatim from
 * `templates/customers.html`, `customer_form.html`, `customer_detail.html`,
 * `customer_nominee_form.html`, `customer_profile_form.html`.
 *
 * NOTE on "filter by status" / "pagination": the customers list view
 * (`core/views.py:604 customers_view`) supports only `?search=` (substring
 * across customer_id / first_name / last_name / phone / cnic). There is NO
 * status filter dropdown and NO server-side pagination — the table is a single
 * unpaginated list with a client-side "View More / View Less" collapse toggle
 * (`static/js/erp.js:368-417`). Those two requirements are therefore covered as
 * status-badge rendering and the client-side collapse, respectively.
 *
 * Run with `DJANGO_DEBUG=True python manage.py runserver` on :8000.
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

/** Customers created during this worker's run (deleted in afterAll). */
const createdCustomers: number[] = [];
/** Portal-login usernames created during this worker's run (deleted in afterAll). */
const createdUsers: string[] = [];

/**
 * Create a customer via the DRF API (admin). The create response uses
 * `CustomerCreateSerializer` (no numeric `id`), so resolve the pk by searching
 * on the generated `customer_id`. Retries on 500: `Customer.save()` derives the
 * next `CUS-XXXXX` id via `select_for_update` on the last row, which races under
 * parallel execution.
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
 * no Payment is auto-created (keeps teardown a clean booking delete).
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

/** Add a nominee via the HTML nominee form (POST with csrfmiddlewaretoken). */
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
// Happy path (admin)
// ══════════════════════════════════════════════════════════════════════════

test.describe('CUS — browser happy path (admin)', () => {
  test.beforeEach(async ({ page }) => { await loginViaApi(page.request, 'admin'); });

  test('CUS-HP-01 — create customer (all fields) + auto CUS-XXXXX id', async ({ page, request }) => {
    await loginViaApi(request, 'admin');
    const { raw, dashed } = makeCnic();
    const email = makeEmail();
    const phone = makePhone();

    await page.goto('/customers/create/');
    await page.getByLabel('First Name').fill('Ali');
    await page.getByLabel('Last Name').fill('Khan');
    await page.getByLabel('Email Address').fill(email);
    await page.getByLabel('CNIC Number').fill(raw);
    await page.getByLabel('Phone Number').fill(phone);
    await page.getByLabel('Alternate Phone').fill(makePhone());
    await page.getByLabel('Occupation', { exact: true }).selectOption('business');
    await page.getByLabel('City').fill('Karachi');
    await page.getByLabel('Full Address').fill('12 Main Street, Clifton');
    await page.getByLabel('Notes').fill('VIP customer');
    await page.getByRole('button', { name: 'Create Customer' }).click();

    await expect(page).toHaveURL(/\/customers\/$/);
    await expect(page.getByText(/created successfully/i).first()).toBeVisible();

    // Data via API: auto id, dashed CNIC, and the rest persisted.
    const list = await request.get('/api/customers/', { params: { search: dashed } });
    const row = (await list.json()).find((r: { cnic: string }) => r.cnic === dashed);
    expect(row, 'created customer persisted').toBeTruthy();
    expect(row.customer_id).toMatch(/^CUS-\d{5}$/);
    expect(row.cnic).toBe(dashed);
    expect(row.email).toBe(email);
    expect(row.phone).toBe(phone);
    expect(row.city).toBe('Karachi');
    createdCustomers.push(row.id);

    // Occupation is not exposed by the Customer list serializer; verify it via the
    // detail page (occupation_display_value renders "Business" for 'business').
    await page.goto(`/customers/${row.id}/`);
    await expect(page.locator('.detail-value', { hasText: 'Business' })).toBeVisible();
  });

  test('CUS-HP-02 — edit customer (phone + city); CNIC prefilled raw', async ({ page, request }) => {
    const token = await loginViaApi(request, 'admin');
    const cust = await createCustomerViaApi(request, token);
    createdCustomers.push(cust.id);
    const newPhone = makePhone();

    await page.goto(`/customers/${cust.id}/edit/`);
    // CNIC pre-fills as raw 13 digits (dashes stripped by the form).
    await expect(page.getByLabel('CNIC Number')).toHaveValue(cust.cnic.replace(/\D/g, ''));
    await page.getByLabel('Phone Number').fill(newPhone);
    await page.getByLabel('City').fill('Karachi');
    await page.getByRole('button', { name: 'Update Customer' }).click();

    await expect(page).toHaveURL(/\/customers\/$/);
    await expect(page.getByText(/updated successfully/i).first()).toBeVisible();

    const res = await request.get(`/api/customers/${cust.id}/`);
    const body = await res.json();
    expect(body.phone).toBe(newPhone);
    expect(body.city).toBe('Karachi');
  });

  test('CUS-HP-03 — detail view shows CNIC, booking and nominee', async ({ page, request }) => {
    const token = await loginViaApi(request, 'admin');
    const cust = await createCustomerViaApi(request, token);
    await createBookingViaApi(request, token, cust.id);
    await addNomineeViaApi(request, token, cust.id);
    createdCustomers.push(cust.id);

    await page.goto(`/customers/${cust.id}/`);
    await expect(page.getByText(`${cust.firstName} ${cust.lastName}`).first()).toBeVisible();
    await expect(page.getByText(cust.cnic)).toBeVisible(); // dashed CNIC
    await expect(page.getByText(/1 booking/i).first()).toBeVisible();
    await expect(page.getByText('Sara Khan')).toBeVisible(); // nominee name
  });

  test('CUS-HP-04 — search filters by name / phone / CNIC / customer ID', async ({ page, request }) => {
    const token = await loginViaApi(request, 'admin');
    const cust = await createCustomerViaApi(request, token, {
      first_name: 'Zulfiqar',
      last_name: `Br-${uniq()}`,
    });
    createdCustomers.push(cust.id);

    await page.goto(`/customers/?search=Zulfiqar`);
    await expect(page.getByText(cust.customerId).first()).toBeVisible();

    await page.goto(`/customers/?search=${cust.phone.slice(-4)}`);
    await expect(page.getByText(cust.customerId).first()).toBeVisible();

    await page.goto(`/customers/?search=${cust.cnic.slice(0, 8)}`);
    await expect(page.getByText(cust.customerId).first()).toBeVisible();

    await page.goto(`/customers/?search=${cust.customerId}`);
    await expect(page.getByText(cust.customerId).first()).toBeVisible();
  });

  test('CUS-HP-05 — add nominee via the manage form', async ({ page, request }) => {
    const token = await loginViaApi(request, 'admin');
    const cust = await createCustomerViaApi(request, token);
    createdCustomers.push(cust.id);
    const { raw } = makeCnic();

    await page.goto(`/customers/${cust.id}/nominee/`);
    // The manage form renders auto-generated labels without `for`, so target by id.
    await page.locator('#id_nominee_name').fill('Sara Khan');
    await page.locator('#id_nominee_cnic').fill(raw);
    await page.locator('#id_relationship').fill('Wife');
    await page.getByRole('button', { name: 'Save Nominee' }).click();

    await expect(page).toHaveURL(new RegExp(`/customers/${cust.id}/$`));
    await expect(page.getByText('Sara Khan')).toBeVisible();
  });

  test('CUS-HP-06 — edit nominee phone via the manage form', async ({ page, request }) => {
    const token = await loginViaApi(request, 'admin');
    const cust = await createCustomerViaApi(request, token);
    await addNomineeViaApi(request, token, cust.id);
    createdCustomers.push(cust.id);
    const newPhone = makePhone();

    await page.goto(`/customers/${cust.id}/nominee/`);
    await page.locator('#id_nominee_phone').fill(newPhone);
    await page.getByRole('button', { name: 'Save Nominee' }).click();

    await expect(page).toHaveURL(new RegExp(`/customers/${cust.id}/$`));
    await expect(page.getByText(newPhone)).toBeVisible();
  });

  test('CUS-HP-07 — clearing nominee name does NOT remove (required field)', async ({
    page,
    request,
  }) => {
    const token = await loginViaApi(request, 'admin');
    const cust = await createCustomerViaApi(request, token);
    await addNomineeViaApi(request, token, cust.id);
    createdCustomers.push(cust.id);

    await page.goto(`/customers/${cust.id}/nominee/`);
    await page.locator('#id_nominee_name').fill('');
    await page.getByRole('button', { name: 'Save Nominee' }).click();

    // The template hints "leave Nominee Name blank to remove", but `nominee_name`
    // is required (customers/models.py:167, no blank=True), so the form re-renders
    // with a required-field error and the nominee is NOT removed.
    await expect(page).toHaveURL(new RegExp(`/customers/${cust.id}/nominee/$`));
    await expect(page.getByText('This field is required')).toBeVisible();
    const detail = await request.get(`/customers/${cust.id}/`);
    expect(await detail.text()).toContain('Sara Khan');
  });

  test('CUS-HP-08 — create portal login (profile-create)', async ({ page, request }) => {
    const token = await loginViaApi(request, 'admin');
    const cust = await createCustomerViaApi(request, token);
    createdCustomers.push(cust.id);
    const username = `qa_portal_${uniq()}`;
    createdUsers.push(username);
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

    // Data via API: the new non-staff login now exists.
    const users = await request.get('/api/users/');
    const found = (await users.json()).find((u: { username: string }) => u.username === username);
    expect(found, 'portal user created').toBeTruthy();
  });

  test('CUS-HP-09 — customer profile PDF downloads with the right filename', async ({
    page,
    request,
  }) => {
    const token = await loginViaApi(request, 'admin');
    const cust = await createCustomerViaApi(request, token);
    await addNomineeViaApi(request, token, cust.id);
    createdCustomers.push(cust.id);

    await page.goto(`/customers/${cust.id}/`);
    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.getByRole('link', { name: /Download Profile PDF/ }).click(),
    ]);
    expect(download.suggestedFilename()).toBe(`customer_profile_${cust.customerId}.pdf`);

    // Data via API: content-type is application/pdf.
    const res = await page.request.get(`/customers/${cust.id}/pdf/`);
    expect(res.status()).toBe(200);
    expect(res.headers()['content-type']).toContain('application/pdf');
  });
});

// ══════════════════════════════════════════════════════════════════════════
// Edge cases (admin)
// ══════════════════════════════════════════════════════════════════════════

test.describe('CUS — browser edge cases (admin)', () => {
  test.beforeEach(async ({ page }) => { await loginViaApi(page.request, 'admin'); });

  test('CUS-EC-01 — duplicate CNIC rejected', async ({ page, request }) => {
    const token = await loginViaApi(request, 'admin');
    const existing = await createCustomerViaApi(request, token);
    createdCustomers.push(existing.id);
    const raw = existing.cnic.replace(/\D/g, ''); // same 13 digits

    await page.goto('/customers/create/');
    await page.getByLabel('First Name').fill('Dup');
    await page.getByLabel('Last Name').fill('CNIC');
    await page.getByLabel('CNIC Number').fill(raw);
    await page.getByLabel('Phone Number').fill(makePhone());
    await page.getByRole('button', { name: 'Create Customer' }).click();

    await expect(page).toHaveURL(/\/customers\/create\/$/);
    await expect(page.getByText(/already exists/i)).toBeVisible();

    const list = await request.get('/api/customers/', { params: { search: existing.cnic } });
    const rows = await list.json();
    expect(rows.filter((r: { cnic: string }) => r.cnic === existing.cnic).length).toBe(1);
  });

  test('CUS-EC-02 — duplicate email rejected', async ({ page, request }) => {
    const token = await loginViaApi(request, 'admin');
    const existing = await createCustomerViaApi(request, token);
    createdCustomers.push(existing.id);
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
  });

  test('CUS-EC-03 — invalid phone format rejected (form strict)', async ({ page }) => {
    await page.goto('/customers/create/');
    await page.getByLabel('First Name').fill('Bad');
    await page.getByLabel('Last Name').fill('Phone');
    await page.getByLabel('CNIC Number').fill(makeCnic().raw);
    await page.getByLabel('Phone Number').fill('-----------'); // 11 dashes
    await page.getByRole('button', { name: 'Create Customer' }).click();

    await expect(page).toHaveURL(/\/customers\/create\/$/);
    await expect(page.getByText(/Phone must be in format/)).toBeVisible();
  });

  test('CUS-EC-04 — empty required fields rejected', async ({ page }) => {
    await page.goto('/customers/create/');
    await page.getByRole('button', { name: 'Create Customer' }).click();

    await expect(page).toHaveURL(/\/customers\/create\/$/);
    await expect(page.getByText('Please correct the errors below.')).toBeVisible();
    await expect(page.getByText('This field is required').first()).toBeVisible();
  });

  test('CUS-EC-05 — whitespace-only first name rejected', async ({ page }) => {
    await page.goto('/customers/create/');
    await page.getByLabel('First Name').fill('   ');
    await page.getByLabel('Last Name').fill('Khan');
    await page.getByLabel('CNIC Number').fill(makeCnic().raw);
    await page.getByLabel('Phone Number').fill(makePhone());
    await page.getByRole('button', { name: 'Create Customer' }).click();

    await expect(page).toHaveURL(/\/customers\/create\/$/);
    await expect(page.getByText('This field is required').first()).toBeVisible();
  });

  test('CUS-EC-06 — CNIC boundary: 12 digits rejected, 14 digits truncated to 13', async ({
    page,
    request,
  }) => {
    const token = await loginViaApi(request, 'admin');

    // Below boundary — 12 digits → rejected.
    await page.goto('/customers/create/');
    await page.getByLabel('First Name').fill('Boundary');
    await page.getByLabel('Last Name').fill('Low');
    await page.getByLabel('CNIC Number').fill('123456789012'); // 12 digits
    await page.getByLabel('Phone Number').fill(makePhone());
    await page.getByRole('button', { name: 'Create Customer' }).click();
    await expect(page).toHaveURL(/\/customers\/create\/$/);
    await expect(page.getByText(/CNIC must be exactly 13 digits/)).toBeVisible();

    // Above boundary — 14 digits are silently sliced to 13 by the client-side
    // JS handler (`this.value.replace(/\D/g,'').slice(0,13)`), so the create
    // succeeds and the 14th digit is dropped.
    const base = makeCnic();
    await page.goto('/customers/create/');
    await page.getByLabel('First Name').fill('Boundary');
    await page.getByLabel('Last Name').fill('High');
    await page.getByLabel('CNIC Number').fill(base.raw + '9'); // 14 digits
    await page.getByLabel('Phone Number').fill(makePhone());
    await page.getByRole('button', { name: 'Create Customer' }).click();
    await expect(page).toHaveURL(/\/customers\/$/);

    const list = await request.get('/api/customers/', { params: { search: base.dashed } });
    const row = (await list.json()).find((r: { cnic: string }) => r.cnic === base.dashed);
    expect(row, '14-digit cnic truncated to the first 13 digits').toBeTruthy();
    createdCustomers.push(row.id);
  });
});

// ══════════════════════════════════════════════════════════════════════════
// List & filters (admin) — status badge + client-side collapse (no server pagination)
// ══════════════════════════════════════════════════════════════════════════

test.describe('CUS — browser list & filters (admin)', () => {
  test.beforeEach(async ({ page }) => { await loginViaApi(page.request, 'admin'); });

  test('CUS-list-01 — list renders search, stats and table headers', async ({ page }) => {
    await page.goto('/customers/');
    await expect(page.getByRole('heading', { name: 'Customers', exact: true })).toBeVisible();
    await expect(page.getByPlaceholder('Search by ID, name, phone, or CNIC...')).toBeVisible();
    for (const h of ['Customer ID', 'Name', 'Phone', 'Occupation', 'City', 'Status', 'Created', 'Actions']) {
      await expect(page.getByRole('columnheader', { name: h })).toBeVisible();
    }
    await expect(page.getByText('Total Customers')).toBeVisible();
    await expect(page.getByText('Active Customers')).toBeVisible();
    await expect(page.getByText('With Bookings')).toBeVisible();
  });

  test('CUS-list-02 — status badge shows Active then Inactive after edit', async ({
    page,
    request,
  }) => {
    const token = await loginViaApi(request, 'admin');
    const cust = await createCustomerViaApi(request, token);
    createdCustomers.push(cust.id);

    await page.goto(`/customers/?search=${cust.cnic.slice(0, 8)}`);
    const row = page.getByRole('row', { name: new RegExp(cust.customerId) });
    await expect(row.getByText('Active', { exact: true })).toBeVisible();

    // Deactivate via the edit form (uncheck "Active Customer").
    await page.goto(`/customers/${cust.id}/edit/`);
    await page.getByLabel('Active Customer').uncheck();
    await page.getByRole('button', { name: 'Update Customer' }).click();
    await expect(page).toHaveURL(/\/customers\/$/);

    await page.goto(`/customers/?search=${cust.cnic.slice(0, 8)}`);
    await expect(row.getByText('Inactive', { exact: true })).toBeVisible();
  });

  test('CUS-list-03 — single unpaginated table with client-side View More collapse', async ({
    page,
  }) => {
    await page.goto('/customers/');
    await expect(page.getByRole('columnheader', { name: 'Customer ID' })).toBeVisible();

    // No server-side pagination: the full list renders in one table. With >5 rows
    // the client-side "View More / View Less" collapse toggle appears (erp.js).
    await expect(page.getByRole('button', { name: 'View More' })).toBeVisible();
    await page.getByRole('button', { name: 'View More' }).click();
    await expect(page.getByRole('button', { name: 'View Less' })).toBeVisible();
  });
});

// ══════════════════════════════════════════════════════════════════════════
// Delete flow (admin)
// ══════════════════════════════════════════════════════════════════════════

test.describe('CUS — browser delete flow (admin)', () => {
  test.beforeEach(async ({ page }) => { await loginViaApi(page.request, 'admin'); });

  test('CUS-DEL-01 — delete blocked when bookings exist', async ({ page, request }) => {
    const token = await loginViaApi(request, 'admin');
    const cust = await createCustomerViaApi(request, token);
    await createBookingViaApi(request, token, cust.id);
    createdCustomers.push(cust.id);

    await page.goto(`/customers/${cust.id}/delete/`);
    await expect(page).toHaveURL(new RegExp(`/customers/${cust.id}/$`));
    await expect(
      page.getByText(/Cannot delete a customer with bookings or ledger history/),
    ).toBeVisible();

    const get = await request.get(`/api/customers/${cust.id}/`);
    expect(get.status()).toBe(200); // customer intact
  });

  test('CUS-DEL-02 — delete a clean customer via the UI', async ({ page, request }) => {
    const token = await loginViaApi(request, 'admin');
    const cust = await createCustomerViaApi(request, token);
    // Not pushed to createdCustomers — the delete is the point of this test.

    await page.goto(`/customers/${cust.id}/`);
    await page.getByRole('link', { name: /Delete Customer/ }).click();
    await expect(page).toHaveURL(new RegExp(`/customers/${cust.id}/delete/$`));
    await page.getByRole('button', { name: /Yes, Delete/ }).click();

    await expect(page).toHaveURL(/\/customers\/$/);
    await expect(page.getByText(/deleted successfully/i).first()).toBeVisible();

    const get = await request.get(`/api/customers/${cust.id}/`);
    expect(get.status()).toBe(404); // hard-deleted
  });
});

// ══════════════════════════════════════════════════════════════════════════
// Security (RED — CONFIRMED BUG: docs/qa/findings-confirmed.md F3)
// ══════════════════════════════════════════════════════════════════════════

test.describe('CUS — browser security (IDOR, sales)', () => {
  test.beforeEach(async ({ page }) => { await loginViaApi(page.request, 'sales'); });

  test('CUS-SEC-01 — sales user reads any customer detail', async ({ page, request }) => {
    // CONFIRMED BUG: docs/qa/findings-confirmed.md F3
    const token = await loginViaApi(request, 'admin');
    const victim = await createCustomerViaApi(request, token);
    createdCustomers.push(victim.id);

    await page.goto(`/customers/${victim.id}/`);
    // Correct behaviour: a sales user who did not create this customer is redirected away.
    await expect(page).toHaveURL(/\/dashboard\//);
  });

  test('CUS-SEC-02 — sales user edits any customer', async ({ page, request }) => {
    // CONFIRMED BUG: docs/qa/findings-confirmed.md F3
    const token = await loginViaApi(request, 'admin');
    const victim = await createCustomerViaApi(request, token);
    createdCustomers.push(victim.id);
    const originalPhone = victim.phone;
    const tampered = makePhone();

    await page.goto(`/customers/${victim.id}/edit/`);
    await page.getByLabel('Phone Number').fill(tampered);
    await page.getByRole('button', { name: 'Update Customer' }).click();

    // Correct behaviour: the edit is denied and the victim's phone is unchanged.
    const res = await request.get(`/api/customers/${victim.id}/`);
    expect((await res.json()).phone).toBe(originalPhone);
  });
});

test.describe('CUS — browser security (IDOR, portal customer)', () => {
  test.beforeEach(async ({ page }) => { await loginViaApi(page.request, 'customer'); });

  test('CUS-SEC-03 — portal customer reads any customer detail', async ({ page, request }) => {
    // CONFIRMED BUG: docs/qa/findings-confirmed.md F3
    const token = await loginViaApi(request, 'admin');
    const victim = await createCustomerViaApi(request, token);
    createdCustomers.push(victim.id);

    // Land on the portal first (confirms we are the non-staff customer).
    await page.goto('/portal/');
    await expect(page).toHaveURL(/\/portal\/$/);

    await page.goto(`/customers/${victim.id}/`);
    // Correct behaviour: a non-staff portal customer is redirected away from the ERP.
    await expect(page).toHaveURL(/\/portal\//);
  });

  test('CUS-SEC-04 — portal customer downloads any customer PDF', async ({ page, request }) => {
    // CONFIRMED BUG: docs/qa/findings-confirmed.md F3
    const token = await loginViaApi(request, 'admin');
    const victim = await createCustomerViaApi(request, token);
    createdCustomers.push(victim.id);

    const res = await page.request.get(`/customers/${victim.id}/pdf/`);
    // Correct behaviour: denied for a non-staff portal customer (not a 200 PDF).
    expect(res.status()).not.toBe(200);
    expect(res.headers()['content-type']).not.toContain('application/pdf');
  });
});

// ══════════════════════════════════════════════════════════════════════════
// Cleanup — afterAll deletes every customer/user this worker created.
// ══════════════════════════════════════════════════════════════════════════

test.afterAll(async ({ playwright }) => {
  const request = await playwright.request.newContext({ baseURL: 'http://127.0.0.1:8000' });
  try {
    const token = await loginViaApi(request, 'admin');
    for (const username of createdUsers) {
      try {
        const users = await request.get('/api/users/');
        const list = await users.json();
        const u = list.find((x: { username: string }) => x.username === username);
        if (u) await request.delete(`/api/users/${u.id}/`, { headers: { 'X-CSRFToken': token } });
      } catch {
        /* best-effort */
      }
    }
    for (const id of createdCustomers) {
      await deleteCustomerViaApi(request, token, id);
    }
  } catch {
    /* best-effort */
  }
  await request.dispose();
});
