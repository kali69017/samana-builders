# HR — Test Plan

> QA test plan for the `hr` module (Django 6 + DRF) of Samana Builders ERP.
> Scenario IDs are the contract Phase C test names must match. Source of truth for
> findings: `docs/qa/hr_analysis.md`; role/permission/URL context: `docs/qa/_shared-context.md`.

## 1. Scope & roles

This plan covers the full workforce + payroll cycle in `hr`: departments, designations,
component-based salary structures, employees (`EMP-xxxxx` auto-ID), monthly payroll runs
(generate → process → pay, posting one ledger row per salary payment), salary slips and
slip items, bulk attendance, leave apply/approve, and the employee self-service "My Leave"
portal. It also covers the DRF API surface and the security posture of both layers.

Roles that exercise the module (and the ones expected to be denied):

- **`hr`** — primary actor: employee/salary CRUD, payroll run lifecycle, bulk attendance,
  leave approval, employee profile (login) creation.
- **`accounts`** — can view payroll and run **pay** (posts to ledger); denied HR master CRUD.
- **`management` / `admin` / `super_admin`** — full HR management.
- **`staff` linked to an `Employee`** — self-service "My Leave"; must be denied admin nav
  and must NOT see other employees' data.
- **`sales` (or any low-privilege authenticated user)** — expected denied on server-rendered
  HR pages (redirect to `/dashboard/`); **the DRF API is the exception and is expected to
  FAIL open (see SEC-01)**.

## 2. Preconditions & fixtures

All tests run against `http://127.0.0.1:8000` with `DJANGO_DEBUG=True` (else
`SECURE_SSL_REDIRECT` 301s every request). Default superuser `admin` / `admin123`.

Fixtures (create via Django shell, the admin UI, or the API; timestamp/unique-suffix values
so runs never collide):

- **Roles**: `hr`, `accounts`, `management`, `sales` profiles; one `staff` user linked to an
  `Employee` via the `Employee.user` OneToOne (use `/hr/employee-profile/` or
  `EmployeeProfileForm.save()` which also creates a `UserProfile(role='staff')`).
- **Master data**: one Department, one Designation, earning component "Basic Salary"
  (`earning`), deduction component "Income Tax" (`deduction`).
- **Employees**:
  - `A` (active, Basic 50000) → net > 0.
  - `B` (active, **no salary components**) → net = 0 (critical `pay`-fails fixture).
  - `C` (active, Basic 50000 + Tax 60000) → net < 0 (critical `pay`-fails fixture).
  - `D` (`on_leave`) and `E` (`resigned`) → verify `generate_slips` filters to `active` only.
  - `F` (active, `staff` user linked) → self-service actor.
  - `G` (active, distinct CNIC `37405-0235722-4`) → CNIC bypass fixture.
- **PayrollRun isolation**: `(month, year)` is globally unique — use a fresh month/year per
  test (e.g. 01/2026, 02/2026, …) or clean up runs between tests.

URLs exercised (server-rendered, under `/hr/`): `employees/`, `employees/create/`,
`employees/<pk>/`, `payroll/`, `payroll/create/`, `payroll/<pk>/` (+ `generate|process|pay`),
`slips/<pk>/`, `slips/<pk>/add-item/`, `slip-items/<pk>/remove/`, `attendance/`,
`attendance/create/`, `leaves/`, `leaves/create/`, `leaves/<pk>/approve/`, `my-leave/`,
`my-leave/apply/`, `employee-profile/`, `payroll-report/`.

API URLs (DRF router, flat under `/api/`, session auth): `/api/employees/`,
`/api/employee-salaries/`, `/api/payroll-runs/` (+ `/<pk>/generate|process|pay/`),
`/api/salary-slips/`, `/api/salary-payments/`, `/api/attendance/`, `/api/leaves/`
(+ `/<pk>/approve|reject/`), `/api/departments/`, `/api/designations/`, `/api/salary-components/`.

## 3. Scenario catalog

### HP — happy path

**HR-HP-01 — Create employee: `EMP-xxxxx` auto-ID and `monthly_gross` from salary components**
- **Preconditions**: logged in as `hr`; one Department and one Designation exist; earning
  component "Basic Salary" exists.
- **Steps**:
  1. Navigate to `/hr/employees/create/` and submit first/last name, department, designation,
     joining_date (and CNIC `3740502357224`).
  2. Note the redirect to the employee detail page.
  3. On the detail page, add salary component "Basic Salary" amount `50000` via
     `/hr/employees/<pk>/salary/add/`.
  4. Re-open the employee detail page.
- **Expected result**: employee is created with `employee_id` `EMP-00001` (monotonic,
  5-digit zero-padded suffix); the CNIC is stored/displayed as canonical
   `37405-0235722-4`; the detail page `monthly_gross` shows `50000.00` (sum of `earning`
  components only; a deduction component would NOT add to it).
- **Evidence on failure**: stored `Employee.employee_id` is empty/wrong format or a duplicate
  key 500 under concurrency; `monthly_gross` on the detail page is `0` or excludes/incorrectly
  includes components.

**HR-HP-02 — Payroll run generate → process → pay posts the ledger exactly once**
- **Preconditions**: logged in as `hr` (or `accounts` for the pay step); active Employee A
  (Basic 50000); a fresh `(month, year)`.
- **Steps**:
  1. `/hr/payroll/create/` → create run for the fresh month/year.
  2. `/hr/payroll/<pk>/generate/` → then `/hr/payroll/<pk>/process/`.
  3. `/hr/payroll/<pk>/pay/`.
  4. Inspect `SalaryPayment` and `AccountTransaction` rows.
- **Expected result**: generate creates one `SalarySlip` (draft) for Employee A with
  `gross=net=50000`; process sets slip `approved` and run `processed`; pay creates one
  `SalaryPayment(amount=50000)` and exactly **one** `AccountTransaction`
  (`reference_type='SalaryPayment'`, `reference_id=<payment.pk>`, `transaction_type='payroll'`,
  `direction='out'`, `category='Salary'`); slip → `paid`, run → `paid`.
- **Evidence on failure**: zero or more-than-one ledger row for the payment; wrong
  `transaction_type`/`direction`/`category`; slip/run status not advanced.

**HR-HP-03 — Salary slip recalculation (`recalculate`) recomputes gross/net from items**
- **Preconditions**: a draft slip for Employee A (Basic 50000 + Tax 5000) exists on a draft run.
- **Steps**:
  1. Open `/hr/slips/<pk>/`; note `gross`, `total_earnings`, `total_deductions`, `net`.
  2. Add an earning item "Allowance" 10000 via `/hr/slips/<pk>/add-item/`.
  3. Re-open the slip.
- **Expected result**: `gross=total_earnings=60000`, `total_deductions=5000`,
  `net=55000` (earnings − deductions), exactly matching the item rows.
- **Evidence on failure**: displayed totals diverge from the sum of `SalarySlipItem.amount`
  rows (recalc drift), or `net` wrong sign.

**HR-HP-04 — Bulk attendance mark updates, never duplicates, per employee+date**
- **Preconditions**: logged in as `hr`; active Employees A and D (`on_leave`) exist.
- **Steps**:
  1. `/hr/attendance/create/` → set Employee A `absent`, leave Employee D at default
     (should pre-fill `leave`), submit with a chosen date.
  2. Re-open the same date and re-submit with A changed to `present`.
- **Expected result**: step 1 creates one `Attendance` row per employee (A=absent, D=leave);
  step 2 **updates** A to `present` (same `(employee,date)` row, no duplicate) and does not
  create a second row. The `hr_attendance` list shows exactly one row per employee for that date.
- **Evidence on failure**: duplicate `Attendance` rows for the same `(employee,date)` (would
  also hit the `unique_together` constraint → 500), or an `on_leave` employee not coerced to `leave`.

**HR-HP-05 — Leave apply then approve (with `approved_by` stamp)**
- **Preconditions**: Employee F (staff) applies via self-service; `hr` approves via admin path.
- **Steps**:
  1. As F at `/hr/my-leave/apply/`, submit `leave_type=annual`, start/end covering 3 days,
     `days=3`, reason.
  2. As `hr` at `/hr/leaves/`, open the pending leave and POST approve via
     `/hr/leaves/<pk>/approve/`.
- **Expected result**: leave created with `status='pending'`, bound to F only; after approval
  `status='approved'` and `approved_by` = the approving `hr` user; the leave appears in F's
  "My Leave" with the correct status.
- **Evidence on failure**: leave bound to a different employee; `approved_by` null after the
  approve action; status not advancing.

**HR-HP-06 — Employee self-service portal hides admin nav and scopes data to self**
- **Preconditions**: a `staff` user linked to Employee F; an unrelated Employee A also exists.
- **Steps**:
  1. Log in as the staff user and land post-login.
  2. Inspect the sidebar and visit `/hr/my-leave/`.
- **Expected result**: `is_employee=True` hides all admin/HR nav items (departments,
  payroll runs, employees list, salary components, attendance, report); "My Leave" shows
  **only F's** requests and a balance table; no link/route exposes A's data.
- **Evidence on failure**: admin nav still rendered for the staff user; My Leave lists other
  employees' leaves.

### EC — edge case / boundary

**HR-EC-01 — Zero- or negative-net slip breaks the whole pay run (CRITICAL repro)**
- **Preconditions**: logged in as `hr`; active Employees A (Basic 50000, net>0) and B
  (no salary components, net=0) — optionally also C (net<0). A fresh `(month, year)`.
- **Steps**:
  1. Create the run, then POST generate, then POST process (all three slips become `approved`).
  2. POST pay.
- **Expected result (correct behaviour)**: the zero/negative-net slip is skipped and does not
  block the others.
- **Actual/failing result**: `pay` iterates approved slips and creates
  `SalaryPayment(amount=0)` (or negative) for B/C, calls `post_to_ledger()`, which writes an
  `AccountTransaction` violating `account_transaction_amount_positive` → `IntegrityError`
  inside `transaction.atomic()` → **the whole pay run rolls back** and the view returns 500.
- **Evidence on failure**: HTTP 500 on `/hr/payroll/<pk>/pay/`; `AccountTransaction` count = 0
  (Employee A's otherwise-valid payment was rolled back too); `SalaryPayment` count = 0;
  run status still `processed`, slips still `approved`. Reproduce for the negative-net variant
  by giving B earning 50000 + deduction 60000.

**HR-EC-02 — Duplicate payroll month via API returns 500**
- **Preconditions**: logged in as `hr`; a `PayrollRun` already exists for `(month=1, year=2026)`.
- **Steps**: `POST /api/payroll-runs/` with `{"month": 1, "year": 2026}`.
- **Expected result (correct)**: 400 with a uniqueness validation error.
- **Actual/failing result**: the serializer has no `UniqueTogetherValidator`, so the create
  hits the DB `unique_together ['month','year']` → `IntegrityError` → **500**.
- **Evidence on failure**: HTTP 500 response; Django traceback showing
  `UNIQUE constraint failed: hr_payrollrun.month, hr_payrollrun.year`.

**HR-EC-03 — Leave over-allowance is accepted (no balance enforcement)**
- **Preconditions**: Employee F has 0 approved annual days; annual allowance is 18.
- **Steps**:
  1. As `hr`, create a leave for F with `leave_type=annual`, `days=25` (over 18) and approve it.
  2. View F's "My Leave" balance.
- **Expected result (correct)**: blocked or warned at 18.
- **Actual/failing result**: approval succeeds with `days=25`; the portal only clamps the
  display to `remaining=0` (`max(allowance − used, 0)`), so the over-allowance is silently
  persisted with no stored balance field to reconcile against.
- **Evidence on failure**: leave with `days > 18` has `status='approved'`; portal shows
  `remaining=0` while total approved exceeds allowance.

**HR-EC-04 — Slip-item edit on a processed/paid slip (no status guard)**
- **Preconditions**: a run for a unique month has been processed and paid; its slip (for A)
  is `paid` and a ledger row exists.
- **Steps**:
  1. Craft a POST to `/hr/slips/<pk>/add-item/` with `component=<earning id>` and
     `amount=99999`, or POST to `/hr/slip-items/<item_pk>/remove/`.
  2. Re-open the slip.
- **Expected result (correct)**: rejected ("slip is locked").
- **Actual/failing result**: the view has no `slip.status == 'draft'` check (only the template
  hides the button); the item is added/removed and `recalculate()` re-runs, mutating a
  `paid` slip. The ledger row is NOT re-posted (idempotent by design), so the ledger amount
  and slip `net` silently diverge.
- **Evidence on failure**: slip `net` changed on a `paid` slip while the corresponding
  `AccountTransaction.amount` is unchanged.

**HR-EC-05 — Non-numeric slip-item amount → uncaught 500**
- **Preconditions**: a draft slip exists.
- **Steps**: POST `/hr/slips/<pk>/add-item/` with `component=<id>` and `amount=abc`.
- **Expected result (correct)**: a friendly "invalid amount" error.
- **Actual/failing result**: `amount` is read as a raw string and only
  `(SalaryComponent.DoesNotExist, ValueError)` is caught; `Decimal('abc')` raises
  `decimal.InvalidOperation` (an `ArithmeticError`, not `ValueError`) → **uncaught 500**.
  Negative amounts are likewise accepted (no sign constraint on `SalarySlipItem.amount`).
- **Evidence on failure**: HTTP 500; traceback `decimal.InvalidOperation: [<class 'decimal.ConversionSyntax'>]`.

**HR-EC-06 — Pay on a non-processed (draft) run marks it paid with 0 payments**
- **Preconditions**: a draft run with generated (still `draft`) slips.
- **Steps**: craft a POST to `/hr/payroll/<pk>/pay/` before processing.
- **Expected result (correct)**: rejected with "run must be processed first".
- **Actual/failing result**: no `run.status == 'processed'` check in the view (button is only
  hidden in the template); the loop finds no `approved` slips, `paid=0`, yet
  `run.status='paid'` is still set.
- **Evidence on failure**: run shows `paid` with 0 `SalaryPayment` rows and all slips still `draft`.

**HR-EC-07 — CNIC duplicate guard bypassed via API (raw vs canonical dashed)**
- **Preconditions**: Employee G exists with canonical CNIC `37405-0235722-4`.
- **Steps**: `POST /api/employees/` with a new name/joining_date and `"cnic": "3740502357224"`
  (raw 13 digits, no dashes).
- **Expected result (correct)**: 400 duplicate-CNIC error.
- **Actual/failing result**: `EmployeeSerializer.validate_cnic` compares raw strings only (no
  dash normalization, unlike `EmployeeForm.clean_cnic`), so the raw form is treated as a
  different employee and the create succeeds.
- **Evidence on failure**: two employees exist with the same 13-digit CNIC in different
  string forms; the API returns 201 instead of 400.

**HR-EC-08 — Attendance duplicate POST via API → 500**
- **Preconditions**: an `Attendance` row exists for `(employee=A, date=2026-01-15)`.
- **Steps**: `POST /api/attendance/` with the same `employee` and `date`.
- **Expected result (correct)**: 200 update or 400 uniqueness error.
- **Actual/failing result**: the `AttendanceViewSet` has no `update_or_create`/uniqueness
  validation (unlike the bulk view), so the duplicate hits `unique_together ['employee','date']`
  → `IntegrityError` → **500**.
- **Evidence on failure**: HTTP 500; traceback `UNIQUE constraint failed: hr_attendance.employee_id, hr_attendance.date`.

**HR-EC-09 — Bulk attendance with an invalid date silently marks today**
- **Preconditions**: logged in as `hr`.
- **Steps**: POST `/hr/attendance/create/` with `date=not-a-date` and valid per-employee statuses.
- **Expected result (correct)**: field error on the date.
- **Actual/failing result**: `date.fromisoformat` raises `ValueError` which is swallowed and
  defaults to `date.today()` — the mistyped date marks **today** instead of erroring.
- **Evidence on failure**: `Attendance` rows created for today's date despite the invalid input;
  no error message shown.

**HR-EC-10 — Leave form/model accepts an invalid date range or `days=0`**
- **Preconditions**: logged in as `hr`.
- **Steps**: `/hr/leaves/create/` with `start_date=2026-01-10`, `end_date=2026-01-05`
  (end before start) or `days=0`.
- **Expected result (correct)**: form validation error.
- **Actual/failing result**: only the serializer validates `end >= start` and `days > 0`;
  `LeaveForm` and the model do not (`PositiveIntegerField` allows 0), so the admin form
  accepts both.
- **Evidence on failure**: `Leave` persisted with `end_date < start_date` or `days=0`.

### SEC — negative & security

**HR-SEC-01 — HR API read-open: any authenticated user reads the full employee directory (CRITICAL)**
- **Preconditions**: a low-privilege user with role `sales` (the default) — no HR/payroll
  membership — and at least one Employee with a CNIC, phone, email, address, and a salary row.
- **Steps** (precise):
  1. Log in as the `sales` user (session login `/login/`, or `/api/auth/login/` and carry the
     session cookie).
  2. `GET http://127.0.0.1:8000/api/employees/`
  3. Repeat for `/api/salary-slips/`, `/api/salary-payments/`, `/api/payroll-runs/`,
     `/api/attendance/`, `/api/leaves/`, `/api/employee-salaries/`.
- **Expected result (correct)**: 403 — these are server-rendered-only, gated behind
  `@payroll_access`/`@hr_required`; a `sales` user has no HR/payroll access.
- **Actual/failing result**: `IsHRManagement.has_permission` returns `True` for
  `SAFE_METHODS` for **any authenticated user** (no role check, contrast
  `core/api_views.IsStaffOrAbove`), so every endpoint returns **200** with the full directory:
  `cnic`, `phone`, `email`, `address`, nested `salaries` **amounts**, `SalarySlip` gross/net,
  `SalaryPayment` amounts, and `PayrollRun.total_net`.
- **Evidence on failure**: HTTP 200 body contains employee PII (search the JSON for a seeded
  CNIC/phone). Cross-check: the same user hitting server-rendered `/hr/employees/` is
  redirected to `/dashboard/` with a permission message — proving the API and UI disagree.

**HR-SEC-02 — `LeaveSerializer.status` writable: self-approve bypassing the `approve` action (CRITICAL)**
- **Preconditions**: an `hr`-role user (any HR write-capable user) and an existing leave
  (or none — create path also works). To demonstrate the self-approve angle, use an `hr` user
  who is also the `employee` of the leave.
- **Steps** (precise):
  1. `POST /api/leaves/` with `{"employee": <id>, "leave_type": "annual", "start_date":
     "2026-02-01", "end_date": "2026-02-03", "days": 3, "status": "approved"}` —
     or `PATCH /api/leaves/<pk>/` with `{"status": "approved"}` on an existing pending leave.
  2. Read the response `status` and `approved_by`.
- **Expected result (correct)**: `status` should be read-only; approval must go through
  `POST /api/leaves/<pk>/approve/`, which sets `approved_by=request.user`.
- **Actual/failing result**: `status` is a writable field (not in `read_only_fields`), so the
  leave is created/updated directly to `approved` with **`approved_by=null`** — bypassing the
  approve action and its audit stamp (and the action's `approved_by` side effect). An `hr`
  user can thereby approve their own leave with no recorded approver.
- **Evidence on failure**: response `status` is `approved` while `approved_by` is `null`;
  contrast with `POST /api/leaves/<pk>/approve/` which returns `approved_by=<user id>`.

**HR-SEC-03 — Employee deletion leaves a dangling ledger `reference_id` (no guard)**
- **Preconditions**: Employee A has a paid slip → one `AccountTransaction`
  (`reference_type='SalaryPayment'`, `reference_id=<payment.pk>`, `employee=<A>`).
- **Steps**: as `hr`, POST `/hr/employees/<A.pk>/delete/` (confirm page) and delete A.
- **Expected result (correct)**: deletion blocked (like projects-with-plots / offices-with-ledger).
- **Actual/failing result**: `employee_delete_view` has no ledger guard; deleting A cascades
  slips/payments but the `AccountTransaction` row survives with a dangling
  `reference_id` pointing at a deleted `SalaryPayment` (and `employee` SET_NULL).
- **Evidence on failure**: after delete, an `AccountTransaction` with
  `reference_type='SalaryPayment'` references a non-existent `SalaryPayment.pk`.

**HR-SEC-04 — Leave approval has no pending/ownership guard (re-approve/reject any leave by pk)**
- **Preconditions**: an already-approved leave (or any leave pk) and an `hr` user.
- **Steps**: `POST /api/leaves/<pk>/approve/` on an already-approved leave, then
  `POST /api/leaves/<pk>/reject/`, then approve again — or use the server view
  `/hr/leaves/<pk>/approve/` with `action=approve`/`action=reject` on a non-pending leave.
- **Expected result (correct)**: transition only allowed from `pending`; ownership/state checked.
- **Actual/failing result**: both the API actions and `leave_approve_view` set status
  unconditionally with no `status == 'pending'` or ownership check, so a leave can be flipped
  approved → rejected → approved repeatedly, overwriting `approved_by` each time with no audit.
- **Evidence on failure**: a non-pending leave's status changes on approve/reject; no error
  and no traceability of the flip sequence.

**HR-SEC-05 — My Leave cannot be scoped to another employee (negative confirmation)**
- **Preconditions**: a `staff` user linked to Employee F; Employee A exists with a leave.
- **Steps**: as F, attempt to POST `/hr/my-leave/apply/` with a tampered `employee=A`
  (or any foreign id), and attempt to view A's leave by any my-leave URL.
- **Expected result**: the posted `employee` value is ignored (always bound to F); A's leave
  is not reachable from My Leave.
- **Evidence on failure**: a leave created under F's session is bound to A, or My Leave
  renders another employee's records.

### API — API contract

All requests use session auth. Unless noted, writes require an `hr`-role user.

**HR-API-01 — `GET/POST /api/employees/`**
- **Preconditions**: `hr` user; Department/Designation exist.
- **Steps**: `GET /api/employees/`; then `POST` with `first_name`, `last_name`, `joining_date`
  (+ optional cnic/phone/email/address/status).
- **Expected result**: GET lists employees (incl. nested `salaries`); POST returns 201 with
  auto `employee_id` `EMP-xxxxx` and an AuditLog `create` entry.
- **Evidence on failure**: 4xx/5xx on valid POST; missing auto-id; missing nested salaries.

**HR-API-02 — `GET/POST /api/leaves/` (status writable)**
- **Preconditions**: `hr` user; an employee exists.
- **Steps**: `GET /api/leaves/`; `POST` with employee/leave_type/start_date/end_date/days;
  then `POST` again with `"status": "approved"`.
- **Expected result (contract)**: POST validates `end >= start` and `days > 0`; but note
  `status` is writable (see HR-SEC-02) — a leave can be created directly in `approved` state
  with `approved_by=null`.
- **Evidence on failure**: missing range/day validation (end<start accepted); status silently
  writable.

**HR-API-03 — `GET/POST /api/payroll-runs/`**
- **Preconditions**: `hr` user; fresh `(month, year)`.
- **Steps**: `GET /api/payroll-runs/`; `POST` with `month`, `year`, optional `notes`; then
  `POST` a duplicate `(month, year)`.
- **Expected result**: GET lists runs with `total_net`/`slip_count`; first POST returns 201
  with an AuditLog `create`; duplicate POST **should** 400 but currently 500 (HR-EC-02).
- **Evidence on failure**: no `(month,year)` uniqueness validation → 500 on duplicate.

**HR-API-04 — `GET/POST /api/salary-slips/`**
- **Preconditions**: a run + generated slip exist.
- **Steps**: `GET /api/salary-slips/` (note nested `items`); `POST` a slip for a new
  `(employee, run)`.
- **Expected result**: GET lists slips with `gross/total_earnings/total_deductions/net`
  read-only; POST creates a draft slip (gross/net are read-only, derived by recalc).
- **Evidence on failure**: gross/net writable in POST; missing nested items in GET.

**HR-API-05 — `GET/POST /api/salary-payments/`**
- **Preconditions**: a slip exists.
- **Steps**: `GET /api/salary-payments/`; `POST` with `slip`, `amount`, `payment_date`,
  `method`.
- **Expected result**: POST creates a `SalaryPayment` and `perform_create` posts one ledger
  row; note there is **no `amount == slip.net` and no `amount > 0` check** — a 0/negative
  amount 500s on the ledger positive-amount constraint (see HR-EC-01 mechanics).
- **Evidence on failure**: ledger not posted on create; amount accepted with no slip.net check.

**HR-API-06 — `GET/POST /api/attendance/`**
- **Preconditions**: an employee exists.
- **Steps**: `GET /api/attendance/` (optionally `?date=` / `?employee=`); `POST` with
  `employee`, `date`, `status`; then `POST` the same `(employee, date)` again.
- **Expected result**: GET filters by date/employee; first POST 201; duplicate POST **should**
  update/400 but currently 500 (HR-EC-08, no uniqueness guard).
- **Evidence on failure**: duplicate POST → 500.

**HR-API-07 — `approve` / `pay` actions**
- **Preconditions**: a leave (pending) and a processed payroll run with approved slips.
- **Steps**: `POST /api/leaves/<pk>/approve/` and `/reject/`; `POST /api/payroll-runs/<pk>/pay/`.
- **Expected result**: approve/reject set status + `approved_by`; pay posts one ledger row per
  new payment and returns `{"paid": n}`. Note: none of these actions guard state — approve
  re-approves non-pending (HR-SEC-04) and pay marks a draft run `paid` (HR-EC-06).
- **Evidence on failure**: `approved_by` not stamped; pay ledger count ≠ paid count; pay
  succeeds on a non-processed run.

## 4. Data isolation rules

- **Unique months/years**: `PayrollRun` is globally unique on `(month, year)` — each test that
  creates a run must use a distinct month/year or clean up the run in teardown.
- **Employee auto-ID**: `EMP-xxxxx` suffixes increment from the last row's suffix; tests that
  assert a specific ID must reset `Employee` state first (or assert only the `EMP-` prefix and
  monotonicity). Deleted max-id employees cause suffix reuse (gap fill) — do not assume
  contiguous IDs across runs.
- **Attendance**: unique `(employee, date)` — use unique dates per test.
- **CNIC**: seed one canonical-dashed employee per test; assert duplicates by 13-digit digits.
- **Ledger**: assert `AccountTransaction` counts by `reference_type='SalaryPayment'` +
  `reference_id` (should be exactly 1 after a single pay, 0 after a rolled-back pay).
- **Teardown**: delete created `PayrollRun`, `SalaryPayment`, `SalarySlip`, `Employee`,
  `Leave`, `Attendance`, and `AccountTransaction` rows created by the test, in that dependency
  order, to keep the shared DB clean.

## 5. Coverage checklist (for the master map)

- HR-HP-01 — Create employee: EMP auto-ID + monthly_gross from salary components
- HR-HP-02 — Payroll generate→process→pay posts ledger exactly once
- HR-HP-03 — Salary slip recalc recomputes gross/net from items
- HR-HP-04 — Bulk attendance mark updates, never duplicates, per employee+date
- HR-HP-05 — Leave apply then approve with approved_by stamp
- HR-HP-06 — Employee self-service portal hides admin nav and scopes to self
- HR-EC-01 — Zero/negative-net slip breaks the whole pay run (rollback → 500)
- HR-EC-02 — Duplicate payroll month via API → 500
- HR-EC-03 — Leave over-allowance accepted (no balance enforcement)
- HR-EC-04 — Slip-item edit on processed/paid slip (no status guard)
- HR-EC-05 — Non-numeric slip-item amount → uncaught 500
- HR-EC-06 — Pay on non-processed run marks paid with 0 payments
- HR-EC-07 — CNIC duplicate guard bypassed via API (raw vs dashed)
- HR-EC-08 — Attendance duplicate POST via API → 500
- HR-EC-09 — Bulk attendance invalid date silently marks today
- HR-EC-10 — Leave form/model accepts invalid range or days=0
- HR-SEC-01 — HR API read-open: any authenticated user reads employee PII (CRITICAL)
- HR-SEC-02 — LeaveSerializer.status writable: self-approve bypassing approve (CRITICAL)
- HR-SEC-03 — Employee deletion leaves dangling ledger reference_id
- HR-SEC-04 — Leave approval has no pending/ownership guard
- HR-SEC-05 — My Leave scoping holds (negative confirmation)
- HR-API-01 — GET/POST /api/employees/
- HR-API-02 — GET/POST /api/leaves/ (status writable)
- HR-API-03 — GET/POST /api/payroll-runs/
- HR-API-04 — GET/POST /api/salary-slips/
- HR-API-05 — GET/POST /api/salary-payments/
- HR-API-06 — GET/POST /api/attendance/
- HR-API-07 — approve/pay actions
