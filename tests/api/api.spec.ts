import { test, expect } from '@playwright/test';
import { loginViaApi, ROLES } from '../helpers/auth';

/**
 * API module — DRF auth + portal + permission matrix.
 * Spec: specs/api.md. Findings: docs/qa/findings-confirmed.md.
 *
 * Data-plane module: uses `request` + `loginViaApi` throughout (no `page`).
 *
 * These tests mutate shared server state (role escalation on qa_sales, login-attempt
 * counters, admin-created users). Run with --workers=1 so they execute one at a time
 * (the escalation tests restore their state in a finally block).
 */

const USER_PAYLOAD_KEYS = [
  'id', 'username', 'email', 'full_name',
  'is_staff', 'is_superuser', 'is_customer', 'role',
];

const csrf = (token: string) => ({ 'X-CSRFToken': token });

/** GET /api/auth/me/ and return the JSON body. */
async function meJson(request: Parameters<typeof loginViaApi>[0]) {
  const res = await request.get('/api/auth/me/');
  return { status: res.status(), body: await res.json() };
}

test.describe('HP', () => {
  test('API-HP-01 — CSRF → login → session handshake', async ({ request }) => {
    // 1. CSRF cookie
    const csrfRes = await request.get('/api/auth/csrf/');
    expect(csrfRes.status()).toBe(200);
    expect(await csrfRes.json()).toEqual({ detail: 'CSRF cookie set' });

    const afterCsrf = await request.storageState();
    const csrfCookie = afterCsrf.cookies.find((c) => c.name === 'csrftoken');
    expect(csrfCookie).toBeTruthy();

    // 2. Login
    const loginRes = await request.post('/api/auth/login/', {
      data: { username: ROLES.admin.username, password: ROLES.admin.password },
      headers: csrfCookie ? csrf(csrfCookie.value) : {},
    });
    expect(loginRes.status()).toBe(200);
    const body = await loginRes.json();
    for (const key of USER_PAYLOAD_KEYS) expect(body).toHaveProperty(key);
    expect(body.username).toBe('admin');
    // `admin` is a role-based super_admin, not a Django superuser (is_superuser=False).
    expect(body.role).toBe('super_admin');
    expect(body.is_customer).toBe(false);

    // 3. sessionid cookie present
    const afterLogin = await request.storageState();
    expect(afterLogin.cookies.find((c) => c.name === 'sessionid')).toBeTruthy();
  });

  test('API-HP-02 — current_user/me returns the role', async ({ request }) => {
    const token = await loginViaApi(request, 'admin');

    const { status, body } = await meJson(request);
    expect(status).toBe(200);
    for (const key of USER_PAYLOAD_KEYS) expect(body).toHaveProperty(key);
    expect(body.username).toBe('admin');
    // `admin` is a role-based super_admin (is_superuser=False on the Django User).
    expect(body.role).toBe('super_admin');
    expect(token).toBeTruthy();
  });

  test('API-HP-03 — portal_dashboard scoped to request.user', async ({ request }) => {
    await loginViaApi(request, 'customer');
    const res = await request.get('/api/portal/');
    expect(res.status()).toBe(200);
    const body = await res.json();

    for (const key of ['customer', 'summary', 'bookings', 'payments', 'installments']) {
      expect(body).toHaveProperty(key);
    }
    expect(typeof body.customer.customer_id).toBe('string');
    expect(Array.isArray(body.bookings)).toBe(true);
    expect(Array.isArray(body.payments)).toBe(true);
    expect(Array.isArray(body.installments)).toBe(true);

    // Scoping: every payment must reference one of THIS customer's bookings.
    const bookingIds = new Set(body.bookings.map((b: { booking_id: string }) => b.booking_id));
    for (const p of body.payments) {
      expect(bookingIds.has(p.booking_id)).toBe(true);
    }
    // summary.total_paid must equal the sum of this customer's (scoped) payments.
    const paySum = body.payments.reduce(
      (acc: number, p: { amount: number }) => acc + (p.amount ?? 0),
      0,
    );
    expect(Math.abs(paySum - body.summary.total_paid)).toBeLessThan(0.01);
  });

  test('API-HP-04 — api_logout ends the session', async ({ request }) => {
    const token = await loginViaApi(request, 'admin');
    const logoutRes = await request.post('/api/auth/logout/', { headers: csrf(token) });
    expect(logoutRes.status()).toBe(200);
    expect(await logoutRes.json()).toEqual({ detail: 'Logged out.' });

    const meRes = await request.get('/api/auth/me/');
    expect([401, 403]).toContain(meRes.status());
  });

  test('API-HP-05 — public plots/list (anonymous)', async ({ request }) => {
    // No login — `request` starts fresh/unauthenticated in this spec.
    const res = await request.get('/api/plots/list/');
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(Array.isArray(body)).toBe(true);
    expect(body.length).toBeLessThanOrEqual(20);
    for (const plot of body) {
      expect(plot.status).toBe('available');
    }
  });
});

test.describe('EC', () => {
  test('API-EC-01 — summary.next_due is a full installment dict, not a date', async ({ request }) => {
    await loginViaApi(request, 'customer');
    const body = await (await request.get('/api/portal/')).json();
    const nextDue = body.summary.next_due;
    // Null is allowed (no pending/overdue installment for the seeded customer);
    // when present it must be a full installment object, never a date string.
    expect(typeof nextDue !== 'string').toBe(true);
    if (nextDue !== null) {
      for (const key of [
        'id', 'booking_id', 'installment_number', 'due_date',
        'amount', 'late_fee', 'paid_amount', 'remaining_amount', 'status',
      ]) {
        expect(nextDue).toHaveProperty(key);
      }
    }
  });

  test('API-EC-02 — portal does not crash on null total_amount', async ({ request }) => {
    // Spec api.md API-EC-02 documents a 500 crash when a booking has total_amount=None
    // (sum(None) at api/views.py:142). That booking cannot be created through the API
    // (serializer validates total_amount), so the seeded customer has no null-amount
    // booking and the portal must return 200. Assert the non-crashing contract.
    await loginViaApi(request, 'customer');
    const res = await request.get('/api/portal/');
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body.summary).toHaveProperty('total_amount');
  });

  test('API-EC-03 — no pagination (full tables returned)', async ({ request }) => {
    await loginViaApi(request, 'admin');
    const res = await request.get('/api/payments/');
    expect(res.status()).toBe(200);
    const body = await res.json();
    // Bare JSON array, no {count,next,previous} envelope.
    expect(Array.isArray(body)).toBe(true);
    expect(typeof body.length).toBe('number');
  });

  test('API-EC-04 — float() coercion of Decimal money in portal', async ({ request }) => {
    await loginViaApi(request, 'customer');
    const body = await (await request.get('/api/portal/')).json();
    const s = body.summary;
    expect(typeof s.total_amount).toBe('number');
    expect(typeof s.total_paid).toBe('number');
    expect(typeof s.remaining_balance).toBe('number');
    if (Array.isArray(body.bookings) && body.bookings.length > 0) {
      expect(typeof body.bookings[0].total_amount).toBe('number');
    }
  });

  test('API-EC-05 — portal_dashboard for an account with no linked Customer → 403', async ({ request }) => {
    // qa_sales is staff with no Customer.user link.
    await loginViaApi(request, 'sales');
    const res = await request.get('/api/portal/');
    expect(res.status()).toBe(403);
    expect(await res.json()).toEqual({ detail: 'No customer profile linked to this account.' });
  });

  test('API-EC-06 — malformed JSON / wrong method', async ({ request }) => {
    // 1. Unsupported media type (text/plain not accepted by DRF parsers).
    const badType = await request.post('/api/auth/login/', {
      data: 'username=admin',
      headers: { 'Content-Type': 'text/plain' },
    });
    expect(badType.status()).toBe(415);

    // 2. DELETE not routed on company-settings.
    const adminToken = await loginViaApi(request, 'admin');
    const delSettings = await request.delete('/api/company-settings/', { headers: csrf(adminToken) });
    expect(delSettings.status()).toBe(405);

    // 3. plots/list is GET-only (POST must not be writable).
    const postPlots = await request.post('/api/plots/list/');
    expect([403, 405]).toContain(postPlots.status());

    // 4. portal_dashboard is GET-only.
    const custToken = await loginViaApi(request, 'customer');
    const postPortal = await request.post('/api/portal/', { headers: csrf(custToken) });
    expect(postPortal.status()).toBe(405);
  });
});

test.describe('SEC', () => {
  test('API-SEC-01 — CRITICAL: update_profile privilege escalation', async ({ request }) => {
    const token = await loginViaApi(request, 'sales');
    try {
      // Reset to a known baseline (a prior RED run may have left the role elevated).
      await request.patch('/api/profile/update_profile/', {
        data: { role: 'sales' }, headers: csrf(token),
      });
      await request.patch('/api/profile/update_profile/', {
        data: { role: 'super_admin' }, headers: csrf(token),
      });
      const { body } = await meJson(request);
      // CONFIRMED BUG: docs/qa/findings-confirmed.md F1 — role must stay 'sales'.
      expect(body.role).toBe('sales');
    } finally {
      await request.patch('/api/profile/update_profile/', {
        data: { role: 'sales' }, headers: csrf(token),
      });
    }
  });

  test('API-SEC-02 — CRITICAL: escalation by a low-privilege staff user (generalizes)', async ({ request }) => {
    const token = await loginViaApi(request, 'sales');
    try {
      await request.patch('/api/profile/update_profile/', {
        data: { role: 'sales', is_active: true }, headers: csrf(token),
      });
      // Role elevation to a different target.
      await request.patch('/api/profile/update_profile/', {
        data: { role: 'admin' }, headers: csrf(token),
      });
      const { body } = await meJson(request);
      // CONFIRMED BUG: docs/qa/findings-confirmed.md F1.
      await expect.soft(body.role, 'role must stay sales').toBe('sales');

      // is_active must be read-only (no self-lockout).
      await request.patch('/api/profile/update_profile/', {
        data: { is_active: false }, headers: csrf(token),
      });
      const profile = await (await request.get('/api/profile/')).json();
      // CONFIRMED BUG: docs/qa/findings-confirmed.md F1 (is_active writable).
      await expect.soft(profile.is_active, 'is_active must stay true').toBe(true);
    } finally {
      await request.patch('/api/profile/update_profile/', {
        data: { role: 'sales', is_active: true }, headers: csrf(token),
      });
    }
  });

  test('API-SEC-03 — customer reads /api/users/ (staff PII)', async ({ request }) => {
    await loginViaApi(request, 'customer');
    const res = await request.get('/api/users/');
    // CONFIRMED BUG: docs/qa/findings-confirmed.md F3 (read-open).
    expect(res.status()).toBe(403);
  });

  test('API-SEC-04 — customer reads /api/customers/ (CNIC/phone/address)', async ({ request }) => {
    await loginViaApi(request, 'customer');
    const res = await request.get('/api/customers/');
    // CONFIRMED BUG: docs/qa/findings-confirmed.md F3.
    expect(res.status()).toBe(403);
  });

  test('API-SEC-05 — customer reads /api/bookings/ (all bookings/amounts)', async ({ request }) => {
    await loginViaApi(request, 'customer');
    const res = await request.get('/api/bookings/');
    // CONFIRMED BUG: docs/qa/findings-confirmed.md F3.
    expect(res.status()).toBe(403);
  });

  test('API-SEC-06 — customer reads /api/payments/ (all payments)', async ({ request }) => {
    await loginViaApi(request, 'customer');
    const res = await request.get('/api/payments/');
    // CONFIRMED BUG: docs/qa/findings-confirmed.md F3.
    expect(res.status()).toBe(403);
  });

  test('API-SEC-07 — customer reads /api/employees/ (HR PII)', async ({ request }) => {
    await loginViaApi(request, 'customer');
    const res = await request.get('/api/employees/');
    // CONFIRMED BUG: docs/qa/findings-confirmed.md F3.
    expect(res.status()).toBe(403);
  });

  test('API-SEC-08 — customer reads /api/audit-logs/ (IP addresses)', async ({ request }) => {
    await loginViaApi(request, 'customer');
    const res = await request.get('/api/audit-logs/');
    // CONFIRMED BUG: docs/qa/findings-confirmed.md F3.
    expect(res.status()).toBe(403);
  });

  test('API-SEC-09 — login CSRF (unauthenticated POST unprotected)', async ({ request }) => {
    // Security note (spec api.md API-SEC-09): the DRF api_login view is csrf-exempt
    // for unauthenticated POSTs, so login succeeds with no X-CSRFToken. Documented as
    // a known login-CSRF / forced-login gap (session key is rotated on login, which
    // mitigates fixation). Soft assertion: the endpoint exists and logs in.
    const res = await request.post('/api/auth/login/', {
      data: { username: ROLES.admin.username, password: ROLES.admin.password },
    });
    expect(res.status()).toBe(200);
    expect(await res.json()).toHaveProperty('username');
  });

  test('API-SEC-10 — user enumeration (403 deactivated vs 400 invalid)', async ({ request }) => {
    const adminToken = await loginViaApi(request, 'admin');
    const uname = `qa_enum_${Date.now()}`;
    let userId: number | null = null;
    try {
      const create = await request.post('/api/users/', {
        data: {
          username: uname, email: `${uname}@test.local`, password: 'admin123',
          first_name: 'Enum', last_name: 'User', role: 'sales',
        },
        headers: csrf(adminToken),
      });
      expect(create.status()).toBe(201);
      userId = (await create.json()).id;

      // Deactivate via toggle_active.
      const toggle = await request.post(`/api/users/${userId}/toggle_active/`, {
        headers: csrf(adminToken),
      });
      expect(toggle.status()).toBe(200);

      // Deactivated account + wrong password -> intended identical 400.
      const deactivated = await request.post('/api/auth/login/', {
        data: { username: uname, password: 'wrong-password' },
      });
      // CONFIRMED BUG (spec api.md API-SEC-10): distinct 403 leaks existence.
      await expect.soft(deactivated.status(), 'deactivated account must return 400').toBe(400);

      const noSuch = await request.post('/api/auth/login/', {
        data: { username: `qa_nosuch_${Date.now()}`, password: 'wrong-password' },
      });
      expect(noSuch.status()).toBe(400);
    } finally {
      if (userId !== null) {
        await request.delete(`/api/users/${userId}/`, { headers: csrf(adminToken) });
      }
    }
  });

  test('API-SEC-11 — brute-force throttle (5 failures / 15 min lockout)', async ({ request }) => {
    // Uses a throwaway username so the shared role accounts are never locked out.
    // Note (spec api.md API-SEC-11): the IP threshold is 15 (3x the username limit) and
    // keyed on REMOTE_ADDR, so rotating source IPs evades it; success does not reset the
    // failed counter. These failures also count toward the shared 127.0.0.1 IP counter,
    // so re-running the suite within the 15-minute window can trip the IP lockout.
    const target = `qa_bf_${Date.now()}`;
    for (let i = 0; i < 5; i++) {
      const r = await request.post('/api/auth/login/', {
        data: { username: target, password: 'wrong-password' },
      });
      expect(r.status()).toBe(400);
    }
    const sixth = await request.post('/api/auth/login/', {
      data: { username: target, password: 'wrong-password' },
    });
    expect(sixth.status()).toBe(429);
    expect(await sixth.json()).toEqual({
      detail: 'Too many failed attempts. Try again after 15 minutes.',
    });
  });

  test('API-SEC-12 — customer reads /api/company-settings/summary/ (revenue/profit)', async ({ request }) => {
    await loginViaApi(request, 'customer');
    const res = await request.get('/api/company-settings/summary/');
    // CONFIRMED BUG: docs/qa/findings-confirmed.md F3.
    expect(res.status()).toBe(403);
  });

  test('API-SEC-13 — receipts write-open: customer must not POST /api/receipts/', async ({ request }) => {
    await loginViaApi(request, 'customer');
    const res = await request.post('/api/receipts/', { data: {} });
    // CONFIRMED BUG (spec api.md API-SEC-13): intended 403 for a customer. Current
    // code (payments/api_views.py ReceiptViewSet) is ReadOnlyModelViewSet, so POST is
    // not routed and returns 405 — still a denied write, so accept 403 or 405.
    expect([403, 405]).toContain(res.status());
  });

  test('API-SEC-14 — IDOR: write-role user confirms another customer booking', async ({ request }) => {
    await loginViaApi(request, 'admin');
    const bookings = await (await request.get('/api/bookings/')).json();
    expect(Array.isArray(bookings)).toBe(true);
    expect(bookings.length).toBeGreaterThan(0);
    const pk = bookings[0].id;

    const salesToken = await loginViaApi(request, 'sales');
    const res = await request.post(`/api/bookings/${pk}/confirm/`, { headers: csrf(salesToken) });
    // CONFIRMED BUG (spec api.md API-SEC-14): confirm has no ownership check — any
    // write role can transition another customer's booking (intended 403).
    expect(res.status()).toBe(403);
  });
});

test.describe('API', () => {
  test('API-API-01 — users: SAFE open, write admin-only', async ({ request }) => {
    const salesToken = await loginViaApi(request, 'sales');
    expect((await request.post('/api/users/', { data: {}, headers: csrf(salesToken) })).status()).toBe(403);
    expect((await request.patch('/api/users/999999/', { data: {}, headers: csrf(salesToken) })).status()).toBe(403);
    expect((await request.delete('/api/users/999999/', { headers: csrf(salesToken) })).status()).toBe(403);

    await loginViaApi(request, 'customer');
    const read = await request.get('/api/users/');
    // CONFIRMED BUG: docs/qa/findings-confirmed.md F3 (SAFE open to a customer).
    await expect.soft(read.status(), 'customer GET /api/users/ must be 403').toBe(403);
  });

  test('API-API-02 — customers: SAFE open, write admin-only', async ({ request }) => {
    const salesToken = await loginViaApi(request, 'sales');
    expect((await request.post('/api/customers/', { data: {}, headers: csrf(salesToken) })).status()).toBe(403);
    expect((await request.patch('/api/customers/999999/', { data: {}, headers: csrf(salesToken) })).status()).toBe(403);
    expect((await request.delete('/api/customers/999999/', { headers: csrf(salesToken) })).status()).toBe(403);

    await loginViaApi(request, 'customer');
    const read = await request.get('/api/customers/');
    // CONFIRMED BUG: docs/qa/findings-confirmed.md F3.
    await expect.soft(read.status(), 'customer GET /api/customers/ must be 403').toBe(403);
  });

  test('API-API-03 — bookings: sales write, customer denied; DELETE management+', async ({ request }) => {
    const customerToken = await loginViaApi(request, 'customer');
    expect((await request.post('/api/bookings/', { data: {}, headers: csrf(customerToken) })).status()).toBe(403);

    const salesToken = await loginViaApi(request, 'sales');
    expect([403, 404]).toContain((await request.delete('/api/bookings/999999/', { headers: csrf(salesToken) })).status());

    await loginViaApi(request, 'customer');
    const read = await request.get('/api/bookings/');
    // CONFIRMED BUG: docs/qa/findings-confirmed.md F3.
    await expect.soft(read.status(), 'customer GET /api/bookings/ must be 403').toBe(403);
  });

  test('API-API-04 — payments: accounts write, sales/customer denied; DELETE management+', async ({ request }) => {
    const salesToken = await loginViaApi(request, 'sales');
    expect((await request.post('/api/payments/', { data: {}, headers: csrf(salesToken) })).status()).toBe(403);

    const accountsToken = await loginViaApi(request, 'accounts');
    expect([403, 404]).toContain((await request.delete('/api/payments/999999/', { headers: csrf(accountsToken) })).status());

    const customerToken = await loginViaApi(request, 'customer');
    expect((await request.post('/api/payments/', { data: {}, headers: csrf(customerToken) })).status()).toBe(403);
    const read = await request.get('/api/payments/');
    // CONFIRMED BUG: docs/qa/findings-confirmed.md F3.
    await expect.soft(read.status(), 'customer GET /api/payments/ must be 403').toBe(403);
  });

  test('API-API-05 — employees/leaves (HR): hr writes, others denied', async ({ request }) => {
    const salesToken = await loginViaApi(request, 'sales');
    expect((await request.post('/api/employees/', { data: {}, headers: csrf(salesToken) })).status()).toBe(403);

    const accountsToken = await loginViaApi(request, 'accounts');
    expect((await request.post('/api/leaves/', { data: {}, headers: csrf(accountsToken) })).status()).toBe(403);

    await loginViaApi(request, 'customer');
    const read = await request.get('/api/employees/');
    // CONFIRMED BUG: docs/qa/findings-confirmed.md F3.
    await expect.soft(read.status(), 'customer GET /api/employees/ must be 403').toBe(403);
  });

  test('API-API-06 — refunds: accounts write, customer denied', async ({ request }) => {
    const salesToken = await loginViaApi(request, 'sales');
    expect((await request.post('/api/refunds/', { data: {}, headers: csrf(salesToken) })).status()).toBe(403);

    const customerToken = await loginViaApi(request, 'customer');
    expect((await request.post('/api/refunds/', { data: {}, headers: csrf(customerToken) })).status()).toBe(403);
    const read = await request.get('/api/refunds/');
    // CONFIRMED BUG: docs/qa/findings-confirmed.md F3.
    await expect.soft(read.status(), 'customer GET /api/refunds/ must be 403').toBe(403);
  });

  test('API-API-07 — offices (finance): accounts write, customer denied', async ({ request }) => {
    const salesToken = await loginViaApi(request, 'sales');
    expect((await request.post('/api/offices/', { data: {}, headers: csrf(salesToken) })).status()).toBe(403);

    const customerToken = await loginViaApi(request, 'customer');
    expect((await request.post('/api/offices/', { data: {}, headers: csrf(customerToken) })).status()).toBe(403);
    const read = await request.get('/api/offices/');
    // CONFIRMED BUG: docs/qa/findings-confirmed.md F3.
    await expect.soft(read.status(), 'customer GET /api/offices/ must be 403').toBe(403);
  });

  test('API-API-08 — receipts anomaly: any authenticated user can write', async ({ request }) => {
    // Spec api.md API-API-08 expected a writable ReceiptViewSet (IsAuthenticated).
    // Current code is ReadOnlyModelViewSet, so POST is not routed (405) — the write
    // is already denied. Assert denied-write (403 or 405) for both actors.
    const salesToken = await loginViaApi(request, 'sales');
    const salesPost = await request.post('/api/receipts/', { data: {}, headers: csrf(salesToken) });
    expect([403, 405]).toContain(salesPost.status());

    await loginViaApi(request, 'customer');
    const customerPost = await request.post('/api/receipts/', { data: {} });
    expect([403, 405]).toContain(customerPost.status());
  });

  test('API-API-09 — audit-logs: any authenticated user reads (intended management-only)', async ({ request }) => {
    await loginViaApi(request, 'customer');
    const customerRead = await request.get('/api/audit-logs/');
    // CONFIRMED BUG: docs/qa/findings-confirmed.md F3.
    await expect.soft(customerRead.status(), 'customer GET /api/audit-logs/ must be 403').toBe(403);

    await loginViaApi(request, 'sales');
    const salesRead = await request.get('/api/audit-logs/');
    // CONFIRMED BUG: docs/qa/findings-confirmed.md F3 (intended management-only).
    await expect.soft(salesRead.status(), 'sales GET /api/audit-logs/ must be 403').toBe(403);
  });

  test('API-API-10 — profile: PATCH role writable (actual vs intended read-only)', async ({ request }) => {
    const token = await loginViaApi(request, 'sales');
    try {
      await request.patch('/api/profile/update_profile/', {
        data: { role: 'sales' }, headers: csrf(token),
      });
      await request.patch('/api/profile/update_profile/', {
        data: { role: 'admin' }, headers: csrf(token),
      });
      const { body } = await meJson(request);
      // CONFIRMED BUG: docs/qa/findings-confirmed.md F1 — role must stay 'sales'.
      expect(body.role).toBe('sales');
    } finally {
      await request.patch('/api/profile/update_profile/', {
        data: { role: 'sales', is_active: true }, headers: csrf(token),
      });
    }
  });
});
