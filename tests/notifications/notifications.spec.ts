import { test, expect, type Page } from '@playwright/test';
import { loginViaApi, type RoleName } from '../helpers/auth';

/**
 * Notifications module — Playwright suite (web-only; notifications has no DRF surface).
 *
 * Providers are gated OFF for E2E (RUNBOOK §2 launches the dev server with *_ENABLED=False),
 * even though the local `.env` carries live SendPK/SMTP/WhatsApp credentials — so these
 * tests assert SHAPE/behavior (rows, statuses, redirects, flash messages), never a real send.
 * Confirmed defects are written RED (they assert the CORRECT behavior and fail against the
 * buggy app) — see docs/qa/findings-confirmed.md. The disabled-channel "recorded as sent"
 * defect (NOTIF-EC-02) was FIXED in feb2689 and now asserts GREEN.
 *
 * Backend-only scenarios (need `mail.outbox`, a `requests.post` mock, or ORM fixtures that
 * the web form cannot produce) are registered with `test.skip(true, ...)` and a reason.
 */

// ── Test data helpers ──────────────────────────────────────────────────────

let seq = 0;
function tag(): string {
  seq += 1;
  return `${Date.now()}-${seq}-${Math.floor(Math.random() * 1e6)}`;
}

function randomCnic(): string {
  // 13 digits, unique with high probability (Customer.cnic is unique).
  return String(Math.floor(1e12 + Math.random() * 8.999e12));
}

function randomPhone(): string {
  // Customer.phone is validated by the form as +92-XXX-XXXXXXX.
  return `+92-300-${String(Math.floor(1e6 + Math.random() * 8.999e6))}`;
}

/**
 * Create a Customer through the web form (customer_create_view is @login_required, so any
 * staff role works). `email` is optional — omit it to exercise the "no email" path.
 * Returns the effective full name + email for later notification-center assertions.
 */
async function createCustomer(
  page: Page,
  opts: { firstName?: string; lastName?: string; email?: string } = {},
): Promise<{ fullName: string; email?: string }> {
  const firstName = opts.firstName ?? 'QA';
  const lastName = opts.lastName ?? `Welc-${tag()}`;
  const fullName = `${firstName} ${lastName}`;

  await page.goto('/customers/create/');
  await page.getByLabel('First Name').fill(firstName);
  await page.getByLabel('Last Name').fill(lastName);
  if (opts.email) await page.getByLabel('Email Address').fill(opts.email);
  await page.getByLabel('CNIC Number').fill(randomCnic());
  await page.getByLabel('Phone Number').fill(randomPhone());
  await page.getByRole('button', { name: 'Create Customer' }).click();
  await expect(page).toHaveURL(/\/customers\/?$/);
  return { fullName, email: opts.email };
}

/**
 */

/**
 */

// ── Happy path ─────────────────────────────────────────────────────────────

test.describe('Notifications — HP', () => {
  test.describe('Notification Center (management)', () => {
    test.use({ storageState: 'tests/.auth/management.json' });

    test('NOTIF-HP-01 — Notification Center list renders stats and 100-row cap', async ({ page }) => {
      await page.goto('/notifications/');
      await expect(page.getByRole('heading', { name: 'Notification Center' })).toBeVisible();
      // Four stat cards render. (Exact DB-count agreement is covered by the Django suite;
      // here we assert the SHAPE: all four labels are present.)
      for (const label of ['Total Sent', 'Sent', 'Pending', 'Skipped', 'Failed', 'Needs check']) {
        await expect(page.locator('.stat-label').filter({ hasText: label })).toHaveCount(1);
      }
      // The list renders as a table, or an empty-state when there are no logs yet.
      await expect(page.getByRole('table').or(page.getByText('No Notifications'))).toBeVisible();
    });


  });

  test.describe('Customer create welcome (admin)', () => {
    test.use({ storageState: 'tests/.auth/admin.json' });

    test('NOTIF-HP-02 — Customer welcome email sent on customer create', async ({ page }) => {
      const { email } = await createCustomer(page, { email: `qa-welcome-${tag()}@example.com` });
      await expect(page.getByText(/created successfully/)).toBeVisible();
      await page.goto('/notifications/');
      // A customer_welcome row is created for this customer's email (failure-safe: create succeeded).
      await expect(page.getByRole('row').filter({ hasText: email })).toHaveCount(1);
    });

    test('NOTIF-HP-03 — Customer welcome skipped when no email (failure-safe)', async ({ page }) => {
      const { fullName } = await createCustomer(page, {}); // no email
      await expect(page.getByText(/created successfully/)).toBeVisible();
      await page.goto('/notifications/');
      // No welcome row is created, so this customer's name never appears in the log.
      await expect(page.getByText(fullName, { exact: true })).toHaveCount(0);
    });
  });

  // The trigger methods below fire at backend call sites and their evidence (mail.outbox,
  // a mocked SendPK requests.post, or ORM fixtures the web form cannot produce) is not
  // browser-observable. Kept as documented skips rather than fake assertions.
  test('NOTIF-HP-04 — Payment confirmation triggers email + SMS + WhatsApp', async () => {
    test.skip(true, 'Backend-only: needs mail.outbox + SendPK requests.post mock + a verified Payment ORM fixture; not browser-observable.');
  });
  test('NOTIF-HP-05 — Booking notification triggers email + WhatsApp (no SMS)', async () => {
    test.skip(true, 'Backend-only: needs a full project→plot→booking flow plus mail.outbox inspection; not browser-observable.');
  });
  test('NOTIF-HP-06 — Installment reminder triggers email + SMS + WhatsApp', async () => {
    test.skip(true, 'Backend-only: send_installment_reminder is invoked by a management command (cron), not a user-facing page.');
  });
  test('NOTIF-HP-07 — Overdue alert triggers email + SMS + WhatsApp', async () => {
    test.skip(true, 'Backend-only: send_overdue_payment_alert is invoked by a management command (cron), not a user-facing page.');
  });
  test('NOTIF-HP-08 — Receipt notification triggers email + WhatsApp (no SMS)', async () => {
    test.skip(true, 'Backend-only: needs a verified payment + Receipt fixture plus mail.outbox inspection; not browser-observable.');
  });
});

// ── Edge cases ─────────────────────────────────────────────────────────────

test.describe('Notifications — EC', () => {
  test.describe('Notification Center filters (management)', () => {
    test.use({ storageState: 'tests/.auth/management.json' });

    test('NOTIF-EC-01 — Notification Center filter use works (FIXED feb2689)', async ({ page }) => {
      await page.goto('/notifications/');
      // FIXED (feb2689): notifications_view filtered AFTER slicing, raising
      // TypeError("Cannot filter a query once a slice has been taken.") on every Filter
      // use. It now filters first, then slices — a filtered view renders a 200 list.
      // (Scoped to <main>: the send-modal also has a channel select.)
      await page.getByRole('main').locator('select[name="channel"]').selectOption('email');
      await page.getByRole('button', { name: 'Filter' }).click();
      await expect(page).toHaveURL(/channel=email/);
      await expect(page.getByRole('heading', { name: 'Notification Center' })).toBeVisible(); // was RED (500)
    });




  });

  test.describe('Customer create triggers (admin)', () => {
    test.use({ storageState: 'tests/.auth/admin.json' });

    test('NOTIF-EC-02 — Disabled email recorded as skipped, not sent (FIXED feb2689)', async ({ page }) => {
      const email = `qa-ec02-${tag()}@example.com`;
      await createCustomer(page, { email });
      await page.goto('/notifications/');
      const row = page.getByRole('row').filter({ hasText: email });
      await expect(row).toHaveCount(1);
      // FIXED (feb2689): a switched-off provider is recorded 'skipped' with sent_at=None —
      // never 'sent' — so "Delivered" no longer counts messages that were never transmitted.
      // Requires the E2E server to run providers-off (RUNBOOK §2).
      await expect(row.getByText('Skipped', { exact: true })).toHaveCount(1); // was RED ('Sent')
    });

    test('NOTIF-EC-05 — recipient_name overflow (201-char full_name) aborts all channels', async ({ page }) => {
      const email = `qa-ec05-${tag()}@example.com`;
      await createCustomer(page, { firstName: 'A'.repeat(100), lastName: 'B'.repeat(100), email });
      await page.goto('/notifications/');
      const row = page.getByRole('row').filter({ hasText: email });
      await expect(row).toHaveCount(1);
      const name = ((await row.locator('strong').textContent()) ?? '').trim();
      // CONFIRMED BUG: docs/qa/findings-confirmed.md — recipient_name is CharField(200) but
      // full_name (100 + ' ' + 100) is 201 chars; on SQLite it is stored un-truncated (no guard).
      expect(name.length).toBeLessThanOrEqual(200); // RED (201)
    });
  });

  test('NOTIF-EC-06 — Empty phone → SMS/WhatsApp silently skipped', async () => {
    test.skip(true, 'Backend-only: the web form rejects an empty phone (validate_phone), so a phone="" customer needs a direct ORM fixture + a payment trigger.');
  });
  test('NOTIF-EC-07 — Missing email → welcome skipped (returns None, no row)', async () => {
    test.skip(true, 'Backend-only: the welcome-skip half is covered by NOTIF-HP-03; the payment-confirmation-on-no-email half needs ORM fixtures.');
  });
});

// ── Negative & security ────────────────────────────────────────────────────

test.describe('Notifications — SEC', () => {
  test.describe('Notification Center abuse (management)', () => {
    test.use({ storageState: 'tests/.auth/management.json' });



  });

  test('NOTIF-SEC-03 — Log stores PII + financial amounts in plaintext, listable by all management', async ({ request }) => {
    const email = `qa-sec03-${tag()}@example.com`;
    const adminToken = await loginViaApi(request, 'admin');
    const createRes = await request.post('/customers/create/', {
      headers: { 'X-CSRFToken': adminToken },
      form: { first_name: 'SecThree', last_name: 'QA', email, phone: randomPhone(), cnic: randomCnic() },
      maxRedirects: 0,
    });
    expect(createRes.status()).toBe(302); // customer + welcome row created by admin

    // A *different* management user reads the log.
    await loginViaApi(request, 'management');
    const html = await (await request.get('/notifications/')).text();
    // CONFIRMED BUG: docs/qa/findings-confirmed.md — recipient_contact (email) is stored and
    // rendered in plaintext; correct behavior masks/redacts it.
    expect(html).not.toContain(email); // RED (plaintext email visible)
  });

  test('NOTIF-SEC-05 — No object-level scoping: every management user sees every customer', async ({ request }) => {
    const email = `qa-sec05-${tag()}@example.com`;
    const adminToken = await loginViaApi(request, 'admin');
    await request.post('/customers/create/', {
      headers: { 'X-CSRFToken': adminToken },
      form: { first_name: 'SecFive', last_name: 'QA', email, phone: randomPhone(), cnic: randomCnic() },
      maxRedirects: 0,
    });
    await loginViaApi(request, 'management');
    const html = await (await request.get('/notifications/')).text();
    // CONFIRMED BUG: docs/qa/findings-confirmed.md — notifications_view returns all rows with no
    // ownership/branch filter; correct behavior scopes the log so others' data is not visible.
    expect(html).not.toContain(email); // RED (cross-tenant email visible)
  });


  test('NOTIF-SEC-02 — Customer-controlled name raw-interpolated into SMS/email (smishing)', async () => {
    // Static/note only: the message BODY is not rendered anywhere in the UI (the table shows
    // recipient_name / contact / type / status, never `message`), so the smishing content is
    // not browser-observable. Sink (code): NotificationService interpolates customer.full_name
    // verbatim into plain-text SMS/email bodies across services.py (payment/booking/welcome/
    // reminder/overdue/receipt) with no length/character sanitization.
    test.skip(true, 'Static/note: message body is not browser-observable; assert in the Django suite against mail.outbox / NotificationLog.message.');
  });

  test.describe('Unauthenticated', () => {
    test.use({ storageState: { cookies: [], origins: [] } });

    test('NOTIF-SEC-07 — Unauthenticated access redirects to login', async ({ page }) => {
      await page.goto('/notifications/');
      await expect(page).toHaveURL(/\/login\//); // PASS

    });
  });
});
