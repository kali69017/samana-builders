# Samana ERP — Data-Integrity Audit Findings Report

**Date:** 26 Aug 2026
**Scope:** Full-model data-entry audit with cross-model impact verification
**Method:** 288 new automated tests that enter data into every model and verify
the effect on all related models (IDs, balances, statuses, receipts, ledger
entries, audit logs, notifications), plus a live-DB consistency scan.

---

## 1. Real bugs found and fixed (13)

Each bug was caught by a failing test, fixed, and the test verified green.

### P0 — Data loss / money integrity

1. **API booking delete silently destroyed payment history.**
   `BookingViewSet` had no delete guard. A booking with verified payments was
   deleted with HTTP 204 and its payments, receipts, and related history
   cascaded away. The web UI had guards; the API did not.
   Fix: `destroy()` now returns 400 when verified payments exist, and releases
   the plot back to `available` on legal deletes. (`bookings/api_views.py`)

2. **API payment verify could drive `advance_paid` past `total_amount`.**
   The verify action did `advance_paid += amount` with no cap (the web path
   capped it), producing negative remaining balances. It also never tracked
   installment overpayment (`unallocated_amount` stayed 0).
   Fix: cap at total + full overpayment tracking mirroring the web flow.
   (`payments/api_views.py`)

3. **Refunds were unbounded.**
   The API accepted a refund larger than everything the customer had paid
   (999,999 refund on a 10K payment).
   Fix: serializer validates refund amount <= verified payments for the booking.
   (`payments/serializers.py`)

4. **Upfront advance at booking time never entered the payment ledger.**
   A customer paying Rs. 75,000 at booking time showed `advance_paid = 75000`
   on the booking, but no Payment row, no receipt, and no entry in the payment
   ledger — the payment history disagreed with the booking balance. This is the
   exact anomaly seen on BKG-00058 (75K advance vs one 25K payment row).
   Fix: both web `booking_create_view` and API `BookingViewSet.perform_create`
   now create a verified `Payment` row (type `down_payment`) plus an automatic
   receipt for the advance. New bookings are ledger-consistent by construction.
   (`core/views.py`, `bookings/api_views.py`)

### P1 — Invalid data accepted

5. **Negative money accepted at the database layer.**
   ORM/admin/seed paths accepted negative `Expense`, `ProjectCost`,
   `OfficeExpense`, `AccountTransaction`, `Payment`, `Installment`, `Booking`
   total/advance, `Reservation` token, `ProjectBudget`, `ProjectInvestment`,
   and `EmployeeSalary` amounts. Serializers and forms rejected negatives, but
   the database itself did not.
   Fix: 12 `CheckConstraint`s added (4 migrations applied: expenses, finance,
   payments, bookings + hr salary). SQLite now rejects negative money on any
   write path. (`expenses/models.py`, `finance/models.py`, `payments/models.py`,
   `bookings/models.py`, `hr/models.py`)

6. **Reservation accepted negative/zero token amounts** and could be created
   on already-booked/sold plots.
   Fix: serializer requires token > 0 and rejects reservations on unavailable
   plots. (`bookings/serializers.py`)

7. **AccountTransaction API accepted negative amounts and invalid directions**
   (`sideways`). Fix: serializer validates amount > 0 and direction in/out.
   (`finance/serializers.py`)

### P2 — Missing duplicate/consistency checks

8. **Employee duplicate CNIC accepted** — two employees could register the same
   CNIC. Fix: serializer-level uniqueness check (mirrors customers).
   (`hr/serializers.py`)

9. **Agent duplicate phone accepted.** Fix: serializer uniqueness check.
   (`core/serializers.py`)

10. **Leave accepted end-date before start-date and zero/negative days.**
    Fix: serializer date-order + days validation. (`hr/serializers.py`)

11. **Booking transfer accepted same-customer transfers and negative fees.**
    Fix: serializer validation. (`bookings/serializers.py`)

### P3 — API/web inconsistency

12. **API booking create sent no booking notification** (web flow did).
    Fix: `perform_create` now sends the booking notification, catch-guarded.
    (`bookings/api_views.py`)

13. **API booking create silently dropped the `agent` field** and allowed
    assigning inactive agents. `BookingCreateSerializer` did not include
    `agent`, so agent assignments via API were lost. Fix: field added +
    active-only validation. (`bookings/serializers.py`)

---

## 2. Test coverage added

288 new tests across 4 audit modules (full suite: 351 -> 639):

| Module | Tests | Coverage |
|---|---|---|
| `api/tests_audit_flows.py` | 87 | customer/booking/plot/reservation/plan/payment/refund flows, ID sequences, advance-ledger consistency |
| `api/tests_audit_money.py` | 78 | payments, installments, receipts, refund bounds, expenses, office/project costs -> ledger, budgets, money invariants |
| `api/tests_audit_crm_hr.py` | 65 | leads, agents, properties, HR structure, salary, payroll, attendance/leave, transfers, notifications, profiles |
| `api/tests_audit_web.py` | 58 | web renders, form submits, notification logs, audit edge cases, settings, role access, nominee, reminders, receivable aging, cancellation policy |

Each test enters data into one model and asserts the impact on every related
model. Edge cases: negative amounts, duplicate identifiers, invalid choices,
cross-booking installment refs, zero-total constraints, overpayment tracking,
refund bounds, role-based access, and singleton settings.

## 3. Live-data consistency scan (dev DB)

A verifier checked all 63 bookings / 81 plots against money invariants:
`advance_paid == verified payments`, `remaining == total - advance`,
unpaid-plan total == remaining, receipts for verified payments, refunds within
paid amounts, plot/book status agreement.

- **Code-level invariants now hold for all new data.**
- **Pre-existing seed-data gaps (not fixed automatically):** exactly 6 bookings
  (BKG-00001..04 seed bookings, BKG-00058 Muaaz Abdullah, BKG-00061 test row)
  have `advance_paid` set but no matching Payment rows; and 100 paid
  installments carry `paid_amount` with no linked Payment row — artifacts of
  demo seed data entered before the fixes.
  - **Backfilled during this audit:** BKG-00058 (Muaaz) — a 50,000
    down-payment Payment (PAY-00066) plus receipt was recorded for the
    upfront advance paid at booking, closing the advance-vs-ledger gap.
    BKG-00056 payment #63 also received its missing receipt. Backup taken
    before mutation: `db.sqlite3.bak-20260826-audit-backfill`.
  - Remaining seed rows (BKG-00001..04, BKG-00061, and the 100 paid
    installments without linked payments) are demo data; backfilling them
    would create synthetic receipt history, left for the owner to decide.
- One pre-existing negative expense ("bad -100", a leftover debug row) was
  corrected to 100 so the new DB constraints could apply.

## 4. Notes / design observations

- Django does not enforce `choices` at the ORM layer — only forms/serializers.
  Tests that check invalid statuses go through the API serializer.
- `ProjectCost` statuses are `draft/approved/paid` (no `pending`).
- `CompanySettings` uses a `load()` singleton (pk=1); tests use `load()`, not
  `objects.first()`.
- Lead phone duplicates are allowed by design (pre-sales enquiries may repeat);
  customer/agent/employee identifiers are enforced unique.
- Root `/` is the public corporate home; the staff dashboard is `/dashboard/`.

## 5. Files changed

Code: `bookings/api_views.py`, `bookings/serializers.py`, `bookings/models.py`,
`payments/api_views.py`, `payments/serializers.py`, `payments/models.py`,
`expenses/models.py`, `finance/models.py`, `finance/serializers.py`,
`core/views.py`, `core/serializers.py`, `hr/models.py`, `hr/serializers.py`.

Migrations: `expenses/0002`, `finance/0003`, `payments/0006`,
`bookings/0004`, `hr/0002` (constraints).

Tests: `api/tests_audit_flows.py`, `api/tests_audit_money.py`,
`api/tests_audit_crm_hr.py`, `api/tests_audit_web.py` (new);
`api/tests.py`, `api/tests_flaw_fixes.py`, `api/tests_real_estate.py`
(adjusted for new contracts).

All changes remain uncommitted for review (`git diff`).
