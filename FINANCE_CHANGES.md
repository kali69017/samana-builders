# Finance Module Changes

## Stage 1: Chart of Accounts

### What was broken or missing

- Only 10 account heads existed, with codes such as `100`, `1000`, `1100`, `5000` and no fixed level 1 roots.
- Nature was editable and not inherited from a root.
- Codes were editable and manually entered.
- Parent was optional, used CASCADE, and there was no cash or bank flag.
- Automated posting resolved accounts by hard-coded codes, so recoding would break every writer.

### What changed

- Five fixed roots: `1 Assets` (debit), `2 Liabilities` (credit), `3 Capital` (credit), `4 Revenue` (credit), `5 Expenses` (debit).
- Nature is derived from the root and removed from forms and API input.
- Codes are generated from the parent code plus the next sibling number.
- Code is read-only in forms and API.
- Parent is required for every non-root account.
- Parent changes are blocked when ledger entries exist. Otherwise the account and descendants are recoded in one transaction.
- Accounts with children or ledger entries cannot be deleted. Roots and system accounts cannot be deleted.
- Added `account_kind` with normal, cash and bank choices. Cash and bank are only valid under Assets.
- Added a stable `system_role` on AccountHead for automated posting.
- Changed `AccountHead.parent` from CASCADE to PROTECT.
- Added a system-role resolver so posting no longer depends on numeric codes.

### Files

- `finance/models.py`
- `finance/forms.py`
- `finance/serializers.py`
- `finance/views.py`
- `finance/api_views.py`
- `finance/admin.py`
- `finance/accounting.py`
- `finance/tests_stage1_coa.py`
- `finance/migrations/0010_accounthead_roles_and_kind.py`
- `finance/migrations/0011_seed_chart_of_accounts.py`
- `templates/finance/account_heads.html`
- `templates/finance/account_head_form.html`
- `finance/management/commands/backfill_customer_account_heads.py`

### Old code to new code

| Old | New | Name |
|---|---|---|
| 100 | 1.1 | Current Assets |
| 1000 | 1.1.1.1 | Cash |
| 1010 | 1.1.1.2 | Bank |
| 110 | 1.1.2 | Receivables |
| 1100 | 1.1.2.1 | Accounts Receivable |
| 500 | 5.1 | Operating Expenses |
| 5000 | 5.1.1 | Office Expenses |
| 5100 | 5.1.2 | Project Costs |
| 5200 | 5.1.3 | Salaries |
| 5900 | 5.1.4 | Depreciation |

No account was placed in a holding parent.

### System roles

- `cash_default`: 1.1.1.1 Cash
- `bank_default`: 1.1.1.2 Bank
- `receivable`: 1.1.2.1 Accounts Receivable
- `customer_advances`: 2.1.1 Customer Advances
- `refunds`: 2.1.2 Refunds Payable
- `payable`: 2.1.3 Accounts Payable
- `revenue`: 4.1.1 Plot Sales Revenue
- `office_expenses`: 5.1.1 Office Expenses
- `project_costs`: 5.1.2 Project Costs
- `salaries`: 5.1.3 Salaries

## Stage 2: Vouchers

### What was broken or missing

- Every voucher type used the same manual debit and credit line form.
- There was no cash or bank account field.
- Vouchers could be deleted through the API and admin, and lines could be deleted on edit.
- No balance rule was enforced for manual journal saves.

### What changed

- Cash Receipt and Cash Payment use a single cash account flagged cash.
- Bank Receipt and Bank Payment use a single bank account flagged bank.
- The server generates the cash or bank side and ignores client-sent sides.
- Journal vouchers stay manual and must balance.
- Contra lines cannot equal the cash or bank account, cannot be a level 1 root, and must be positive.
- Voucher and line creation is atomic.
- Voucher delete was removed from the API (405), URL layer (no route), admin, model and queryset.
- Voucher line delete is blocked at model and queryset level.
- Source records with posted vouchers cannot be deleted.
- API edit re-runs the same validation. Cash and bank voucher lines and cash account cannot change after creation. Journal line count cannot change and balance is rechecked.

### Source delete paths changed

- `Payment.delete`, `Refund.delete`, `Expense.delete`, `ProjectCost.delete`, `OfficeExpense.delete`.
- `PaymentViewSet.destroy`, `RefundViewSet.destroy`, `OfficeExpenseViewSet.destroy`, `ProjectCostViewSet.destroy`.
- Expense web delete and Project Cost web delete.

### Files

- `finance/models.py`
- `finance/forms.py`
- `finance/views.py`
- `finance/serializers.py`
- `finance/api_views.py`
- `finance/admin.py`
- `finance/tests_stage2_vouchers.py`
- `finance/migrations/0012_voucher_cash_bank_account.py`
- `templates/finance/voucher_form.html`
- `payments/models.py`
- `payments/api_views.py`
- `expenses/models.py`
- `expenses/views.py`

## Stage 3: Finance links and posting

### What changed

- Central posting functions now live in `finance/accounting.py`.
- Booking posts a JV: Dr Accounts Receivable, Cr Revenue.
- Booking voucher date is `booking_date`.
- Booking posting is idempotent and linked by `reference_type='Booking'`.
- Booking revenue account is resolved through the `revenue` system role, so it can be switched to a deferred revenue or customer advance account by changing the role mapping.
- Installments link to the receivable account and create no voucher.
- Payment links `received_into`, required in forms and create API.
- Refund links `paid_from`, required in forms and API.
- Expense links `expense_account` and optional `paid_from`. Approved unpaid expenses credit Accounts Payable.
- Project Cost and Office Expense link `expense_account` and `paid_from`.
- Salary payments use the central service.

### Files

- `bookings/models.py`
- `payments/models.py`
- `payments/forms.py`
- `payments/serializers.py`
- `expenses/models.py`
- `expenses/forms.py`
- `finance/models.py`
- `finance/forms.py`
- `finance/serializers.py`
- `finance/accounting.py`
- `hr/models.py`
- `finance/management/commands/backfill_finance_links.py`
- `finance/tests_stage3_links.py`
- `finance/tests_backfill_links.py`
- `bookings/migrations/0006_booking_installment_accounts.py`
- `payments/migrations/0008_finance_account_links.py`
- `expenses/migrations/0006_finance_account_links.py`
- `finance/migrations/0013_finance_account_links.py`
- `templates/payment_form.html`
- `templates/expense_form.html`

### Entity mapping

| Entity | Event | Debit | Credit |
|---|---|---|---|
| Booking | Confirmed, active or completed | 1.1.2.1 Accounts Receivable | 4.1.1 Plot Sales Revenue |
| Payment | Received | Selected cash or bank | 1.1.2.1 Accounts Receivable |
| Installment | Raised or paid | No voucher, link only | None |
| Refund | Paid | 1.1.2.1 Accounts Receivable | Selected cash or bank |
| Expense | Paid | Selected expense account | Selected cash or bank |
| Expense | Approved unpaid | Selected expense account | 2.1.3 Accounts Payable |
| Project Cost | Paid | Selected expense account | Selected cash or bank |
| Office Expense | Paid | Selected expense account | Selected cash or bank |
| Salary Payment | Paid | 5.1.3 Salaries | Selected cash or bank |

## Cancelled bookings and refunds

Current behavior:
- Cancel is blocked while unrefunded verified payments exist. The user is told to process a refund first.
- After refunds fully cover verified payments, cancel is allowed.
- Refund approval reduces `Booking.advance_paid`.
- Refund processing posts Dr Accounts Receivable, Cr cash or bank.
- Cancel sets the plot to available, sets the booking to cancelled, and writes an audit log.
- Cancel posts a BookingCancel JV when a Booking voucher exists: Dr revenue role, Cr receivable role, dated the cancel date.
- Reopen sets the booking to pending and re-reserves the plot.
- Reopen posts a BookingReopen JV when a BookingCancel voucher exists: Dr receivable role, Cr revenue role, dated the reopen date.

Ledger effect:
- The Booking voucher and BookingCancel voucher net to zero for receivable and revenue.
- The refund voucher reverses the cash receipt against Accounts Receivable.
- A fully refunded booking with a Booking voucher nets its receivable to zero after cancellation.

## Backfill

Command:
`python manage.py backfill_finance_links --dry-run`
`python manage.py backfill_finance_links`

It is idempotent and only fills null links. It does not rewrite vouchers and never touches orphan vouchers.

Copy run results:

- Receivable balance before: -4,977,607.90
- Receivable balance after: -2,537,933.26
- Payment: 19 linked, 0 newly posted
- Booking: 7 linked, 5 posted, 2 skipped because status is pending
- Installment: 120 linked, 0 vouchers
- Office Expense: 1 record, 2 fields linked, 0 newly posted
- Project Cost: 6 records, 12 fields linked, 0 newly posted
- Skipped bookings: BKG-00011 and BKG-00012, both pending
- Bookings still showing a credit receivable balance after backfill: BKG-00011 (-50,000.00), BKG-00012 (-1,500.00)

The remaining receivable credit is largely caused by the 27 orphan vouchers, which were left untouched.

## Report verification on the copy

| Report | Before backfill | After backfill |
|---|---|---|
| Financial Reports total revenue | 225,533.24 | 225,533.24 |
| Financial Reports year revenue | 225,533.24 | 225,533.24 |
| Financial Reports month revenue | 216,236.36 | 216,236.36 |
| Financial Reports total expenses | 0.00 | 0.00 |
| Financial Reports net profit | 225,533.24 | 225,533.24 |
| Financial Reports collection rate | 10.3% | 10.3% |
| Receivables total | 17,300,678.12 | 17,300,678.12 |
| Sales Report total sales | 18,625,274.64 | 18,625,274.64 |
| Sales Report booking count | 7 | 7 |
| Dashboard total revenue | 542,448.08 | 542,448.08 |
| Dashboard monthly revenue | 51,500.00 | 51,500.00 |

The reports did not change. They read source business records, not voucher totals.

## Stage 4 walkthrough on the test database

- Create account under Assets with client-sent nature and code: 201, generated code `1.1.4.1`, nature `debit`. Client-sent code and nature were ignored.
- Cash Receipt: 201, debit cash, credit contra.
- Cash Payment: 201, debit contra, credit cash.
- Bank Receipt: 201, debit bank, credit contra.
- Bank Payment: 201, debit contra, credit bank.
- Balanced journal: 201.
- Unbalanced journal: 400, `Journal is not balanced: debit 100.00 does not equal credit 50.00.`
- Delete voucher URL: 404, no route exists.
- Delete voucher API: 405.
- Payment: 201, posted voucher exists.
- Refund: 200, posted voucher exists.
- Expense: create 302, approve 302, posted voucher exists.

## Integrity

`python manage.py finance_integrity_check` on the copy:

- Posted debit total: 8,495,882.54
- Posted credit total: 8,495,882.54
- Difference: 0
- Unbalanced posted vouchers: 0
- Posted lines on level 1 roots: 0

## Existing vouchers

- 55 posted vouchers existed before the changes, all balanced, with no level 1 root lines.
- 110 voucher lines existed before and after the account recode.
- All 55 existing vouchers have `cash_bank_account = null` because existing vouchers were not rewritten.
- No existing voucher has a wrong cash or bank side after the recode.

## Orphan vouchers never touched

- BR-00016 to BR-00027, Payment reference IDs 372 to 383.
- CR-00004 to CR-00007, Payment reference IDs 385 to 388.
- BP-00009 to BP-00019, OfficeExpense reference IDs 56, 63, 69, 72, 77, 79, 94, 97, 105, 112, 120.

## Foreign keys changed

- `AccountHead.parent`: CASCADE to PROTECT.
- `Voucher.cash_bank_account`: new PROTECT.
- `Payment.received_into`: new PROTECT.
- `Refund.paid_from`: new PROTECT.
- `Expense.expense_account`, `Expense.paid_from`: new PROTECT.
- `ProjectCost.expense_account`, `ProjectCost.paid_from`: new PROTECT.
- `OfficeExpense.expense_account`, `OfficeExpense.paid_from`: new PROTECT.
- `Booking.receivable_account`, `Booking.revenue_account`: new PROTECT.
- `Installment.receivable_account`: new PROTECT.
- `Customer.account_head` was not changed.

`Booking.delete` now refuses deletion when the booking, its payments or its refunds have posted vouchers, so a cascade cannot create new orphans.

## Removed or disabled

- Voucher delete URL: no route exists.
- Voucher API delete: returns 405.
- Voucher admin delete: `has_delete_permission` false and `delete_selected` removed.
- Voucher model and queryset delete: raises ValidationError.
- Voucher line model and queryset delete: raises ValidationError.
- Source record delete with a posted voucher: blocked in model, web and API paths.

## Behaviour changes the client will notice

- Account codes are generated, not typed. Nature is no longer a form field.
- Level 1 roots are fixed.
- Create account requires a parent.
- Cash and bank flags are available only under Assets.
- Cash and bank vouchers no longer show debit and credit columns. They show a cash or bank account and contra lines with an amount.
- Journal vouchers must balance before saving.
- Vouchers cannot be deleted anywhere.
- Booking now creates a receivable and revenue journal when confirmed, active or completed.
- Booking voucher date is the booking date.
- Installments show a linked receivable account.
- Payment and Refund forms require a received-into or paid-from account.
- Expense, Project Cost and Office Expense forms require an expense account. Project Cost and Office Expense also require paid-from.

## Migrations added

1. `finance/0010_accounthead_roles_and_kind.py`: adds account kind, system role, code editability, parent PROTECT and the system role unique constraint. Schema only.
2. `finance/0011_seed_chart_of_accounts.py`: seeds roots and reference tree, recodes and reparents existing accounts, sets cash and bank flags and system roles. Data migration.
3. `finance/0012_voucher_cash_bank_account.py`: adds the voucher cash or bank account. Schema only.
4. `finance/0013_finance_account_links.py`: adds expense and paid-from fields to ProjectCost and OfficeExpense. Schema only.
5. `payments/0008_finance_account_links.py`: adds received-into to Payment and paid-from to Refund. Schema only.
6. `expenses/0006_finance_account_links.py`: adds expense account and paid-from to Expense. Schema only.
7. `bookings/0006_booking_installment_accounts.py`: adds Booking receivable and revenue accounts and Installment receivable account. Schema only.

There are also pending properties migrations from the previous task: `properties/0009` to `properties/0014`. Applying `migrate` runs them too.

## Commands for the real database

Back up the database first. Then:

```powershell
$env:PYTHONPATH=$null
$env:DJANGO_DEBUG='False'
D:\samana\.venv312\Scripts\python.exe manage.py migrate
D:\samana\.venv312\Scripts\python.exe manage.py backfill_finance_links --dry-run
D:\samana\.venv312\Scripts\python.exe manage.py backfill_finance_links
D:\samana\.venv312\Scripts\python.exe manage.py finance_integrity_check
```

## Tests added

- Stage 1: `finance/tests_stage1_coa.py`, 13 tests.
- Stage 2: `finance/tests_stage2_vouchers.py`, 17 tests.
- Stage 3: `finance/tests_stage3_links.py`, 17 tests.
- Stage 3 backfill: `finance/tests_backfill_links.py`, 2 tests.

Final full suite after the follow-up: 1,077 tests, OK, 0 failures. `makemigrations --check` reports no changes.

## Follow-up: orphan voucher report

The 27 orphan vouchers were not changed.

| Voucher | Date | Created at | Narration | Amount |
|---|---|---|---|---|
| BR-00016 | 2026-08-01 | 2026-10-09 22:03:00 | Payment PAY-00019 - Bank Transfer | 300,000.00 |
| BR-00017 | 2026-08-01 | 2026-10-09 22:03:01 | Payment PAY-00020 - Bank Transfer | 200,000.00 |
| BR-00018 | 2026-08-01 | 2026-10-09 22:03:02 | Payment PAY-00021 - Bank Transfer | 200,000.00 |
| BR-00019 | 2026-08-01 | 2026-10-09 22:03:04 | Payment PAY-00022 - Cheque | 200,000.00 |
| BR-00020 | 2026-08-01 | 2026-10-09 22:03:05 | Payment PAY-00023 - Bank Transfer | 200,000.00 |
| BR-00021 | 2026-08-01 | 2026-10-09 22:05:56 | Payment PAY-00019 - Bank Transfer | 200,000.00 |
| BR-00022 | 2026-08-01 | 2026-10-09 22:09:43 | Payment PAY-00019 - Bank Transfer | 300,000.00 |
| BR-00023 | 2026-08-01 | 2026-10-09 22:09:44 | Payment PAY-00020 - Bank Transfer | 200,000.00 |
| BR-00024 | 2026-08-01 | 2026-10-09 22:09:45 | Payment PAY-00021 - Bank Transfer | 200,000.00 |
| BR-00025 | 2026-08-01 | 2026-10-09 22:09:46 | Payment PAY-00022 - Cheque | 200,000.00 |
| BR-00026 | 2026-08-01 | 2026-10-09 22:09:48 | Payment PAY-00023 - Bank Transfer | 200,000.00 |
| BR-00027 | 2026-08-01 | 2026-10-09 22:09:49 | Payment PAY-00024 - Bank Transfer | 300,000.00 |
| CR-00004 | 2026-01-05 | 2026-10-12 11:34:19 | Payment PAY-00020 - Cash | 500,000.00 |
| CR-00005 | 2026-01-05 | 2026-10-12 11:36:20 | Payment PAY-00021 - Cash | 500,000.00 |
| CR-00006 | 2026-01-05 | 2026-10-12 11:37:14 | Payment PAY-00022 - Cash | 500,000.00 |
| CR-00007 | 2026-01-05 | 2026-10-12 12:16:39 | Payment PAY-00023 - Cash | 500,000.00 |
| BP-00009 | 2026-10-09 | 2026-10-09 15:39:55 | Office expense - QA-HO-1791560390903-729880 | 25,000.00 |
| BP-00010 | 2026-10-09 | 2026-10-09 15:40:22 | Office expense - QA-HO-1791560422801-528107 | 25,000.00 |
| BP-00011 | 2026-10-09 | 2026-10-09 15:40:32 | Office expense - QA-HO-1791560432656-115297 | 25,000.00 |
| BP-00012 | 2026-10-09 | 2026-10-09 15:49:49 | Office expense - QA-HO-1791560989762-262178 | 25,000.00 |
| BP-00013 | 2026-10-09 | 2026-10-09 19:17:32 | Office expense - QA-HO-1791573452134-644027 | 25,000.00 |
| BP-00014 | 2026-10-09 | 2026-10-09 21:43:04 | Office expense - QA-HO-1791582182013-111287 | 25,000.00 |
| BP-00015 | 2026-10-09 | 2026-10-09 21:45:43 | Office expense - QA-HO-1791582340996-949936 | 25,000.00 |
| BP-00016 | 2026-10-09 | 2026-10-09 21:55:08 | Office expense - QA-HO-1791582906001-972301 | 25,000.00 |
| BP-00017 | 2026-10-09 | 2026-10-09 21:55:37 | Office expense - QA-HO-1791582937671-7146 | 30,000.00 |
| BP-00018 | 2026-10-09 | 2026-10-09 21:59:49 | Office expense - QA-HO-1791583187345-517614 | 25,000.00 |
| BP-00019 | 2026-10-09 | 2026-10-09 22:00:16 | Office expense - QA-HO-1791583216202-566195 | 30,000.00 |

- The 16 receipt orphans (BR and CR) credited Accounts Receivable by **4,700,000.00**.
- Receivable balance including orphans: **-4,977,607.90**.
- Receivable balance excluding the 16 receipt orphans: **-277,607.90**.
- The 11 BP orphans do not affect Accounts Receivable.

The dates and narrations strongly suggest deleted QA test data. The BP narrations contain QA prefixes and millisecond-stamped names. Several BR and CR vouchers repeat the same payment narration across multiple vouchers, and all were created in short test-like bursts on 2026-10-09 and 2026-10-12. They do not look like normal production payments.

## Follow-up: Booking cancellation and reopen

Cancellation:
- If a Booking voucher exists, cancel posts `BookingCancel` as a JV dated the cancel date.
- Lines: Dr revenue role account, Cr receivable role account.
- Amount: original Booking voucher total debit.
- Idempotent by `reference_type='BookingCancel'` and `reference_id=booking.pk`.
- Cancel twice does not post twice.
- Cancel is allowed after refunds fully cover verified payments. The web and API guards now compare verified payments against non-rejected refunds.

Reopen:
- If a BookingCancel voucher exists and no BookingReopen voucher exists, reopen posts `BookingReopen` as a JV dated the reopen date.
- Lines: Dr receivable role account, Cr revenue role account.
- Amount: BookingCancel voucher total debit.
- Idempotent by `reference_type='BookingReopen'` and `reference_id=booking.pk`.
- Reopen twice does not post twice.
- If no BookingCancel voucher exists, reopen does not post.

Exact limitation:
- One cancel and one reopen cycle per booking is supported. A second cancel after a reopen does not post another reversal because the single BookingCancel reference already exists. This is recorded as an open item.

## Follow-up: payments on bookings without Booking vouchers

All 19 existing payments are on bookings with no Booking voucher because Booking posting has not been run on the real database.

| Booking | Status | Payment | Amount | Payment status |
|---|---|---|---|---|
| BKG-00007 | active | PAY-00014 | 18,888.89 | pending |
| BKG-00007 | active | PAY-00017 | 18,888.89 | pending |
| BKG-00007 | active | PAY-00002 | 18,888.89 | verified |
| BKG-00007 | active | PAY-00005 | 18,888.89 | verified |
| BKG-00007 | active | PAY-00008 | 18,888.89 | verified |
| BKG-00008 | active | PAY-00015 | 9,296.88 | pending |
| BKG-00008 | active | PAY-00018 | 9,296.88 | verified |
| BKG-00008 | active | PAY-00003 | 9,296.88 | verified |
| BKG-00008 | active | PAY-00006 | 9,296.88 | verified |
| BKG-00008 | active | PAY-00009 | 9,296.88 | verified |
| BKG-00009 | active | PAY-00016 | 5,000.00 | pending |
| BKG-00009 | active | PAY-00004 | 5,000.00 | verified |
| BKG-00009 | active | PAY-00007 | 5,000.00 | verified |
| BKG-00009 | active | PAY-00010 | 5,000.00 | verified |
| BKG-00010 | completed | PAY-00011 | 21,726.35 | verified |
| BKG-00010 | completed | PAY-00012 | 21,726.35 | verified |
| BKG-00010 | completed | PAY-00013 | 21,726.35 | verified |
| BKG-00011 | pending | PAY-00019 | 50,000.00 | verified |
| BKG-00012 | pending | PAY-00020 | 1,500.00 | verified |

Total: **277,607.90**.

Pending booking payments:
- BKG-00011: PAY-00019, 50,000.00, verified.
- BKG-00012: PAY-00020, 1,500.00, verified.

Options:
1. Post Booking vouchers for pending bookings. Ledger effect: Dr Accounts Receivable and Cr Revenue for the full booking amount. BKG-00011 adds 1,185,600.00 and BKG-00012 adds 15,000,000.00. After their existing receipts, BKG-00011 would show 1,135,600.00 debit and BKG-00012 would show 14,998,500.00 debit. This treats pending bookings as sales.
2. Treat pending receipts as customer advances. Ledger effect: reclassify 50,000.00 and 1,500.00 from Accounts Receivable to Customer Advances, or change Payment posting to credit Customer Advances while the booking is pending. Accounts Receivable returns to zero for these two bookings and Customer Advances increases by 51,500.00. When the booking is confirmed, post the Booking voucher and apply the advance against the receivable. Recommended because the bookings are not confirmed.

Not implemented.

## Follow-up: migration 0011 robustness

On a copy with fake legacy heads, migration 0011 handled all cases without crashing and preserved the fake voucher line.

| Fake old code | New code | Placed under |
|---|---|---|
| A00001 | 1.10 | Root 1 Assets |
| A00002 | 1.10.1 | A00001 |
| A00003 | 1.10.1.1 | A00002 |
| L00001 | 2.1.4 | 2.1 Current Liabilities |
| C00001 | 3.2 | Root 3 Capital |
| R00001 | 4.1.2 | 4.1 Sales Revenue |
| E00001 | 5.1.5 | 5.1 Operating Expenses |
| X00001 | 1.9.1 | 1.9 Holding - Unclassified |

- Nested fake heads stayed under their mapped parents.
- Fake heads that would exceed four levels were moved up the root chain until they fit.
- Unknown prefixes went to `1.9 Holding - Unclassified`.
- Mixed natures were replaced by the target root nature.
- The fake voucher line still pointed to the same account ID after recoding.
- Test: `finance/tests_migration_0011.py`.

## Follow-up: legacy voucher narration edit

The existing voucher detail page and ledger both render for a posted voucher with `cash_bank_account = null`. The API previously rejected a narration-only edit on such a voucher because it demanded a cash or bank account. The serializer now allows header-only edits on legacy cash and bank vouchers when no lines or cash account are supplied. A test covers detail view, unlock, narration edit and ledger view.

## Follow-up changed items

| Item | Status | Files or result |
|---|---|---|
| Orphan voucher detail report | Done, no data change | This file, orphan section |
| AR credit by 16 receipt orphans | Done | 4,700,000.00 |
| Receivable excluding orphans | Done | -277,607.90 |
| Booking cancel reversal | Done | `finance/accounting.py`, `bookings/models.py`, `core/views.py`, `bookings/api_views.py` |
| Cancel allowed after full refund | Done | `core/views.py`, `bookings/api_views.py` |
| Reopen restatement | Done | `finance/accounting.py`, `bookings/models.py` |
| Cancel/reopen tests | Done | `finance/tests_stage3_links.py` |
| Pending payment options | Reported only | This file |
| Migration 0011 robustness | Fixed and tested | `finance/migrations/0011_seed_chart_of_accounts.py`, `finance/tests_migration_0011.py` |
| Legacy voucher narration edit | Fixed and tested | `finance/serializers.py`, `finance/tests_stage2_vouchers.py` |

## Expense Categories list actions

What existed before:
- Create: yes. URL `/finance/expense-categories/create/`, view `expense_category_create_view`.
- Edit: yes. URL `/finance/expense-categories/<pk>/edit/`, view `expense_category_edit_view`.
- Delete: yes. URL `/finance/expense-categories/<pk>/delete/`, view `expense_category_delete_view`.
- API: `ExpenseCategoryViewSet` already exposed list, create, retrieve, update and delete.

What was missing:
- No Actions column on the list page.
- Edit and delete existed in the backend but were not reachable from the list.
- No case-insensitive duplicate validation.
- Delete did not check whether the category was in use.
- `OfficeExpense.category` used SET_NULL, so deleting a category silently detached expenses.
- No Deactivate or Activate action for used categories.
- The delete permission was stricter than create.

What changed:
- Added Actions column with Edit, Delete and, when used, Deactivate or Activate.
- Used categories show a disabled Delete button with a tooltip and an active toggle button.
- Unused categories show Edit and a Delete link to the existing confirmation page.
- Delete is POST only and CSRF protected.
- Delete is blocked when any reverse FK references the category. The message is `This category is used by N records. Deactivate it instead.`
- Added case-insensitive name validation in the form, serializer and a database unique constraint on Lower(name).
- Changed `OfficeExpense.category` from SET_NULL to PROTECT.
- Delete web permission now matches create: `finance_or_above`.
- API DELETE of a used category returns 400 with the same message.
- API permissions remain `IsFinanceOrAbove`, matching create.
- Added `expense_category_toggle_active_view` and URL.

Type column explanation:
- `category_type` is a choice field, not a free field and not auto-filled.
- The seven seeded category names are Rent, Utilities, Internet, Maintenance, Stationery, Salaries and Miscellaneous, which are the same words as their type labels.
- That is why Type appears to repeat Name for those seven rows.
- No fix is required unless custom names are introduced. If the client wants names different from the type labels, the existing Type dropdown already supports that and only the Name needs editing.

Foreign keys to ExpenseCategory:
- `OfficeExpense.category`: changed from SET_NULL to PROTECT.
- No other model currently has an FK to ExpenseCategory.
- The delete guard also counts every reverse relation dynamically, so future FKs are covered.

Files changed:
- `finance/models.py`
- `finance/forms.py`
- `finance/serializers.py`
- `finance/views.py`
- `finance/urls.py`
- `finance/api_views.py`
- `templates/finance/expense_categories.html`
- `finance/tests_expense_categories.py`
- `finance/migrations/0014_expense_category_actions.py`

Migration:
- `finance/0014_expense_category_actions.py`: changes OfficeExpense.category to PROTECT and adds the case-insensitive name constraint. Schema only.

Tests:
- `finance/tests_expense_categories.py`, 12 tests.
- Final full suite: 1,089 tests, OK, 0 failures.
- `makemigrations --check`: no changes detected.

## Assumptions

- Accounts Receivable is the shared receivable control account. Customer account linking was not changed.
- Refunds debit Accounts Receivable, matching the existing cash receipt reversal pattern.
- Booking revenue is recognized at confirmed, active or completed status. Pending and cancelled bookings do not post.
- If the revenue system role changes, new Booking vouchers use the new account. Existing posted vouchers are not rewritten.
- Approved unpaid expenses credit Accounts Payable. The current Expense UI posts on approve, so a later paid transition does not create a second voucher.
- Existing vouchers are not rewritten. Their `cash_bank_account` remains null.
- Orphan vouchers are never modified or backfilled.

## Cash basis revenue recognition (2026-10-20)

This section supersedes the earlier accrual assumptions above.

New mapping:
- Booking confirmation, cancellation and reopen: no ledger voucher is posted.
- Payment received on pending, confirmed, active or completed bookings: Dr selected cash or bank, Cr the account with system role `revenue` (currently 4.1.1 Plot Sales Revenue).
- Refund paid: Dr the `revenue` account, Cr selected cash or bank. No receivable or customer advances account is used.
- The revenue account remains configurable through `AccountHead.system_role='revenue'`.
- Receivable and customer advances system roles stay seeded and linked for reporting and legacy data, but new cash-basis postings do not use them.
- The existing `refunds` role (Refunds Payable) is also seeded and remains unused; this task debits Revenue directly rather than adding a Sales Refunds contra account.

Existing vouchers:
- No existing voucher is edited or deleted.
- `convert_to_cash_basis` posts additive correcting journals with `reference_type='CashBasisConversion'`, idempotent on the source voucher id.
- Old Payment vouchers that credited Receivable: Dr Receivable, Cr Revenue for the credited amount, dated the payment date.
- Old Booking vouchers: Dr Revenue, Cr Receivable for the voucher total, dated the booking date.
- `backfill_finance_links` no longer creates Booking vouchers. It still links booking and installment receivable accounts for legacy reporting, but those links do not post.

Files changed:
- `finance/accounting.py`
- `bookings/models.py`
- `finance/management/commands/backfill_finance_links.py`
- `finance/management/commands/convert_to_cash_basis.py`
- `finance/tests_cash_basis.py`
- Updated finance tests for cash-basis expectations.

Copy database conversion result:
- Copy: `db.cash-basis-copy.sqlite3`, all migrations applied, providers disabled.
- Dry run: 35 payment corrections, 0 booking reversals.
- Real run on the copy: 35 payment corrections, 0 booking reversals. The copy had no Booking vouchers.
- Receivable before: -4,977,607.90. After: 0.00.
- Revenue before: 0.00. After: 4,977,607.90 (reported as a credit balance).
- Integrity before: debits 6,056,207.90, credits 6,056,207.90, difference 0, unbalanced 0, root lines 0, passed.
- Integrity after: debits 11,033,815.80, credits 11,033,815.80, difference 0, unbalanced 0, root lines 0, passed.
- Second conversion run: 0 corrections, receivable 0.00, revenue 4,977,607.90.

Report and dashboard values before and after conversion were unchanged:
- Dashboard total revenue: 542,448.08.
- Financial Reports total revenue: 225,533.24.
- Receivables total: 17,300,678.12.
- Sales Report total sales: 18,625,274.64.

No migrations were added. `makemigrations --check --dry-run`: no changes detected.

Tests:
- `finance/tests_cash_basis.py`: cash-basis writing, no booking vouchers, configurable revenue, conversion dry-run, idempotency, zero receivable, unchanged reports.
- Finance suite: 216 tests OK.
- Full suite: 1121 tests, OK, 0 failures, 0 errors.

## 2026-11-16: Customer liability accounting replaces cash basis

Client decision: every amount received from a customer before final delivery is a customer liability, not revenue. This supersedes the cash-basis mapping recorded earlier in this file.

### Chart of accounts

- `2.1.1` is now named `Customer Advances & Bookings` and keeps the `customer_advances` system role.
- The unused Fixed Assets head `1.2.5 Advances & Bookings` was removed by data migration. The migration stops if that head has ledger lines or children.
- Account heads after migration: 29 on the released database. Cash `1.1.1.1`, Bank `1.1.1.2`, Revenue `4.1.1` and Customer Advances `2.1.1` all exist.

### Final posting map

| Entity | Event | Debit | Credit |
|---|---|---|---|
| Payment | Received before delivery, any booking status | Selected cash or bank | 2.1.1 Customer Advances & Bookings |
| Payment | Received on or after delivery date | Selected cash or bank | 4.1.1 Plot Sales Revenue |
| Refund | Paid before delivery | 2.1.1 Customer Advances & Bookings | Selected cash or bank |
| Refund | Paid on or after delivery date | 4.1.1 Plot Sales Revenue | Selected cash or bank |
| Booking delivery | Marked delivered | 2.1.1 Customer Advances & Bookings | 4.1.1 Plot Sales Revenue, net advances only |
| Booking | Created, confirmed, cancelled or reopened | No voucher | No voucher |
| Expense, Project Cost, Office Expense, Salary | Paid | Selected expense account | Selected cash or bank |

### Delivery workflow

- `Booking.delivery_date` and `Booking.delivered_by` added by schema migration.
- Mark as Delivered is available to super_admin, admin and management.
- Only confirmed, active or completed bookings can be delivered. Pending and cancelled bookings are blocked.
- Delivery date defaults to today and cannot be in the future.
- An unpaid balance shows a warning and requires the explicit confirmation checkbox. Delivery is still allowed.
- The status change, delivery fields and `BookingDelivery` journal are one transaction.
- Delivery is idempotent through the source-voucher guard and cannot be run twice.
- No undo exists. This is an open item.

### Cancellation

Cancellation has no ledger effect of its own. A cancelled booking keeps its advance in Customer Advances until a refund is processed through the refund workflow. No forfeiture rule has been defined.

### Existing data conversion

`convert_to_customer_liability` posts additive correcting journals, `Dr Revenue / Cr Customer Advances & Bookings`, for undelivered booking payments that previously reached revenue. It never edits old vouchers and is idempotent on `(LiabilityConversion, source voucher id)`.

Current database result on the release copy:

- 19 corrections posted.
- Revenue 277,607.90 to 0.00.
- Customer Advances 0.00 to 277,607.90.
- Second run posted 0.

`convert_to_cash_basis` remains as a deprecated command for history only.

### Reports

Dashboard, Financial, Sales and Receivables read business records, not ledger revenue. Their values were compared before and after conversion on a copy and were identical.

### Voucher deletion reversal

This reverses the earlier no-delete rule for a narrow case. Only manual vouchers may be deleted, only by super_admin and admin, and only through `Voucher.delete_manual_voucher(user, reason)`. This needs client acknowledgement:

- The API still returns 405 for DELETE.
- System vouchers remain undeletable and must be corrected at the source record.
- A deletion snapshot is written to `VoucherDeletionLog` with no foreign key to the voucher.
- The voucher number is retired and a gap remains.
