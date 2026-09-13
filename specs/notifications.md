# Notifications — Test Plan

> Module: `notifications/` (Email / SMS / WhatsApp + `NotificationLog`).
> Companion analysis: `docs/qa/notifications_analysis.md`. Shared facts (roles, decorators, URL map, money semantics) are in `docs/qa/_shared-context.md` and are not re-derived here.
> Scenario IDs here are the Phase C test-name contract: automated tests MUST be named `<ID>_<slug>` (e.g. `NOTIF-EC-01_filter_500`).

## 1. Scope & roles

This plan covers the outbound messaging layer: the `NotificationLog` record, the three channel services (`EmailService`, `SMSService`, `WhatsAppService`), the `NotificationService` facade and its trigger methods (customer welcome, payment confirmation, booking notification, installment reminder, overdue alert, receipt notification), and the two web endpoints (the Notification Center list and the manual-send form). It also covers the failure-safety contract (a broken channel must never break the underlying customer/payment/booking transaction) and the PII/injection/abuse exposure of the log and manual endpoint.

**Roles that exercise it (allowed):** `super_admin`, `admin`, `management` — enforced by `@management_or_above` on both web views.
**Roles expected to be DENIED:** `accounts`, `sales`, `hr`, `project_manager`, `contractor`, `staff` (redirect to `/dashboard/` with an error message); unauthenticated requests redirect to `/login/`.

The automated trigger methods (welcome / payment / booking / reminder / overdue / receipt) have **no user-facing endpoint** and are exercised by calling their call sites in `core/views.py`, `core/views_crm.py`, `core/api_views.py`, `customers/api_views.py`, `bookings/api_views.py`, and the management commands.

**API surface note (web-only, no DRF):** `notifications` has **no DRF ViewSet** and no `/api/notifications/` route — it is invoked programmatically from other apps' ViewSets. The only HTTP routes (from `notifications/urls.py`) are:

| Method + path | View | Permission | Request fields | Response |
|---|---|---|---|---|
| GET `/notifications/` | `notifications_view` | `management_or_above` | optional `channel`, `type`, `status` query params | HTML list (100-row cap; filters — but see `NOTIF-EC-01`) |
| POST `/notifications/send/` | `send_manual_notification` | `management_or_above` | `recipient_name`, `recipient_contact` (required), `channel` (email|sms|whatsapp), `subject`, `message` | 302 redirect to `/notifications/` with success/error flash |

Because there is no DRF surface, there are **no `NOTIF-API-*` scenarios** in this plan.

**Known UI labeling defect (folded into `NOTIF-EC-02`):** the "Total Sent" stat card renders `total_count` (all rows, including `failed` and `pending`), while "Delivered" renders `sent_count`. The labels are misleading and are asserted alongside the "disabled channel counted as sent" defect.

## 2. Preconditions & fixtures

**URLs (relative to `http://127.0.0.1:8000`):**
- `/notifications/` — Notification Center list + filters.
- `/notifications/send/` — manual-send POST target.
- `/login/` — default login `admin` / `admin123`.
- Call-site pages (for UI-driven trigger tests): `/customers/create/`, `/bookings/`, `/payments/` (verify/payment-create), `/portal/`.

**Environment:**
- Run with `DJANGO_DEBUG=True` (otherwise `SECURE_SSL_REDIRECT` 301s every request and the suite mass-fails).
- Email tests use `EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'` and assert against `mail.outbox`.
- SMS tests mock `notifications.services.requests.post` (return `{'success':'true','results':[{'status':'OK','messageid':'6502124'}]}`) and use `@override_settings(SENDPK_ENABLED=True/False)`, `EMAIL_ENABLED=True/False` to assert gating and network-vs-no-network.

**Seed data (create cleanly, all unique + timestamped):**
- `Customer` requires `first_name`, `last_name`, `cnic` (unique), `phone` (non-null, no default → use `''` for "no phone"), `email` (unique, `blank=True/null=True`), `created_by`. Variants needed:
  - `EMAIL_AND_PHONE`: email + phone `+92-300-1234567`.
  - `NO_EMAIL`: `email=None`, phone set.
  - `NO_PHONE`: email set, `phone=''`.
  - `INVALID_PHONE`: email set, `phone='abc123'` (non-empty, invalid).
  - `LONG_NAME`: `first_name` = 100×'A', `last_name` = 100×'B' → `full_name` = 201 chars.
  - `MALICIOUS_NAME`: `first_name` = `https://evil.example/pay?`, `last_name` = `line2` (URL + content suitable for smishing).
- `Project` → `Plot` (needs `plot_number`, `project`, `size_marla`, `price`) → `Booking` (`customer`, `plot`, `total_amount`, `advance_paid`, `status`, `created_by`).
- `InstallmentPlan` on the booking + `auto_generate()` to obtain numbered `Installment` rows (for reminder/overdue triggers).
- `Payment` with `status='verified'`, `payment_type='installment'`, `payment_method='cash'` (for confirmation/receipt triggers). A `Receipt` for receipt-notification.
- Role fixtures: one user per role via `UserProfile` (`super_admin`, `admin`, `management`, `accounts`, `sales`, `staff`); confirm a Django `is_superuser` is treated as `super_admin`.

## 3. Scenario catalog

### HP — Happy path

#### NOTIF-HP-01 — Notification Center list renders stats and 100-row cap
- **Preconditions:** management user logged in; at least one `NotificationLog` row exists.
- **Steps:** 1. Log in as management. 2. GET `/notifications/`. 3. Inspect page.
- **Expected result:** HTTP 200. Table lists up to the 100 most recent rows (`-created_at`). Four stat cards render: Total Sent = `total_count`, Delivered = `sent_count` (`status='sent'`), Pending = `pending_count`, Failed = `failed_count`, each matching `NotificationLog.objects.count()` / the `status`-filtered counts.
- **Evidence on failure:** non-200 status; a stat number that disagrees with the DB count; rows missing or out of order.

#### NOTIF-HP-02 — Customer welcome email sent on customer create
- **Preconditions:** `EMAIL_ENABLED=True`; locmem email backend; `EMAIL_AND_PHONE`-style customer (email present).
- **Steps:** 1. As a sales-and-above user, create the customer via the web form (or call the create view). 2. Check `mail.outbox` and `NotificationLog`.
- **Expected result:** customer is created. Exactly one `NotificationLog` row: `channel='email'`, `notification_type='customer_welcome'`, `status='sent'`, `recipient_contact` = customer email, `related_customer_id` = `CUS-…`. One email in `mail.outbox` with subject "Welcome to Samana Builders & Developers".
- **Evidence on failure:** no log row; no outbox entry; wrong channel/type; customer-create rolled back (violates failure-safety).

#### NOTIF-HP-03 — Customer welcome skipped when no email (failure-safe)
- **Preconditions:** `NO_EMAIL`-style customer (`email=None` or `''`).
- **Steps:** 1. Create the customer via web form (or create view). 2. Check `NotificationLog` and `mail.outbox`.
- **Expected result:** customer is created with no error. **No** `customer_welcome` row; **no** outbox entry. No exception escapes to the user.
- **Evidence on failure:** a `customer_welcome` row created with an empty contact; an unhandled exception/500 on customer create.

#### NOTIF-HP-04 — Payment confirmation triggers email + SMS + WhatsApp
- **Preconditions:** `EMAIL_ENABLED=True`, `SENDPK_ENABLED=True` with `requests.post` mocked OK; customer with email **and** phone; a verified payment.
- **Steps:** 1. Record/verify the payment (trigger `send_payment_confirmation`). 2. Inspect `NotificationLog`.
- **Expected result:** three rows, all `notification_type='payment_confirmation'`: `email` (full message), `sms` (concise message, `provider_message_id='6502124'`), `whatsapp`. `related_booking_id` set; email row's `subject` = "Payment Confirmation - PAY-…". SMS message contains "payment of Rs. … received" and "Remaining".
- **Evidence on failure:** fewer than three rows; SMS row carrying the long email body (concise-message switch broken); missing `provider_message_id`.

#### NOTIF-HP-05 — Booking notification triggers email + WhatsApp (no SMS)
- **Preconditions:** customer with email + phone; `send_booking_notification` call site reached by creating a booking.
- **Steps:** 1. Create a booking. 2. Inspect `NotificationLog`.
- **Expected result:** two rows, `notification_type='booking_notification'`: `email` and `whatsapp`. **No** `sms` row (booking path appends only `whatsapp`, never `sms`).
- **Evidence on failure:** an unexpected `sms` row; missing `whatsapp`.

#### NOTIF-HP-06 — Installment reminder triggers email + SMS + WhatsApp
- **Preconditions:** booking with installment plan + generated installments; customer with email + phone.
- **Steps:** 1. Invoke `send_installment_reminder(installment)`. 2. Inspect rows.
- **Expected result:** three rows, `notification_type='installment_reminder'`; SMS uses the concise message ("installment #N … due on …"); email has subject "Installment Reminder - Installment #N".
- **Evidence on failure:** wrong channel set; wrong subject/body.

#### NOTIF-HP-07 — Overdue alert triggers email + SMS + WhatsApp
- **Preconditions:** an overdue installment (past due date, `status='overdue'`); customer with email + phone.
- **Steps:** 1. Invoke `send_overdue_payment_alert(installment)`. 2. Inspect rows.
- **Expected result:** three rows, `notification_type='overdue_payment'`; subject "OVERDUE: Installment #N"; SMS message contains "OVERDUE" and "Outstanding: Rs. …".
- **Evidence on failure:** wrong type/subject; missing SMS/WhatsApp.

#### NOTIF-HP-08 — Receipt notification triggers email + WhatsApp (no SMS)
- **Preconditions:** verified payment with a generated `Receipt`; customer with email + phone.
- **Steps:** 1. Invoke `send_receipt_notification(receipt)`. 2. Inspect rows.
- **Expected result:** two rows, `notification_type='receipt_notification'`: `email` and `whatsapp`. **No** `sms` row.
- **Evidence on failure:** unexpected `sms` row; missing `whatsapp`.

#### NOTIF-HP-09 — SMS number normalization to 92XXXXXXXXXX
- **Preconditions:** none (pure unit test on `SMSService`).
- **Steps:** call `SMSService.normalize_phone` with `+92-300-1234567`, `0300-1234567`, `3001234567`, `+92 300 1234567`, `''`, `None`, and `is_valid_mobile` on each.
- **Expected result:** `923001234567` for the first four; `''` for empty/None; `is_valid_mobile` True only for inputs normalizing to a 12-digit `92…`.
- **Evidence on failure:** wrong normalization; a non-Pakistani number accepted; an empty/None input crashing.

#### NOTIF-HP-10 — Manual send (management) delivers a general email
- **Preconditions:** management user logged in; `EMAIL_ENABLED=True`; locmem backend.
- **Steps:** 1. GET `/notifications/`, open the Send Notification modal. 2. Fill recipient name, a valid contact email, channel=email, subject, message. 3. Submit (POST `/notifications/send/`).
- **Expected result:** 302 to `/notifications/` with a success flash. One `NotificationLog` row: `notification_type='general'`, `channel='email'`, `status='sent'`, `created_by` = the user. One outbox email.
- **Evidence on failure:** no row; failure flash; wrong type/channel; `created_by` null.

### EC — Edge cases / boundaries

#### NOTIF-EC-01 — Filter use on Notification Center 500s (sliced queryset) — PRIORITY
- **Preconditions:** management user; at least one `NotificationLog` row; `DEBUG=True`.
- **Steps:** 1. GET `/notifications/`. 2. Select any `channel` (e.g. Email) and click Filter (or GET `/notifications/?channel=email`). Repeat for `type` and `status`, singly and combined.
- **Expected result:** HTTP 200 with the list filtered to the selected channel/type/status.
- **Actual (bug):** HTTP 500 — `notifications_view` slices first (`NotificationLog.objects.all()[:100]`) then calls `.filter(...)`, and Django raises `TypeError: Cannot filter a query once a slice has been taken.` at `notifications/views.py:17` (and 19/21). Every use of the Filter button 500s.
- **Evidence on failure:** Django debug page / server log showing the `TypeError`; a 200 with an unfiltered list also counts as a fail (filter silently dropped).

#### NOTIF-EC-02 — Disabled email recorded as `sent` (inflates "Delivered")
- **Preconditions:** `EMAIL_ENABLED=False`; customer with email.
- **Steps:** 1. Create the customer (welcome trigger). 2. Inspect the resulting row and the stats.
- **Expected result:** the message is not actually delivered, so it should be recorded as `skipped`/`failed` with a clear reason — and the "Delivered" stat must not count it.
- **Actual (bug):** `EmailService.send` returns `(True, "Email disabled")`, so the row is `status='sent'`, `error_message='Email disabled'`. The Notification Center "Delivered" card counts a message that was never sent. Note the "Total Sent" card actually shows `total_count`, so both labels are misleading.
- **Evidence on failure:** a `sent` row whose `error_message` is "Email disabled"; `sent_count` incrementing with `mail.outbox` empty.

#### NOTIF-EC-03 — Disabled SMS recorded as `sent`
- **Preconditions:** `SENDPK_ENABLED=False`; `requests.post` mocked to raise if called; customer with phone; verified payment.
- **Steps:** 1. Trigger `send_payment_confirmation`. 2. Assert `requests.post` was never called and inspect the `sms` row.
- **Expected result:** SMS not delivered; should be a `skipped`/`failed` outcome with no network call.
- **Actual (bug):** `SMSService.send` returns `(True, "SMS disabled")` before any POST, so the row is `status='sent'`, `error_message='SMS disabled'`, counted as Delivered.
- **Evidence on failure:** `requests.post` called (network hit while disabled) or a `sent` row with "SMS disabled".

#### NOTIF-EC-04 — WhatsApp is a no-op that always "succeeds"; URL never persisted — PRIORITY
- **Preconditions:** customer with phone; verified payment (or any phone-bearing trigger).
- **Steps:** 1. Trigger a notification. 2. Inspect the `whatsapp` row and grep the DB for `wa.me`.
- **Expected result:** either the `wa.me` click-to-chat URL is persisted/used, or the row is recorded as a non-delivery.
- **Actual (bug):** `WhatsAppService.send` only builds the URL and `logger.info`s it, returning `(True, url)` — no network, no delivery. `send_notification` stores the raw `message`, not the URL, so the row is `status='sent'` while no customer ever receives anything, and the URL is nowhere in the DB.
- **Evidence on failure:** a `whatsapp` row with `status='sent'`; grep of `message`/`error_message` shows no `wa.me`; log shows only "WhatsApp message prepared".

#### NOTIF-EC-05 — `recipient_name` overflow (201-char full_name) aborts all channels
- **Preconditions:** `LONG_NAME` customer (201-char `full_name`). For the DataError to surface, run against **PostgreSQL** (SQLite does not enforce `varchar(200)` at the DB layer — see expected result).
- **Steps:** 1. Trigger a multi-channel send (payment confirmation). 2. Inspect `NotificationLog` and the transaction outcome.
- **Expected result:** the name should be truncated/sanitized to ≤200 chars and all channels delivered.
- **Actual (bug):** `NotificationLog.recipient_name` is `CharField(200)` but `full_name` = `first_name(100) + " " + last_name(100)` = up to 201 chars. `NotificationLog.objects.create` in `send_notification` raises `DataError` ("value too long for type character varying(200)") on PostgreSQL; the exception aborts the loop, so **no** channel is logged for that event. In the welcome path it is swallowed (`send_customer_welcome` returns `None`); in the payment/booking paths it is swallowed at the call site, silently losing all notifications. On SQLite the 201-char value is stored silently (no error) — a separate defect (no length guard).
- **Evidence on failure:** PostgreSQL — `DataError` in logs and zero rows for the event; SQLite — a stored `recipient_name` longer than 200 with no error/truncation.

#### NOTIF-EC-06 — Empty phone → SMS/WhatsApp silently skipped
- **Preconditions:** `NO_PHONE` customer (`phone=''`); verified payment.
- **Steps:** 1. Trigger `send_payment_confirmation`. 2. Inspect rows.
- **Expected result:** exactly one row, `channel='email'`. No `sms` and no `whatsapp` rows (the `if customer.phone:` guard skips both). No exception.
- **Evidence on failure:** `sms`/`whatsapp` rows created with an empty contact; any raised exception.

#### NOTIF-EC-07 — Missing email → welcome skipped (returns None, no row)
- **Preconditions:** `NO_EMAIL` customer (`email=None`); also test a phone-bearing customer with `email=None` for non-welcome triggers.
- **Steps:** 1. Create the customer (welcome path) — assert no row and no exception. 2. Trigger a payment confirmation on the same customer — assert SMS + WhatsApp are still sent but **no** email row.
- **Expected result:** welcome returns `None` with no `customer_welcome` row; for other triggers the `if contact:` guard skips email but sends `sms` + `whatsapp`.
- **Evidence on failure:** an email row with `recipient_contact=''`; a crash from `.strip()`/`getattr` on a null email.

#### NOTIF-EC-08 — `customer_welcome` type is not filterable in the UI
- **Preconditions:** at least one `customer_welcome` row exists; management user.
- **Steps:** 1. GET `/notifications/`. 2. Inspect the "Type" `<select>` options.
- **Expected result:** the type dropdown lists all eight `TYPE_CHOICES`.
- **Actual (bug):** the dropdown (`templates/notifications/notifications.html`) lists only seven types and omits `customer_welcome`; welcome rows can only be reached via "All Types". (Attempting `?type=customer_welcome` manually additionally hits `NOTIF-EC-01`.)
- **Evidence on failure:** snapshot/HTML showing seven `<option>`s with no `customer_welcome`.

#### NOTIF-EC-09 — Invalid (non-empty) phone → SMS `failed`, WhatsApp still "sent", no exception
- **Preconditions:** `INVALID_PHONE` customer (`phone='abc123'`); verified payment.
- **Steps:** 1. Trigger `send_payment_confirmation`. 2. Inspect `sms` and `whatsapp` rows.
- **Expected result:** SMS row `status='failed'`, `error_message='Invalid phone number'` (returned, never raised); WhatsApp row still `status='sent'` (it never validates the phone — see `NOTIF-EC-04`). Parent transaction unaffected.
- **Evidence on failure:** an unhandled exception; SMS row marked `sent` for an invalid number.

### SEC — Negative & security

#### NOTIF-SEC-01 — Manual send has no rate limiting + arbitrary recipient (spam blast) — PRIORITY
- **Preconditions:** a `management`-role user (not superuser); `EMAIL_ENABLED=True`; locmem backend.
- **Steps:** 1. POST `/notifications/send/` with arbitrary `recipient_contact` (e.g. `victim@example.com`) and arbitrary message, repeatedly in a tight loop (e.g. 100×). 2. Observe there is no throttling, no CAPTCHA, no per-user quota.
- **Expected result:** abuse is bounded (rate limit / cooldown / allow-listed recipients / audit of high-volume sends).
- **Actual (bug):** `send_manual_notification` accepts any contact + message from any management user with no rate limiting; each POST produces a `general` log row and an outbox send. A compromised management account can blast arbitrary SMS/email to arbitrary numbers/addresses. The `channel` is client-supplied, so an SMS blast needs only a valid SendPK key.
- **Evidence on failure:** N POSTs → N `general` rows / N outbox entries with no rejection; a 4xx/429 never returned.

#### NOTIF-SEC-02 — Customer-controlled name raw-interpolated into SMS/email (smishing / URL injection) — PRIORITY
- **Preconditions:** `MALICIOUS_NAME` customer (name containing a URL and/or `\n` line break). Names reach customers via the corporate-site `lead_submit` → lead → customer conversion, so the value is attacker-influenced.
- **Steps:** 1. Create the customer with the hostile name. 2. Trigger a payment confirmation (and welcome). 3. Inspect the stored `message` on the `sms`/`email` rows and the outbox body.
- **Expected result:** customer-controlled name is sanitized/truncated/validated before interpolation (no URL, no injected line breaks, no smishing framing).
- **Actual (bug):** `customer.full_name` is interpolated verbatim into plain-text SMS and email bodies across `services.py` (payment/booking/welcome/reminder/overdue/receipt). No length/character sanitization beyond `CharField(100)` per field. An SMS such as "Dear https://evil.example/pay? …, your payment …" arrives from the SAMANA sender and reads as a phishing message; newlines allow body forging.
- **Evidence on failure:** the stored SMS/email message contains the unsanitized URL/newline; the brand sender carries attacker-chosen content.

#### NOTIF-SEC-03 — Log stores PII + financial amounts in plaintext, listable by all management
- **Preconditions:** rows produced by real triggers (payment confirmation, overdue alert) containing a customer phone/email and amounts; a second, unrelated `management` user.
- **Steps:** 1. As management user B, GET `/notifications/`. 2. Inspect the table and the underlying rows.
- **Expected result:** PII/amounts are redacted, masked, or access-restricted by ownership/need-to-know.
- **Actual (bug):** every `NotificationLog` row stores `recipient_contact` (email or phone) and `message` (payment amounts, remaining balances, installment amounts) in plaintext, searchable in admin and visible to any management user. No retention or redaction.
- **Evidence on failure:** management user B can read another customer's phone/email and financial amounts; admin search surfaces amounts.

#### NOTIF-SEC-04 — `EmailService.send` does no address-format validation on the manual path
- **Preconditions:** management user; `EMAIL_ENABLED=True`; locmem backend.
- **Steps:** 1. POST `/notifications/send/` with `channel=email` and `recipient_contact='not-an-email'` (or `'a b c'`, `'@',` `'x@'`). 2. Observe the flash and the resulting row.
- **Expected result:** malformed address rejected at input with a validation error and **no** send attempted.
- **Actual (bug):** `EmailService.send` only checks truthiness (`if not to_email`); there is no format validation on this path (SMS is validated via `is_valid_mobile`; email is not). The row is created regardless and the result depends on backend behavior (locmem silently "succeeds" → `sent`; a real SMTP backend would raise → caught → `failed`). Either way the address is never rejected as invalid.
- **Evidence on failure:** a `general` row accepted for a malformed address; no "invalid email" feedback to the user.

#### NOTIF-SEC-05 — No object-level scoping: every management user sees every customer's contact + amounts
- **Preconditions:** customers/logs created by/for customer A (owned by one sales/management context) and customer B; two management users with no shared ownership.
- **Steps:** 1. As management user X, GET `/notifications/`. 2. Confirm the full log (all customers, all channels, all amounts) is returned regardless of who created the underlying records.
- **Expected result:** log rows are scoped (branch/owner/creator) so a management user sees only what they should.
- **Actual (bug):** `notifications_view` returns `NotificationLog.objects.all()` with no ownership/branch filter; there is no object-level authorization on the log. Combined with `NOTIF-SEC-03`, this is a cross-tenant PII dump.
- **Evidence on failure:** user X sees rows for customers outside their remit; no filtering applied.

#### NOTIF-SEC-06 — Non-management roles denied on both endpoints
- **Preconditions:** users with roles `accounts`, `sales`, `staff` (and `hr`/`project_manager`/`contractor`), each logged in.
- **Steps:** 1. As each role, GET `/notifications/`. 2. POST `/notifications/send/` with valid fields.
- **Expected result:** both requests redirect to `/dashboard/` with an error message; **no** `NotificationLog` row is created; no message sent.
- **Evidence on failure:** a 200 list page or a created `general` row for a denied role.

#### NOTIF-SEC-07 — Unauthenticated access redirects to login
- **Preconditions:** no session.
- **Steps:** 1. GET `/notifications/`. 2. POST `/notifications/send/`.
- **Expected result:** 302 to `/login/` (with `next`), no row created.
- **Evidence on failure:** a 200/other non-redirect status; a row created anonymously.

#### NOTIF-SEC-08 — Manual send missing required fields is rejected without a send
- **Preconditions:** management user.
- **Steps:** 1. POST `/notifications/send/` with empty `recipient_contact`, and separately with empty `message`.
- **Expected result:** error flash ("Recipient contact and message are required."), 302 to `/notifications/`, **no** `NotificationLog` row, no send.
- **Evidence on failure:** a `general` row created for an empty contact/message; a 500 instead of a graceful redirect.

## 4. Data isolation rules

- All fixture values unique per test using a timestamp/nonce suffix (e.g. `cnic='11111-{ts}…'`, `email='qa-{ts}@example.com'`) because `Customer.cnic` and `Customer.email` are unique and `customer_id` is auto-incremented from the last numeric suffix.
- Scope `NotificationLog`/`Customer`/`Booking`/`Payment`/`Receipt` creation to the test's own `created_by` user and clean up in reverse dependency order (delete logs → payments → receipts → installments/plan → booking → plot → project → customer) or wrap in a transaction rollback.
- `Installment` is unique on `(plan, installment_number)` — always generate via `InstallmentPlan.auto_generate()`; never hand-craft.
- Provider/network must be mocked on every SMS/WhatsApp test: `patch('notifications.services.requests.post', …)`; `WhatsAppService` performs no network call, so assert its absence explicitly.
- Email asserts use `mail.outbox` (locmem) and are cleared between tests.

## 5. Coverage checklist

- NOTIF-HP-01 — Notification Center list renders stats and 100-row cap
- NOTIF-HP-02 — Customer welcome email sent on customer create
- NOTIF-HP-03 — Customer welcome skipped when no email (failure-safe)
- NOTIF-HP-04 — Payment confirmation triggers email + SMS + WhatsApp
- NOTIF-HP-05 — Booking notification triggers email + WhatsApp (no SMS)
- NOTIF-HP-06 — Installment reminder triggers email + SMS + WhatsApp
- NOTIF-HP-07 — Overdue alert triggers email + SMS + WhatsApp
- NOTIF-HP-08 — Receipt notification triggers email + WhatsApp (no SMS)
- NOTIF-HP-09 — SMS number normalization to 92XXXXXXXXXX
- NOTIF-HP-10 — Manual send (management) delivers a general email
- NOTIF-EC-01 — Filter use on Notification Center 500s (sliced queryset)
- NOTIF-EC-02 — Disabled email recorded as sent (inflates "Delivered")
- NOTIF-EC-03 — Disabled SMS recorded as sent
- NOTIF-EC-04 — WhatsApp is a no-op that always "succeeds"; URL never persisted
- NOTIF-EC-05 — recipient_name overflow (201-char full_name) aborts all channels
- NOTIF-EC-06 — Empty phone → SMS/WhatsApp silently skipped
- NOTIF-EC-07 — Missing email → welcome skipped (returns None, no row)
- NOTIF-EC-08 — customer_welcome type is not filterable in the UI
- NOTIF-EC-09 — Invalid (non-empty) phone → SMS failed, WhatsApp still "sent"
- NOTIF-SEC-01 — Manual send has no rate limiting + arbitrary recipient (spam blast)
- NOTIF-SEC-02 — Customer-controlled name raw-interpolated into SMS/email (smishing)
- NOTIF-SEC-03 — Log stores PII + financial amounts in plaintext, listable by all management
- NOTIF-SEC-04 — EmailService.send does no address-format validation on the manual path
- NOTIF-SEC-05 — No object-level scoping (every management user sees every customer)
- NOTIF-SEC-06 — Non-management roles denied on both endpoints
- NOTIF-SEC-07 — Unauthenticated access redirects to login
- NOTIF-SEC-08 — Manual send missing required fields is rejected without a send
