# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Real Estate Management ERP + corporate website for Samana Builders & Developers. Django 6.0 + Django REST Framework backend serving two frontends: a server-rendered ERP (Django templates) and a corporate marketing site (also Django templates, with a compiled React build artifact in `frontend/dist/`). SQLite for dev, PostgreSQL for production.

## Work status (last updated 2026-09-14)

### Shipped (committed + pushed to origin/main)

Two commits landed since 2026-09-08, both on `main` and pushed. Working tree is clean.

- **`aeead4d` — "Client feedback round"** — the client-feedback batch below (booking pricing guards, cancel/reopen, refund + expense workflows, ledger dedup, nominee, welcome email, milestones, UI polish), plus the CLAUDE.md refresh and the SendPK API 3.0 doc. 663 tests green at commit time.
- **`d2e6d34` — "QA remediation"** — permission tightening, read-only expense status, office-delete guard, self-service profile, XSS/ledger fixes (details below). 663 tests green at commit time.

What shipped (client-feedback round):

1. **Booking pricing guardrails** — `Plot` gained `development_charge`, `lease_charge`, `other_charges`; `Plot.total_charges` and `Plot.total_cost` (price + charges) are the single source of truth. Booking create/edit forms and the API serializer reject a `total_amount` below `plot.total_cost` and an `advance_paid` below `plot.holding_deposit`. `Booking` also gained `payment_plan` / `amount_paid` / `total_charges` display helpers.
2. **Confirm requires an advance** — `booking_confirm_view` and the API `confirm` action refuse to confirm when `advance_paid <= 0`.
3. **Cancel / reopen bookings** — new `booking_cancel_view` / `booking_reopen_view` (+ `booking_cancel.html`, `booking_reopen.html`, URL routes). Cancel is blocked while verified payments exist (refund first); it releases the plot to `available` and records `cancelled_at` / `cancelled_by` / `cancelled_reason`. Reopen returns the booking to `pending`, stamps `reopened_at`, and re-reserves the plot. Both write AuditLog entries.
4. **Refund workflow upgrade** — `Refund` gained `refund_method`, `refund_date`, `supporting_document`, `processed_by`, `updated_at`, an `amount > 0` constraint, and `-created_at` ordering. Computed helpers: `total_paid`, `total_refunded`, `refundable_amount` (verified payments − non-rejected refunds), `refund_percentage`. Lifecycle: `pending → approved → processed | rejected`; `process()` marks it processed and posts exactly one ledger row (idempotent, skips if already posted). Validation enforced on model + form + serializer. UI: process button on `refunds.html`; API: `approve` / `reject` / `process` actions with audit logging.
5. **Expense approval workflow** — `Expense` gained `status` (`pending → approved → paid | rejected`), `approved_by` / `approved_at`, `payment_reference`, `receipt_attachment`. New approve / reject / mark-paid views + URLs; approve and mark-paid post the expense to the ledger exactly once; approved/paid expenses are locked from editing.
6. **Ledger de-duplication** — unique constraint on `AccountTransaction` (`reference_type`, `reference_id`); refunds, expenses, and salary payments post via idempotent `update_or_create` keyed on that pair.
7. **Deletion guards** — a project with plots cannot be deleted; an office with expenses or ledger transactions cannot be deleted (enforced in both the web view and `OfficeViewSet.destroy`).
8. **Nominee management** — `customer_nominee_manage_view` + `customer_nominee_form.html` lets staff add/edit/remove a customer's nominee (also shown on customer detail + the portal).
9. **Customer welcome email** — `NotificationService.send_customer_welcome()` fires on customer create (UI + API) and lead conversion; failure-safe and skipped when no email. New `customer_welcome` notification type.
10. **Milestones** — `ProjectMilestone` gained `start_date`, `milestone_type`, `completion_percent`, `progress_date`; form, list (progress bar), and detail updated.
11. **UI polish** — `money` template filter; print stylesheet (hides chrome) + Print button on the sales report; refreshed properties / expenses / refunds / offices / milestones tables.

New files from both commits: `api/tests_booking_pricing.py`; migrations `bookings/0005`, `expenses/0003` + `expenses/0004`, `finance/0004` + `finance/0005`, `notifications/0003`, `payments/0007`, `properties/0006` + `properties/0007`, `customers/0005`; templates `booking_cancel.html`, `booking_reopen.html`, `customer_nominee_form.html`; `Business_SMS_API_3.0.pdf`.

### QA remediation (commit `d2e6d34`)

Permissions and API-contract tightening applied as part of the QA pass:

- **`project_create_view` / `plot_create_view` / plot_edit now require `management_or_above`** (were `login_required` only). Tests updated to give the view-test user an admin profile.
- **Portal customers blocked from staff/financial API reads** — new `core.permissions.is_portal_customer()`; finance `IsFinanceOrAbove` returns `not is_portal_customer(...)`.
- **Office/project-cost `status` is now read-only on the API** (removed from the form; serializer `read_only_fields`). Create always lands `pending` and never auto-posts to the ledger. `OfficeExpense` is moved to `paid` via the `pay` action (posts ledger); `ProjectCost` has no pay action. `ProjectCost.status` default changed from `paid` → `pending` (migration `finance/0005`).
- **`OfficeViewSet.destroy`** refuses deletion while the office has expenses/ledger transactions (was view-only guard).
- **Self-service profile form is `theme`-only** — `role` / `is_active` are no longer user-editable; `UserCreateSerializer` write_only. `CustomerNominee.nominee_name` `blank=True`; expense receipt attachment wired.

**Verification:** full Django suite green — 663/663, `OK` — with `DJANGO_DEBUG=True` + shared venv, run before both commits.

### SMS (SendPK) status

The SMS channel is wired to the SendPK HTTP API (`SMSService`) but **disabled in the local `.env`** (`SENDPK_ENABLED=False`, no `SENDPK_API_KEY`). Reference docs: `sendpk_documentation.md` (gitignored) and `Business_SMS_API_3.0.pdf`. Live account findings (2026-09):

- Sends work and are billed (~3.9 PKR/SMS). "Accepted for delivery" only means queued; the delivery report is where real per-number status shows.
- On the shared sender route the message arrived on Telenor showing a generic "TEXT SMS" sender — shared sender names are not carried reliably, and the brand only appears in the auto-appended footer.
- Showing **SAMANA** as the sender requires a branded sender mask approval (one-time; account verification documents needed). After approval set `SENDPK_SENDER_ID=SAMANA` (see the comment in `settings.py`).
- A ported number (Ufone → Jazz) did not receive the shared-route message (routing follows the original operator). For ported numbers pass the `network` parameter (Jazz/Zong/Ufone/Telenor), or verify the branded route resolves MNP automatically.

### Production deploy notes

Recent commits on `main` (through `d2e6d34`, Sep 14) cover prod safety: `DEBUG` defaults to False in production, CSRF trusted origins + secure proxy/cookie settings, and AI/OpenRouter env mappings in compose. Prod is docker-compose on the VPS; env vars (`DJANGO_SECRET_KEY`, `DB_*`, `EMAIL_*`, `SENDPK_*`, `OPENROUTER_API_KEY`) must be supplied there. The two shipped commits above are not yet deployed to the VPS — `git pull` + `docker compose up -d --build` there will deploy them (and the new migrations needed).

## Commands

The working virtualenv is **`D:\samana\.venv312`** (Python 3.12) — activate it as below, or call its `Scripts\python.exe` directly. Always run with `PYTHONPATH` unset (`env -u PYTHONPATH` in bash): a stray `PYTHONPATH` from the surrounding tooling can shadow the venv packages and break imports. Note: the `.venv312` inside this checkout is an incomplete copy (no pydantic / langchain, so the AI-backed tests fail under it) — use the shared venv for the full run. The README's `venv` is stale.

```powershell
# Activate (PowerShell)
D:\samana\.venv312\Scripts\Activate.ps1
# or Bash
source /d/samana/.venv312/Scripts/activate

# Run dev server
python manage.py runserver

# Migrations
python manage.py makemigrations
python manage.py migrate

# Tests — full suite, one app, or a single test.
# IMPORTANT: prefix DJANGO_DEBUG=True (bash) or set $env:DJANGO_DEBUG='True'
# (PowerShell) — see the note below the commands. Without it the suite
# mass-fails with 301 redirects (SECURE_SSL_REDIRECT is `not DEBUG`).
DJANGO_DEBUG=True python manage.py test
DJANGO_DEBUG=True python manage.py test payments
DJANGO_DEBUG=True python manage.py test payments.tests.PaymentModelTest.test_payment_id_generation

# Django shell / superuser / migrations check
python manage.py shell
python manage.py createsuperuser
python manage.py showmigrations
```

**Set `DJANGO_DEBUG=True` when running tests.** With the `.env` default (`DJANGO_DEBUG=False`), `SECURE_SSL_REDIRECT` redirects every test-client request (301), so the suite mass-fails with hundreds of bogus failures. Full suite: 663 tests, ~9 minutes.

Default login: `admin` / `admin123`. Login URL `/login/`, post-login staff land on `/dashboard/`, customers on `/portal/`.

Useful scripts: `populate_dummy_data.py` (seed data), `debug_revenue.py` (ad-hoc revenue debugging).

## Architecture

### `core/` is the hub — most HTML views live there

Despite each module having its own `views.py`, **`samana_erp/urls.py` routes nearly every ERP page to functions in `core/views.py`** (~2000 lines): customers, properties, bookings, payments, receipts, PDFs, users, audit logs, backup, the corporate home page, and the customer portal. When working on an ERP page, the view logic is almost always in `core/views.py`, not the app's `views.py`.

The domain apps split responsibilities like this:

- **`core/`** — the monolith view layer, plus `UserProfile` (role + theme), `AuditLog`, `Lead`, approval-chain models, permission decorators (`permissions.py`), template context processors, and backup.
- **`customers/`, `properties/`, `bookings/`, `payments/`** — models, forms, serializers, and DRF `api_views.py` (ViewSets). Their own `views.py` are largely unused for the ERP.
- **`expenses/`, `notifications/`** — the only apps with their own `urls.py` and active template views.
- **`api/`** — a single DRF `DefaultRouter` (`api/urls.py`) that registers every app's ViewSet; auth/session endpoints live in `api/views.py`.

### Data model (core business relationships)

```
Project ──< ProjectPhase ──< Plot ──< Booking ──< Payment
                                  │
                                  ├──< InstallmentPlan (1:1) ──< Installment
                                  └──< BookingTransfer / Refund / EarlySettlement
Customer ──< Booking / CustomerLedgerEntry / CustomerNominee / ReceivableAging
```

- **Booking.installment_plan** is a `OneToOneField`; `InstallmentPlan.auto_generate()` creates `Installment` rows on demand.
- **Payments** have a status workflow (`draft → pending → verified / rejected / bounced / reversed`) and `PaymentAllocation` joins payments to installments.
- **Expenses** are project-scoped and standalone (no customer/booking linkage).
- **Booking lifecycle**: `pending → confirmed → ...`, plus `cancelled` (cancel releases the plot to `available`; reopen returns it to `pending` and re-reserves it). Confirming requires `advance_paid > 0`; cancelling is blocked while verified payments exist (refund first). Booking amounts are validated against `Plot.total_cost` (price + development/lease/other charges) and `plot.holding_deposit`.
- **Refunds**: `pending → approved → processed | rejected`; `refundable_amount` = verified payments − non-rejected refunds. Processing posts exactly one ledger row (idempotent).
- **Account ledger**: `AccountTransaction` is uniquely constrained on (`reference_type`, `reference_id`); refunds, expenses, and salary payments post via idempotent `update_or_create` keyed on that pair.

### Auto-generated IDs

IDs are generated in `Model.save()` by parsing the last record's numeric suffix (not DB sequences). Prefixed formats: `CUS-00001` (Customer), `BKG-00001` (Booking), `PAY-00001` (Payment), `GRP-00001` (BookingGroup), `RCP-00001` (Receipt). Receipts also get a fiscal-year `receipt_number` like `RCP-FY25-26/00001` (July–June fiscal year).

### Role-based access control

Roles: `super_admin`, `admin`, `management`, `accounts`, `sales` (defined in `core/models.py` `UserProfile.ROLE_CHOICES`).

- Decorators in `core/permissions.py`: `role_required`, `super_admin_required`, `admin_or_above`, `management_or_above`, `finance_or_above`, `payments_access`. They redirect to `/dashboard/` with a message on denial.
- `core/context_processors.py` (`erp_context`) injects per-role flags (`can_view_payments`, `can_manage_users`, `can_delete`, etc.) into every template for role-aware UI.
- DRF equivalents (`IsAdminOrReadOnly`, `IsSuperAdmin`, `IsStaffOrAbove`) live in `core/api_views.py`.
- A superuser is always treated as `super_admin` regardless of profile.

### Revenue semantics

**Revenue = the sum of `Booking.advance_paid` across all bookings** — the single source of truth. `advance_paid` is what makes a booking "revenue", not the `Payment` rows. This is a deliberate design decision (see `dashboard_view` in `core/views.py`); don't reintroduce `Payment`-based totals for headline revenue.

### PDFs

Generated from Django templates via **xhtml2pdf** (`pisa`) in `payments/pdf_utils.py` (`render_to_pdf`, `generate_receipt_pdf`, `generate_invoice_pdf`, `generate_customer_profile_pdf`). `payments/utils.py` has `amount_in_words()` using Pakistani numbering (Crore/Lakh). Receipts/invoices/customer profiles each have dedicated `*.pdf.html` templates.

### Notifications

`notifications/services.py` provides `EmailService`, `SMSService`, `WhatsAppService`, and a `NotificationService` facade that logs every send to `NotificationLog` (with `provider_message_id` for SMS).

- **Email** — uses SMTP (Brevo relay) when `EMAIL_HOST` / `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` are set, otherwise Django's console backend. Gated by `EMAIL_ENABLED`.
- **SMS** — real SendPK HTTP API integration (not a stub): posts to `sms.php` with `format=json`, normalizes Pakistani numbers to `92XXXXXXXXXX`, stores the returned message id, and has `check_delivery()` / `check_balance()` helpers. Env: `SENDPK_ENABLED`, `SENDPK_API_KEY`, `SENDPK_SENDER_ID`, `SENDPK_BASE_URL`. Currently disabled in the local `.env` (see Work status above).
- **WhatsApp** — returns a `wa.me` click-to-chat URL only (no Business API).
- Triggers: payment confirmation, booking notification, installment reminder, overdue alert, receipt notification, and customer welcome (fires on customer create via UI + API and on lead conversion; failure-safe so a broken email can never break the customer transaction).

### Backup / restore

`core/backup.py` serializes each DB table to CSV and bundles media into a zip. Restore is exposed via `core/views.py` (`backup_restore_latest_view`, `backup_restore_upload_view`) and gated by `admin_or_above`.

### Corporate website & React

The public site is a Django template (`templates/corporate/home.html` extending `corporate_base.html`); its forms POST to `lead_submit` which creates `core.Lead` rows. `frontend/dist/` is a compiled Vite React build (`index.html` + hashed assets) with **no `src/` or `package.json` in the repo** — the React source lives outside this checkout, so treat `frontend/dist/` as a generated artifact. `docs/superpowers/specs/2026-07-24-react-frontend-design.md` documents the intended SPA design.

## Notes & gotchas

- `requirements.txt` is **UTF-16 encoded** (a BOM + wide chars); open it carefully — normal UTF-8 tooling may garble it. Key deps: `Django==6.0.7`, `djangorestframework`, `psycopg2-binary`, `django-cors-headers`, `xhtml2pdf`, `requests`.
- `AGENTS.md` and `docs/superpowers/` hold planning/spec artifacts (spec-driven development); `README.md` has module and API-endpoint tables. `opencode.json` enables the `superpowers` plugin.
- Templates live in `templates/` with the ERP base as `base.html` / `base_form.html` and the corporate base as `corporate_base.html`. Theme CSS files (`theme-*.css`) correspond to `UserProfile.THEME_CHOICES`.
- Static files (hand-written) live in `static/` (`css/`, `js/`); the React build outputs to `static/assets/`.
