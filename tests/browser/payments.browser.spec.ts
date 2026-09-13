import { test, expect, APIRequestContext, Page } from '@playwright/test';
import { loginViaApi, ROLES } from '../helpers/auth';

type Role = keyof typeof ROLES;

// ================================================================================
// Samana ERP — Payments (browser-driven, cross-table money verification)
//
// This is the BROWSER suite for the payments module: the UI flows are driven with a
// real `page` (admin session) while every money effect is verified CROSS-TABLE via
// `loginViaApi` + API GETs against exact Decimal strings (DRF returns "300000.00").
//
// Key facts discovered while writing this suite (asserted honestly):
//  - The web payment form (payment_form.html) exposes booking (hidden when pre-filled),
//    payment_date, amount, payment_type, payment_method, notes and method_data. It does
//    NOT render an `installment` selector — so a UI-recorded payment never targets an
//    installment. Installment linkage is exercised through the VERIFY flow instead:
//    create a pending payment WITH installment via API, then click "Verify" in the UI.
//  - `CustomerLedgerEntry` is NOT auto-created by any payment path (record/verify) — only
//    seed/management commands and the /api/customer-ledger/ endpoint create rows. The
//    real cross-table money signal on the customer is `current_balance`
//    (= sum(bookings.total_amount) − sum(verified payments)), which IS recomputed live.
//  - `page` runs as admin (superuser → full payments access, `can_manage_users=True`).
//  - `request` starts unauthenticated; call login()/loginViaApi explicitly for API work.
// ================================================================================

// Run independently under --workers=1 (no serial mode): the confirmed-bug SEC tests
// must be allowed to fail (RED) without skipping the tests that follow them.
// Browser context is authenticated as admin for every UI flow in this file.
test.beforeEach(async ({ page }) => { await loginViaApi(page.request, 'admin'); });

// ─── Helpers ────────────────────────────────────────────────────────────────────
let uidCounter = 0;
function uniq(): string {
  uidCounter += 1;
  const rnd = Math.floor(Math.random() * 1e6).toString().padStart(6, '0');
  return `${Date.now().toString().slice(-8)}${rnd}${uidCounter}`;
}

async function readCsrf(request: APIRequestContext): Promise<string> {
  try {
    const state = await request.storageState();
    const c = state.cookies.find((c) => c.name === 'csrftoken');
    return c ? c.value : '';
  } catch {
    return '';
  }
}

// The browser page's storageState (admin.json) is shared with other concurrently-run
// suites; a concurrent setup run can rotate that session and log our UI out mid-test.
// Track the current test's page so `login()` can re-sync a fresh session after the API
// login (which always produces a valid admin session regardless of admin.json's state).
let currentPage: Page | null = null;
test.beforeEach(async ({ page }) => {
  currentPage = page;
});
test.afterEach(() => {
  currentPage = null;
});

async function login(request: APIRequestContext, role: Role): Promise<string> {
  await loginViaApi(request, role);
  if (currentPage) {
    // Re-establish the UI session from the fresh API login so UI actions don't
    // depend on the (possibly invalidated) shared admin.json session.
    const state = await request.storageState();
    await currentPage.context().addCookies(state.cookies);
  }
  return readCsrf(request);
}

async function mustPost(request: APIRequestContext, token: string, url: string, data: any): Promise<any> {
  const res = await request.post(url, { data, headers: { 'X-CSRFToken': token } });
  if (res.status() >= 400) throw new Error(`${url} -> ${res.status()}: ${await res.text()}`);
  return res.json();
}

// ─── Fixture tracking (afterAll cleanup) ────────────────────────────────────────
const createdCustomers: number[] = [];
const createdProjects: number[] = [];
const createdPlots: number[] = [];
const createdBookings: number[] = [];

interface Fixture {
  customerId: number;
  projectId: number;
  plotId: number;
  bookingId: number;
  planId: number;
  installmentId?: number;
  bookingApiId: string;
}

async function createCustomer(request: APIRequestContext, token: string, tag: string): Promise<number> {
  // Fully random 13-digit CNIC (format XXXXX-XXXXXXX-X) — avoids collisions with
  // leftover QA customers from prior runs that the afterAll cleanup cannot delete.
  const d = Math.floor(Math.random() * 1e13).toString().padStart(13, '0');
  const cnic = `${d.slice(0, 5)}-${d.slice(5, 12)}-${d.slice(12)}`;
  const res = await request.post('/api/customers/', {
    data: {
      first_name: 'QA', last_name: `BR ${tag}`,
      email: `qa.br.${tag}@example.com`,
      phone: `+92${tag.slice(0, 10)}`,
      cnic, address: 'QA Address', city: 'Lahore',
    },
    headers: { 'X-CSRFToken': token },
  });
  if (res.status() !== 201) throw new Error(`createCustomer -> ${res.status()}: ${await res.text()}`);
  const found = await (await request.get(`/api/customers/?search=${encodeURIComponent(cnic)}`)).json();
  const list = Array.isArray(found) ? found : (found.results ?? []);
  const id = list.find((c: any) => c.cnic === cnic)?.id;
  if (!id) throw new Error('created customer not found by cnic');
  createdCustomers.push(id);
  return id;
}

/** project → plot → customer → booking → installment plan (+1 auto-generated installment). */
async function seedFixture(
  request: APIRequestContext, token: string, opts: { totalAmount?: number } = {},
): Promise<Fixture> {
  const totalAmount = opts.totalAmount ?? 1000000;
  const tag = uniq();
  const customerId = await createCustomer(request, token, tag);
  const project = await mustPost(request, token, '/api/projects/', { name: `QA-BR-${tag}`, location: 'Lahore', status: 'booking_open' });
  createdProjects.push(project.id);
  const plot = await mustPost(request, token, '/api/plots/', { plot_number: `B-${tag}`, project: project.id, size_marla: 5, price: totalAmount });
  createdPlots.push(plot.id);
  // advance_paid: 0 → BookingViewSet.perform_create records no upfront verified Payment.
  await mustPost(request, token, '/api/bookings/', { customer: customerId, plot: plot.id, total_amount: totalAmount, advance_paid: 0 });
  const bookings = await (await request.get(`/api/bookings/?customer=${customerId}`)).json();
  const booking = bookings[0];
  if (!booking) throw new Error('created booking not found');
  createdBookings.push(booking.id);
  const plan = await mustPost(request, token, '/api/installment-plans/', {
    booking: booking.id, total_installments: 1,
    installment_amount: Math.floor(totalAmount / 2),
    down_payment_amount: 0, start_date: '2026-01-01', frequency: 'monthly', due_day: 1,
  });
  const installments = await (await request.get(`/api/installments/?plan=${plan.id}`)).json();
  return {
    customerId, projectId: project.id, plotId: plot.id, bookingId: booking.id,
    planId: plan.id, installmentId: installments[0]?.id, bookingApiId: booking.booking_id,
  };
}

/** POST /api/payments/ (creates a pending payment) and resolve the full row (id + status). */
async function createApiPayment(
  request: APIRequestContext, token: string, data: any,
): Promise<{ status: number; payment: any }> {
  const res = await request.post('/api/payments/', { data, headers: { 'X-CSRFToken': token } });
  const status = res.status();
  if (status !== 201) return { status, payment: null };
  const created = await res.json();
  const pays = await (await request.get(`/api/payments/?booking=${data.booking}`)).json();
  const payment = pays.find((p: any) => p.payment_id === created.payment_id) ?? created;
  return { status, payment };
}

async function getBooking(request: APIRequestContext, id: number): Promise<any> {
  return (await request.get(`/api/bookings/${id}/`)).json();
}
async function getInstallment(request: APIRequestContext, id: number): Promise<any> {
  return (await request.get(`/api/installments/${id}/`)).json();
}
async function getPayments(request: APIRequestContext, bookingId: number): Promise<any[]> {
  return (await request.get(`/api/payments/?booking=${bookingId}`)).json();
}
async function getCustomer(request: APIRequestContext, id: number): Promise<any> {
  return (await request.get(`/api/customers/${id}/`)).json();
}
async function getLedger(request: APIRequestContext, customerId: number): Promise<any[]> {
  return (await request.get(`/api/customers/${customerId}/ledger/`)).json();
}
async function getRefundsForBooking(request: APIRequestContext, bookingId: number): Promise<any[]> {
  const all = await (await request.get('/api/refunds/')).json();
  return all.filter((r: any) => r.booking === bookingId);
}
async function findReceipts(request: APIRequestContext, paymentId: number): Promise<any[]> {
  return (await request.get(`/api/receipts/?payment=${paymentId}`)).json();
}
async function countLedgerRefund(request: APIRequestContext, refundId: number): Promise<number> {
  const rows = await (await request.get('/api/account-transactions/?transaction_type=refund')).json();
  return rows.filter((r: any) => r.reference_type === 'Refund' && r.reference_id === refundId).length;
}

/** Accept the native confirm() dialogs fired by verify/reject/bounce/reverse buttons. */
function acceptDialogs(page: Page): void {
  page.on('dialog', (d) => d.accept());
}

// ================================================================================
// PAY-BR-HP — happy path (browser UI + cross-table API verification)
// ================================================================================
test.describe('PAY-BR-HP', () => {
  test('PAY-BR-HP-01 — Record payment via UI form (cross-table: Payment/Booking/Receipt/balance)', async ({ page, request }) => {
    const token = await login(request, 'admin');
    const fx = await seedFixture(request, token); // total 1,000,000, advance_paid 0

    await page.goto(`/payments/create/?booking_id=${fx.bookingId}`);
    await expect(page.getByRole('heading', { name: 'Receive Payment' })).toBeVisible();
    await page.getByLabel('Payment Date').fill('2026-09-01');
    await page.getByLabel('Amount (PKR)').fill('300000');
    await page.getByLabel('Payment Type').selectOption('down_payment');
    await page.locator('select[name="payment_method"]').selectOption('bank_transfer');
    await page.getByRole('button', { name: 'Receive Payment' }).click();

    await expect(page).toHaveURL(/\/payments\/$/);
    await expect(page.getByText(/recorded successfully/)).toBeVisible();

    // Cross-table verification (exact Decimal strings).
    const pays = await getPayments(request, fx.bookingId);
    expect(pays).toHaveLength(1);
    const payment = pays[0];
    // 1. Payment row: verified, amount = X, PAY-xxxxx.
    expect(payment.status).toBe('verified');
    expect(payment.amount).toBe('300000.00');
    expect(payment.payment_id).toMatch(/^PAY-\d{5}$/);

    // 2. Booking.advance_paid increased by X (capped at total_amount).
    expect((await getBooking(request, fx.bookingId)).advance_paid).toBe('300000.00');

    // 3. Receipt: RCP-FY26-27/NNNNN (fiscal year July–June), receipt_date set.
    const receipts = await findReceipts(request, payment.id);
    expect(receipts).toHaveLength(1);
    expect(receipts[0].receipt_number).toMatch(/^RCP-FY26-27\/\d{5}$/);
    expect(receipts[0].receipt_date).toBe('2026-09-01');

    // 5. CustomerLedgerEntry: NOT auto-posted by the payment flow (documented gap).
    //    No 'payment' ledger row is written on record/verify — only seed/management
    //    commands and the /api/customer-ledger/ endpoint create entries.
    const ledger = await getLedger(request, fx.customerId);
    expect(ledger.filter((e: any) => e.transaction_type === 'payment')).toHaveLength(0);

    // 6. Customer.current_balance decreased by X (total_owed − verified payments).
    //    Note: current_balance is serialized as a number (not a Decimal string).
    expect((await getCustomer(request, fx.customerId)).current_balance).toBe(700000);
  });

  test('PAY-BR-HP-02 — Verify a pending payment via UI button (installment cross-table)', async ({ page, request }) => {
    const token = await login(request, 'admin');
    const fx = await seedFixture(request, token);

    const { status, payment } = await createApiPayment(request, token, {
      booking: fx.bookingId, installment: fx.installmentId, amount: 200000,
      payment_date: '2026-09-01', payment_method: 'bank_transfer', payment_type: 'installment',
    });
    expect(status).toBe(201);
    expect(payment.status).toBe('pending');

    await page.goto(`/payments/${payment.id}/`);
    await expect(page.getByText('Pending Verification', { exact: true }).first()).toBeVisible();

    acceptDialogs(page);
    await page.getByRole('button', { name: 'Verify' }).click();
    await expect(page.getByText('Verified', { exact: true }).first()).toBeVisible();

    // Cross-table.
    const p = await (await request.get(`/api/payments/${payment.id}/`)).json();
    expect(p.status).toBe('verified');
    expect(p.payment_id).toMatch(/^PAY-\d{5}$/);
    expect(p.amount).toBe('200000.00');
    expect((await getBooking(request, fx.bookingId)).advance_paid).toBe('200000.00');
    // 4. Installment paid_amount/status updated (the payment targets an installment).
    const inst = await getInstallment(request, fx.installmentId!);
    expect(inst.paid_amount).toBe('200000.00');
    expect(inst.status).toBe('partial');
    expect(await findReceipts(request, payment.id)).toHaveLength(1);
  });

  test('PAY-BR-HP-03 — Reject a pending payment via UI button (no financial effect)', async ({ page, request }) => {
    const token = await login(request, 'admin');
    const fx = await seedFixture(request, token);

    const { payment } = await createApiPayment(request, token, {
      booking: fx.bookingId, installment: fx.installmentId, amount: 200000,
      payment_date: '2026-09-01', payment_method: 'bank_transfer', payment_type: 'installment',
    });

    await page.goto(`/payments/${payment.id}/`);
    await expect(page.getByText('Pending Verification', { exact: true }).first()).toBeVisible();
    acceptDialogs(page);
    await page.getByRole('button', { name: 'Reject' }).click();
    await expect(page.getByText('Rejected', { exact: true }).first()).toBeVisible();

    expect((await (await request.get(`/api/payments/${payment.id}/`)).json()).status).toBe('rejected');
    expect((await getBooking(request, fx.bookingId)).advance_paid).toBe('0.00');
    expect((await getInstallment(request, fx.installmentId!)).paid_amount).toBe('0.00');
    expect(await findReceipts(request, payment.id)).toHaveLength(0);
  });

  test('PAY-BR-HP-04 — Bounce a pending cheque via UI button (no financial effect)', async ({ page, request }) => {
    const token = await login(request, 'admin');
    const fx = await seedFixture(request, token);

    const { payment } = await createApiPayment(request, token, {
      booking: fx.bookingId, installment: fx.installmentId, amount: 200000,
      payment_date: '2026-09-01', payment_method: 'cheque', payment_type: 'installment',
      cheque_number: 'CHQ-001', bank_name: 'Test Bank',
    });

    await page.goto(`/payments/${payment.id}/`);
    await page.getByPlaceholder('Bounce reason').fill('insufficient funds');
    acceptDialogs(page);
    await page.getByRole('button', { name: 'Bounce' }).click();
    await expect(page.getByText('Bounced', { exact: true }).first()).toBeVisible();

    const p = await (await request.get(`/api/payments/${payment.id}/`)).json();
    expect(p.status).toBe('bounced');
    expect(p.bounce_reason).toBe('insufficient funds');
    expect((await getBooking(request, fx.bookingId)).advance_paid).toBe('0.00');
    expect((await getInstallment(request, fx.installmentId!)).paid_amount).toBe('0.00');
  });

  test('PAY-BR-HP-05 — Reverse a verified payment via UI button (restores advance_paid)', async ({ page, request }) => {
    const token = await login(request, 'admin');
    const fx = await seedFixture(request, token);

    const { payment } = await createApiPayment(request, token, {
      booking: fx.bookingId, installment: fx.installmentId, amount: 200000,
      payment_date: '2026-09-01', payment_method: 'bank_transfer', payment_type: 'down_payment',
    });
    await request.post(`/api/payments/${payment.id}/verify/`, { data: { action: 'verify' }, headers: { 'X-CSRFToken': token } });
    expect((await getBooking(request, fx.bookingId)).advance_paid).toBe('200000.00');

    await page.goto(`/payments/${payment.id}/`);
    await expect(page.getByText('Verified', { exact: true }).first()).toBeVisible();
    acceptDialogs(page);
    await page.getByRole('button', { name: 'Reverse Payment' }).click();
    await expect(page.getByText('Reversed', { exact: true }).first()).toBeVisible();

    expect((await (await request.get(`/api/payments/${payment.id}/`)).json()).status).toBe('reversed');
    expect((await getBooking(request, fx.bookingId)).advance_paid).toBe('0.00');
    const inst = await getInstallment(request, fx.installmentId!);
    expect(inst.paid_amount).toBe('0.00');
    expect(inst.status).toBe('pending');
  });

  test('PAY-BR-HP-06 — Receipt detail page + PDF renders', async ({ page, request }) => {
    const token = await login(request, 'admin');
    const fx = await seedFixture(request, token);

    const { payment } = await createApiPayment(request, token, {
      booking: fx.bookingId, amount: 300000, payment_date: '2026-09-01',
      payment_method: 'bank_transfer', payment_type: 'down_payment',
    });
    await request.post(`/api/payments/${payment.id}/verify/`, { data: { action: 'verify' }, headers: { 'X-CSRFToken': token } });
    const receipt = (await findReceipts(request, payment.id))[0];

    await page.goto(`/receipts/${receipt.id}/`);
    await expect(page.getByText('OFFICIAL RECEIPT')).toBeVisible();
    await expect(page.locator('.receipt-id')).toHaveText(receipt.receipt_number);

    const pdf = await page.request.get(`/receipts/${receipt.id}/pdf/`);
    expect(pdf.status()).toBe(200);
    expect(pdf.headers()['content-type']).toContain('application/pdf');
    const body = await pdf.body();
    expect(body.length).toBeGreaterThan(0);
  });

  test('PAY-BR-HP-07 — Refund create → approve → process via UI (advance reduced once; one ledger row)', async ({ page, request }) => {
    const token = await login(request, 'admin');
    const fx = await seedFixture(request, token);

    const { payment } = await createApiPayment(request, token, {
      booking: fx.bookingId, amount: 500000, payment_date: '2026-09-01',
      payment_method: 'bank_transfer', payment_type: 'down_payment',
    });
    await request.post(`/api/payments/${payment.id}/verify/`, { data: { action: 'verify' }, headers: { 'X-CSRFToken': token } });
    expect((await getBooking(request, fx.bookingId)).advance_paid).toBe('500000.00');

    // Create the refund through the UI form.
    await page.goto('/refunds/create/');
    await page.locator('select[name="booking"]').selectOption(String(fx.bookingId));
    await page.getByLabel('Amount').fill('100000');
    await page.locator('select[name="reason"]').selectOption('cancellation');
    await page.locator('select[name="refund_method"]').selectOption('bank_transfer');
    await page.getByRole('button', { name: 'Create' }).click();
    await expect(page.getByText('Refund request created successfully!')).toBeVisible();

    const refund = (await getRefundsForBooking(request, fx.bookingId))[0];
    expect(refund.status).toBe('pending');

    // Approve (admin → admin_or_above). The success flash doubles as the POST-completion barrier
    // (approve/process redirect back to /refunds/, so the URL does not change to signal completion).
    const pendingRow = page.getByRole('row', { name: new RegExp(fx.bookingApiId) }).filter({ hasText: 'Pending Approval' });
    await expect(pendingRow.getByRole('button', { name: 'Approve' })).toBeVisible();
    await pendingRow.getByRole('button', { name: 'Approve' }).click();
    await expect(page.getByText('Refund Approved.')).toBeVisible();
    expect((await getBooking(request, fx.bookingId)).advance_paid).toBe('400000.00');
    expect((await (await request.get(`/api/refunds/${refund.id}/`)).json()).status).toBe('approved');

    // Process (admin → management_or_above) → exactly one ledger row.
    const approvedRow = page.getByRole('row', { name: new RegExp(fx.bookingApiId) }).filter({ hasText: 'Approved' });
    await expect(approvedRow.getByRole('button', { name: 'Process' })).toBeVisible();
    await approvedRow.getByRole('button', { name: 'Process' }).click();
    await expect(page.getByText('Refund processed and posted to the ledger.')).toBeVisible();
    expect((await (await request.get(`/api/refunds/${refund.id}/`)).json()).status).toBe('processed');
    expect(await countLedgerRefund(request, refund.id)).toBe(1);
  });
});

// ================================================================================
// PAY-BR-EC — edge cases (UI form validation + one server-level case)
// ================================================================================
test.describe('PAY-BR-EC', () => {
  test('PAY-BR-EC-01 — Amount 0 / negative is rejected', async ({ page, request }) => {
    const token = await login(request, 'admin');
    const fx = await seedFixture(request, token);

    for (const bad of ['0', '-5']) {
      await page.goto(`/payments/create/?booking_id=${fx.bookingId}`);
      await page.getByLabel('Amount (PKR)').fill(bad);
      await page.getByLabel('Payment Date').fill('2026-09-01');
      await page.getByLabel('Payment Type').selectOption('down_payment');
      await page.getByRole('button', { name: 'Receive Payment' }).click();
      await expect(page.getByText('Please correct the errors below.')).toBeVisible();
      await expect(page).toHaveURL(/\/payments\/create\//);
    }
    expect(await getPayments(request, fx.bookingId)).toHaveLength(0);
  });

  test('PAY-BR-EC-02 — Amount above remaining balance is blocked client-side', async ({ page, request }) => {
    const token = await login(request, 'admin');
    const fx = await seedFixture(request, token); // remaining 1,000,000

    await page.goto(`/payments/create/?booking_id=${fx.bookingId}`);
    await page.getByLabel('Amount (PKR)').fill('1200000');
    await page.getByLabel('Payment Date').fill('2026-09-01');
    await page.getByLabel('Payment Type').selectOption('down_payment');
    await page.getByRole('button', { name: 'Receive Payment' }).click();
    await expect(page.getByText(/Amount exceeds remaining balance/)).toBeVisible();
    await expect(page).toHaveURL(/\/payments\/create\//);
    expect(await getPayments(request, fx.bookingId)).toHaveLength(0);
  });

  test('PAY-BR-EC-03 — Cheque without a cheque number is rejected', async ({ page, request }) => {
    const token = await login(request, 'admin');
    const fx = await seedFixture(request, token);

    await page.goto(`/payments/create/?booking_id=${fx.bookingId}`);
    await page.getByLabel('Amount (PKR)').fill('50000');
    await page.getByLabel('Payment Date').fill('2026-09-01');
    await page.getByLabel('Payment Type').selectOption('down_payment');
    await page.locator('select[name="payment_method"]').selectOption('cheque');
    await page.getByRole('button', { name: 'Receive Payment' }).click();
    await expect(page.getByText('Please correct the errors below.')).toBeVisible();
    await expect(page).toHaveURL(/\/payments\/create\//);
    expect(await getPayments(request, fx.bookingId)).toHaveLength(0);
  });

  test('PAY-BR-EC-04 — Invalid / empty payment date is rejected', async ({ page, request }) => {
    const token = await login(request, 'admin');
    const fx = await seedFixture(request, token);

    await page.goto(`/payments/create/?booking_id=${fx.bookingId}`);
    await page.getByLabel('Amount (PKR)').fill('50000');
    await page.getByLabel('Payment Date').fill('');
    await page.getByLabel('Payment Type').selectOption('down_payment');
    await page.getByRole('button', { name: 'Receive Payment' }).click();
    await expect(page.getByText('Please correct the errors below.')).toBeVisible();
    await expect(page).toHaveURL(/\/payments\/create\//);
    expect(await getPayments(request, fx.bookingId)).toHaveLength(0);
  });

  test('PAY-BR-EC-05 — Payment on a non-existent booking is rejected', async ({ request }) => {
    const token = await login(request, 'admin');
    // Server-level case (no such option exists in the UI booking selector).
    const res = await request.post('/payments/create/', {
      form: { booking: '999999999', amount: '100000', payment_date: '2026-09-01', payment_method: 'cash', payment_type: 'down_payment' },
      headers: { 'X-CSRFToken': token },
      maxRedirects: 0,
    });
    expect(res.status()).toBe(200); // form re-rendered with an error, not a 302 create
  });
});

// ================================================================================
// PAY-BR-SEC — negative / security (confirmed defects, written RED on purpose)
// ================================================================================
test.describe('PAY-BR-SEC', () => {
  test('PAY-BR-SEC-01 — Reverse a pending payment must be a no-op', async ({ request }) => {
    // CONFIRMED BUG: docs/qa/findings-confirmed.md F6 — payment_reverse_view has no status guard.
    const token = await login(request, 'admin');
    const fx = await seedFixture(request, token);

    const { payment: p1 } = await createApiPayment(request, token, {
      booking: fx.bookingId, installment: fx.installmentId, amount: 500000,
      payment_date: '2026-09-01', payment_method: 'bank_transfer', payment_type: 'down_payment',
    });
    await request.post(`/api/payments/${p1.id}/verify/`, { data: { action: 'verify' }, headers: { 'X-CSRFToken': token } });
    expect((await getBooking(request, fx.bookingId)).advance_paid).toBe('500000.00');
    expect((await getInstallment(request, fx.installmentId!)).paid_amount).toBe('500000.00');

    const { payment: p2 } = await createApiPayment(request, token, {
      booking: fx.bookingId, installment: fx.installmentId, amount: 100000,
      payment_date: '2026-09-01', payment_method: 'bank_transfer', payment_type: 'installment',
    });
    expect(p2.status).toBe('pending');

    // The UI hides the reverse button for pending payments; POST directly.
    await request.post(`/payments/${p2.id}/reverse/`, { headers: { 'X-CSRFToken': token }, maxRedirects: 0 });

    // CORRECT: balances untouched (500000). Actual: corrupted to 400000.
    expect((await getBooking(request, fx.bookingId)).advance_paid).toBe('500000.00');
    expect((await getInstallment(request, fx.installmentId!)).paid_amount).toBe('500000.00');
  });

  test('PAY-BR-SEC-02 — Verify is idempotent (double-verify counted once)', async ({ request }) => {
    // CONFIRMED BUG: docs/qa/findings-confirmed.md F6 — check-then-act race (no select_for_update).
    // The sequential status guard masks the race on the single-threaded dev server; asserting
    // idempotency documents the correct behaviour (race is only reproducible on PostgreSQL).
    const token = await login(request, 'admin');
    const fx = await seedFixture(request, token);

    const { payment: p } = await createApiPayment(request, token, {
      booking: fx.bookingId, installment: fx.installmentId, amount: 200000,
      payment_date: '2026-09-01', payment_method: 'bank_transfer', payment_type: 'installment',
    });

    expect((await request.post(`/api/payments/${p.id}/verify/`, { data: { action: 'verify' }, headers: { 'X-CSRFToken': token } })).status()).toBe(200);
    expect((await request.post(`/api/payments/${p.id}/verify/`, { data: { action: 'verify' }, headers: { 'X-CSRFToken': token } })).status()).toBe(400);

    expect((await getBooking(request, fx.bookingId)).advance_paid).toBe('200000.00');
    expect((await getInstallment(request, fx.installmentId!)).paid_amount).toBe('200000.00');
    expect(await findReceipts(request, p.id)).toHaveLength(1);
  });

  test('PAY-BR-SEC-03 — Second refund approve must be refused', async ({ request }) => {
    // CONFIRMED BUG: docs/qa/findings-confirmed.md F6 — refund_approve_view lacks a status=='pending' guard.
    let token = await login(request, 'admin');
    const fx = await seedFixture(request, token);

    const { payment: p } = await createApiPayment(request, token, {
      booking: fx.bookingId, amount: 500000, payment_date: '2026-09-01',
      payment_method: 'bank_transfer', payment_type: 'down_payment',
    });
    await request.post(`/api/payments/${p.id}/verify/`, { data: { action: 'verify' }, headers: { 'X-CSRFToken': token } });

    token = await login(request, 'accounts');
    await request.post('/refunds/create/', {
      form: { booking: String(fx.bookingId), amount: '100000', reason: 'cancellation', refund_method: 'bank_transfer' },
      headers: { 'X-CSRFToken': token },
      maxRedirects: 0,
    });
    const refund = (await getRefundsForBooking(request, fx.bookingId))[0];

    token = await login(request, 'admin');
    await request.post(`/refunds/${refund.id}/approve/`, { form: { action: 'approve' }, headers: { 'X-CSRFToken': token }, maxRedirects: 0 });
    await request.post(`/refunds/${refund.id}/approve/`, { form: { action: 'approve' }, headers: { 'X-CSRFToken': token }, maxRedirects: 0 });

    // CORRECT: reduced once → 400000. Actual: reduced twice → 300000.
    expect((await getBooking(request, fx.bookingId)).advance_paid).toBe('400000.00');
  });

  test('PAY-BR-SEC-04 — Sales and portal customer are denied the receipts API', async ({ request }) => {
    // CONFIRMED BUG: docs/qa/findings-confirmed.md F3 — ReceiptViewSet is IsAuthenticated (read-open).
    const token = await login(request, 'admin');
    const fx = await seedFixture(request, token);
    const { payment: p } = await createApiPayment(request, token, {
      booking: fx.bookingId, amount: 100000, payment_date: '2026-09-01', payment_method: 'cash', payment_type: 'other',
    });
    await request.post(`/api/payments/${p.id}/verify/`, { data: { action: 'verify' }, headers: { 'X-CSRFToken': token } });
    await findReceipts(request, p.id); // ensure a receipt exists

    await login(request, 'sales');
    const salesList = await request.get('/api/receipts/');
    await login(request, 'customer');
    const customerList = await request.get('/api/receipts/');

    // CORRECT: 403 for sales and customer. Actual: 200 with full receipt data.
    expect(salesList.status()).toBe(403);
    expect(customerList.status()).toBe(403);
  });
});

// ================================================================================
// PAY-BR-INT — interactive (list search/filter, status badges, refund buttons)
// ================================================================================
test.describe('PAY-BR-INT', () => {
  test('PAY-BR-INT-01 — Payments list search/filter + detail status badge', async ({ page, request }) => {
    const token = await login(request, 'admin');
    const fx = await seedFixture(request, token);
    const { payment: p } = await createApiPayment(request, token, {
      booking: fx.bookingId, amount: 200000, payment_date: '2026-09-01',
      payment_method: 'bank_transfer', payment_type: 'down_payment',
    });
    await request.post(`/api/payments/${p.id}/verify/`, { data: { action: 'verify' }, headers: { 'X-CSRFToken': token } });

    await page.goto('/payments/');
    await page.getByPlaceholder('Search by ID, booking, or customer...').fill(p.payment_id);
    await page.getByRole('button', { name: 'Filter' }).click();

    const row = page.getByRole('row', { name: new RegExp(p.payment_id) });
    await expect(row).toContainText(fx.bookingApiId);
    await expect(row).toContainText('Down Payment');

    await row.getByRole('link', { name: 'View' }).click();
    await expect(page.getByText('Verified', { exact: true }).first()).toBeVisible();
  });
});

// ================================================================================
// Cleanup (best-effort, FK order: payments → refunds → bookings → plots → projects → customers)
// ================================================================================
test.afterAll(async ({ request }) => {
  const token = await login(request, 'admin');
  for (const b of createdBookings) {
    try {
      const pays = await (await request.get(`/api/payments/?booking=${b}`)).json();
      for (const p of pays) {
        await request.delete(`/api/payments/${p.id}/`, { headers: { 'X-CSRFToken': token } });
      }
    } catch { /* ignore */ }
    try {
      const refunds = await (await request.get('/api/refunds/')).json();
      for (const r of refunds.filter((r: any) => r.booking === b)) {
        await request.delete(`/api/refunds/${r.id}/`, { headers: { 'X-CSRFToken': token } });
      }
    } catch { /* ignore */ }
    try { await request.delete(`/api/bookings/${b}/`, { headers: { 'X-CSRFToken': token } }); } catch { /* ignore */ }
  }
  for (const p of createdPlots) {
    try { await request.delete(`/api/plots/${p}/`, { headers: { 'X-CSRFToken': token } }); } catch { /* ignore */ }
  }
  for (const p of createdProjects) {
    try { await request.delete(`/api/projects/${p}/`, { headers: { 'X-CSRFToken': token } }); } catch { /* ignore */ }
  }
  for (const c of createdCustomers) {
    try { await request.delete(`/api/customers/${c}/`, { headers: { 'X-CSRFToken': token } }); } catch { /* ignore */ }
  }
});
