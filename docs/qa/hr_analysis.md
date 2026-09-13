# HR Module — QA Analysis

> Deep QA/security analysis of the `hr` app (Django 6 + DRF) for Samana Builders ERP.
> Read alongside `docs/qa/_shared-context.md` — roles, permission groups, URL map,
> money/decimal conventions and the ledger `reference_type/reference_id` de-dup rule
> are established there and not re-derived here.

## 1. Business purpose & user journeys

The HR module owns the workforce and payroll cycle: departments, designations,
component-based salary structures, employees, monthly payroll runs → salary slips →
salary payments (posted to the finance ledger), attendance, and leave. It also exposes
a customer-style **employee self-service portal** ("My Leave") for employees to apply
for and track their own leave. It matters because it is the only path by which salaries
become ledger entries (`AccountTransaction.transaction_type='payroll'`), so correctness
of the generate→process→pay flow is financially load-bearing.

User journeys (role labels from `core/permissions.py`):

- **HR staff (`hr` role)** — login → HR Overview → add Employee (`EMP-xxxxx` auto-ID) →
  define salary components (Basic Salary, Income Tax, …) → add components to the employee
  → create a PayrollRun for a month → Generate Slips → Process & Approve → Mark Paid
  (posts one ledger row per slip). Also mark bulk attendance and approve/reject leave.
- **Accounts (`accounts` role)** — login → Payroll → open a run → Mark Paid (the `pay`
  flow is gated by `payroll_access`, which includes `accounts`, so accounts can record
  salary payments and post them to the ledger even though they cannot edit HR masters).
- **Management/admin (`management`, `admin`, `super_admin`)** — full HR management incl.
  departments/designations/components CRUD, employee edit/delete, and creating employee
  portal logins (`employee_profile_create_view`).
- **Employee (self-service, `staff` role linked to an `Employee`)** — login → "My Leave"
  → view balance → Apply Leave (own record only) → track pending/approved/rejected. The
  sidebar hides all admin/HR nav for `is_employee` users.

## 2. Data model

All in `hr/models.py`.

- **Department** (`:21`) — `name` (CharField 100, unique), `description` (Text, blank),
  `is_active` (bool default True). Ordering `['name']`. No `clean()`.
- **Designation** (`:33`) — `title` (unique), `is_active`. Ordering `['title']`.
- **SalaryComponent** (`:44`) — `name` (unique), `component_type` in
  `earning|deduction` (default `earning`), `is_active`. Ordering `['component_type','name']`.
- **Employee** (`:61`) — `employee_id` (CharField 20, **unique, editable=False**, auto-generated),
  `user` (OneToOne `User`, SET_NULL, null/blank, `related_name='employee'` — this is what
  drives `is_employee`), `first_name`/`last_name` (required), `department`/`designation`
  (SET_NULL FK, null/blank), `joining_date` (DateField, required), `cnic` (CharField 15,
  blank), `phone` (20, blank), `email` (EmailField, blank), `address` (Text, blank),
  `status` in `active|on_leave|resigned|terminated` (default active), `notes` (Text, blank),
  `created_by` (SET_NULL), timestamps.
  - `save()` (`:86`) auto-generates `EMP-00001` inside `transaction.atomic()` by taking
    `select_for_update().order_by('-id').first()` and incrementing the numeric suffix
    parsed from `last.employee_id.split('-')[1]`.
  - `full_name` property (`:98`), `monthly_gross` property (`:102`) = sum of
    `salaries` where `component__component_type='earning'` (no `is_active` / `effective_from` filter).
  - Indexes on `status`, `department`.
- **EmployeeDocument** (`:114`) — `employee` (CASCADE, `related_name='documents'`),
  `title`, `file` (`upload_to='employee_documents/%Y/%m/'`). No view/serializer — admin
  inline only (noted as a gap in §7).
- **EmployeeSalary** (`:124`) — `employee` (CASCADE, `related_name='salaries'`),
  `component` (CASCADE), `amount` (Decimal 15,2 default 0), `effective_from` (Date, null).
  `unique_together = ['employee','component']` (`:136`); CheckConstraint `amount >= 0`
  (`employee_salary_amount_non_negative`, `:138`). No form/API validation of `amount` beyond
  the DB constraint.
- **PayrollRun** (`:146`) — `month` (PositiveIntegerField, choices 1–12), `year`
  (PositiveIntegerField, unvalidated), `status` in `draft|processed|paid` (default draft),
  `notes`, `created_by`, timestamps. **`unique_together = ['month','year']`** (`:195`).
  - Properties `period_label`, `total_net`, `total_gross`, `slip_count` (`:164`–`:178`).
  - `generate_slips()` (`:180`) — iterates **`Employee.objects.filter(status='active')` only**
    (on_leave/resigned/terminated excluded), `get_or_create` a `SalarySlip`, creates
    `SalarySlipItem` rows from the employee's `EmployeeSalary` components, then calls
    `slip.recalculate()`. Idempotent for existing slips (get_or_create + recalc).
- **SalarySlip** (`:198`) — `employee` (CASCADE, `related_name='salary_slips'`), `run`
  (CASCADE, `related_name='slips'`), `status` in `draft|approved|paid`, `gross`,
  `total_earnings`, `total_deductions`, `net` (all Decimal 15,2 default 0), `notes`.
  `unique_together = ['employee','run']` (`:231`). `recalculate()` (`:219`) recomputes
  earnings/deductions from `items`, sets `gross = earnings`, `net = earnings − deductions`,
  and saves only those four fields.
- **SalarySlipItem** (`:234`) — `slip` (CASCADE, `related_name='items'`), `component`
  (CASCADE), `amount` (Decimal 15,2, **no sign/positive constraint**).
  `unique_together = ['slip','component']` (`:244`).
- **SalaryPayment** (`:247`) — `slip` (OneToOne, CASCADE, `related_name='payment'`),
  `amount` (Decimal 15,2, **no constraint**), `payment_date`, `method` in
  `cash|bank_transfer|cheque|online`, `reference_number` (blank), `created_by`.
  `post_to_ledger()` (`:266`) — `AccountTransaction.update_or_create(reference_type='SalaryPayment',
  reference_id=self.pk, ...)` with `direction='out'`, `transaction_type='payroll'`,
  `category='Salary'`, `employee`, `description`. Idempotent at DB level.
- **Attendance** (`:295`) — `employee` (CASCADE), `date`, `status` in
  `present|absent|half_day|leave|holiday`, `notes`. `unique_together = ['employee','date']`
  (`:314`); index `['date','status']`.
- **Leave** (`:318`) — `employee` (CASCADE, `related_name='leaves'`), `leave_type` in
  `annual|sick|casual|unpaid`, `start_date`, `end_date`, `days` (PositiveIntegerField
  default 1), `reason` (blank), `status` in `pending|approved|rejected`, `approved_by`
  (SET_NULL, null), `applied_on`. Index on `status`. **No model `clean()`** — no
  `end >= start` and no `days > 0` validation at model level (only in the serializer).

`LEAVE_POLICY_ALLOWANCES` (`:14`) = `{annual:18, sick:10, casual:6}` is a hardcoded dict;
"unpaid" has no allowance and the balance table treats it as 0.

## 3. Roles & permissions

Server views use `core/permissions.py`; the DRF API uses the module-local
`IsHRManagement` (`hr/api_views.py:23`). Template flags come from `erp_context`
(`core/context_processors.py`).

| Action | Allowed roles | Enforced by |
|---|---|---|
| HR home / employees list / payroll runs / attendance list / leaves list / payroll report | `PAYROLL_ROLES` (super_admin, admin, management, hr, accounts) | `@payroll_access` (`hr/views.py:34,205,328,464,562,712`) |
| Department / designation / salary component CRUD | `HR_MANAGEMENT_ROLES` (super_admin, admin, management, hr) | `@hr_required` (`hr/views.py:52–200`) |
| Employee create/edit/delete, salary add/remove | HR_MANAGEMENT_ROLES | `@hr_required` (`hr/views.py:231,267,284,297,315`) |
| Employee detail | PAYROLL_ROLES (accounts included) | `@payroll_access` (`hr/views.py:248`) |
| Payroll run create / generate / process | HR_MANAGEMENT_ROLES | `@hr_required` (`hr/views.py:334,365,376`) |
| Payroll run detail / **pay** / salary slip detail | PAYROLL_ROLES (accounts included) | `@payroll_access` (`hr/views.py:351,393,419`) |
| Salary slip add/remove item | HR_MANAGEMENT_ROLES | `@hr_required` (`hr/views.py:431,451`) |
| Attendance bulk mark | HR_MANAGEMENT_ROLES | `@hr_required` (`hr/views.py:475`) |
| Leave create / approve-reject | HR_MANAGEMENT_ROLES | `@hr_required` (`hr/views.py:576,591`) |
| Create employee portal login | HR_MANAGEMENT_ROLES | `@hr_required` (`hr/views.py:604`) |
| My Leave (self-service) | any authenticated user with an `Employee` link | `@login_required` + `getattr(user,'employee')` (`hr/views.py:626,673`) |
| DRF HR ViewSets (departments, designations, salary-components, employees, employee-salaries, payroll-runs, salary-slips, salary-payments, attendance, leaves) | **Read: ANY authenticated user. Write: HR_MANAGEMENT_ROLES** | `IsHRManagement.has_permission` (`hr/api_views.py:23–33`) |

### Object-level gating / IDOR assessment

- **My Leave is correctly scoped** — `my_leave_view`/`my_leave_apply_view` bind the query
  and the created record to `request.user.employee`; the posted `employee` value is
  ignored (`hr/views.py:635,700–702`). No IDOR here.
- **Leave approval (`leave_approve_view`) is intentionally cross-employee** (HR approves
  anyone), but it is `pk`-based with no ownership/status check; any `hr`-role user can
  approve/reject *and* an already-approved leave can be flipped back to `approved`/`rejected`
  again (no guard against re-approving a non-pending leave) (`hr/views.py:592–601`).
- **Salary slip add/remove item has no status guard** — the view (`hr/views.py:431,451`)
  does not check `slip.status == 'draft'`; only the template hides the button
  (`salary_slip_detail.html:35,54`). A crafted POST can mutate items on an **approved or
  paid** slip after it has been posted to the ledger (recalc drift; see §4/§5).
- **The API is the biggest hole**: `IsHRManagement` returns `True` for `SAFE_METHODS` for
  *any authenticated user*, including customer-portal users (there is no staff-role check —
  compare `core/api_views.py` `IsStaffOrAbove`). Any authenticated user can `GET` the full
  employee directory (CNIC, phone, email, address, nested `salaries` amounts), salary slips,
  salary payments, payroll runs and leave. This is the highest-severity finding (§6).

## 4. Business rules, state machines, invariants

**PayrollRun lifecycle:** `draft → processed → paid` (no backward transitions enforced
anywhere in code).

- `generate_slips` (create, idempotent, drafts only in practice) → `process`
  (recalc + set all slips `approved` + run `processed`) → `pay` (for each `approved` slip,
  `get_or_create` a `SalaryPayment` of `slip.net`, `post_to_ledger` **only if created**,
  set slip `paid`, run `paid`).
- **Ledger invariant:** one `AccountTransaction` per `SalaryPayment`, enforced by the DB
  unique constraint `(reference_type, reference_id)` in `finance/models.py:69` and by
  `update_or_create` in `post_to_ledger` (`hr/models.py:277`). Posting is idempotent.

**SalarySlip lifecycle:** `draft → approved → paid`; `recalculate()` is the single source
of truth for `gross/total_earnings/total_deductions/net`, derived from `SalarySlipItem`s.

**Attendance invariant:** `unique_together ['employee','date']` (`hr/models.py:314`);
bulk mark uses `update_or_create` so re-marking updates instead of duplicating
(`hr/views.py:510`).

**Leave:** no balance enforcement. `days` is user-supplied and not reconciled against
`end_date − start_date`. Approval does **not** check the employee's remaining balance, so
over-allowance approval is possible and the "remaining" figure in the portal is purely
cosmetic (`max(allowance − used, 0)` at `hr/views.py:655`).

**Side effects:**
- Ledger posts: `SalaryPayment.post_to_ledger()` (pay flow and
  `SalaryPaymentViewSet.perform_create`, `hr/api_views.py:154`).
- Audit logs: written for department/designation/component/employee/payroll-run/leave
  mutations via `_log` (`hr/views.py:24`) and for API employee/payroll-run creates
  (`hr/api_views.py:73,99`). **No AuditLog for `pay`/`process`/`generate` actions, for
  salary-slip item edits, for attendance bulk, or for leave approval** — a traceability gap.

## 5. Edge cases (deep)

- **Payroll "process" run twice (double process).** Expected: no-op / no duplicate ledger.
  Actual: safe — `process` only recalcs and re-stamps `approved`/`processed`; it never posts
  to the ledger (`hr/views.py:377`, `hr/api_views.py:111`). Idempotent. ✅
- **Payroll "pay" run twice (double pay).** Expected: exactly one ledger row per slip.
  Actual: safe at the ledger (unique constraint + `update_or_create`) and at the slip level
  (second `pay` finds no `approved` slips → `paid=0`) (`hr/views.py:397–411`). ✅
- **Payroll run for the same month twice (unique constraint).** Expected: rejected with a
  clean message. Actual: the **ModelForm** (`PayrollRunForm`) does raise
  `unique_together` validation, but the **API** (`PayrollRunViewSet`) and the model have no
  such guard — `POST /api/payroll-runs/` for an existing `(month,year)` raises
  `IntegrityError` → 500. ❌ (`hr/models.py:195`, `hr/serializers.py:105` has no
  `validate`/`UniqueTogetherValidator`.)
- **Employee with no salary components (empty `monthly_gross`).** Expected: slip with
  net 0, or the pay step skipped. Actual: `generate_slips` creates a slip with no items →
  `net = 0`; `pay` then creates `SalaryPayment(amount=0)` and calls `post_to_ledger()`,
  which writes an `AccountTransaction(amount=0)` — violating the
  `account_transaction_amount_positive` CheckConstraint (`finance/models.py:64`) →
  **IntegrityError inside `transaction.atomic()` rolls back the entire pay run** → 500.
  Same failure if an employee's deductions exceed earnings (negative `net`). ❌ **HIGH.**
- **Salary slip recalc drift.** Expected: manual item edits stay consistent with
  `gross/net`. Actual: `recalculate()` re-derives correctly, but `salary_slip_add_item_view`
  (`hr/views.py:431`) reads `amount` as a raw string and only catches
  `(SalaryComponent.DoesNotExist, ValueError)`; a non-numeric amount raises
  `decimal.InvalidOperation` (subclass of `ArithmeticError`, not `ValueError`) → uncaught
  500. Negative `amount` is accepted (no sign constraint on `SalarySlipItem.amount`). ❌
- **Editing a processed/paid slip.** Expected: locked. Actual: view has no status check
  (§3); a crafted POST can add/remove items and re-run `recalculate()` on an `approved`/`paid`
  slip after the ledger row was posted — the ledger row is *not* re-posted (idempotent by
  design), so the ledger amount and the slip `net` silently diverge. ❌
- **Attendance duplicate entry.** Expected: update not duplicate. Actual: bulk view uses
  `update_or_create` keyed on `(employee,date)` ✅, but the single-record `AttendanceForm`
  is dead code — no view uses it (`hr/forms.py:113`, never referenced in `hr/views.py`).
  The `AttendanceViewSet` (`POST /api/attendance/`) has **no** `update_or_create` guard and
  no uniqueness validation — a duplicate POST raises `IntegrityError` → 500. ❌
- **Bulk attendance for all employees.** Expected: every active employee marked. Actual:
  only `status__in=['active','on_leave']` are included (`hr/views.py:486`); resigned/
  terminated are silently skipped. `notes` is never written. An employee already
  `on_leave` is force-coerced to `leave` unless HR explicitly overrides (`hr/views.py:508`).
  If `date` is invalid, it silently defaults to `date.today()` (`hr/views.py:496`) — a
  mistyped date marks today rather than erroring. ⚠️
- **Leave exceeding balance (negative remaining).** Expected: blocked or at least warned.
  Actual: no enforcement anywhere. `days` is free-form (`hr/views.py:674–707` self-service,
  `hr/views.py:576` admin form); the portal clamps `remaining` to 0 for display only
  (`hr/views.py:655`). An employee can apply for and be approved for more days than their
  allowance. There is no stored `leave_days`/balance field — the "balance" is computed
  on the fly. ❌
- **`days` vs date range mismatch / invalid range.** Expected: `days == end − start + 1`,
  `end >= start`. Actual: only the **serializer** validates `end >= start` and `days > 0`
  (`hr/serializers.py:134–143`); the **form** (`LeaveForm`) and the **model** do not. Via
  the admin form an `end_date` before `start_date` or `days=0` is accepted
  (`PositiveIntegerField` allows 0). ❌
- **Employee ID auto-gen.** Expected: monotonic `EMP-00001…` with no collisions.
  Actual: parses the suffix of `order_by('-id').first()` (`hr/models.py:90`). Correct in
  the single-user dev SQLite case, but (a) `select_for_update()` is a no-op on SQLite, so
  concurrent creates can race and the loser hits the `unique` constraint → 500; (b) it
  orders by `-id`, not `-employee_id` — benign today because the two stay in lockstep, but
  fragile; (c) a deleted max-id employee's suffix is reused (id is not), which is fine for
  uniqueness but means the gap is filled. ⚠️
- **`pay` on a non-processed run.** Expected: rejected. Actual: the view
  (`hr/views.py:393`) has no `run.status == 'processed'` check (the button is only shown in
  the template at `payroll_run_detail.html:31`). A crafted POST on a `draft` run sets
  `run.status='paid'` with `paid=0` payments. ❌
- **Pay date drift.** `SalaryPayment.payment_date` and the ledger `date` use
  `date.today()` (`hr/views.py:402`, `hr/api_views.py:131`), not the run's month/year —
  a run for `01/2026` paid later posts to the ledger under the payment date, not the
  payroll period. ⚠️
- **CNIC duplicate via API.** The form normalizes CNIC to `XXXXX-XXXXXXX-X` and enforces
  13 digits (`hr/forms.py:81–89`); the serializer only checks `cnic` equality against a raw
  string (`hr/serializers.py:53–61`) with no normalization, so `3740502357224` and
  `37405-0235722-4` are treated as different employees — duplicate-CNIC guard bypassable. ⚠️
- **Deleting an employee with paid history.** `employee_delete_view` (`hr/views.py:284`)
  cascades salary slips/payments, but the `AccountTransaction` rows survive with a dangling
  `reference_id` (and `employee` SET_NULL). Unlike projects/offices there is **no deletion
  guard** for employees with ledger rows. ⚠️
- **Wrong verb.** All state-changing views check `if request.method == 'POST'` and fall
  through to redirect otherwise; deletes render a confirm page on GET and only delete on
  POST. Consistent. ✅

## 6. Cross-cutting risks

- **Sensitive data exposure (CRITICAL).** `IsHRManagement.has_permission` grants read
  (`SAFE_METHODS`) to **any authenticated user** (`hr/api_views.py:26–29`), with the global
  DRF default being `IsAuthenticated` (`samana_erp/settings.py:224`). A customer-portal
  user or any low-privilege staff role can `GET /api/hr/employees/` and receive every
  employee's `cnic`, `phone`, `email`, `address`, plus nested `salaries` **amounts**
  (`hr/serializers.py:51`); likewise `/api/hr/salary-slips/`, `/api/hr/salary-payments/`,
  `/api/hr/payroll-runs/` (with `total_net`), `/api/hr/attendance/`, `/api/hr/leaves/`.
  The server-rendered views correctly gate these behind `@payroll_access`/`@hr_required`;
  the API does not.
- **XSS.** Low. No `|safe`/`mark_safe`/`autoescape off` in `templates/hr/` (grep confirmed
  zero matches). `attendance.html:40` renders `rec.notes` and `my_leave.html:106` renders
  `leave.reason`, both auto-escaped. `Employee.notes` and `Employee.address` are collected
  but **not rendered** in the employee detail/list templates at all.
- **CSRF.** All state-changing forms carry `{% csrf_token %}`; no `@csrf_exempt` in `hr/`.
  The DRF viewsets use `SessionAuthentication`, so CSRF is enforced for browser-originated
  writes. No CSRF gap found. ✅
- **IDOR / broken object-level authorization.** My-Leave is safe (§3). The material gaps
  are (a) the API read-open exposure above, and (b) slip-item edit with no status guard,
  and (c) `pay`/`process` with no state-transition guard (both only guarded in templates).
- **Accessibility.** Bulk attendance relies on JS to recalc the summary and to color-code
  status selects (`.attendance-status` class swap, `attendance_form.html:136–173`); the
  summary counts are JS-only and would be wrong/empty without JS. No `aria-live` on the
  summary. Floating labels in `base_form.html` are `position`-based and may lose label
  association for screen readers. Contrast of `var(--text-secondary)`/`--text-2` used for
  secondary text was not measured.

## 7. API surface

Base: `/api/` (DRF `DefaultRouter`, `api/urls.py:72–82`). All HR endpoints use
`IsHRManagement` (read-open / HR-write) unless noted. Session authentication.

| Method + path | ViewSet / action | Permission | Request fields (required) | Response |
|---|---|---|---|---|
| GET/POST `/api/departments/` | `DepartmentViewSet` | IsHRManagement | `name`(req), `description`, `is_active` | dept + `employee_count` |
| GET/PUT/PATCH/DELETE `/api/departments/{id}/` | `DepartmentViewSet` | IsHRManagement | — | dept |
| GET/POST `/api/designations/` | `DesignationViewSet` | IsHRManagement | `title`(req), `is_active` | designation + `employee_count` |
| GET/POST `/api/salary-components/` | `SalaryComponentViewSet` | IsHRManagement | `name`(req), `component_type`, `is_active` | component |
| GET/POST `/api/employees/` | `EmployeeViewSet` | IsHRManagement (read-open) | `first_name`,`last_name`,`joining_date`(req); cnic/phone/email/address/status/notes optional | employee + nested `salaries` (amounts) |
| GET/PUT/PATCH/DELETE `/api/employees/{id}/` | `EmployeeViewSet` | IsHRManagement | — | employee |
| POST `/api/employees/{id}/add_salary/` | `EmployeeViewSet.add_salary` | IsHRManagement | `component`, `amount` | `EmployeeSalary` |
| GET/POST `/api/employee-salaries/` | `EmployeeSalaryViewSet` | IsHRManagement | `employee`,`component`,`amount` | salary row (no `amount>=0` validation in serializer; DB constraint only) |
| GET/POST `/api/payroll-runs/` | `PayrollRunViewSet` | IsHRManagement | `month`,`year`(req), `notes` | run (no `(month,year)` uniqueness validation → 500 on dup) |
| POST `/api/payroll-runs/{id}/generate/` | `PayrollRunViewSet.generate` | IsHRManagement | — | `{generated: n}` |
| POST `/api/payroll-runs/{id}/process/` | `PayrollRunViewSet.process` | IsHRManagement | — | run (recalc + approve) |
| POST `/api/payroll-runs/{id}/pay/` | `PayrollRunViewSet.pay` | IsHRManagement | — | `{paid: n}` (posts ledger once per new payment) |
| GET/POST `/api/salary-slips/` | `SalarySlipViewSet` | IsHRManagement (read-open) | — (gross/net read-only) | slip + nested `items` |
| GET/POST `/api/salary-payments/` | `SalaryPaymentViewSet` | IsHRManagement | `slip`,`amount`,`payment_date`,`method` | payment; `perform_create` posts ledger (no `amount==slip.net` check) |
| GET/POST `/api/attendance/` | `AttendanceViewSet` | IsHRManagement (read-open) | `employee`,`date`,`status`,`notes` | attendance (no duplicate guard → 500) |
| GET/POST `/api/leaves/` | `LeaveViewSet` | IsHRManagement (read-open) | `employee`,`leave_type`,`start_date`,`end_date`,`days`,`reason` | leave; **`status` is writable** (bypasses `approve`) |
| POST `/api/leaves/{id}/approve/` | `LeaveViewSet.approve` | IsHRManagement | — | leave (no pending-state guard) |
| POST `/api/leaves/{id}/reject/` | `LeaveViewSet.reject` | IsHRManagement | — | leave |

Notable serializer/API gaps:
- `LeaveSerializer` leaves `status` writable (`hr/serializers.py:146–151`), so a client can
  set `status='approved'` directly on create/update, bypassing the `approve` action and the
  `approved_by` stamp. ❌
- `EmployeeSalaryViewSet` exposes `EmployeeSalary` create without `amount>=0` validation
  and with no graceful handling of the `(employee,component)` unique constraint → 500.
- `EmployeeDocument` has **no** serializer/ViewSet — documents are upload-inaccessible via
  API and there is no server-rendered upload UI either (admin only).
- `SalaryPaymentViewSet` accepts any `amount` for any `slip` and posts it to the ledger with
  no check that it equals `slip.net` or is > 0 (a 0/negative amount 500s on the ledger
  positive-amount constraint).

## 8. Test data & fixtures needed

Preconditions and isolation:

- **Roles:** create profiles for `hr`, `accounts`, `management`, `sales`, and a
  `staff` user **linked to an `Employee`** (`Employee.user` OneToOne) to exercise
  self-service and the `is_employee` sidebar hiding.
- **Master data:** Department, Designation, at least one earning `SalaryComponent`
  (e.g. Basic) and one deduction (e.g. Tax); a couple of `EmployeeSalary` rows per employee.
- **Employees:** one with salary (net > 0), one with **no salary components** (net = 0),
  one with deductions > earnings (net < 0) — the last two are the critical `pay`-fails
  fixtures; one `on_leave` and one `resigned` (to verify `generate_slips` filtering).
- **Payroll run isolation:** `(month, year)` is globally unique, so tests must use a
  unique/current month or the suite collides; same for `Employee` auto-ID (expect
  `EMP-00001` suffix reuse after deletion) and `Attendance (employee,date)`.
- **Ledger isolation:** assert `AccountTransaction` row count by
  `reference_type='SalaryPayment', reference_id=<payment.pk>` equals 1 after double `pay`;
  assert no `amount=0` rows (currently fails for zero-net employees).
- **CNIC uniqueness:** seed one employee, then attempt API create with the same 13 digits
  but alternate formatting to demonstrate the normalization bypass.

Isolation rules: timestamped/usernamed employees and unique months to avoid
`unique_together` collisions across runs; reset `Employee` and `PayrollRun` between tests
so auto-ID increments don't leak state.

## 9. Key files (for traceability)

- `hr/models.py` — all HR/payroll models, auto EMP id, `recalculate`, `generate_slips`,
  `post_to_ledger`, `unique_together` constraints, `LEAVE_POLICY_ALLOWANCES`.
- `hr/forms.py` — Department/Designation/Component/Employee (CNIC normalization)/
  EmployeeSalary/PayrollRun/Attendance/Leave/EmployeeProfile forms. `AttendanceForm` unused.
- `hr/serializers.py` — DRF serializers; `LeaveSerializer.validate` (end>=start, days>0);
  `EmployeeSerializer.validate_cnic` (un-normalized).
- `hr/api_views.py` — `IsHRManagement` (read-open), all HR ViewSets + `generate`/`process`/
  `pay`/`approve`/`reject`/`add_salary` actions.
- `hr/views.py` — 715-line server-rendered view layer; `hr_home`, departments/designations/
  components CRUD, employees, salary, payroll run flow, slips, bulk attendance, leave,
  employee-profile create, my-leave self-service, payroll report.
- `hr/urls.py` — HR URL map (own `urls.py`).
- `hr/admin.py` — admin registrations (readonly slip gross/net; document inline only).
- `templates/hr/*.html` — 22 templates; key ones reviewed: `employee_detail`, `employees`,
  `attendance_form`, `attendance`, `leaves`, `my_leave`, `leave_form` (extends base_form),
  `salary_slip_detail`, `payroll_run_detail`, `payroll_runs`, `payroll_report`, `hr_home`,
  `salary_components`, `departments`, `employee_profile_form`, `payroll_run_form`,
  `salary_form`, `employee_form`.
- `templates/includes/sidebar.html` — nav gating (`is_employee`, `can_view_payroll`,
  `can_manage_hr`).
- `finance/models.py` — `AccountTransaction` unique constraint `(reference_type,
  reference_id)` + `amount>0` check (ledger contract HR posts into).
- `core/permissions.py` — `hr_required`, `payroll_access`, role groups.
- `core/context_processors.py` — `is_employee`, `can_manage_hr`, `can_view_payroll` flags.
- `api/urls.py` — HR ViewSet registration under `/api/`.
- `samana_erp/settings.py` — `REST_FRAMEWORK` default `IsAuthenticated` (why HR API is read-open).
