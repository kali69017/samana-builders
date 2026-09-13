# QA Shared Context — Samana Builders ERP

Internal reference for the module-analysis agents. This captures facts already
verified from the code so each module agent does not re-derive them.

## Roles (core/models.py `UserProfile.ROLE_CHOICES`)

`super_admin`, `admin`, `management`, `accounts`, `sales`, `hr`,
`project_manager`, `contractor`, `staff`. Default role on a new profile is
`sales`. A Django `is_superuser` is ALWAYS treated as `super_admin` regardless
of any profile.

## Permission groups (core/permissions.py)

- `MANAGEMENT_ROLES` = super_admin, admin, management
- `FINANCE_ROLES` = super_admin, admin, management, accounts
- `ADMIN_ROLES` = super_admin, admin  (user mgmt + backup)
- `PAYMENTS_ACCESS_ROLES` = super_admin, admin, management, accounts (sales EXCLUDED)
- `HR_MANAGEMENT_ROLES` = super_admin, admin, management, hr
- `PAYROLL_ROLES` = super_admin, admin, management, hr, accounts

## Decorators (all redirect to `/dashboard/` with an error message on denial)

`role_required(*roles)`, `super_admin_required`, `admin_or_above`,
`management_or_above`, `finance_or_above`, `payments_access`, `hr_required`,
`payroll_access`.

All decorators: unauthenticated → redirect to `/login/`; `is_superuser` → allow;
otherwise allow iff `request.user.profile.role` is in the role set. NOTE: if the
user has NO `profile` (and is not superuser) they are denied — `hasattr` guard.

## Template context flags (core/context_processors.py `erp_context`)

`can_view_payments` (PAYMENTS_ACCESS_ROLES), `can_view_expenses` (FINANCE_ROLES),
`can_manage_users` (ADMIN_ROLES), `can_view_users` (MANAGEMENT_ROLES),
`can_backup` (ADMIN_ROLES), `can_audit` (MANAGEMENT_ROLES),
`can_delete` (MANAGEMENT_ROLES), `can_view_leads` (MANAGEMENT + accounts + sales),
`can_view_reports` (FINANCE_ROLES), `can_manage_settings` (ADMIN_ROLES),
`can_manage_hr` (HR_MANAGEMENT_ROLES), `can_view_payroll` (PAYROLL_ROLES).

Also injected: `user_role`, `user_display_name`, `user_initials`, `is_employee`
(bool(getattr(user, 'employee', None))), `whatsapp_number`.

## Revenue semantics

Revenue = sum of `Booking.advance_paid` across all bookings — the single source
of truth (see `dashboard_view`). Do NOT reintroduce `Payment`-row totals for
headline revenue.

## Money / decimal

Amounts are `DecimalField(max_digits=15, decimal_places=2)` (PKR, no sub-paisa).
Assert money values EXACTLY in tests, never floored loosely.

## Auto-generated IDs

Generated in `Model.save()` by parsing the last record's numeric suffix (NOT DB
sequences): `CUS-00001` (Customer), `BKG-00001` (Booking), `PAY-00001`
(Payment), `GRP-00001` (BookingGroup), `RCP-00001` (Receipt), `AGT-00001`
(Agent). Receipts also get a fiscal-year `receipt_number` `RCP-FY25-26/00001`
(July–June fiscal year).

## Business invariants (from CLAUDE.md work status)

- `Plot.total_charges` and `Plot.total_cost` (price + development/lease/other
  charges) are the single source of truth for booking price guards.
- Booking create/edit + API reject `total_amount < plot.total_cost` and
  `advance_paid < plot.holding_deposit`.
- Confirm requires `advance_paid > 0`.
- Cancel is blocked while verified payments exist (refund first); releases plot
  to `available`; reopen returns booking to `pending` and re-reserves plot.
- Refund: `pending → approved → processed | rejected`; `refundable_amount` =
  verified payments − non-rejected refunds. `process()` posts exactly one ledger
  row (idempotent).
- Expense: `pending → approved → paid | rejected`; approve/mark-paid post to
  ledger exactly once; approved/paid expenses locked from editing.
- `AccountTransaction` unique on (`reference_type`, `reference_id`); refunds,
  expenses, salary payments post via idempotent `update_or_create`.
- A project with plots cannot be deleted; an office with expenses/ledger rows
  cannot be deleted.

## URL map (samana_erp/urls.py — most ERP pages route to core/views.py)

See `samana_erp/urls.py`. Key facts:
- `core/views.py` (~2400 lines) is the monolith: customers, properties, bookings,
  payments, receipts, PDFs, users, audit, backup, portal, AI pages, corporate home.
- `core/views_crm.py`: leads + agents. `core/views_settings.py`: receivables,
  sales report, company settings, milestones.
- `bookings/views_installments.py`: installment plans/installments.
- `payments/views_workflow.py`: payment verify/reject/bounce/reverse + refunds.
- `finance/urls.py`, `expenses/urls.py`, `hr/urls.py`, `notifications/urls.py`
  have their own `urls.py`.
- DRF router at `api/urls.py` registers every app's ViewSet under `/api/...`;
  auth endpoints `auth/csrf`, `auth/login`, `auth/logout`, `auth/me` in
  `api/views.py`; AI under `api/ai/...` (`ai/urls.py`); portal `portal/`,
  `customer-profiles/`.

## Conventions

- Server-rendered templates use `form-control` / `floating-group` classes; no
  `data-testid`. Interact via role/accessible-name.
- Login: `admin` / `admin123`; post-login staff land on `/dashboard/`, customers
  on `/portal/`.
- Dev server: `DJANGO_DEBUG=True` required (else `SECURE_SSL_REDIRECT` 301s).
- `requirements.txt` is UTF-16.
