import { test, expect, APIRequestContext } from '@playwright/test';
import { loginViaApi, ROLES } from '../helpers/auth';

type Role = keyof typeof ROLES;

// Whole file runs serially (one worker) so module-level fixture tracking and the
// single afterAll cleanup are reliable, and money-flow tests can't interleave.
test.describe.configure({ mode: 'serial' });

// ─── Notes ──────────────────────────────────────────────────────────────────────
// - Django's login() rotates the CSRF token (rotate_token). `loginViaApi` returns the
//   pre-login token, so we re-read the fresh csrftoken cookie after every login.
// - DRF endpoints (`/api/...`) accept JSON (`data`) + `X-CSRFToken`; Django template
//   views (`/payments/...`, `/refunds/...`, `/receipts/...`) need urlencoded (`form`).
// - Money is asserted as exact Decimal strings (DRF DecimalField → "300000.00").
// - Several DRF *create* serializers omit `id` (CustomerCreateSerializer,
//   BookingCreateSerializer, PaymentCreateSerializer); helpers resolve the numeric id
//   from the list endpoint (the list serializers DO include `id`).
// - RED scenarios assert the CORRECT behaviour; the app is buggy so they fail.

// ─── CSRF / login helpers ───────────────────────────────────────────────────────
async function readCsrf(request: APIRequestContext): Promise<string> {
  try {
    const state = await request.storageState();
    const c = state.cookies.find((c) => c.name === 'csrftoken');
    return c ? c.value : '';
  } catch {
    return '';
  }
}

async function login(request: APIRequestContext, role: Role): Promise<string> {
  await loginViaApi(request, role);
  return readCsrf(request);
}

// ─── Unique id generation ───────────────────────────────────────────────────────
let uidCounter = 0;
function uniq(): string {
  uidCounter += 1;
  const rnd = Math.floor(Math.random() * 1e6).toString().padStart(6, '0');
  return `${Date.now().toString().slice(-8)}${rnd}${uidCounter}`;
}

// ─── Fixture tracking (for afterAll cleanup) ────────────────────────────────────
const createdCustomers: number[] = [];
const createdProjects: number[] = [];
const createdPlots: number[] = [];
const createdBookings: number[] = [];

// ─── Low-level API helpers ──────────────────────────────────────────────────────
async function mustPost(request: APIRequestContext, token: string, url: string, data: any): Promise<any> {
  const res = await request.post(url, { data, headers: { 'X-CSRFToken': token } });
  if (res.status() >= 400) {
    throw new Error(`${url} -> ${res.status()}: ${await res.text()}`);
  }
  return res.json();
}

async function createCustomer(request: APIRequestContext, token: string, tag: string): Promise<number> {
  const cnic = `35202-${tag.slice(0, 7)}-${tag.slice(7, 8)}`;
  const res = await request.post('/api/customers/', {
    data: {
      first_name: 'QA', last_name: `Pay ${tag}`,
      email: `qa.pay.${tag}@example.com`,
      phone: `+92${tag.slice(0, 10)}`,
      cnic, address: 'QA Address', city: 'Lahore',
    },
    headers: { 'X-CSRFToken': token },
  });
  if (res.status() !== 201) throw new Error(`createCustomer -> ${res.status()}: ${await res.text()}`);
  // CustomerCreateSerializer omits `id`; resolve it via the search endpoint (CustomerSerializer).
  const found = await (await request.get(`/api/customers/?search=${encodeURIComponent(cnic)}`)).json();
  const id = found[0]?.id;
  if (!id) throw new Error('created customer not found by cnic');
  createdCustomers.push(id);
  return id;
}

/** Create customer → project → plot → booking → installment plan (+ 1 installment). */
async function seedFixture(
  request: APIRequestContext, token: string, opts: { totalAmount?: number } = {},
): Promise<{
  customerId: number; projectId: number; plotId: number; bookingId: number;
  planId: number; installmentId?: number; bookingApiId: string;
}> {
  const totalAmount = opts.totalAmount ?? 1000000;
  const tag = uniq();
  const customerId = await createCustomer(request, token, tag);
  const project = await mustPost(request, token, '/api/projects/', { name: `QA-PAY-${tag}`, location: 'Lahore', status: 'booking_open' });
  createdProjects.push(project.id);
  const plot = await mustPost(request, token, '/api/plots/', { plot_number: `P-${tag}`, project: project.id, size_marla: 5, price: totalAmount });
  createdPlots.push(plot.id);
  await mustPost(request, token, '/api/bookings/', { customer: customerId, plot: plot.id, total_amount: totalAmount, advance_paid: 0 });
  // BookingCreateSerializer omits `id`/`booking_id`; resolve via the list endpoint.
  const bookings = await (await request.get(`/api/bookings/?customer=${customerId}`)).json();
  const booking = bookings[0];
  if (!booking) throw new Error('created booking not found');
  createdBookings.push(booking.id);
  const plan = await mustPost(request, token, '/api/installment-plans/', {
    booking: booking.id, total_installments: 1,
    installment_amount: Math.floor(totalAmount / 2),
    down_payment_amount: 0, start_date: '2026-01-01', frequency: 'monthly', due_day: 1,
  });
  return {
    customerId, projectId: project.id, plotId: plot.id, bookingId: booking.id,
    planId: plan.id, installmentId: plan.installments?.[0]?.id, bookingApiId: booking.booking_id,
  };
}

/** POST /api/payments/ and resolve the full row (PaymentCreateSerializer omits `id`). */
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

// ================================================================================
// PAY-HP — happy path
// ================================================================================
test.describe('PAY-HP', () => {
  test('PAY-HP-01 — Record payment (web) verifies immediately', async ({ request }) => {
    const token = await login(request, 'admin');
    const fx = await seedFixture(request, token); // total 1,000,000, 1 installment 500,000

    const res = await request.post('/payments/create/', {
      form: {
        booking: String(fx.bookingId), installment: String(fx.installmentId),
        amount: '300000', payment_date: '2026-08-01',
        payment_method: 'bank_transfer', payment_type: 'down_payment',
      },
      headers: { 'X-CSRFToken': token },
      maxRedirects: 0,
    });
    expect(res.status()).toBe(302);

    const b = await getBooking(request, fx.bookingId);
    expect(b.advance_paid).toBe('300000.00');
    const inst = await getInstallment(request, fx.installmentId!);
    expect(inst.paid_amount).toBe('300000.00');
    expect(inst.status).toBe('partial');

    const pays = await getPayments(request, fx.bookingId);
    expect(pays).toHaveLength(1);
    expect(pays[0].status).toBe('verified'); // NOT pending
    expect(pays[0].receipt_generated).toBe(true);

    const receipts = await findReceipts(request, pays[0].id);
    expect(receipts).toHaveLength(1);
    expect(receipts[0].receipt_number).toMatch(/^RCP-FY/);
  });

  test('PAY-HP-02 — Verify a pending payment', async ({ request }) => {
    const token = await login(request, 'admin');
    const fx = await seedFixture(request, token);

    const { status, payment } = await createApiPayment(request, token, {
      booking: fx.bookingId, installment: fx.installmentId,
      amount: 200000, payment_date: '2026-08-01',
      payment_method: 'bank_transfer', payment_type: 'installment',
    });
    expect(status).toBe(201);
    expect(payment.status).toBe('pending');

    const res = await request.post(`/payments/${payment.id}/verify/`, { headers: { 'X-CSRFToken': token }, maxRedirects: 0 });
    expect(res.status()).toBe(302);

    expect((await getBooking(request, fx.bookingId)).advance_paid).toBe('200000.00');
    const inst = await getInstallment(request, fx.installmentId!);
    expect(inst.paid_amount).toBe('200000.00');

    const p2 = await (await request.get(`/api/payments/${payment.id}/`)).json();
    expect(p2.status).toBe('verified');
    expect(p2.verified_by_name).toBe('admin');
    expect(await findReceipts(request, payment.id)).toHaveLength(1);
  });

  test('PAY-HP-03 — Reject a pending payment (no financial effect)', async ({ request }) => {
    const token = await login(request, 'admin');
    const fx = await seedFixture(request, token);

    const { payment } = await createApiPayment(request, token, {
      booking: fx.bookingId, installment: fx.installmentId,
      amount: 200000, payment_date: '2026-08-01',
      payment_method: 'bank_transfer', payment_type: 'installment',
    });

    const res = await request.post(`/payments/${payment.id}/reject/`, { headers: { 'X-CSRFToken': token }, maxRedirects: 0 });
    expect(res.status()).toBe(302);

    const p2 = await (await request.get(`/api/payments/${payment.id}/`)).json();
    expect(p2.status).toBe('rejected');
    expect((await getBooking(request, fx.bookingId)).advance_paid).toBe('0.00');
    expect((await getInstallment(request, fx.installmentId!)).paid_amount).toBe('0.00');
    expect(await findReceipts(request, payment.id)).toHaveLength(0);
  });

  test('PAY-HP-04 — Bounce a pending cheque (no financial effect)', async ({ request }) => {
    const token = await login(request, 'admin');
    const fx = await seedFixture(request, token);

    const { status, payment } = await createApiPayment(request, token, {
      booking: fx.bookingId, installment: fx.installmentId,
      amount: 200000, payment_date: '2026-08-01',
      payment_method: 'cheque', payment_type: 'installment',
      cheque_number: 'CHQ-001', bank_name: 'Test Bank',
    });
    expect(status).toBe(201);

    const res = await request.post(`/payments/${payment.id}/bounce/`, {
      form: { bounce_reason: 'insufficient funds' },
      headers: { 'X-CSRFToken': token },
      maxRedirects: 0,
    });
    expect(res.status()).toBe(302);

    const p2 = await (await request.get(`/api/payments/${payment.id}/`)).json();
    expect(p2.status).toBe('bounced');
    expect(p2.bounce_reason).toBe('insufficient funds');
    expect((await getBooking(request, fx.bookingId)).advance_paid).toBe('0.00');
    expect((await getInstallment(request, fx.installmentId!)).paid_amount).toBe('0.00');
  });

  test('PAY-HP-05 — Reverse a verified payment (restores advance_paid)', async ({ request }) => {
    const token = await login(request, 'admin');
    const fx = await seedFixture(request, token);

    const { payment } = await createApiPayment(request, token, {
      booking: fx.bookingId, installment: fx.installmentId,
      amount: 200000, payment_date: '2026-08-01',
      payment_method: 'bank_transfer', payment_type: 'down_payment',
    });
    await request.post(`/api/payments/${payment.id}/verify/`, { headers: { 'X-CSRFToken': token }, maxRedirects: 0 });
    expect((await getBooking(request, fx.bookingId)).advance_paid).toBe('200000.00');

    const res = await request.post(`/payments/${payment.id}/reverse/`, { headers: { 'X-CSRFToken': token }, maxRedirects: 0 });
    expect(res.status()).toBe(302);

    const p2 = await (await request.get(`/api/payments/${payment.id}/`)).json();
    expect(p2.status).toBe('reversed');
    expect((await getBooking(request, fx.bookingId)).advance_paid).toBe('0.00');
    const inst = await getInstallment(request, fx.installmentId!);
    expect(inst.paid_amount).toBe('0.00');
    expect(inst.status).toBe('pending');
    // NOTE: payment_reverse_view (web) does not cancel the linked Receipt (gap, not in findings).
  });

  test.describe('receipt UI', () => {
    test.use({ storageState: 'tests/.auth/accounts.json' });

    test('PAY-HP-06 — Receipt PDF renders and downloads', async ({ page, request }) => {
      const token = await login(request, 'admin');
      const fx = await seedFixture(request, token);

      await request.post('/payments/create/', {
        form: {
          booking: String(fx.bookingId), installment: String(fx.installmentId),
          amount: '300000', payment_date: '2026-08-01',
          payment_method: 'bank_transfer', payment_type: 'down_payment',
        },
        headers: { 'X-CSRFToken': token },
        maxRedirects: 0,
      });
      const payment = (await getPayments(request, fx.bookingId))[0];
      const receipt = (await findReceipts(request, payment.id))[0];

      // Detail page as `accounts` (payments_access allows it).
      await page.goto(`/receipts/${receipt.id}/`);
      await expect(page.getByText('OFFICIAL RECEIPT')).toBeVisible();
      await expect(page.locator('.receipt-id')).toHaveText(receipt.receipt_number);
      await expect(page.locator('.receipt-amount-words')).toContainText('Rupees Three Lakh Only');

      // PDF endpoint.
      const pdf = await page.request.get(`/receipts/${receipt.id}/pdf/`);
      expect(pdf.status()).toBe(200);
      expect(pdf.headers()['content-type']).toContain('application/pdf');
      const body = await pdf.body();
      expect(body.length).toBeGreaterThan(0);
    });
  });

  test('PAY-HP-07 — Refund create → approve → process (one ledger row)', async ({ request }) => {
    let token = await login(request, 'admin');
    const fx = await seedFixture(request, token);

    const { payment } = await createApiPayment(request, token, {
      booking: fx.bookingId, amount: 500000, payment_date: '2026-08-01', payment_method: 'bank_transfer', payment_type: 'down_payment',
    });
    await request.post(`/api/payments/${payment.id}/verify/`, { headers: { 'X-CSRFToken': token }, maxRedirects: 0 });
    expect((await getBooking(request, fx.bookingId)).advance_paid).toBe('500000.00');

    // accounts creates the refund (web)
    token = await login(request, 'accounts');
    const rc = await request.post('/refunds/create/', {
      form: { booking: String(fx.bookingId), amount: '100000', reason: 'cancellation', refund_method: 'bank_transfer' },
      headers: { 'X-CSRFToken': token },
      maxRedirects: 0,
    });
    expect(rc.status()).toBe(302);
    const refunds = await getRefundsForBooking(request, fx.bookingId);
    expect(refunds).toHaveLength(1);
    const refund = refunds[0];
    expect(refund.status).toBe('pending');

    // admin approves (web)
    token = await login(request, 'admin');
    const ar = await request.post(`/refunds/${refund.id}/approve/`, {
      form: { action: 'approve' }, headers: { 'X-CSRFToken': token }, maxRedirects: 0,
    });
    expect(ar.status()).toBe(302);
    expect((await getBooking(request, fx.bookingId)).advance_paid).toBe('400000.00');
    expect((await (await request.get(`/api/refunds/${refund.id}/`)).json()).status).toBe('approved');

    // management processes (web)
    token = await login(request, 'management');
    const pr = await request.post(`/refunds/${refund.id}/process/`, { headers: { 'X-CSRFToken': token }, maxRedirects: 0 });
    expect(pr.status()).toBe(302);
    expect((await (await request.get(`/api/refunds/${refund.id}/`)).json()).status).toBe('processed');
    expect(await countLedgerRefund(request, refund.id)).toBe(1);

    // re-process is refused (idempotent) — still exactly one ledger row
    await request.post(`/refunds/${refund.id}/process/`, { headers: { 'X-CSRFToken': token }, maxRedirects: 0 });
    expect(await countLedgerRefund(request, refund.id)).toBe(1);
  });

  test('PAY-HP-08 — amount_in_words (Pakistani Crore/Lakh)', async ({ request }) => {
    const token = await login(request, 'admin');
    const fx = await seedFixture(request, token, { totalAmount: 100000000 });

    const cases = [
      { amount: 999999, words: 'Rupees Nine Lakh Ninety Nine Thousand Nine Hundred and Ninety Nine Only' },
      { amount: 1000, words: 'Rupees One Thousand Only' },
      { amount: 12345678, words: 'Rupees One Crore Twenty Three Lakh Forty Five Thousand Six Hundred and Seventy Eight Only' },
    ];
    for (const c of cases) {
      const { payment } = await createApiPayment(request, token, {
        booking: fx.bookingId, amount: c.amount, payment_date: '2026-08-01', payment_method: 'bank_transfer', payment_type: 'other',
      });
      await request.post(`/api/payments/${payment.id}/verify/`, { headers: { 'X-CSRFToken': token }, maxRedirects: 0 });
      const receipt = (await findReceipts(request, payment.id))[0];
      const html = await (await request.get(`/receipts/${receipt.id}/`)).text();
      expect(html).toContain(c.words);
    }
    // `0 → "Zero"` is a pure-function case, not reachable through a payment flow (amount must be > 0).
  });
});

// ================================================================================
// PAY-EC — edge case / boundary
// ================================================================================
test.describe('PAY-EC', () => {
  test('PAY-EC-01 — Reverse a pending payment is a no-op', async ({ request }) => {
    // CONFIRMED BUG: docs/qa/findings-confirmed.md F6 — payment_reverse_view has no status guard.
    const token = await login(request, 'admin');
    const fx = await seedFixture(request, token);

    const { payment: p1 } = await createApiPayment(request, token, {
      booking: fx.bookingId, installment: fx.installmentId, amount: 500000, payment_date: '2026-08-01', payment_method: 'bank_transfer', payment_type: 'down_payment',
    });
    await request.post(`/api/payments/${p1.id}/verify/`, { headers: { 'X-CSRFToken': token }, maxRedirects: 0 });
    expect((await getBooking(request, fx.bookingId)).advance_paid).toBe('500000.00');
    expect((await getInstallment(request, fx.installmentId!)).paid_amount).toBe('500000.00');

    const { payment: p2 } = await createApiPayment(request, token, {
      booking: fx.bookingId, installment: fx.installmentId, amount: 100000, payment_date: '2026-08-01', payment_method: 'bank_transfer', payment_type: 'installment',
    });
    expect(p2.status).toBe('pending');

    // Reverse the (never-verified) payment — the UI hides the button, we POST directly.
    await request.post(`/payments/${p2.id}/reverse/`, { headers: { 'X-CSRFToken': token }, maxRedirects: 0 });

    // CORRECT: balances untouched (still 500000). Actual: corrupts to 400000.
    expect((await getBooking(request, fx.bookingId)).advance_paid).toBe('500000.00');
    expect((await getInstallment(request, fx.installmentId!)).paid_amount).toBe('500000.00');
  });

  test('PAY-EC-02 — Verify is idempotent (double-verify counted once)', async ({ request }) => {
    // CONFIRMED BUG: docs/qa/findings-confirmed.md F6 — check-then-act race (no select_for_update).
    // The sequential status guard masks the race on the single-threaded dev server; asserting
    // idempotency documents the correct behaviour (race is only reproducible on PostgreSQL).
    const token = await login(request, 'admin');
    const fx = await seedFixture(request, token);

    const { payment: p } = await createApiPayment(request, token, {
      booking: fx.bookingId, installment: fx.installmentId, amount: 200000, payment_date: '2026-08-01', payment_method: 'bank_transfer', payment_type: 'installment',
    });

    expect((await request.post(`/api/payments/${p.id}/verify/`, { headers: { 'X-CSRFToken': token }, maxRedirects: 0 })).status()).toBe(302);
    expect((await request.post(`/api/payments/${p.id}/verify/`, { headers: { 'X-CSRFToken': token }, maxRedirects: 0 })).status()).toBe(302);

    expect((await getBooking(request, fx.bookingId)).advance_paid).toBe('200000.00');
    expect((await getInstallment(request, fx.installmentId!)).paid_amount).toBe('200000.00');
    expect(await findReceipts(request, p.id)).toHaveLength(1);
  });

  test('PAY-EC-03 — Second refund approve is refused', async ({ request }) => {
    // CONFIRMED BUG: docs/qa/findings-confirmed.md F6 — refund_approve_view lacks a status=='pending' guard.
    let token = await login(request, 'admin');
    const fx = await seedFixture(request, token);

    const { payment: p } = await createApiPayment(request, token, {
      booking: fx.bookingId, amount: 500000, payment_date: '2026-08-01', payment_method: 'bank_transfer', payment_type: 'down_payment',
    });
    await request.post(`/api/payments/${p.id}/verify/`, { headers: { 'X-CSRFToken': token }, maxRedirects: 0 });

    token = await login(request, 'accounts');
    await request.post('/refunds/create/', {
      form: { booking: String(fx.bookingId), amount: '100000', reason: 'cancellation', refund_method: 'bank_transfer' },
      headers: { 'X-CSRFToken': token },
      maxRedirects: 0,
    });
    const refund = (await getRefundsForBooking(request, fx.bookingId))[0];

    token = await login(request, 'admin');
    await request.post(`/refunds/${refund.id}/approve/`, { form: { action: 'approve' }, headers: { 'X-CSRFToken': token }, maxRedirects: 0 });
    // Second approve — should be refused.
    await request.post(`/refunds/${refund.id}/approve/`, { form: { action: 'approve' }, headers: { 'X-CSRFToken': token }, maxRedirects: 0 });

    // CORRECT: reduced once → 400000. Actual: reduced twice → 300000.
    expect((await getBooking(request, fx.bookingId)).advance_paid).toBe('400000.00');
  });

  test('PAY-EC-04 — Note-only refund edit is accepted', async ({ request }) => {
    // RefundSerializer.validate double-counts self → rejects note-only edits (defect, spec §3).
    const token = await login(request, 'admin');
    const fx = await seedFixture(request, token);

    const { payment: p } = await createApiPayment(request, token, {
      booking: fx.bookingId, amount: 100000, payment_date: '2026-08-01', payment_method: 'bank_transfer', payment_type: 'down_payment',
    });
    await request.post(`/api/payments/${p.id}/verify/`, { headers: { 'X-CSRFToken': token }, maxRedirects: 0 });

    const rc = await request.post('/api/refunds/', {
      data: { booking: fx.bookingId, amount: 100000, reason: 'cancellation', refund_method: 'bank_transfer' },
      headers: { 'X-CSRFToken': token },
    });
    expect(rc.status()).toBe(201);
    const refund = await rc.json();

    const patch = await request.patch(`/api/refunds/${refund.id}/`, { data: { notes: 'amended' }, headers: { 'X-CSRFToken': token } });
    // CORRECT: 200. Actual: 400 ("exceeds refundable").
    expect(patch.status()).toBe(200);
  });

  test('PAY-EC-05 — Overpayment is capped at total (never negative)', async ({ request }) => {
    const token = await login(request, 'admin');
    const fx = await seedFixture(request, token); // total 1,000,000

    const res = await request.post('/payments/create/', {
      form: {
        booking: String(fx.bookingId), installment: String(fx.installmentId),
        amount: '1200000', payment_date: '2026-08-01',
        payment_method: 'bank_transfer', payment_type: 'down_payment',
      },
      headers: { 'X-CSRFToken': token },
      maxRedirects: 0,
    });
    expect(res.status()).toBe(302);
    // Server caps advance_paid at total_amount (no negative remaining balance).
    expect((await getBooking(request, fx.bookingId)).advance_paid).toBe('1000000.00');
  });

  test('PAY-EC-06 — Refund above refundable is rejected', async ({ request }) => {
    const token = await login(request, 'admin');
    const fx = await seedFixture(request, token);

    const { payment: p } = await createApiPayment(request, token, {
      booking: fx.bookingId, amount: 300000, payment_date: '2026-08-01', payment_method: 'bank_transfer', payment_type: 'down_payment',
    });
    await request.post(`/api/payments/${p.id}/verify/`, { headers: { 'X-CSRFToken': token }, maxRedirects: 0 });

    // API rejects
    const rc = await request.post('/api/refunds/', {
      data: { booking: fx.bookingId, amount: 350000, reason: 'cancellation', refund_method: 'bank_transfer' },
      headers: { 'X-CSRFToken': token },
    });
    expect(rc.status()).toBe(400);

    // Web form rejects (re-renders, no redirect)
    const wr = await request.post('/refunds/create/', {
      form: { booking: String(fx.bookingId), amount: '350000', reason: 'cancellation', refund_method: 'bank_transfer' },
      headers: { 'X-CSRFToken': token },
      maxRedirects: 0,
    });
    expect(wr.status()).toBe(200);
    expect(await getRefundsForBooking(request, fx.bookingId)).toHaveLength(0);
  });

  test('PAY-EC-07 — Receipt fiscal-year June/July boundary', async ({ request }) => {
    const token = await login(request, 'admin');
    const fx = await seedFixture(request, token);

    const { payment: p1 } = await createApiPayment(request, token, {
      booking: fx.bookingId, amount: 50000, payment_date: '2026-06-30', payment_method: 'bank_transfer', payment_type: 'other',
    });
    await request.post(`/api/payments/${p1.id}/verify/`, { headers: { 'X-CSRFToken': token }, maxRedirects: 0 });

    const { payment: p2 } = await createApiPayment(request, token, {
      booking: fx.bookingId, amount: 50000, payment_date: '2026-07-01', payment_method: 'bank_transfer', payment_type: 'other',
    });
    await request.post(`/api/payments/${p2.id}/verify/`, { headers: { 'X-CSRFToken': token }, maxRedirects: 0 });

    const r1 = (await findReceipts(request, p1.id))[0];
    const r2 = (await findReceipts(request, p2.id))[0];
    expect(r1.receipt_number).toMatch(/^RCP-FY25-26\//);
    expect(r2.receipt_number).toMatch(/^RCP-FY26-27\//);
  });

  test('PAY-EC-08 — Receipt numbering is sequential and unique per FY', async ({ request }) => {
    const token = await login(request, 'admin');
    const fx = await seedFixture(request, token);

    const nums: string[] = [];
    for (const d of ['2026-08-01', '2026-08-02', '2026-08-03']) {
      const { payment: p } = await createApiPayment(request, token, {
        booking: fx.bookingId, amount: 10000, payment_date: d, payment_method: 'cash', payment_type: 'other',
      });
      await request.post(`/api/payments/${p.id}/verify/`, { headers: { 'X-CSRFToken': token }, maxRedirects: 0 });
      nums.push((await findReceipts(request, p.id))[0].receipt_number);
    }

    const prefixes = nums.map((n) => n.split('/')[0]);
    expect(new Set(prefixes).size).toBe(1);
    expect(new Set(nums).size).toBe(3);
    const suffixes = nums.map((n) => parseInt(n.split('/')[1], 10));
    expect(suffixes[0]).toBeLessThan(suffixes[1]);
    expect(suffixes[1]).toBeLessThan(suffixes[2]);
  });

  test('PAY-EC-09 — Duplicate payment within 60s is blocked', async ({ request }) => {
    const token = await login(request, 'admin');
    const fx = await seedFixture(request, token);

    const payload = {
      booking: String(fx.bookingId), installment: String(fx.installmentId),
      amount: '250000', payment_date: '2026-08-01', payment_method: 'bank_transfer', payment_type: 'down_payment',
    };
    expect((await request.post('/payments/create/', { form: payload, headers: { 'X-CSRFToken': token }, maxRedirects: 0 })).status()).toBe(302);
    // identical second submit within 60s → blocked
    expect((await request.post('/payments/create/', { form: payload, headers: { 'X-CSRFToken': token }, maxRedirects: 0 })).status()).toBe(302);
    expect(await getPayments(request, fx.bookingId)).toHaveLength(1);
    // third with a different date → allowed
    expect((await request.post('/payments/create/', { form: { ...payload, payment_date: '2026-08-02' }, headers: { 'X-CSRFToken': token }, maxRedirects: 0 })).status()).toBe(302);
    expect(await getPayments(request, fx.bookingId)).toHaveLength(2);
  });

  test('PAY-EC-10 — Refund against a booking with no payments is rejected', async ({ request }) => {
    const token = await login(request, 'admin');
    const fx = await seedFixture(request, token); // advance_paid 0, no payments

    const rc = await request.post('/api/refunds/', {
      data: { booking: fx.bookingId, amount: 50000, reason: 'cancellation', refund_method: 'bank_transfer' },
      headers: { 'X-CSRFToken': token },
    });
    expect(rc.status()).toBe(400);
  });

  test('PAY-EC-11 — mark_bounced rejects non-numeric bounce_fee with 400', async ({ request }) => {
    // defect (spec §3): bounce_fee is not coerced → Decimal coercion raises → 500.
    const token = await login(request, 'admin');
    const fx = await seedFixture(request, token);

    const { payment: p } = await createApiPayment(request, token, {
      booking: fx.bookingId, amount: 100000, payment_date: '2026-08-01', payment_method: 'cash', payment_type: 'other',
    });

    const res = await request.post(`/api/payments/${p.id}/mark_bounced/`, { data: { bounce_fee: 'abc' }, headers: { 'X-CSRFToken': token } });
    // CORRECT: 400. Actual: 500.
    expect(res.status()).toBe(400);
  });

  test('PAY-EC-12 — Cheque method without cheque_number on update is rejected', async ({ request }) => {
    // defect (spec §3): PaymentSerializer (update) lacks cheque validation.
    const token = await login(request, 'admin');
    const fx = await seedFixture(request, token);

    const { payment: p } = await createApiPayment(request, token, {
      booking: fx.bookingId, amount: 100000, payment_date: '2026-08-01', payment_method: 'cash', payment_type: 'other',
    });

    const patch = await request.patch(`/api/payments/${p.id}/`, { data: { payment_method: 'cheque' }, headers: { 'X-CSRFToken': token } });
    // CORRECT: 400. Actual: 200.
    expect(patch.status()).toBe(400);
  });

  test('PAY-EC-13 — amount_in_words has no raw digits for very large sums', async ({ request }) => {
    // defect (spec §3): crore component >= 100 falls through to str(n) → "10000 Crore".
    const token = await login(request, 'admin');
    const fx = await seedFixture(request, token, { totalAmount: 100000000000 });

    const { payment: p } = await createApiPayment(request, token, {
      booking: fx.bookingId, amount: 100000000000, payment_date: '2026-08-01', payment_method: 'bank_transfer', payment_type: 'other',
    });
    await request.post(`/api/payments/${p.id}/verify/`, { headers: { 'X-CSRFToken': token }, maxRedirects: 0 });

    const receipt = (await findReceipts(request, p.id))[0];
    const html = await (await request.get(`/receipts/${receipt.id}/`)).text();
    // CORRECT: words line is full words. Actual: "Rupees 10000 Crore Only".
    expect(html).not.toContain('10000 Crore');
  });

  test('PAY-EC-14 — Reverse a payment with no installment', async ({ request }) => {
    const token = await login(request, 'admin');
    const fx = await seedFixture(request, token);

    const { payment: p } = await createApiPayment(request, token, {
      booking: fx.bookingId, amount: 200000, payment_date: '2026-08-01', payment_method: 'cash', payment_type: 'other',
    });
    await request.post(`/api/payments/${p.id}/verify/`, { headers: { 'X-CSRFToken': token }, maxRedirects: 0 });
    expect((await getBooking(request, fx.bookingId)).advance_paid).toBe('200000.00');

    const rr = await request.post(`/payments/${p.id}/reverse/`, { headers: { 'X-CSRFToken': token }, maxRedirects: 0 });
    expect(rr.status()).toBe(302);
    expect((await (await request.get(`/api/payments/${p.id}/`)).json()).status).toBe('reversed');
    expect((await getBooking(request, fx.bookingId)).advance_paid).toBe('0.00');
  });
});

// ================================================================================
// PAY-SEC — negative & security
// ================================================================================
test.describe('PAY-SEC', () => {
  test('PAY-SEC-01 — Sales and portal customer are denied the receipts API', async ({ request }) => {
    // CONFIRMED BUG: docs/qa/findings-confirmed.md F3 — ReceiptViewSet is IsAuthenticated (read-open).
    const token = await login(request, 'admin');
    const fx = await seedFixture(request, token);
    const { payment: p } = await createApiPayment(request, token, {
      booking: fx.bookingId, amount: 100000, payment_date: '2026-08-01', payment_method: 'cash', payment_type: 'other',
    });
    await request.post(`/api/payments/${p.id}/verify/`, { headers: { 'X-CSRFToken': token }, maxRedirects: 0 });
    const receipt = (await findReceipts(request, p.id))[0];

    await login(request, 'sales');
    const salesList = await request.get('/api/receipts/');
    const salesDetail = await request.get(`/api/receipts/${receipt.id}/`);

    await login(request, 'customer');
    const customerList = await request.get('/api/receipts/');

    // CORRECT: 403 for sales and customer. Actual: 200 with full receipt data.
    expect(salesList.status()).toBe(403);
    expect(salesDetail.status()).toBe(403);
    expect(customerList.status()).toBe(403);
  });

  test('PAY-SEC-02 — Finance roles may read; non-finance denied at decorator', async ({ request }) => {
    let token = await login(request, 'admin');
    const fx = await seedFixture(request, token);
    const { payment: p } = await createApiPayment(request, token, {
      booking: fx.bookingId, amount: 100000, payment_date: '2026-08-01', payment_method: 'cash', payment_type: 'other',
    });
    await request.post(`/api/payments/${p.id}/verify/`, { headers: { 'X-CSRFToken': token }, maxRedirects: 0 });
    const receipt = (await findReceipts(request, p.id))[0];

    await login(request, 'accounts');
    expect((await request.get(`/payments/${p.id}/`)).status()).toBe(200);
    expect((await request.get(`/receipts/${receipt.id}/`)).status()).toBe(200);
    expect((await request.get(`/receipts/${receipt.id}/pdf/`)).status()).toBe(200);

    await login(request, 'sales');
    const r1 = await request.get(`/payments/${p.id}/`, { maxRedirects: 0 });
    expect(r1.status()).toBe(302);
    expect(r1.headers()['location']).toContain('/dashboard/');
    expect((await request.get(`/receipts/${receipt.id}/`, { maxRedirects: 0 })).status()).toBe(302);
    expect((await request.get(`/receipts/${receipt.id}/pdf/`, { maxRedirects: 0 })).status()).toBe(302);
  });

  test('PAY-SEC-03 — Accounts cannot approve/process refunds via API', async ({ request }) => {
    // defect (spec §3): RefundViewSet only requires IsStaffReadAdminWrite → accounts approves via API.
    let token = await login(request, 'admin');
    const fx = await seedFixture(request, token);
    const { payment: p } = await createApiPayment(request, token, {
      booking: fx.bookingId, amount: 500000, payment_date: '2026-08-01', payment_method: 'cash', payment_type: 'down_payment',
    });
    await request.post(`/api/payments/${p.id}/verify/`, { headers: { 'X-CSRFToken': token }, maxRedirects: 0 });

    token = await login(request, 'accounts');
    const refund = await (await request.post('/api/refunds/', {
      data: { booking: fx.bookingId, amount: 100000, reason: 'cancellation', refund_method: 'bank_transfer' },
      headers: { 'X-CSRFToken': token },
    })).json();

    const approve = await request.post(`/api/refunds/${refund.id}/approve/`, { headers: { 'X-CSRFToken': token } });
    // CORRECT: 403. Actual: 200 (advance_paid reduced).
    expect(approve.status()).toBe(403);
  });

  test('PAY-SEC-04 — Accounts cannot mark_bounced a verified payment', async ({ request }) => {
    // defect (spec §3): mark_bounced has no role check and reverses verified payments.
    let token = await login(request, 'admin');
    const fx = await seedFixture(request, token);
    const { payment: p } = await createApiPayment(request, token, {
      booking: fx.bookingId, amount: 500000, payment_date: '2026-08-01', payment_method: 'cash', payment_type: 'down_payment',
    });
    await request.post(`/api/payments/${p.id}/verify/`, { headers: { 'X-CSRFToken': token }, maxRedirects: 0 });
    expect((await getBooking(request, fx.bookingId)).advance_paid).toBe('500000.00');

    token = await login(request, 'accounts');
    const res = await request.post(`/api/payments/${p.id}/mark_bounced/`, { data: { bounce_reason: 'insufficient funds' }, headers: { 'X-CSRFToken': token } });
    // CORRECT: 403. Actual: 200 + advance_paid reduced to 0.
    expect(res.status()).toBe(403);
  });

  test('PAY-SEC-05 — Customer profile PDF is denied for non-finance roles', async ({ request }) => {
    // CONFIRMED BUG: docs/qa/findings-confirmed.md F3 — @login_required only.
    const token = await login(request, 'admin');
    const customerId = await createCustomer(request, token, uniq());

    // sanity: the PDF generates for an authorized (authenticated) admin
    const adminRes = await request.get(`/customers/${customerId}/pdf/`);
    expect(adminRes.status()).toBe(200);
    expect(adminRes.headers()['content-type']).toContain('application/pdf');

    await login(request, 'sales');
    const salesRes = await request.get(`/customers/${customerId}/pdf/`, { maxRedirects: 0 });
    // CORRECT: denied (non-200). Actual: 200 PDF with PII.
    expect(salesRes.status()).not.toBe(200);
  });

  test('PAY-SEC-06 — Payment serializer masks sensitive fields for non-finance', async ({ request }) => {
    // defect (spec §3): IsStaffReadAdminWrite returns True for SAFE_METHODS → full serializer leaks.
    const token = await login(request, 'admin');
    const fx = await seedFixture(request, token);
    const { payment: p } = await createApiPayment(request, token, {
      booking: fx.bookingId, amount: 100000, payment_date: '2026-08-01',
      payment_method: 'bank_transfer', payment_type: 'other',
      method_data: { company_account_number: 'PK1234567890' }, notes: 'secret note',
    });

    await login(request, 'sales');
    const detail = await (await request.get(`/api/payments/${p.id}/`)).json();
    // CORRECT: method_data masked/omitted for non-finance. Actual: present.
    expect(detail.method_data).toBeUndefined();
  });

  test('PAY-SEC-07 — Sales is denied the web payments pages', async ({ request }) => {
    const token = await login(request, 'admin');
    const fx = await seedFixture(request, token);
    const { payment: p } = await createApiPayment(request, token, {
      booking: fx.bookingId, amount: 100000, payment_date: '2026-08-01', payment_method: 'cash', payment_type: 'other',
    });

    await login(request, 'sales');
    for (const url of ['/payments/', '/payments/create/', `/payments/${p.id}/`]) {
      const res = await request.get(url, { maxRedirects: 0 });
      expect(res.status()).toBe(302);
      expect(res.headers()['location']).toContain('/dashboard/');
    }
  });

  test.describe('refunds UI', () => {
    test.use({ storageState: 'tests/.auth/accounts.json' });

    test('PAY-SEC-08 — Refund approve/process buttons hidden for accounts', async ({ page, request }) => {
      // defect (spec §3): refunds.html renders buttons with no can_manage_users guard.
      const token = await login(request, 'admin');
      const fx = await seedFixture(request, token);

      const { payment: p } = await createApiPayment(request, token, {
        booking: fx.bookingId, amount: 100000, payment_date: '2026-08-01', payment_method: 'cash', payment_type: 'down_payment',
      });
      await request.post(`/api/payments/${p.id}/verify/`, { headers: { 'X-CSRFToken': token }, maxRedirects: 0 });

      // pending refund (renders Approve/Reject) + approved refund (renders Process)
      await request.post('/api/refunds/', { data: { booking: fx.bookingId, amount: 10000, reason: 'cancellation', refund_method: 'bank_transfer' }, headers: { 'X-CSRFToken': token } });
      const approved = await (await request.post('/api/refunds/', { data: { booking: fx.bookingId, amount: 20000, reason: 'overpayment', refund_method: 'cash' }, headers: { 'X-CSRFToken': token } })).json();
      await request.post(`/api/refunds/${approved.id}/approve/`, { form: { action: 'approve' }, headers: { 'X-CSRFToken': token }, maxRedirects: 0 });

      await page.goto('/refunds/');
      const pendingRow = page.getByRole('row', { name: new RegExp(fx.bookingApiId) }).filter({ hasText: 'Pending Approval' });
      const approvedRow = page.getByRole('row', { name: new RegExp(fx.bookingApiId) }).filter({ hasText: 'Approved' });

      // CORRECT: no Approve/Process buttons for accounts. Actual: visible (no guard).
      await expect(pendingRow.getByRole('button', { name: 'Approve' })).toHaveCount(0);
      await expect(approvedRow.getByRole('button', { name: 'Process' })).toHaveCount(0);
    });
  });
});

// ================================================================================
// PAY-API — API contract
// ================================================================================
test.describe('PAY-API', () => {
  test('PAY-API-01 — POST /api/payments/ creates a pending payment', async ({ request }) => {
    const token = await login(request, 'admin');
    const fx = await seedFixture(request, token);

    const { status, payment } = await createApiPayment(request, token, {
      booking: fx.bookingId, installment: fx.installmentId, amount: 200000, payment_date: '2026-08-01', payment_method: 'bank_transfer', payment_type: 'installment',
    });
    expect(status).toBe(201);
    expect(payment.status).toBe('pending');
    expect(payment.payment_id).toMatch(/^PAY-/);
    expect((await getBooking(request, fx.bookingId)).advance_paid).toBe('0.00');
    expect((await getInstallment(request, fx.installmentId!)).paid_amount).toBe('0.00');
    expect(await findReceipts(request, payment.id)).toHaveLength(0);

    // amount <= 0 → 400
    expect((await createApiPayment(request, token, {
      booking: fx.bookingId, amount: 0, payment_date: '2026-08-01', payment_method: 'cash', payment_type: 'other',
    })).status).toBe(400);

    // cheque without cheque_number/bank_name → 400
    expect((await createApiPayment(request, token, {
      booking: fx.bookingId, amount: 10000, payment_date: '2026-08-01', payment_method: 'cheque', payment_type: 'other',
    })).status).toBe(400);

    // installment of a different booking → 400
    const fx2 = await seedFixture(request, token);
    expect((await createApiPayment(request, token, {
      booking: fx.bookingId, installment: fx2.installmentId, amount: 10000, payment_date: '2026-08-01', payment_method: 'cash', payment_type: 'installment',
    })).status).toBe(400);
  });

  test('PAY-API-02 — GET /api/payments/ list + retrieve (any auth read)', async ({ request }) => {
    const token = await login(request, 'admin');
    const fx = await seedFixture(request, token);
    const { payment: p } = await createApiPayment(request, token, {
      booking: fx.bookingId, amount: 200000, payment_date: '2026-08-01', payment_method: 'bank_transfer', payment_type: 'installment',
    });

    await login(request, 'sales');
    const list = await request.get('/api/payments/');
    expect(list.status()).toBe(200);
    const detail = await request.get(`/api/payments/${p.id}/`);
    expect(detail.status()).toBe(200);

    // filters work
    const filtered = await (await request.get(`/api/payments/?status=pending&booking=${fx.bookingId}`)).json();
    expect(filtered.some((x: any) => x.id === p.id)).toBe(true);
  });

  test('PAY-API-03 — verify/reject action (role + status guard)', async ({ request }) => {
    let token = await login(request, 'admin');
    const fx = await seedFixture(request, token);
    const { payment: p } = await createApiPayment(request, token, {
      booking: fx.bookingId, installment: fx.installmentId, amount: 200000, payment_date: '2026-08-01', payment_method: 'bank_transfer', payment_type: 'installment',
    });

    // accounts → 403
    token = await login(request, 'accounts');
    const denied = await request.post(`/api/payments/${p.id}/verify/`, { data: { action: 'verify' }, headers: { 'X-CSRFToken': token } });
    expect(denied.status()).toBe(403);

    // admin (superuser) → 200 + financial effect once
    token = await login(request, 'admin');
    const ok = await request.post(`/api/payments/${p.id}/verify/`, { data: { action: 'verify' }, headers: { 'X-CSRFToken': token } });
    expect(ok.status()).toBe(200);
    expect((await getBooking(request, fx.bookingId)).advance_paid).toBe('200000.00');

    // second verify → status guard → 400
    const again = await request.post(`/api/payments/${p.id}/verify/`, { data: { action: 'verify' }, headers: { 'X-CSRFToken': token } });
    expect(again.status()).toBe(400);
    expect((await getBooking(request, fx.bookingId)).advance_paid).toBe('200000.00');
  });

  test('PAY-API-04 — mark_bounced does not reverse a verified payment via API', async ({ request }) => {
    // defect (spec §3): API reverses verified payments with no role check.
    const token = await login(request, 'admin');
    const fx = await seedFixture(request, token);
    const { payment: p } = await createApiPayment(request, token, {
      booking: fx.bookingId, amount: 500000, payment_date: '2026-08-01', payment_method: 'cash', payment_type: 'down_payment',
    });
    await request.post(`/api/payments/${p.id}/verify/`, { headers: { 'X-CSRFToken': token }, maxRedirects: 0 });
    expect((await getBooking(request, fx.bookingId)).advance_paid).toBe('500000.00');

    const res = await request.post(`/api/payments/${p.id}/mark_bounced/`, { data: { bounce_reason: 'insufficient funds' }, headers: { 'X-CSRFToken': token } });
    // CORRECT (per web parity): refused. Actual: 200, advance_paid reduced to 0.
    expect(res.status()).toBe(400);
  });

  test('PAY-API-05 — Refund create + approve/reject/process actions', async ({ request }) => {
    const token = await login(request, 'admin');
    const fx = await seedFixture(request, token);
    const { payment: p } = await createApiPayment(request, token, {
      booking: fx.bookingId, amount: 500000, payment_date: '2026-08-01', payment_method: 'cash', payment_type: 'down_payment',
    });
    await request.post(`/api/payments/${p.id}/verify/`, { headers: { 'X-CSRFToken': token }, maxRedirects: 0 });

    const r1 = await (await request.post('/api/refunds/', {
      data: { booking: fx.bookingId, amount: 100000, reason: 'cancellation', refund_method: 'bank_transfer' },
      headers: { 'X-CSRFToken': token },
    })).json();
    expect(r1.status).toBe('pending');

    // approve → reduces advance_paid once
    await request.post(`/api/refunds/${r1.id}/approve/`, { headers: { 'X-CSRFToken': token } });
    expect((await getBooking(request, fx.bookingId)).advance_paid).toBe('400000.00');

    // process → exactly one ledger row
    await request.post(`/api/refunds/${r1.id}/process/`, { headers: { 'X-CSRFToken': token } });
    expect((await (await request.get(`/api/refunds/${r1.id}/`)).json()).status).toBe('processed');
    expect(await countLedgerRefund(request, r1.id)).toBe(1);

    // reject on a second refund → no financial effect
    const r2 = await (await request.post('/api/refunds/', {
      data: { booking: fx.bookingId, amount: 100000, reason: 'overpayment', refund_method: 'cash' },
      headers: { 'X-CSRFToken': token },
    })).json();
    await request.post(`/api/refunds/${r2.id}/reject/`, { data: { notes: 'no' }, headers: { 'X-CSRFToken': token } });
    expect((await (await request.get(`/api/refunds/${r2.id}/`)).json()).status).toBe('rejected');
    expect((await getBooking(request, fx.bookingId)).advance_paid).toBe('400000.00');
  });

  test('PAY-API-06 — GET /api/receipts/ unauthenticated denied, sales denied', async ({ request }) => {
    // Unauthenticated check first — the per-test `request` fixture starts with no session.
    const anon = await request.get('/api/receipts/', { maxRedirects: 0 });
    expect([401, 403]).toContain(anon.status());

    const token = await login(request, 'admin');
    const fx = await seedFixture(request, token);
    const { payment: p } = await createApiPayment(request, token, {
      booking: fx.bookingId, amount: 100000, payment_date: '2026-08-01', payment_method: 'cash', payment_type: 'other',
    });
    await request.post(`/api/payments/${p.id}/verify/`, { headers: { 'X-CSRFToken': token }, maxRedirects: 0 });

    // sales → should be 403 (finance data). Actual: 200 (IsAuthenticated).
    await login(request, 'sales');
    const sales = await request.get('/api/receipts/');
    expect(sales.status()).toBe(403);
  });

  test('PAY-API-07 — PATCH /api/refunds/{pk} note-only edit accepted', async ({ request }) => {
    // same defect as EC-04 (serializer double-counts self).
    const token = await login(request, 'admin');
    const fx = await seedFixture(request, token);
    const { payment: p } = await createApiPayment(request, token, {
      booking: fx.bookingId, amount: 100000, payment_date: '2026-08-01', payment_method: 'bank_transfer', payment_type: 'down_payment',
    });
    await request.post(`/api/payments/${p.id}/verify/`, { headers: { 'X-CSRFToken': token }, maxRedirects: 0 });

    const refund = await (await request.post('/api/refunds/', {
      data: { booking: fx.bookingId, amount: 100000, reason: 'cancellation', refund_method: 'bank_transfer' },
      headers: { 'X-CSRFToken': token },
    })).json();

    const patch = await request.patch(`/api/refunds/${refund.id}/`, { data: { notes: 'amended' }, headers: { 'X-CSRFToken': token } });
    // CORRECT: 200. Actual: 400 ("over refundable").
    expect(patch.status()).toBe(200);
  });

  test('PAY-API-08 — No reverse action on PaymentViewSet (web-only)', async ({ request }) => {
    const token = await login(request, 'admin');
    const fx = await seedFixture(request, token);
    const { payment: p } = await createApiPayment(request, token, {
      booking: fx.bookingId, amount: 100000, payment_date: '2026-08-01', payment_method: 'cash', payment_type: 'other',
    });

    // reverse is not a registered action → 404 (web-only; no 500).
    const res = await request.post(`/api/payments/${p.id}/reverse/`, { data: {}, headers: { 'X-CSRFToken': token } });
    expect(res.status()).toBe(404);
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
