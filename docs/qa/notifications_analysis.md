# Notifications Module — QA Analysis

> Deep module analysis of `notifications/` (Email / SMS / WhatsApp + `NotificationLog`).
> Shared facts (roles, decorators, URL map, money) are in `docs/qa/_shared-context.md` and are not re-derived here.

## 1. Business purpose & user journeys

The notifications module is the outbound messaging layer of the ERP. It wraps three channels — email (SMTP/Brevo relay), SMS (SendPK HTTP API), and WhatsApp (a `wa.me` click-to-chat link only) — behind a single `NotificationService` facade that logs every attempt to `NotificationLog`. Its purpose is customer communication for financial events (payments, installments, receipts) and lifecycle events (customer welcome, booking created/approved). It also exposes a management-facing "Notification Center" to browse the log and send a one-off manual message.

User journeys:

- **Staff records a payment** (`payments_access` role) → `payment_create_view` (core/views.py:1666) → `send_payment_confirmation` + `send_receipt_notification` → customer gets email (+ SMS + WhatsApp if a phone exists). Role: management/accounts/admin.
- **Staff creates a customer** (core/views.py:647; customers/api_views.py:53; core/api_views.py:221) or **converts a lead** (core/views_crm.py:197) → `send_customer_welcome` → welcome email (skipped silently if no email). Role: sales-and-above (web) / staff (API).
- **Staff creates a booking** (core/views.py:1127; bookings/api_views.py:115) → `send_booking_notification` → email (+ WhatsApp). Role: sales-and-above.
- **Staff confirms a booking** (core/views.py:1359-1391) → inline `booking_approval` email (+ WhatsApp). Role: management/accounts/admin.
- **Cron/scheduler runs** `check_installment_notifications` (core/management/commands/) → `send_overdue_payment_alert` / `send_installment_reminder`. No human role.
- **Staff sends an ad-hoc message** (`management_or_above`) → `send_manual_notification` (notifications/views.py:38) → generic `general` notification to an arbitrary contact.
- **Management browses the log** (`management_or_above`) → `notifications_view` (notifications/views.py:10) → list + filters.

## 2. Data model

### `NotificationLog` (notifications/models.py:5-50)
- `recipient_name` CharField(200) — free text; populated with `customer.full_name`.
- `recipient_contact` CharField(200) — email address OR phone (overloaded; no channel-specific validation).
- `channel` CharField(20) choices email/sms/whatsapp (models.py:6-10).
- `notification_type` CharField(30) choices (models.py:11-20): installment_reminder, overdue_payment, payment_confirmation, receipt_notification, booking_notification, booking_approval, customer_welcome, general.
- `subject` CharField(300, blank) — email-style subject, also written for SMS/WhatsApp rows.
- `message` TextField — full message (email/whatsapp) or the concise SMS message for sms rows.
- `status` CharField(20) pending/sent/failed, default `pending` (models.py:21-25).
- `error_message` TextField(blank) — provider error string on failure.
- `provider_message_id` CharField(50, blank) — SendPK `messageid` for SMS (models.py:35).
- `related_customer_id` / `related_booking_id` CharField(20, blank) — denormalized string IDs (no FK; rely on the `CUS-…`/`BKG-…` string format).
- `sent_at` DateTimeField(null/blank); `created_at` auto_now_add; `created_by` FK(User, SET_NULL, null/blank).
- `Meta.ordering = ['-created_at']`; indexes on `(status, channel)` and `(notification_type)` (models.py:45-50).
- No `clean()`; no unique constraints. `__str__` truncates message to 50 chars.

### `NotificationPreference` (notifications/models.py:53-64)
- `user` OneToOneField(User); booleans `email_enabled` (True), `sms_enabled` (False), `whatsapp_enabled` (True), plus per-type toggles (installment_reminders, overdue_payments, payment_confirmations, booking_notifications — all default True).
- **Dead for gating**: referenced only in `admin.py` and tests (api/tests_audit_web.py:316, api/tests_audit_crm_hr.py:690). No `services.py` method ever reads these flags. See §4/§6.

## 3. Roles & permissions

| Action | Allowed roles | Enforced by |
|---|---|---|
| `notifications_view` (list log) | super_admin, admin, management | `@management_or_above` (views.py:8-9) |
| `send_manual_notification` (POST) | super_admin, admin, management | `@management_or_above` (views.py:36-37) |
| Sidebar "Notifications" link visibility | MANAGEMENT_ROLES | `{% if can_audit %}` (includes/sidebar.html:277) — consistent with the decorator |
| All automated sends (payment/booking/welcome/reminder) | n/a (system, no user-facing endpoint) | called from `core/views.py`, `core/views_crm.py`, app `api_views.py`, management commands |

- No DRF/API surface for notifications itself (no `notifications/api_views.py`, no router registration). The automated sends are invoked from other apps' ViewSets (`bookings/api_views.py:115`, `customers/api_views.py:53`, `core/api_views.py:221`).
- **No object-level authorization** on the log: any management user sees *all* rows (all customers' phone numbers, emails, and payment amounts). No customer-scoping. This is by design for an internal ERP but is a PII-exposure surface (§6).

## 4. Business rules, state machines, invariants

### `NotificationLog.status` transitions
- Created with `status='pending'` (models.py:33).
- After the provider attempt: `'sent'` if the provider returned success, else `'failed'` (services.py:204-206). `sent_at` set only on success.
- **No re-send / retry state machine** — a `failed` row is never retried automatically. No transition from `failed`/`sent` back to `pending`.

### Send rules / invariants
- **Log-then-send**: the `NotificationLog` row is created *before* the provider call (services.py:180-190), then mutated in place (services.py:204-207). A crash between create and save leaves a `pending` row (stuck forever).
- **Channel selection** (services.py:253-255, 284-286, 369-371, 406-408, 439-441): always starts `['email']`; adds `sms` + `whatsapp` when `customer.phone` is truthy (payment confirmation, installment reminder, overdue alert); adds only `whatsapp` (not SMS) for booking + receipt notifications; welcome is email-only.
- **SMS uses a concise message**: `effective_message = (sms_message or message) if channel == 'sms' else message` (services.py:178). Confirmed by test (notifications/tests.py:121-134).
- **Gating** (must not hit network when disabled):
  - Email: `EMAIL_ENABLED` (services.py:17) — returns `(True, "Email disabled")` without `send_mail`.
  - SMS: `SENDPK_ENABLED` (services.py:63) — returns `(True, "SMS disabled")` without `requests.post` (verified: notifications/tests.py:26-32).
  - WhatsApp: **no gating** — always "succeeds" (see §5).
- **Failure-safety contract**: a broken email/SMS must never break the customer/payment transaction. `send_customer_welcome` is self-wrapped in try/except (services.py:313-348); the other triggers are wrapped at their call sites (core/views.py:1125-1130, 1359-1390, 1666-1672; bookings/api_views.py:113-120). Management commands wrap per-item in try/except (send_installment_reminders.py:38-42; check_installment_notifications.py:90-95, 130-136).

### Side effects
- Writes one `NotificationLog` row per channel per event (e.g. payment confirmation produces up to 3 rows: email + sms + whatsapp).
- No other side effects (no audit-log entry for the notification itself, no ledger impact).

## 5. Edge cases (go deep)

1. **Filtering the log 500s.** `notifications_view` does `NotificationLog.objects.all()[:100]` then applies `.filter(...)` on the sliced queryset (views.py:11-21). Django raises `TypeError("Cannot filter a query once a slice has been taken.")` (django/db/models/query.py:1552-1554) whenever `channel`/`type`/`status` is supplied. **Expected:** filters narrow results. **Actual:** any use of the Filter button on the Notification Center is a 500. Fix: apply filters first, then slice.
2. **Disabled provider is recorded as `sent`, not skipped.** When `EMAIL_ENABLED=False` or `SENDPK_ENABLED=False`, the service returns success (services.py:19, 65) so `log.status='sent'` (services.py:204). The Notification Center "Delivered" stat (views.py:29, template) therefore counts messages that were never delivered. **Expected:** a distinct `skipped`/`disabled` outcome, or `failed` with a clear reason. There is no `skipped` status in `STATUS_CHOICES` (models.py:21-25).
3. **WhatsApp is a no-op that always "succeeds".** `WhatsAppService.send` only builds a `wa.me` URL and `logger.info`s it (services.py:146-162); it never delivers anything and returns `(True, url)`. The URL is not persisted (the log stores the raw message, not the URL). So every WhatsApp row is `sent` while no customer ever receives it. **Expected:** either persist the URL / use the Business API, or record it as a non-delivery.
4. **`recipient_name` can overflow.** `NotificationLog.recipient_name` is CharField(200) (models.py:27) but `customer.full_name` = `first_name + " " + last_name` where both are CharField(100) (customers/models.py:36-37, 70-71) → up to 201 chars. A max-length name makes `NotificationLog.objects.create` raise `DataError`, which aborts the whole send (the other channels in the same loop are skipped). In the welcome path it's swallowed (services.py:342-348); in payment/booking paths it's swallowed at the call site, losing all notifications for that event.
5. **Missing/invalid phone — skip vs error.** If `customer.phone` is empty (`''`, since `phone` is non-null CharField with no default → empty string), the `if customer.phone:` guard skips SMS/WhatsApp entirely (services.py:254, 285, 370, 407, 440). If a phone *is* present but invalid, `SMSService.send` returns `(False, "Invalid phone number")` (services.py:60-61) and the row is marked `failed` — never raised. **Expected/actual:** both are safe; no exception escapes.
6. **SendPK down / network failure.** `SMSService.send` wraps the POST in try/except and returns `(False, str(e))` (services.py:90-92); `check_delivery`/`check_balance` return `None` on error (services.py:117-119, 139-141). A timeout (15 s) is bounded (services.py:78). **Expected:** a `failed` log row with the exception text; the parent transaction is unaffected (sends happen outside `transaction.atomic`, core/views.py:1589 vs 1666).
7. **Welcome email with no recipient.** `send_customer_welcome` strips and skips empty email, returns `None` (services.py:313-321). Lead-conversion paths can create a customer with `email=None` (core/views_crm.py:186, core/api_views.py:211). **Expected/actual:** silent skip, no log row.
8. **`customer_welcome` is un-filterable.** The type filter dropdown lists 7 types but omits `customer_welcome` (templates/notifications/notifications.html:71-77). Welcome rows can only be seen via "All Types".
9. **Duplicate reminder sends.** `send_installment_reminders.py` (the standalone command) has **no** de-duplication and would re-send every run; `check_installment_notifications.py` de-dupes per booking per day (check_installment_notifications.py:110-121). Two commands with overlapping purpose but divergent behavior — running both on a cron doubles reminders.
10. **`check_delivery` has no `SENDPK_ENABLED` gate** (services.py:101-119) and hardcodes `https://sendpk.com/api/delivery.php` / `balance.php` instead of `SENDPK_BASE_URL` (unlike `send`, services.py:76). `check_balance` does gate (services.py:124). Inconsistent.
11. **`provider_message_id` stored but never used.** `extract_message_id` is only called on send (services.py:200); `check_delivery` is never invoked anywhere in the codebase (grep confirms no call site). Delivery status is never reconciled back into the log.
12. **Wrong HTTP verb.** `send_manual_notification` ignores GET vs POST semantics loosely — GET falls through to a redirect (views.py:68) which is fine, but there is no `require_POST`.

## 6. Cross-cutting risks

- **XSS:** Manual message / subject / recipient name are user-controlled but rendered auto-escaped in the template (templates/notifications/notifications.html:118-124); the message body is *not* rendered in the list template. Admin change-view renders message escaped by default. **No `|safe`/`mark_safe`** in this module. Low risk.
- **CSRF:** the manual send form carries `{% csrf_token %}` (notifications.html:153); the view has no `@csrf_exempt`. Low risk.
- **IDOR:** none in the notification views themselves (no `pk`-based lookup); but the log is a cross-tenant PII dump visible to all management roles (views.py:10-33) with no filtering by branch/owner.
- **Sensitive data exposure:** every row stores `recipient_contact` (customer email or phone) and `message` (payment amounts, remaining balances, installment amounts) in plaintext (models.py:28, 32), searchable in admin (admin.py:9) and listable by management. Amounts + phone are PII/PCI-adjacent; no retention or redaction.
- **Injection via customer-controlled name:** `customer.full_name` is interpolated directly into plain-text email and SMS bodies (services.py:226, 243, 276, 355, 365, 393, 402, 431). Email is plain text (no HTML), so no markup injection; but a hostile name (e.g. containing a URL or a line break) flows verbatim into an SMS and could read as a phishing/smishing message from the company's sender. No length/character sanitization beyond the model CharField(100).
- **Spam / abuse on the manual endpoint:** `send_manual_notification` has **no rate limiting** and accepts an arbitrary `recipient_contact` + `message` from any management user (views.py:38-59). A compromised management account can blast arbitrary SMS/email. `EmailService.send` does no format validation (services.py:15-16 only checks truthy); SMS is validated (services.py:60-61).
- **Accessibility:** the manual-send modal uses inline `onclick` + `style`, with `label`s present but tied to inputs only by proximity (no `for`/`id`); filter `<select>`s have no explicit labels. Minor.

## 7. API surface

Notifications has **no DRF ViewSet**. It is invoked programmatically from other apps. The only HTTP endpoints are:

| Method + path | View | Permission | Request fields | Response |
|---|---|---|---|---|
| GET `/notifications/` | `notifications_view` | `management_or_above` | optional `channel`, `type`, `status` query params | HTML list (100 rows, filtered — but see §5.1 bug) |
| POST `/notifications/send/` | `send_manual_notification` | `management_or_above` | `recipient_name`, `recipient_contact` (required), `channel`, `subject`, `message` | redirect to `/notifications/` with flash message |

Service-layer methods (`NotificationService`): `send_notification(...)`, `send_payment_confirmation(payment)`, `send_booking_notification(booking)`, `send_customer_welcome(customer, user=None)`, `send_installment_reminder(installment)`, `send_overdue_payment_alert(installment)`, `send_receipt_notification(receipt)`.

Serializer validation: n/a. Model-level validation: n/a (no `clean()` on either model).

## 8. Test data & fixtures needed

- A `Customer` with `first_name`, `last_name`, `phone='+92-300-1234567'`, `cnic` (unique), `email` (unique), `created_by` (see notifications/tests.py:67-73 for the exact pattern).
- A `Project` + `Plot` (plot needs `plot_number`, `project`, `size_marla`, `price`) and a `Booking` (`customer`, `plot`, `total_amount`, `advance_paid`, `status`, `created_by`).
- An `InstallmentPlan` + `auto_generate()` to get numbered `Installment` rows (notifications/tests.py:84-89).
- A `Payment` with `status='verified'`, `payment_type='installment'`, `payment_method='cash'` for confirmation/receipt tests.
- **Provider mocking:** `patch('notifications.services.requests.post', …)` with a Mock returning `{'success':'true','results':[{'status':'OK','messageid':'6502124'}]}` (tests.py:35-48); `@override_settings(SENDPK_ENABLED=False)` to assert no network (tests.py:27-32); `EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'` for email tests (tests.py:65).
- **Isolation:** `Customer.cnic`/`email` are unique and `Customer.customer_id` is auto-incremented from the last suffix (customers/models.py:54-64), so use `created_by`-scoped setup and unique emails per test. `Installment` is unique on `(plan, installment_number)` (bookings/models.py:454).

## 9. Key files (for traceability)

- `notifications/models.py` — `NotificationLog` (log + status/channel/type choices), `NotificationPreference` (unused for gating).
- `notifications/services.py` — `EmailService`, `SMSService` (normalize/validate/send/check_delivery/check_balance), `WhatsAppService`, `NotificationService` facade + all trigger methods.
- `notifications/views.py` — `notifications_view` (sliced-queryset filter bug) and `send_manual_notification`.
- `notifications/urls.py` — two routes.
- `notifications/admin.py` — admin registrations (log searchable by message/contact).
- `notifications/tests.py` — normalization + send-gating + message-content tests.
- `notifications/management/commands/send_installment_reminders.py` — standalone reminder command (no de-dup).
- `core/management/commands/check_installment_notifications.py` — mark-overdue + overdue alerts + reminders (has per-day de-dup).
- `templates/notifications/notifications.html` — Notification Center list + filter + manual-send modal.
- Trigger call sites: `core/views.py` (646, 1127, 1378, 1668-1669), `core/views_crm.py:197`, `core/api_views.py:221`, `customers/api_views.py:53`, `bookings/api_views.py:115`.
- Referenced models: `customers/models.py` (full_name, email, phone), `bookings/models.py` (remaining_balance 144, Installment.remaining_amount 449, late_fee 437).
- `payments/views_workflow.py:48-49` — `_apply_payment_effects` updates `booking.advance_paid`, keeping `remaining_balance` current before notification fires (and `payment_verify_view` at :62-85 sends **no** notification — trigger gap).
