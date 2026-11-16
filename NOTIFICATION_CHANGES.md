# Notification hardening, part 2

Date: 2026-10-19

Scope: outbox delivery, provider outcome classification, duplicate submit protection, event preferences, contact matching, and manual-send cleanup. The real `db.sqlite3` was not migrated or written. All provider calls remained disabled or mocked in tests.

## Stage 1: move sending off the request path

| Item | Status | Files changed | Test |
|---|---|---|---|
| `queued` and `sending` statuses plus `sending_at` | Done | `notifications/models.py`, `notifications/migrations/0006_outbox_statuses.py` | `NotificationOutboxTests.test_thread_sender_is_off_in_tests` |
| Triggers create a queued log only, with type, channel, recipient, customer, booking and template params | Done | `notifications/services.py` (`queue_notification`) | `NotificationOutboxTests.test_customer_request_queues_without_calling_providers` |
| Log creation and `transaction.on_commit` sending | Done | `notifications/services.py`; web views now use `transaction.atomic` decorators; API create paths wrap create plus queue | `NotificationOutboxTests.test_on_commit_not_fired_when_transaction_rolls_back` |
| `process_notification_queue` with atomic claim, limit, loop, interval, dry-run and lock backoff | Done | `notifications/management/commands/process_notification_queue.py` | `NotificationOutboxTests.test_atomic_claim_prevents_double_send`, `test_dry_run_changes_nothing` |
| Best effort daemon thread behind `NOTIFICATIONS_SEND_IN_THREAD`, forced off under `TESTING` | Done | `samana_erp/settings.py`, `notifications/services.py` | `NotificationOutboxTests.test_thread_sender_is_off_in_tests` |
| Stuck `sending` older than 10 minutes becomes `unknown`, never resent automatically | Done | `notifications/services.py` (`mark_stale_sending`) | `NotificationOutboxTests.test_stuck_sending_is_marked_unknown` |
| Reminder and overdue command queues with the existing cooldown | Done | Existing command now calls queueing wrappers | Existing reminder tests |
| Report blocking time | Done | No provider wait remains in any web request | See below |
| Crontab and worker commands | Listed only, deploy files not edited | See below | n/a |

### Trigger locations

| Trigger | Where it queues | Customer and booking IDs |
|---|---|---|
| Customer welcome, web and API | `NotificationService.send_customer_welcome` | Customer ID |
| Lead conversion, web and API | `send_customer_welcome` | Customer ID |
| Booking create, web and API | `send_booking_notification` | Customer and booking IDs |
| Booking confirm | direct `queue_notification` in `core/views.py` | Customer and booking IDs |
| Payment confirmation | `send_payment_confirmation` | Customer and booking IDs |
| Receipt | `send_receipt_notification` | Customer and booking IDs |
| Installment reminder | `send_installment_reminder` | Customer and booking IDs |
| Overdue alert | `send_overdue_payment_alert` | Customer and booking IDs |

No automatic trigger calls `NotificationService.send_notification` now. That direct method remains only for legacy tests and internal use.

### Blocking time report

Provider waits were removed from payment create, booking create, booking confirm and customer create. These requests now do local database work, create the log rows, and return. The daemon thread starts only after commit. The target of no provider wait inside a web request is met. I did not benchmark wall clock milliseconds, so I am not claiming a measured duration. Any remaining latency is local form, database, audit, receipt and PDF work, not SMTP, SendPK or Meta.

### Deploy lines to add (not edited)

Crontab:

```cron
* * * * * cd /app && python manage.py process_notification_queue --limit 50 >> /var/log/notification-queue.log 2>&1
15 2 * * * cd /app && python manage.py retry_failed_notifications >> /var/log/notification-retry.log 2>&1
```

Long running worker instead of the queue cron:

```bash
python manage.py process_notification_queue --loop --interval 10 --limit 50
```

Docker service command:

```yaml
command: python manage.py process_notification_queue --loop --interval 10 --limit 50
```

Systemd:

```ini
ExecStart=/app/.venv/bin/python /app/manage.py process_notification_queue --loop --interval 10 --limit 50
Restart=always
```

## Stage 2: retry must not double send

| Item | Status | Files changed | Test |
|---|---|---|---|
| Classify email, SMS and WhatsApp outcomes as retryable, unknown or permanent | Done | `notifications/services.py` (`DeliveryResult`, service returns, `_graph`) | `NotificationOutcomeTests` plus existing provider tests |
| Store unknown as `unknown` with the reason | Done | `notifications/services.py`, `notifications/models.py` | `test_read_timeout_is_unknown_not_retryable` |
| Retry only `failed` rows with attempts below 3 | Done | `notifications/management/commands/retry_failed_notifications.py` | Existing retry tests |
| List unknown rows without a provider message ID and tell a human to check the dashboard | Done | same command | Existing retry output tests plus command output |
| Notification Center unknown count, filter and "Needs check" note | Done | `notifications/views.py`, `templates/notifications/notifications.html` | `notifications.tests.NotificationCenterFilterTest` |
| WhatsApp 24 hour or template errors and invalid numbers never retried | Done; permanent outcomes set attempts to 3 | `notifications/services.py` | `test_permanent_error_sets_attempts_to_three` |

## Stage 3: duplicate payment protection

| Item | Status | Files changed | Test |
|---|---|---|---|
| Payment web submit lock and "Saving" label | Done | `templates/payment_form.html` | Manual browser check not run |
| One time token on Payment web | Done | `payments/forms.py`, `core/views.py`, `templates/payment_form.html` | `PaymentIdempotencyTest.test_double_web_post_same_token_creates_one_payment_and_one_queue_set` |
| Payment API idempotency key | Done | `payments/models.py`, `payments/serializers.py`, `payments/migrations/0009_idempotency_keys.py` | `test_double_api_post_same_token_creates_one_payment` |
| Booking web and API token | Done | `bookings/models.py`, `bookings/forms.py`, `bookings/serializers.py`, `core/views.py`, `bookings/migrations/0007_idempotency_keys.py` | API serializer validation covered by the shared pattern; no dedicated Booking E2E test added |
| Refund web and API token | Done | `payments/models.py`, `payments/forms.py`, `payments/serializers.py`, `payments/views_workflow.py`, `payments/migrations/0009_idempotency_keys.py` | `test_double_post_same_token_creates_one_refund` |
| Shared submit lock on generic forms | Done | `templates/base_form.html` | Manual browser check not run |

Known race limit: the unique database constraint guarantees only one row, but two truly simultaneous web submits can still surface an IntegrityError instead of the friendly redirect. Sequential double submits redirect to the existing record. This is listed as uncertainty below.

## Stage 4: event level preferences

One mapping lives in `notifications/services.py`:

| Notification type | Preference field |
|---|---|
| `installment_reminder` | `installment_reminders` |
| `overdue_payment` | `overdue_payments` |
| `payment_confirmation` | `payment_confirmations` |
| `receipt_notification` | `payment_confirmations` |
| `booking_notification` | `booking_notifications` |
| `booking_approval` | `booking_notifications` |
| `customer_welcome` | always allowed |
| `general` | always allowed |

Channel and event flags are checked before queueing and again in `_deliver` before sending. A disabled event creates a `skipped` row with a reason naming the type. `EventPreferenceTests` covers every mapped type and an unmapped type.

## Stage 5: contact matching gaps

All automatic triggers pass `related_customer_id`; booking triggers also pass `related_booking_id`. No trigger depends on email or phone matching.

Read only counts on the real database:

| Metric | Count |
|---|---|
| Customers total | 148 |
| Customers with a linked user | 3 |
| Customers with a NotificationPreference row | 0 |
| Distinct customers messaged in the last 30 days | 36 |
| Messaged in the last 30 days with no preference row | 36 |

Customers without a linked user cannot opt out today because preferences hang off `User`, not `Customer`. Proposed, not implemented: a customer level preference row keyed by `Customer`, with the user row taking precedence when both exist.

## Stage 6: cleanup

Removed from `tests/notifications/notifications.spec.ts`:

- `NOTIF-HP-09` SMS normalization through the manual form.
- `NOTIF-HP-10` manual send with email disabled.
- `NOTIF-EC-03`, `NOTIF-EC-04`, `NOTIF-EC-08`, `NOTIF-EC-09`.
- `NOTIF-SEC-01`, `NOTIF-SEC-04`, `NOTIF-SEC-08`.
- The remaining manual POST from `NOTIF-SEC-06` and `NOTIF-SEC-07`.
- `postManual` and `manualSendHtml` helpers and the manual form references around them.
- The HP-01 stat labels were updated to the current UI labels, including "Needs check".

Other leftovers fixed: the `WhatsAppService.send` docstring and `notifications/wa_templates.json` notes now describe automatic triggers, not a manual-send view. The 404 regression tests for the removed endpoint remain in `notifications/tests_security.py` on purpose. Playwright was not run.

## Status transitions

```text
queue_notification -> queued
queued --atomic claim--> sending
sending --provider accepted--> sent
sending --provider definite failure--> failed
sending --provider unknown outcome--> unknown
sending --preference disabled--> skipped
queued --preference disabled at queue time--> skipped
sending --older than 10 minutes--> unknown (never resent automatically)
failed --retry command, attempts < 3--> sending -> sent/failed/unknown
permanent failure--> failed with attempts = 3
```

## Migrations added in this task

- `notifications/migrations/0006_outbox_statuses.py` - schema only (status choices/default and `sending_at`).
- `bookings/migrations/0007_idempotency_keys.py` - schema only.
- `payments/migrations/0009_idempotency_keys.py` - schema only.

Not applied to the real database. The full pending list on the real database is: finance 0010 to 0014, payments 0008 to 0009, expenses 0006, bookings 0006 to 0007, properties 0009 to 0014, and notifications 0005 to 0006. The copy used for verification had these applied.

Deploy command order:

```bash
python manage.py migrate
python manage.py process_notification_queue --dry-run
python manage.py retry_failed_notifications --dry-run
python manage.py process_notification_queue --limit 50
```

## Copy verification

On `db.notification-copy.sqlite3` with all migrations applied and providers disabled:

```text
process_notification_queue --dry-run
Would process 0 queued rows and mark 0 stale sending rows unknown.

retry_failed_notifications --dry-run
Retry candidates: 0. Sent: 0. Failed: 0. Skipped: 0.
```

## Verification counts

- Full Django suite: 1108 tests, OK, 0 failures, 0 errors. The earlier 1105-test run had 1 failure and 3 errors; all four were stale-code failures from files edited after that run started (a missing `uuid4` import and one core test that still expected inline provider calls). Those were fixed before the 1108-test run. Two final small changes landed after that run started: the queue command now counts stale rows in dry-run and catches per-row exceptions, and one WhatsApp test now asserts attempts = 3. The same command tests and that single test were rerun and passed.
- `makemigrations --check --dry-run`: No changes detected.
- Targeted suites: notifications 150 OK; notifications outbox 10 OK; payments idempotency 3 OK; core 15 OK; payments, bookings and customers 49 OK; api.tests_audit_web 58 OK.

## Uncertainty and known limits

- True simultaneous double submits can race into the unique constraint and may return a server error rather than the friendly redirect. Sequential replays are handled.
- The queue command retries database lock errors around the claim. A lock during the final save is not retried separately.
- The command does not catch every exception per row; the daemon thread marks its own failure as unknown, but a command worker exception can stop that batch. Re-running the command is safe because claimed rows are left as `sending` and later become `unknown`.
- `--dry-run` reports queued rows but does not count stale `sending` rows that would be changed by a real run.
- Provider outcome classification is conservative. Generic exceptions are treated as unknown, which can create manual checks that a less cautious system would retry automatically.
- No real provider was called. Success, timeout, HTTP error and permanent error paths were exercised with mocks.
- Playwright was not run and its new UI labels were not browser checked.
- Booking duplicate protection has no dedicated browser or API double POST test in this task. The serializer and unique constraint are in place.
- Event preferences only work for customers with a linked user, as stated above.

## Follow-up fixes (2026-10-20)

| Item | Status | Files changed | Test |
|---|---|---|---|
| IntegrityError catch for Payment web and API | Done | `core/views.py`, `payments/api_views.py`, `payments/serializers.py` | `payments.tests_idempotency.RefundIdempotencyTest.test_web_payment_race_hits_constraint_and_redirects_existing`, `test_api_payment_race_hits_constraint_and_returns_existing` |
| IntegrityError catch for Booking web and API | Done | `core/views.py`, `bookings/api_views.py`, `bookings/serializers.py` | `test_web_booking_race_hits_constraint_and_redirects_existing`, `test_api_booking_race_hits_constraint_and_returns_existing` |
| IntegrityError catch for Refund web and API | Done | `payments/views_workflow.py`, `payments/api_views.py`, `payments/serializers.py` | `test_web_refund_race_hits_constraint_and_redirects`, `test_api_refund_race_hits_constraint_and_returns_existing` |
| Booking double-POST test added | Done | `payments/tests_idempotency.py` | Web and API Booking race tests above |
| Queue final status save retries database locked 3 times | Done | `notifications/services.py` (`_save_with_lock_retry`) | `notifications.tests_outbox.QueueLockRetryTests.test_final_status_save_retries_database_locked` |

IntegrityError handling uses inner savepoints so a failed unique insert does not poison the surrounding request or TestCase transaction. API creates now return the existing serialized record with HTTP 200. Web creates redirect to the existing payment or booking detail, or to the refund list.

The serializer idempotency fields declare `validators=[]` so the race path reaches the database unique constraint; the existing explicit pre-check still gives a clear 400 for normal sequential API replays.

### reset_demo.py diff summary

`core/management/commands/reset_demo.py`: 1 file changed, 29 insertions, 25 deletions.

- Added `from decimal import Decimal`.
- Replaced invalid `django.db.models.DecimalField('...')` value construction with `Decimal('...')` in phases, plots, bookings, ledger rows, installments, payments and booking advance updates.
- Added `phase_number=1` to the demo phase lookup.
- Fixed the missing closing braces/parentheses in the `plot1` and `plot2` `defaults` dictionaries.
- No command behavior was intentionally changed beyond making the command valid and runnable.

### Final verification

- Full Django suite: 1115 tests, OK, 0 failures, 0 errors.
- `makemigrations --check --dry-run`: No changes detected.
- No migrations were added or applied in this follow-up.
- Notifications outbox suite after the final save-retry change: 11 tests OK.
- Idempotency suite: 9 tests OK.

## 2026-11-16: Customer level do not message

A customer level opt-out now stops every channel and every notification type, including welcome, payment confirmations, receipts and reminders.

### Fields

- `Customer.do_not_contact` boolean, default false.
- `Customer.do_not_contact_reason` up to 200 characters.
- `Customer.do_not_contact_set_by` user, null on user deletion.
- `Customer.do_not_contact_at` timestamp.

Schema migration: `customers/migrations/0009_customer_do_not_contact_customer_do_not_contact_at_and_more.py`.

### Enforcement

`NotificationService.preference_reason` checks the customer flag before the existing user channel and event preferences. Both queueing and `_deliver` call this method, so the check happens before queueing and again before sending. `retry_failed_notifications` uses `preference_reason_for_log` and skips the same customers. `process_notification_queue` reaches `_deliver` and skips them there.

When a customer is opted out, the log is created or updated as `status='skipped'` with:

`Skipped: customer opted out of all messages`

The existing contact fallback still resolves a customer by `related_customer_id`, then email, then phone. User level preferences are unchanged.

### UI and admin

- Customer detail has a toggle, reason field and last changed information.
- Customer edit has the same fields for super_admin, admin and management.
- Customer list shows a Do not message badge and a messaging state filter.
- Django admin has a list filter and bulk actions Stop all messages and Allow messages.
- API customer serializers expose all four fields as read only.

### Tests

`customers/tests_do_not_contact.py` covers every channel and type, direct send, queueing, retry and queue workers, contact fallback, toggle permissions, list filter and badge, admin actions and API read-only behaviour.
