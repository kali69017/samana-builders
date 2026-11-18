# Samana Builders - Real Estate Management ERP

Django 6.0.7 ERP plus corporate website. SQLite for development, PostgreSQL 16 for production. `CLAUDE.md` remains the long-form project context. This file is the current operating guide for agents and operators.

Last updated: 2026-11-18.

## Production status

The production release is complete.

- Production host app directory: `/opt/samana`
- Remote: `https://github.com/kali69017/samana-builders.git`
- Branch: `main`
- Release commit with the legacy finance conversion fix: `7149a83`
- Postgres container: `samana-db-1`
- Database name and user: both `samana`
- Services: `db`, `web`, `worker`, `scheduler`, `caddy`
- Public site: `https://samanabuilders.com/`
- Production database was recreated empty during the release.
- Production superuser username: `superadmin`. The password is not recorded here.
- Finance integrity check passed after the clean start.
- The host cron backup is installed and was manually tested.

## Environment (Windows development)

- Working venv: `D:\samana\.venv312\Scripts\python.exe`, Python 3.12.
- The in-repo `.venv312` is incomplete. Do not use it for AI-backed tests.
- Always clear `PYTHONPATH` before running Django commands.
- Set `DJANGO_DEBUG=True` for local server and test runs, otherwise HTTPS redirects break the suite.
- `.env` is ignored and contains live provider credentials. Never print it, commit it or copy values into reports, tests or chat.
- `.env.example` contains placeholders only.
- Development uses `db.sqlite3`; production uses PostgreSQL selected by `DB_ENGINE=postgres`.
- SQLite is configured with `timeout=20`, `PRAGMA journal_mode=WAL` and `transaction_mode=IMMEDIATE`.
- WAL creates `db.sqlite3-wal` and `db.sqlite3-shm`. These are ignored.
- Test database is in memory by default.

## Commands

```powershell
$env:PYTHONPATH=$null
$env:DJANGO_DEBUG='True'
$env:EMAIL_ENABLED='False'
$env:SENDPK_ENABLED='False'
$env:WHATSAPP_ENABLED='False'

D:\samana\.venv312\Scripts\python.exe manage.py test
D:\samana\.venv312\Scripts\python.exe manage.py test finance.tests_customer_liability
D:\samana\.venv312\Scripts\python.exe manage.py makemigrations --check --dry-run
D:\samana\.venv312\Scripts\python.exe manage.py migrate
D:\samana\.venv312\Scripts\python.exe manage.py finance_integrity_check
D:\samana\.venv312\Scripts\python.exe manage.py convert_to_customer_liability --dry-run
D:\samana\.venv312\Scripts\python.exe manage.py process_notification_queue --dry-run
D:\samana\.venv312\Scripts\python.exe manage.py retry_failed_notifications --dry-run
```

Current full suite: 1,195 tests, OK. Runtime is roughly 14 to 22 minutes depending on disk and WAL state.

Default local login: `admin` / `admin123`. Staff land on `/dashboard/`, customers on `/portal/`.

## Repository rules

- Do not commit databases, backups, WAL files, reports, screenshots, `.env` or probe scripts.
- `.gitignore` covers `db.sqlite3`, `db.*.sqlite3`, `db.sqlite3.*`, `*.sqlite3-wal`, `*.sqlite3-shm`, `*.dump`, `e2e-report/`, `e2e2-report/`, `release-report/`, `*probe*.py`, `.playwright-mcp/` and `.env`.
- No generated database file was tracked when this was last audited.
- `release-report/` holds release evidence and is intentionally ignored.
- Do not print secrets, tokens, passwords, phone numbers or CNIC values in reports.
- Test fixtures use synthetic phone and CNIC values.
- No em dashes in newly written code, templates, docs or messages.
- Do not push without explicit instruction from the user.

## Architecture

- `core/views.py` is the ERP page hub. Check it first when customer, booking, payment, delivery, voucher or portal pages misbehave.
- `samana_erp/urls.py` routes the main ERP pages. `finance/urls.py`, `notifications/urls.py`, `expenses/urls.py` and `hr/urls.py` hold their own routes.
- Domain models live in `customers/`, `properties/`, `bookings/`, `payments/`, `finance/`, `expenses/`, `notifications/` and `hr/`.
- DRF ViewSets are registered through `api/urls.py`.
- Roles come from `core/permissions.py` and `core/models.py::UserProfile`. A Django superuser always counts as `super_admin`.
- `frontend/dist/` is a compiled artifact with no React source in this repository.
- The corporate site is server-rendered Django templates.

## Finance and accounting

Customer-liability accounting replaced cash basis.

Final posting map:

| Entity | Event | Debit | Credit |
|---|---|---|---|
| Payment | Received before delivery, any booking status | Selected cash or bank | 2.1.1 Customer Advances & Bookings |
| Payment | Received on or after delivery date | Selected cash or bank | 4.1.1 Plot Sales Revenue |
| Refund | Paid before delivery | 2.1.1 Customer Advances & Bookings | Selected cash or bank |
| Refund | Paid on or after delivery date | 4.1.1 Plot Sales Revenue | Selected cash or bank |
| Booking delivery | Marked delivered | 2.1.1 Customer Advances & Bookings | 4.1.1 Plot Sales Revenue |
| Booking | Created, confirmed, cancelled or reopened | No voucher | No voucher |
| Installment | Raised or paid | No voucher | No voucher |
| Expense | Paid | Selected expense account | Selected cash or bank |
| Expense | Approved unpaid | Selected expense account | 2.1.3 Accounts Payable |
| Project Cost | Paid | Selected expense account | Selected cash or bank |
| Office Expense | Paid | Selected expense account | Selected cash or bank |
| Salary Payment | Paid | 5.1.3 Salaries | Selected cash or bank |

Chart of accounts:

- Five roots: Assets, Liabilities, Capital, Revenue, Expenses.
- Cash: `1.1.1.1`, role `cash_default`.
- Bank: `1.1.1.2`, role `bank_default`.
- Accounts Receivable: `1.1.2.1`, role `receivable`.
- Customer Advances & Bookings: `2.1.1`, role `customer_advances`.
- Refunds Payable: `2.1.2`, role `refunds`.
- Accounts Payable: `2.1.3`, role `payable`.
- Revenue: `4.1.1`, role `revenue`.
- The old Fixed Assets head `1.2.5 Advances & Bookings` is removed by data migration.
- Production has 29 account heads after migration.

`finance_integrity_check` checks:

- Posted debits equal posted credits.
- No posted lines on level 1 roots.
- No unbalanced posted vouchers.
- Customer Advances equals posted payments minus posted refunds for undelivered bookings.

## Booking delivery

- `Booking.delivery_date` and `Booking.delivered_by` are nullable schema fields.
- Delivery is allowed only for active or completed bookings, by super_admin, admin or management.
- Delivery date defaults to today and cannot be in the future.
- An unpaid balance shows a warning and requires the explicit confirmation checkbox. Delivery is still allowed.
- Delivery sets status to completed, records the delivery date and poster, and posts net advances to revenue in one transaction.
- Delivery is idempotent on `('BookingDelivery', booking id)` and cannot run twice.
- No undo exists.
- `templates/booking_deliver.html` and `core/views.py::booking_deliver_view` implement the page.
- API action: `POST /api/bookings/<id>/deliver/`.
- Delivery state on production after the clean start: no bookings exist.

Production pre-release delivery state was recorded in `release-report/booking-delivery-state.txt`:

- BKG-00006 active, 0 advances.
- BKG-00007 active, 94,444.45 advances.
- BKG-00008 active, 46,484.40 advances.
- BKG-00009 active, 20,000.00 advances.
- BKG-00010 completed, 65,179.05 advances, no delivery date. This was the only completed booking without delivery.
- BKG-00011 pending, 50,000.00 advances.
- BKG-00012 pending, 1,500.00 advances.
- No booking had possession date or possession taken set without a delivery date.

`release-report/deliver_existing_bookings.py` is a proposed idempotent script. Its mapping is empty and it was not run. Fill the mapping with booking number to ISO date, run `--dry-run` first, then run for real. It wraps all deliveries in one transaction and calls `booking.mark_delivered`.

## Voucher deletion

- Only manual vouchers, meaning no `reference_type` and no `reference_id`, can be deleted.
- Only super_admin and admin can delete from the ERP.
- Django admin deletion is superuser only.
- API DELETE remains 405 for every role.
- The only allowed path is `Voucher.delete_manual_voucher(user, reason)`.
- Reason is required and must be at least 5 characters.
- The flow is POST only, CSRF protected and atomic.
- `VoucherDeletionLog` stores the number, type, date, narration, status, total, full lines, copied audit history, creator, deleter, timestamp and reason.
- The deletion log has no foreign key to the voucher and is immutable.
- System vouchers from Payment, Refund, Expense, Project Cost, Office Expense, Salary, Booking delivery and conversions cannot be deleted. Correct the source record instead.
- A deleted voucher number is never reused, so a gap remains.
- Deleted Vouchers page is visible to super_admin and admin only.

## Notifications and customer messaging

- Notification delivery is outbox based.
- `process_notification_queue` is drained by the long-running `worker` service.
- `retry_failed_notifications` runs from the scheduler crontab.
- `Customer.do_not_contact` blocks every channel and every notification type.
- `do_not_contact_reason`, `do_not_contact_set_by` and `do_not_contact_at` record the change.
- The check runs before queueing and again before sending.
- Queue and retry workers also skip opted-out customers.
- Log status is `skipped` with reason `Skipped: customer opted out of all messages`.
- Customer list has a badge and messaging state filter.
- Django admin has a list filter and bulk Stop all messages and Allow messages actions.
- API customer fields are read only.
- Existing user channel and event preferences still apply.
- Providers are disabled in test runs by the `TESTING` guard.

Production notification worker command:

```bash
python manage.py process_notification_queue --loop --interval 10 --limit 50
```

Scheduler crontab:

```cron
0 8 * * * cd /app && python manage.py send_installment_reminders --days=7 --cooldown=6 >> /var/log/samana-reminders.log 2>&1
15 2 * * * cd /app && python manage.py retry_failed_notifications --days=2 >> /var/log/samana-retry.log 2>&1
```

The worker logs `Processed 0 queued rows` every 10 seconds. This is harmless but noisy.

## Legacy finance conversion

`convert_to_customer_liability` converts existing data without editing old vouchers. It is idempotent on `('LiabilityConversion', source voucher id)`.

It handles:

- Payment vouchers that credit Revenue and should credit Customer Advances.
- Payment vouchers that credit Accounts Receivable and should credit Customer Advances for undelivered bookings.
- Payment vouchers that credit Accounts Receivable for delivered bookings and should credit Revenue.
- Refund vouchers that debit Accounts Receivable and should debit Customer Advances before delivery.
- Refund vouchers that debit Revenue before delivery and should debit Customer Advances.
- Refund vouchers after delivery remain in Revenue.
- Payment vouchers with a paired CashBasisConversion voucher are not corrected twice. The CashBasisConversion voucher is the correction point.

Production scratch rehearsal result:

- Restored production snapshot: 5 payment vouchers crediting Accounts Receivable, 3 refund vouchers debiting Accounts Receivable.
- Dry run: 8 corrections totalling 205,000.00.
- Real run: 8 corrections.
- Revenue remained 0.00.
- Customer Advances became 151,000.00.
- Customer Advances expected was 151,000.00.
- Finance integrity check passed on scratch.
- Empty database integrity check passed.
- Both scratch databases were dropped after validation.

`convert_to_cash_basis` is deprecated. Keep it for history only. Do not run it.

## SQLite concurrency

- `OPTIONS.timeout` is 20 seconds.
- `init_command` sets `PRAGMA journal_mode=WAL`.
- `transaction_mode` is `IMMEDIATE`.
- Verified on Django 6.0.7.
- Test: `core/tests_sqlite_hardening.py`.
- Concurrent payment probe on a copy: one row, zero 500 responses, zero `database is locked`.
- Concurrent booking probe on a copy: one row, zero 500 responses, zero `database is locked`.
- The old failure was a 500 with `database is locked`.
- Notification provider calls run outside transactions. Tests: `notifications/tests_transactions.py`.

## Migrations

Current migration chain includes:

- `properties/0008` to `0014`: plot uniqueness, phase number, phase parsing, phase status, block move, phase required, feature dedupe.
- `finance/0010`: account roles and kind.
- `finance/0011`: chart of accounts seed.
- `finance/0012`: voucher cash or bank account.
- `finance/0013`: finance account links.
- `finance/0014`: expense category actions.
- `finance/0015`: customer advances liability data migration.
- `finance/0016`: `VoucherDeletionLog`.
- `bookings/0006`: booking installment accounts.
- `bookings/0007`: idempotency keys.
- `bookings/0008`: delivery fields.
- `customers/0008`: customer name length.
- `customers/0009`: do-not-contact fields.
- `expenses/0006`: finance account links.
- `notifications/0005`: retry tracking.
- `notifications/0006`: outbox statuses.
- `notifications/0007`: WhatsApp provider message ID width.
- `payments/0008`: finance account links.
- `payments/0009`: idempotency keys.

`makemigrations --check --dry-run` reports no changes as of 2026-11-18.

## Data cleanup and wipe scripts

`release-report/wipe_business_data.py` is a SQLite-only wipe utility. It was dry-run only and was not run with `--confirm`.

It keeps:

- Users, auth users, groups, permissions, group permissions, user groups and user permissions.
- `UserProfile` roles.
- `NotificationPreference`.
- `django_migrations` and `django_content_type`.
- The 29 seeded account heads.
- The seven default expense categories.
- System role accounts.

It wipes all business data, vouchers, voucher audit logs, `VoucherDeletionLog`, notification logs, sessions, audits and delivery booking rows. It resets `sqlite_sequence` only for wiped tables and runs `PRAGMA foreign_key_check`.

Document numbers restart after a wipe:

- CUS-00001
- BKG-00001
- PAY-00001
- GRP-00001
- RCP-00001
- Per-type vouchers such as CR-00001
- Receipt fiscal numbers at RCP-FYxx/00001 for the new fiscal year

User IDs and account codes do not restart.

## Production deployment

Production stack:

- `db`: `postgres:16-alpine`, container `samana-db-1`, database and user `samana`.
- `web`: Gunicorn, runs `migrate --noinput` and `collectstatic --noinput` on start.
- `worker`: `python manage.py process_notification_queue --loop --interval 10 --limit 50`.
- `scheduler`: installs `deploy/crontab` and runs cron.
- `caddy`: TLS and reverse proxy.

`web`, `worker` and `scheduler` build the same repository image and use the same `x-app-env` environment.

Release history on 2026-11-18:

- Pre-release dump: `/root/backups/samana-pre-release-2026-11-16.dump`.
- Final pre-clean dump: `/root/backups/samana-before-clean-start-2026-11-18-082634.dump`.
- Post-release manual dump: `/root/backups/samana-2026-11-18.dump`, about 326K.
- Empty production database was migrated.
- Superuser `superadmin` was created interactively.
- `collectstatic` copied 278 files.
- All services started.
- HTTPS returned HTTP 200 through Caddy.
- Queue and retry dry runs returned zero pending work.
- Scheduler crontab contained both the 08:00 reminder and 02:15 retry lines.
- Host backup cron installed at 02:00 with 14 day retention.

See `DEPLOY.md` for the full command sequence, rollback commands and server validation steps.

## Testing and E2E

- Django full suite: 1,195 tests, OK.
- Python 3.12 shared venv: `D:\samana\.venv312\Scripts\python.exe`.
- Playwright uses system Chrome. Do not run `npx playwright install`, the CDN is blocked.
- Playwright runbook: `RUNBOOK.md`.
- Conventions: `tests/CONVENTIONS.md`.
- Healing patterns: `tests/HEALING.md`.
- E2E reports and screenshots are ignored.
- Release screenshots were stored in `e2e2-report/screenshots` and are not committed.
- Confirmed bug tests must not be weakened.

## Known open items

- Delivery has no undo.
- Cancellation has no forfeiture rule. Advances remain in Customer Advances until refunded.
- System vouchers cannot be deleted.
- Per-customer receivable balances are not tracked in the ledger.
- Manual journals posted directly to Customer Advances can make the integrity check fail by design.
- BKG-00010 was completed without a delivery date before the production wipe.
- The proposed delivery script mapping is empty.
- The wipe script was never run with `--confirm`.
- SQLite concurrent writes are hardened, but production uses PostgreSQL.
- Worker logs zero-row polling every 10 seconds.
- The production database is empty after the clean start. Create the real company data and open the first admin session.
