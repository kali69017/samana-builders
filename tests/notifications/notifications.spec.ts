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
 * POST the manual-send form. The page must already be on /notifications/ so the CSRF token
 * can be read from the send-modal form (the only csrfmiddlewaretoken input on the page).
 */
async function postManual(page: Page, fields: Record<string, string>): Promise<void> {
  const csrf = await page.locator('input[name="csrfmiddlewaretoken"]').first().inputValue();
  await page.request.post('/notifications/send/', {
    form: { ...fields, csrfmiddlewaretoken: csrf },
    maxRedirects: 0,
  });
}

/**
 * Full manual-send round trip over HTTP. Returns the rendered /notifications/ HTML (which
 * consumes the one-time flash), so callers can assert on the flash without a slow page load.
 */
async function manualSendHtml(page: Page, fields: Record<string, string>): Promise<string> {
  await page.goto('/notifications/');
  await postManual(page, fields);
  return (await page.request.get('/notifications/')).text();
}

// ── Happy path ─────────────────────────────────────────────────────────────

test.describe('Notifications — HP', () => {
  test.describe('Notification Center + manual send (management)', () => {
    test.use({ storageState: 'tests/.auth/management.json' });

    test('NOTIF-HP-01 — Notification Center list renders stats and 100-row cap', async ({ page }) => {
      await page.goto('/notifications/');
      await expect(page.getByRole('heading', { name: 'Notification Center' })).toBeVisible();
      // Four stat cards render. (Exact DB-count agreement is covered by the Django suite;
      // here we assert the SHAPE: all four labels are present.)
      for (const label of ['Total Sent', 'Delivered', 'Pending', 'Failed']) {
        await expect(page.locator('.stat-label').filter({ hasText: label })).toHaveCount(1);
      }
      // The list renders as a table, or an empty-state when there are no logs yet.
      await expect(page.getByRole('table').or(page.getByText('No Notifications'))).toBeVisible();
    });

    test('NOTIF-HP-09 — SMS number normalization to 92XXXXXXXXXX', async ({ page }) => {
      // Observable via the manual SMS path: valid Pakistani formats normalize to a valid
      // mobile (SMSService.is_valid_mobile → True) so the send proceeds to the provider —
      // which is switched OFF for E2E (RUNBOOK §2), so the manual send records 'skipped'
      // and returns the disabled warning (was: "sent successfully via sms", the inflated
      // 'sent' contract fixed in feb2689). A non-Pakistani string normalizes to '' and is
      // rejected as invalid. (Subscriber digits are unique per run so the per-recipient
      // anti-spam throttle — 3 sends per address per day — never trips the fixture.)
      const s = ('0000000' + Math.floor(Math.random() * 1e7)).slice(-7);
      const validFormats = [`+92-300-${s}`, `0300-${s}`, `300${s}`, `+92 300 ${s}`];
      for (const phone of validFormats) {
        const html = await manualSendHtml(page, {
          recipient_name: 'QA Norm',
          recipient_contact: phone,
          channel: 'sms',
          subject: 'n',
          message: 'm',
        });
        expect(html).toContain('sms notifications are disabled on this deployment');
      }
      const invalid = await manualSendHtml(page, {
        recipient_name: 'QA Norm',
        recipient_contact: `abc-${tag()}`,
        channel: 'sms',
        subject: 'n',
        message: 'm',
      });
      expect(invalid).toContain('Invalid phone number');
    });

    test('NOTIF-HP-10 — Manual send (management) with email disabled is recorded skipped', async ({ page }) => {
      const name = `QA Manual ${tag()}`;
      const email = `qa-manual-${tag()}@example.com`;
      // FIXED (feb2689): email is switched OFF for E2E, so a manual email send records
      // 'skipped' and surfaces the disabled warning — it no longer claims a delivery
      // ("Notification sent successfully via email." was the inflated-'sent' contract).
      // (Posted via API like NOTIF-HP-09: the top-bar "Send Notification" button is
      // display:none at the test viewport, so the DOM-click path is not actionable.)
      // Contacts are MASKED for management (hardening), so the row is located by the
      // unique recipient name rather than the raw email.
      const html = await manualSendHtml(page, {
        recipient_name: name,
        recipient_contact: email,
        channel: 'email',
        subject: 'QA subject',
        message: 'QA message',
      });
      expect(html).toContain('email notifications are disabled on this deployment');
      await page.goto('/notifications/');
      const row = page.getByRole('row').filter({ hasText: name });
      await expect(row).toHaveCount(1);
      await expect(row.getByText('Skipped', { exact: true })).toHaveCount(1);
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
  test.describe('Notification Center filters + manual send (management)', () => {
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

    test('NOTIF-EC-03 — Disabled SMS recorded as skipped, not sent', async ({ page }) => {
      const name = `QA SMS ${tag()}`;
      const phone = randomPhone();
      await page.goto('/notifications/');
      await postManual(page, { recipient_name: name, recipient_contact: phone, channel: 'sms', subject: 'x', message: 'y' });
      await page.goto('/notifications/');
      // Located by the unique name: the contact is masked for management (hardening).
      const row = page.getByRole('row').filter({ hasText: name });
      await expect(row).toHaveCount(1);
      // SMSService.send returns (True, "SMS disabled") before any network call, so the
      // row must be 'skipped', never 'sent' (FIXED feb2689).
      await expect(row.getByText('Sent', { exact: true })).toHaveCount(0);
      await expect(row.getByText('Skipped', { exact: true })).toHaveCount(1);
    });

    test('NOTIF-EC-04 — WhatsApp no-op is recorded skipped, never "sent"', async ({ page }) => {
      const name = `QA WA ${tag()}`;
      const phone = randomPhone();
      await page.goto('/notifications/');
      await postManual(page, { recipient_name: name, recipient_contact: phone, channel: 'whatsapp', subject: 'x', message: 'y' });
      await page.goto('/notifications/');
      const row = page.getByRole('row').filter({ hasText: name });
      await expect(row).toHaveCount(1);
      // WhatsAppService.send builds a wa.me URL and returns (True, url) without any
      // delivery — recorded 'skipped' (providers off), never 'sent' (FIXED feb2689).
      await expect(row.getByText('Sent', { exact: true })).toHaveCount(0);
      await expect(row.getByText('Skipped', { exact: true })).toHaveCount(1);
    });

    test('NOTIF-EC-08 — customer_welcome type is not filterable in the UI', async ({ page }) => {
      await page.goto('/notifications/');
      // CONFIRMED BUG: docs/qa/findings-confirmed.md — the Type dropdown lists only 7 of the 8
      // TYPE_CHOICES and omits customer_welcome.
      await expect(page.getByRole('option', { name: 'Customer Welcome' })).toHaveCount(1); // RED (0)
    });

    test('NOTIF-EC-09 — Invalid (non-empty) phone → SMS failed, no exception', async ({ page }) => {
      const name = `QA Invalid ${tag()}`;
      const phone = `bad-${tag()}`; // non-empty, not a valid Pakistani mobile
      await page.goto('/notifications/');
      await postManual(page, { recipient_name: name, recipient_contact: phone, channel: 'sms', subject: 'x', message: 'y' });
      await page.goto('/notifications/');
      const row = page.getByRole('row').filter({ hasText: name });
      await expect(row).toHaveCount(1);
      // Correct behavior: SMS fails gracefully for an invalid number (returned, never raised).
      await expect(row.getByText('Failed', { exact: true })).toHaveCount(1); // PASS
      // WhatsApp does not validate the phone (NOTIF-EC-04); its 'sent' row needs a customer
      // with a payment trigger and is not browser-observable here.
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
  test.describe('Manual send abuse (management)', () => {
    test.use({ storageState: 'tests/.auth/management.json' });

    test('NOTIF-SEC-01 — Manual send has no rate limiting + arbitrary recipient (spam blast)', async ({ page }) => {
      await page.goto('/notifications/');
      const csrf = await page.locator('input[name="csrfmiddlewaretoken"]').first().inputValue();
      const form = {
        recipient_name: 'Spam',
        recipient_contact: `victim-${tag()}@example.com`,
        channel: 'email',
        subject: 'spam',
        message: 'spam',
        csrfmiddlewaretoken: csrf,
      };
      // Spec uses 100; 10 is enough to demonstrate the absence of any throttle.
      const statuses: number[] = [];
      for (let i = 0; i < 10; i++) {
        const res = await page.request.post('/notifications/send/', { form, maxRedirects: 0 });
        statuses.push(res.status());
      }
      // CONFIRMED BUG: docs/qa/findings-confirmed.md — no rate limit / cooldown / quota; every
      // POST is accepted (302) and produces a 'general' row. Correct behavior bounds this.
      expect(statuses.filter((s) => s >= 400).length).toBeGreaterThan(0); // RED (all 302)
    });

    test('NOTIF-SEC-04 — EmailService.send does no address-format validation on the manual path', async ({ page }) => {
      await page.goto('/notifications/');
      await postManual(page, {
        recipient_name: 'QA',
        recipient_contact: 'not-an-email',
        channel: 'email',
        subject: 'x',
        message: 'y',
      });
      await page.goto('/notifications/');
      // CONFIRMED BUG: docs/qa/findings-confirmed.md — only a truthiness check; a malformed
      // address is accepted and reported "sent successfully" instead of rejected.
      await expect(page.getByText(/sent successfully/)).toHaveCount(0); // RED (success shown)
    });

    test('NOTIF-SEC-08 — Manual send missing required fields is rejected without a send', async ({ page }) => {
      await page.goto('/notifications/');
      await postManual(page, {
        recipient_name: 'QA',
        recipient_contact: '',
        channel: 'email',
        subject: '',
        message: '',
      });
      await page.goto('/notifications/');
      // Correct behavior: graceful error flash, no send, no row.
      await expect(page.getByText('Recipient contact and message are required.')).toBeVisible(); // PASS
    });
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

  test('NOTIF-SEC-06 — Non-management roles denied on both endpoints', async ({ request }) => {
    const denied: RoleName[] = ['sales', 'accounts', 'hr'];
    for (const role of denied) {
      const token = await loginViaApi(request, role);
      const getRes = await request.get('/notifications/', { maxRedirects: 0 });
      expect(getRes.status()).toBe(302);
      expect(getRes.headers()['location'] ?? '').toContain('/dashboard/');

      const postRes = await request.post('/notifications/send/', {
        headers: { 'X-CSRFToken': token },
        form: { recipient_name: 'QA', recipient_contact: 'x@example.com', channel: 'email', subject: 'x', message: 'y' },
        maxRedirects: 0,
      });
      expect(postRes.status()).toBe(302);
      expect(postRes.headers()['location'] ?? '').toContain('/dashboard/');
    }
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

      // Unauthenticated POST is rejected before the view runs (CSRF middleware returns 403;
      // some setups 302 to login). Either way no row is created anonymously.
      const postRes = await page.request.post('/notifications/send/', { maxRedirects: 0 });
      expect([302, 403]).toContain(postRes.status());
    });
  });
});
