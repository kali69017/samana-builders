# Samana Builders ERP - Project Handover

Date: 2026-11-23. Originally written 2026-11-16.

This document covers the customer-liability accounting change, manual voucher deletion, customer do-not-message controls, and the operating rules needed to run the ERP safely.

## Current production state, 2026-11-23

- Production release commit: `58408d9`.
- Local residual review fixes are committed on `main` but are not pushed or deployed. They are waiting for explicit approval.
- The residual full suite has not been run yet. It is waiting for explicit instruction.
- The production database was wiped on 2026-11-22.
- Only the `superadmin` user remains. Its profile role is `super_admin`.
- 29 seeded account heads, 103 migrations, 308 auth permissions and 77 content types remain.
- Expense categories are empty. Create the real categories in the ERP.
- Finance integrity passed after the wipe with all balances at 0.00.
- Pre-wipe backup: `/root/backups/samana-before-wipe-2026-11-22-134148.dump`, 344K.
- Confirmed, active and completed bookings can be delivered.
- Employees with salary slips cannot be deleted. Set them to Resigned or Terminated instead.
- All 37 menu pages returned HTTP 200 after the wipe.

## Legacy conversion tools

- `convert_to_cash_basis` and `convert_to_customer_liability` are one-time legacy tools. Do not run them on a new database.
- Both commands skip payments that are not verified and print the number skipped.
- The old development copy contains one-time conversion vouchers `JV-00032` to `JV-00038`. They explain the expected Customer Advances mismatch on that copy. They do not exist on the clean production database.
- Stage 1 fresh-database verification is recorded in `release-report/stage1-fresh-integrity.txt`.

## 1. Roles and permissions

| Action | super_admin | admin | management | accounts | sales | hr | others |
|---|---|---|---|---|---|---|---|
| View dashboard, customers, properties, bookings | Yes | Yes | Yes | Yes | Yes | Yes | Per existing module gates |
| Create and edit customers, including do-not-message toggle | Yes | Yes | Yes | No | No | No | No |
| Mark a booking delivered | Yes | Yes | Yes | No | No | No | No |
| Delete a manual voucher | Yes | Yes | No | No | No | No | No |
| View Deleted Vouchers | Yes | Yes | No | No | No | No | No |
| Delete a voucher from Django admin | Yes, superuser only | No | No | No | No | No | No |
| View vouchers and ledger | Yes | Yes | Yes | Yes | No | No | No |
| Create or edit draft vouchers | Yes | Yes | Yes | Yes | No | No | No |
| Post or unlock vouchers | Yes | Yes | Yes | No | No | No | No |
| Record a pending payment | Yes | Yes | Yes | Yes | Yes | No | No |
| Record refunds | Yes | Yes | Yes | Yes | No | No | No |
| Verify payments | Yes | Yes | No | Yes | No | No | No |
| View properties list and detail | Yes | Yes | Yes | Yes | Yes | Yes | Project Manager yes; Contractor no |
| View milestones | Yes | Yes | Yes | Yes | Yes | Yes | Project Manager and Contractor yes |
| View financial, sales and receivables reports | Yes | Yes | Yes | Yes | No | No | No |

A Django superuser always counts as `super_admin`. The API keeps DELETE on vouchers at 405 for every role.

Project Manager and Contractor are explicit view-only roles. Project Manager can view properties and milestones. Contractor can view milestones only. They are hidden from the user create and edit forms unless `SHOW_LIMITED_ROLES=True`. Existing users with these roles keep working and keep their current role visible when edited.

## 2. Final entity and event posting map

| Entity | Event | Debit | Credit | Voucher source |
|---|---|---|---|---|
| Payment | Received before delivery, any booking status | Selected cash or bank | 2.1.1 Customer Advances & Bookings | `Payment` |
| Payment | Received on or after delivery date | Selected cash or bank | 4.1.1 Plot Sales Revenue | `Payment` |
| Refund | Paid before delivery | 2.1.1 Customer Advances & Bookings | Selected cash or bank | `Refund` |
| Refund | Paid on or after delivery date | 4.1.1 Plot Sales Revenue | Selected cash or bank | `Refund` |
| Booking delivery | Marked delivered | 2.1.1 Customer Advances & Bookings | 4.1.1 Plot Sales Revenue | `BookingDelivery` |
| Booking | Created, confirmed, cancelled, reopened | No voucher | No voucher | None |
| Installment | Raised or paid | No voucher | No voucher | None |
| Expense | Paid | Selected expense account | Selected cash or bank | `Expense` |
| Expense | Approved and unpaid | Selected expense account | 2.1.3 Accounts Payable | `Expense` |
| Project Cost | Paid | Selected expense account | Selected cash or bank | `ProjectCost` |
| Office Expense | Paid | Selected expense account | Selected cash or bank | `OfficeExpense` |
| Salary Payment | Paid | 5.1.3 Salaries | Selected cash or bank | `SalaryPayment` |
| Manual journal | Posted by a finance user | Entered debit lines | Entered credit lines | None |
| Liability conversion | Existing cash-basis revenue corrected | 4.1.1 Plot Sales Revenue | 2.1.1 Customer Advances & Bookings | `LiabilityConversion` |

The receivable account and the refunds payable account stay seeded, but the new customer-liability rules do not use them for payment and refund posting.

### 2.1 Reporting metrics

- `finance/reporting.py` is the single source for reporting metrics.
- `collected` is the sum of verified payments in the date range.
- `customer_advances_held` is the posted Customer Advances ledger balance as of the range end.
- `recognized_revenue` is posted credits minus debits on revenue accounts.
- `expenses` is posted debits minus credits under the Expenses root, split into operating, office, project cost, salaries and depreciation.
- `profit` is recognized revenue minus expenses.
- Dashboard, Financial Reports and the Financial Reports PDF use these metrics. The Sales Report and Receivables report stay on booking and installment data.

### 2.2 Deprecated AccountTransaction

- The `AccountTransaction` model and table remain for history.
- Its API route and Django admin registration are removed.
- No production writer exists. Only legacy tests create rows directly.

## 3. Delivery workflow

1. Open a confirmed, active or completed booking.
2. Choose Mark as Delivered.
3. Enter a delivery date. It defaults to today and cannot be in the future.
4. If the booking is not fully paid, the page shows the unpaid amount and requires the confirmation checkbox. Delivery is still allowed.
5. On submit, the booking status becomes completed, delivery date and delivered by are recorded, and one journal moves the booking's net advances to revenue.
6. Delivery cannot run twice. No undo exists.

Net advances are posted payments minus refunds posted on or before the delivery date. The delivery journal is idempotent on `('BookingDelivery', booking id)` and is atomic with the status change.

### 3.1 Employee deletion rules

- Employees with salary slips cannot be deleted.
- `Employee.delete()` raises a validation error when payroll history exists.
- The ERP delete action shows the error and keeps the employee record.
- Set the employee status to Resigned or Terminated instead.
- This prevents salary payments and salary slips from being removed while a posted salary voucher remains.

## 4. Voucher deletion rules

- Only manual vouchers can be deleted. A manual voucher has no `reference_type` and no `reference_id`.
- Only super_admin and admin can delete from the ERP. Django admin deletion is superuser only.
- The flow is POST only, requires CSRF, requires a reason of at least 5 characters, and runs in one transaction.
- The only allowed code path is `Voucher.delete_manual_voucher(user, reason)`.
- The API keeps DELETE at 405.
- A `VoucherDeletionLog` snapshot stores the voucher number, type, date, narration, status, total, full lines, audit history, creator, deleter, deletion time and reason.
- The snapshot has no foreign key to the voucher and cannot be edited or deleted from the UI, API or admin.
- The voucher number is retired. A gap remains and numbers are never reused.
- System vouchers from Payment, Refund, Expense, Project Cost, Office Expense, Salary, Booking delivery and conversions cannot be deleted. Correct the source record instead.
- This reverses the earlier client rule against voucher deletion and needs client acknowledgement.

## 5. Do-not-message behaviour

- `Customer.do_not_contact` blocks every channel and every notification type.
- The check runs before queueing and again before sending.
- `process_notification_queue` and `retry_failed_notifications` also skip these customers.
- The notification log is created or updated as skipped with the reason `Skipped: customer opted out of all messages`.
- The detail page and edit page allow super_admin, admin and management to set the flag, reason, actor and time.
- The customer list shows a badge and a messaging state filter.
- Django admin has a list filter and bulk Stop all messages and Allow messages actions.
- API fields are read only.

### 5.1 Payment notification trigger

- Payment confirmation and receipt notifications are queued only when a payment becomes `verified`.
- Pending, rejected, bounced, reversed and under-clearing payments queue nothing.
- Queueing runs inside the same transaction as the status change, receipt voucher posting and receipt creation.
- The idempotency key is `(notification_type, related_payment_id, channel)`. Double approval, retries and races cannot create a second set.
- Receipt numbers are generated when the receipt row is created during verification. A pending payment has no receipt row and no customer-facing receipt page or PDF.
- Do-not-message and channel preferences still apply.

## 6. Notification worker commands

Cron:

```cron
* * * * * cd /app && python manage.py process_notification_queue --limit 50 >> /var/log/notification-queue.log 2>&1
15 2 * * * cd /app && python manage.py retry_failed_notifications >> /var/log/notification-retry.log 2>&1
```

Long running worker:

```bash
python manage.py process_notification_queue --loop --interval 10 --limit 50
```

Dry runs:

```bash
python manage.py process_notification_queue --dry-run
python manage.py retry_failed_notifications --dry-run
```

## 7. Backup and restore

Create a backup:

```powershell
Copy-Item -Path D:\ERP\samana\db.sqlite3 -Destination "D:\ERP\samana\db.sqlite3.backup-$(Get-Date -Format yyyyMMdd-HHmmss)"
```

Verify the live database:

```powershell
$env:PYTHONPATH=$null
$env:DJANGO_DEBUG='True'
D:\samana\.venv312\Scripts\python.exe manage.py migrate --check
D:\samana\.venv312\Scripts\python.exe manage.py finance_integrity_check
```

Restore a backup:

```powershell
Copy-Item -Path D:\ERP\samana\db.sqlite3.pre-release-backup-TIMESTAMP -Destination D:\ERP\samana\db.sqlite3 -Force
```

Stop the server and all workers before copying a SQLite database.

## 8. Management commands

| Command | Purpose |
|---|---|
| `ai_daily_insights` | Generate daily AI insight rows. |
| `check_wa_templates` | Check WhatsApp template status and wiring. |
| `create_wa_templates` | Create the configured WhatsApp templates. |
| `populate_db` | Populate demonstration data. |
| `reset_demo` | Reset demonstration data. |
| `seed_data` | Seed base demonstration records. |
| `backfill_customer_account_heads` | Link customers to the shared receivable head. |
| `backfill_finance_links` | Fill finance account links on existing source records. |
| `backfill_ledger_vouchers` | Post missing vouchers for paid expenses and project costs. |
| `convert_to_cash_basis` | Deprecated. Kept for history only. Do not run. |
| `convert_to_customer_liability` | Post additive corrections from cash-basis revenue to Customer Advances. Supports `--dry-run` and is idempotent. |
| `finance_integrity_check` | Check double entry, root postings and Customer Advances against undelivered bookings. |
| `seed_finance` | Seed offices, categories and finance defaults. |
| `seed_hr` | Seed HR defaults. |
| `process_notification_queue` | Claim and deliver queued notifications. |
| `retry_failed_notifications` | Retry failed notifications up to three attempts. |
| `send_installment_reminders` | Queue installment and overdue reminders. |

## 9. Known limits and open items

- Cancellation has no forfeiture rule. A cancelled booking keeps its advance in Customer Advances until a refund is processed.
- Delivery has no undo.
- System vouchers cannot be deleted. Their source record must be corrected, and the original voucher remains immutable.
- Per-customer receivable balances are not tracked by the ledger. The receivable control account is shared and currently nets to zero because of the legacy conversion history.
- Voucher deletion leaves a permanent number gap.
- Truly simultaneous payment web submits on SQLite can produce one saved payment and one database-lock response. Production uses PostgreSQL. Sequential double submits return the existing record.
- Existing payments recorded before this change were converted with additive journals. Old vouchers were not edited.
- Manual journals posted directly to Customer Advances can make the integrity check fail by design, because the ledger balance no longer equals payments minus refunds for undelivered bookings.

## 10. Files to delete after handover

Do not delete these until the release is accepted:

- `D:\ERP\samana\db.e2e.sqlite3`
- `D:\ERP\samana\db.e2e2.sqlite3`
- `D:\ERP\samana\db.stage1-test.sqlite3`
- `D:\ERP\samana\db.orphan-test.sqlite3`
- `C:\Users\USER\AppData\Local\Temp\opencode\stage_settings.py`
- `C:\Users\USER\AppData\Local\Temp\opencode\e2e_settings.py`
- `C:\Users\USER\AppData\Local\Temp\opencode\e2e2_settings.py`
- `C:\Users\USER\AppData\Local\Temp\opencode\orphan_copy_settings.py`
- `C:\Users\USER\AppData\Local\Temp\opencode\cleanup_orphan_vouchers.py`
- `C:\Users\USER\AppData\Local\Temp\opencode\cleanup_orphan_vouchers_fk.py`
- `C:\Users\USER\AppData\Local\Temp\opencode\seed_e2e2.py`
- `D:\ERP\samana\.playwright-mcp`
- `D:\ERP\samana\release-report` working scripts after keeping reports
- `D:\ERP\samana\e2e-report` and `D:\ERP\samana\e2e2-report` probe scripts after keeping reports and screenshots
- Keep every `db.sqlite3.pre-release-backup*` file until production behaviour is verified

## 11. Proposed commit groups

1. Properties and phase data fixes.
2. Finance: customer liability, delivery posting, chart migration, conversion command and integrity check.
3. Finance: manual voucher deletion and deletion snapshot.
4. Notifications and customers: do-not-message controls.
5. E2E fixes and reports.
6. This task: handover documents, tests and release report.

No commit was made as part of that original task. Later release commits exist. See the current production state at the top of this document.

## 2026-11-16: Final go-live hardening

### 1. Production database engine

Production uses PostgreSQL. The selection is `DB_ENGINE=postgres` in `docker-compose.yml` and `.env.example`. `samana_erp/settings.py` reads `os.environ.get('DB_ENGINE', 'sqlite')`. If `DB_ENGINE` is absent or any value other than `postgres`, the default is SQLite at `BASE_DIR / 'db.sqlite3'`. The PostgreSQL block is unchanged. No secret values are recorded here.

Production wiring:

- `docker-compose.yml` sets `DB_ENGINE: postgres`, `DB_HOST: db`, `DB_PORT: 5432` and passes `DB_NAME`, `DB_USER`, `DB_PASSWORD`.
- The `db` service runs `postgres:16-alpine`.
- `.env.example` sets `DB_ENGINE=postgres` with placeholder database settings.
- `Dockerfile` runs Gunicorn. The `web` service applies migrations before starting.

### 2. SQLite concurrency hardening

SQLite now uses these options in `samana_erp/settings.py`:

```python
'OPTIONS': {
    'timeout': 20,
    'init_command': 'PRAGMA journal_mode=WAL;',
    'transaction_mode': 'IMMEDIATE',
}
```

Verified on the installed Django 6.0.7:

- `journal_mode` on the file database is `wal`.
- `PRAGMA busy_timeout` is 20000 ms.
- `connection.transaction_mode` is `IMMEDIATE`.

Concurrency probe on a copy, providers off:

| Probe | Rows created | 500 responses | database is locked |
|---|---:|---:|---:|
| Two simultaneous payment submits, same idempotency key | 1 | 0 | 0 |
| Two simultaneous booking submits, same idempotency key | 1 | 0 | 0 |

Before this change the same payment probe produced a 500 with `database is locked`. The new settings remove that failure.

Notification transaction check:

- `NotificationService._deliver` calls providers outside any transaction.
- `process_notification_queue` claims one row, then delivers outside a transaction.
- Regression tests assert `connection.in_atomic_block` is false inside the mocked email provider for both the worker and the queue command.
- No provider wait is held inside a database transaction.

### 3. Booking delivery state

Full read-only table: `release-report/booking-delivery-state.txt`.

| Booking | Status | Delivery date | Possession date | Possession taken | Payments | Refunds | Advances |
|---|---|---|---:|---:|---:|---:|---:|
| BKG-00006 | active | empty | empty | False | 0.00 | 0.00 | 0.00 |
| BKG-00007 | active | empty | empty | False | 94,444.45 | 0.00 | 94,444.45 |
| BKG-00008 | active | empty | empty | False | 46,484.40 | 0.00 | 46,484.40 |
| BKG-00009 | active | empty | empty | False | 20,000.00 | 0.00 | 20,000.00 |
| BKG-00010 | completed | empty | empty | False | 65,179.05 | 0.00 | 65,179.05 |
| BKG-00011 | pending | empty | empty | False | 50,000.00 | 0.00 | 50,000.00 |
| BKG-00012 | pending | empty | empty | False | 1,500.00 | 0.00 | 1,500.00 |

No booking has possession date or possession taken set while delivery is empty. BKG-00010 is already completed but not delivered, which is a separate data gap worth reviewing.

Proposed script: `release-report/deliver_existing_bookings.py`. Fill its `MAPPING` dict with booking number to ISO date. It supports `--dry-run`, validates statuses and dates, wraps all deliveries in one transaction, and calls `booking.mark_delivered`. It is idempotent because delivered bookings are skipped. It was not run.

### 4. User review

Full list: `release-report/users-review.txt`. 76 users were reviewed. 21 match the requested test-name patterns (`e2e`, `test`, `qa`, `demo`, `dbg`, `agt`):

`dbg_admin`, `duptest`, `duptest2`, `qa_accounts`, `qa_api_portal_1791583379264019`, `qa_api_portal_1791583781887027`, `qa_api_portal_1791584530298003`, `qa_customer`, `qa_hr`, `qa_management`, `qa_new_1791583368848005`, `qa_new_1791583769404005`, `qa_old_1791583368029003`, `qa_old_1791583768466003`, `qa_portal_1791583341169008`, `qa_portal_1791583742797008`, `qa_portal_1791584501439008`, `qa_sales`, `searchtester`, `test@example.com`, `test_kashif`.

Additional likely test artifacts that do not match the requested substrings include the `pwreset_*`, `probe_*`, `verify_*`, `vprobe*`, `staff<number>`, `p42a3`, `pe9fe`, `td153`, `t`, and `zz*` accounts. Nothing was changed.

### 5. Wipe script

Script: `release-report/wipe_business_data.py`. It is SQLite only, requires `--dry-run` or `--confirm`, and uses one transaction. On a real run it takes a consistent SQLite backup with the sqlite3 backup API, deletes business tables in foreign-key-safe order, deletes custom account heads and custom expense categories, runs `PRAGMA foreign_key_check`, and resets `sqlite_sequence` only for wiped tables.

Kept:

- Users, auth users, groups, permissions, group permissions, user groups and user permissions.
- `UserProfile` roles.
- `NotificationPreference`.
- `django_migrations` and `django_content_type`.
- The 29 seeded account heads, including the five roots, Cash, Bank, Revenue and Customer Advances.
- The seven default expense categories.
- System role accounts.

Wiped:

- All customers, bookings, payments, refunds, receipts, projects, phases, plots, expenses, project costs, HR records, leads, agents, audits, notifications and finance vouchers.
- `VoucherDeletionLog` and voucher audit logs.
- `Voucher`, `VoucherLine` and the deprecated `AccountTransaction`.
- Sessions and admin logs.

Dry-run on `db.wipe-test.sqlite3` succeeded with no changes. Key counts:

| Table | Rows |
|---|---:|
| `core_auditlog` | 10,020 |
| `notifications_notificationlog` | 515 |
| `finance_voucher` | 66 |
| `finance_voucherline` | 132 |
| `finance_voucherauditlog` | 132 |
| `customers_customer` | 148 |
| `bookings_booking` | 7 |
| `payments_payment` | 19 |
| `properties_project` | 4 |
| `properties_plot` | 60 |
| `hr_employee` | 2 |
| `core_lead` | 129 |
| `ai_aiinteractionlog` | 128 |
| `django_session` | 3,667 |

Full dry-run output: `release-report/wipe-dry-run.txt`.

After a confirmed wipe, document numbers restart from the first value because every business table is empty and its sequence is reset: CUS-00001, BKG-00001, PAY-00001, GRP-00001, RCP-00001 and per-type voucher numbers such as CR-00001. Receipt fiscal numbers restart at RCP-FYxx/00001 for new records in that fiscal year. User IDs and account codes do not restart.

## 2026-11-16: Production worker and cron

- `docker-compose.yml` now has a `worker` service running `python manage.py process_notification_queue --loop --interval 10 --limit 50`, with the same `x-app-env` environment and image as `web` and `scheduler`.
- `deploy/crontab` keeps the 08:00 `send_installment_reminders --days=7 --cooldown=6` line and adds `retry_failed_notifications --days=2` at 02:15.
- The queue is drained by the worker service, not by cron.
- The scheduler service builds the same image and receives the same environment as web.
- `DEPLOY.md` now documents the Postgres scratch restore, empty database migration proof, clean start, rollback to `f33888d`, and a host cron for 14 daily `pg_dump -Fc` backups.

## 2026-11-18: Legacy accrual conversion before scratch integrity

The restored production snapshot has Payment vouchers that credit Accounts Receivable and Refund vouchers that debit Accounts Receivable. `convert_to_customer_liability` now handles that shape as well as the earlier cash-basis shape:

- Payment credit to Receivable becomes Dr Receivable, Cr Customer Advances for an undelivered booking.
- Refund debit to Receivable becomes Dr Customer Advances, Cr Receivable for a refund before delivery.
- A Payment voucher that already has a CashBasisConversion voucher is not corrected twice. The conversion voucher remains the single correction point.
- Delivered-booking payments and refunds move to Revenue instead of Customer Advances.

Run the conversion on the restored scratch database before `finance_integrity_check`. The empty database and the clean production start need no conversion.

## 2026-11-23: Residual review fixes

### Payment creation and verification

- The Record New Payment web form and `POST /api/payments/` now create `pending` payments with no `verified_by` and no `verified_at`.
- A pending payment creates no receipt, no voucher and no notification.
- Verification remains only in the verify action. The maker-checker rules and the super_admin self-verification exception are unchanged.
- Sales may create a pending payment from the web form and the API. Sales still cannot verify payments or open the payment list.
- Web and API creation tests cover management, sales, accounts, admin and super_admin. All five roles get a pending payment.

### Reversal accounting

- `post_payment_reversal` decides the debit head when the reversal is posted.
- If a delivery journal is posted, the reversal debits Plot Sales Revenue and credits the original cash or bank account.
- If the booking is not delivered, the reversal debits Customer Advances & Bookings.
- The reversal is still idempotent on `('PaymentReversal', payment id)`.
- `fix_payment_postings` uses the same reversal function. `post_refund` already chose its head at posting time and had no ordering bug.

### Integrity checks

`finance_integrity_check` now also checks that no booking has a debit Customer Advances balance and that Revenue linked to each booking equals delivered net collected. Undelivered bookings must have zero linked Revenue.

Fresh-database scenario result, with integrity passing after every step:

| Step | Collected | Customer advances | Recognized revenue | Expenses | Profit |
|---|---:|---:|---:|---:|---:|
| 0 baseline | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| 1 pending pre-delivery payment 700 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| 2 verify pre-delivery payment | 700.00 | 700.00 | 0.00 | 0.00 | 0.00 |
| 3 deliver | 700.00 | 0.00 | 700.00 | 0.00 | 700.00 |
| 4 reverse pre-delivery payment after delivery | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| 5 second payment 500 after delivery | 500.00 | 0.00 | 500.00 | 0.00 | 500.00 |
| 6 refund 200 after delivery | 500.00 | 0.00 | 300.00 | 0.00 | 300.00 |

### Peripheral reporting

- `/api/company-settings/summary/`, the AI grounding context and the AI insights page now use `finance.reporting`.
- The names are `collected`, `customer_advances_held`, `recognized_revenue`, `expenses` and `profit`.
- The old summary keys `revenue` and `net_profit` were removed. No frontend or template consumer was found. Internal tests and the release probe were updated.

### Posted payment immutability

After a receipt voucher exists, amount, booking, cash or bank account, payment date and payment method are locked in the model, queryset update, serializer, web form and Django admin. Notes, reference and cheque number remain editable.

### AccountTransaction cleanup

- The unused `AccountTransactionViewSet`, its serializer and their imports were removed.
- The model and table remain.
- `/api/account-transactions/` stays HTTP 404.

### Local commits

- `0671959`: create payments pending until verification.
- `e528d85`: decide payment reversal head at reversal time.
- `f341439`: use reporting service in peripheral consumers.
- `fc36431`: lock payment date and method after posting.
- `3fdefd6`: remove unused account transaction API code.
- `e1df71f`: cover integrity check failure paths.

### Verification and remaining points

- Focused tests for each change passed.
- `makemigrations --check --dry-run`: no changes detected.
- The fresh-database scenario above passed `finance_integrity_check` after every step.
- The full suite was not run after these changes, by explicit instruction.
- Booking create and installment mark paid now create pending payments. See the next section.
- Demo and test scripts also create verified payments directly. They are not production creation paths.
- The temporary database cleanup list is in `release-report/stage6-temp-db-cleanup.txt`. Nothing was deleted.

## 2026-11-23: Booking and installment maker-checker

### Booking create

- The web and API booking create paths create a pending `Payment` for the requested advance.
- `Booking.advance_paid` stays zero until that payment is verified.
- The requested advance is still used for the installment plan down payment.
- No receipt, payment voucher or payment notification is created at booking time.
- The booking-created notification still queues separately at booking create.
- Reservation conversion now creates a pending token payment and stores `advance_paid` as zero.

### Installment mark paid

- The web and API mark-paid actions create a pending `Payment` for the installment.
- The installment stays pending with zero paid amount until that payment is verified.
- The installment displays `Payment pending verification` while the payment is pending.
- A second pending payment for the same installment is refused.

### Balances and reversals

- `Booking.recalculate_advance_paid()` sums verified payments, subtracts approved or processed refunds, and caps at the booking total.
- `Installment.recalculate_paid_amount()` sums verified payments linked to the installment.
- Verification and reversal now apply these balance effects inside the `Payment` model, so web, API and Django admin transitions use the same rule.
- Reject and bounce of a pending payment leave the booking advance and installment unchanged.
- Reversal after delivery still debits revenue and does not make customer advances negative.

### Display

- The booking detail page shows a Pending Verification amount.
- The booking detail installment table and installment plan detail table show a Pending column and the pending verification status.

### Before and after numbers

Sample booking: total 1,000,000.00, advance 200,000.00, two installments of 400,000.00, undelivered.

| Step | Booking advance | Pending payment | Sales Report | Receivables | Dashboard collected | Dashboard advances | Installment paid | Installment pending |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Old behavior at create | 200,000.00 | 0.00 | 1,000,000.00 | 800,000.00 | 200,000.00 | 200,000.00 | 0.00 | 0.00 |
| New behavior at create | 0.00 | 200,000.00 | 1,000,000.00 | 1,000,000.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| After advance verify | 200,000.00 | 0.00 | 1,000,000.00 | 800,000.00 | 200,000.00 | 200,000.00 | 0.00 | 0.00 |
| Installment pending | 200,000.00 | 400,000.00 | 1,000,000.00 | 800,000.00 | 200,000.00 | 200,000.00 | 0.00 | 400,000.00 |
| Installment verified | 600,000.00 | 0.00 | 1,000,000.00 | 400,000.00 | 600,000.00 | 600,000.00 | 400,000.00 | 0.00 |

The Sales Report does not change because it uses `Booking.total_amount` only. The other figures move only when a payment is verified.

### Scenario and verification

Fresh migrated database, with `finance_integrity_check` passing after every step:

- Booking with a 200,000.00 advance pending: collected 0.00, advances 0.00, revenue 0.00.
- Advance verified: collected 200,000.00, advances 200,000.00, revenue 0.00.
- Installment 400,000.00 pending: collected 200,000.00, advances 200,000.00, revenue 0.00.
- Installment verified: collected 600,000.00, advances 600,000.00, revenue 0.00.
- Delivery: collected 600,000.00, advances 0.00, revenue 600,000.00.
- Pre-delivery advance reversed after delivery: collected 400,000.00, advances 0.00, revenue 400,000.00.

### Local commits

- `385a644`: align suite with pending payment creation.
- `a27fcdc`: make booking and installment advances pending.
- `54d31c6`: cover booking and installment maker checker.
- `378a03e`: migrate Playwright ledger specs to the Voucher API.
- `188280d`: expect pending reservation token payment.

### Remaining

- Full suite: 1,298 tests, OK, 0 failures, 0 errors.
- The PowerShell wrapper reported exit code 1 because it surfaced the Django test database message from stderr. The Django output was `Ran 1298 tests in 900.927s` and `OK`.
- Playwright is not run, by instruction.
- Demo and test scripts that insert verified payments directly are not production creation paths.
