# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Real Estate Management ERP + corporate website for Samana Builders & Developers. Django 6.0 + Django REST Framework backend serving two frontends: a server-rendered ERP (Django templates) and a corporate marketing site (also Django templates, with a compiled React build artifact in `frontend/dist/`). SQLite for dev, PostgreSQL for production.

## Commands

The virtualenv is **`.venv312`** (Python 3.12), not `venv` as the README says.

```powershell
# Activate (PowerShell)
.\.venv312\Scripts\Activate.ps1
# or Bash
source .venv312/Scripts/activate

# Run dev server
python manage.py runserver

# Migrations
python manage.py makemigrations
python manage.py migrate

# Tests — full suite, one app, or a single test
python manage.py test
python manage.py test payments
python manage.py test payments.tests.PaymentModelTest.test_payment_id_generation

# Django shell / superuser / migrations check
python manage.py shell
python manage.py createsuperuser
python manage.py showmigrations
```

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

`notifications/services.py` provides `EmailService`, `SMSService`, `WhatsAppService`, and a `NotificationService` facade that logs every send to `NotificationLog`. Email uses Django's console backend in dev; SMS and WhatsApp are stubs (WhatsApp returns a `wa.me` click-to-chat URL). Existing triggers: payment confirmation, booking notification, installment reminder, overdue alert, receipt notification.

### Backup / restore

`core/backup.py` serializes each DB table to CSV and bundles media into a zip. Restore is exposed via `core/views.py` (`backup_restore_latest_view`, `backup_restore_upload_view`) and gated by `admin_or_above`.

### Corporate website & React

The public site is a Django template (`templates/corporate/home.html` extending `corporate_base.html`); its forms POST to `lead_submit` which creates `core.Lead` rows. `frontend/dist/` is a compiled Vite React build (`index.html` + hashed assets) with **no `src/` or `package.json` in the repo** — the React source lives outside this checkout, so treat `frontend/dist/` as a generated artifact. `docs/superpowers/specs/2026-07-24-react-frontend-design.md` documents the intended SPA design.

## Notes & gotchas

- `requirements.txt` is **UTF-16 encoded** (a BOM + wide chars); open it carefully — normal UTF-8 tooling may garble it. Key deps: `Django==6.0.7`, `djangorestframework`, `psycopg2-binary`, `django-cors-headers`, `xhtml2pdf`, `requests`.
- `AGENTS.md` and `docs/superpowers/` hold planning/spec artifacts (spec-driven development); `README.md` has module and API-endpoint tables. `opencode.json` enables the `superpowers` plugin.
- Templates live in `templates/` with the ERP base as `base.html` / `base_form.html` and the corporate base as `corporate_base.html`. Theme CSS files (`theme-*.css`) correspond to `UserProfile.THEME_CHOICES`.
- Static files (hand-written) live in `static/` (`css/`, `js/`); the React build outputs to `static/assets/`.
